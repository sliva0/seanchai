"""The Wireshark plugin `seanchai wireshark-plugin` writes: its core under
every Lua found here, and the whole plugin under tshark, over messages encoded
below.

The core is plain Lua for Wireshark 4.2's Lua 5.2 and 4.4's 5.4 alike; each
interpreter on PATH runs it (5.1 standing in for the oldest), and a test is
skipped where none is. The tshark tests run the generated plugin over a pcap
of the same messages, skipped without tshark.
"""

import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from seanchai import corpus, dictionary, model, wireshark
from seanchai.cli import main
from seanchai.wireshark import _rules as generator

CORE = Path(wireshark.__file__).parent / "core.lua"
LUAS = [name for name in ("lua5.1", "lua5.2", "lua5.3", "lua5.4") if shutil.which(name)]
CX = 16777216
RX = 16777236
GX = 16777238
TGPP = 10415

R, P, E = 0x80, 0x40, 0x20
V, M = 0x80, 0x40


def avp(code: int, data: bytes, *, flags: int = M, vendor: int | None = None) -> bytes:
    """One AVP, padded; `vendor` sets the V bit."""
    if vendor is not None:
        flags |= V
        header = struct.pack("!IB", code, flags) + (12 + len(data)).to_bytes(3, "big")
        header += struct.pack("!I", vendor)
    else:
        header = struct.pack("!IB", code, flags) + (8 + len(data)).to_bytes(3, "big")
    body = header + data
    return body + b"\0" * (-len(body) % 4)


def u32(value: int) -> bytes:
    return struct.pack("!I", value)


def message(
    code: int, flags: int, application: int, *avps: bytes, hop: int = 1
) -> bytes:
    body = b"".join(avps)
    length = 20 + len(body)
    return (
        bytes([1])
        + length.to_bytes(3, "big")
        + bytes([flags])
        + code.to_bytes(3, "big")
        + struct.pack("!III", application, hop, hop)
        + body
    )


def _base(*, session: bool = True) -> list[bytes]:
    return [
        *([avp(263, b"hss.example.com;1;2")] if session else []),
        avp(260, avp(266, u32(10415)) + avp(258, u32(CX))),
        avp(277, u32(1)),
        avp(264, b"icscf.example.com"),
        avp(296, b"example.com"),
    ]


def good_uar() -> bytes:
    return message(
        300,
        R | P,
        CX,
        *_base(),
        avp(283, b"example.com"),
        avp(1, b"user@example.com"),
        avp(601, b"sip:user@example.com", vendor=10415, flags=M),
        avp(600, b"example.com", vendor=10415, flags=M),
    )


def bad_uar() -> bytes:
    # Session-Id second, no Public-Identity, Visited-Network-Identifier without
    # the M bit TS 29.229 table 6.3.0.1 puts in Must, a host name with a space,
    # Auth-Session-State 7, which RFC 6733 section 8.11 does not define.
    session, application, _, _, realm = _base()
    return message(
        300,
        R | P,
        CX,
        application,
        session,
        avp(277, u32(7)),
        avp(264, b"icscf example.com"),
        realm,
        avp(283, b"example.com"),
        avp(1, b"user@example.com"),
        avp(600, b"example.com", vendor=10415, flags=0),
    )


def error_uaa() -> bytes:
    # With the E bit, TS 29.229 clause 7.3.1's answer-message, not UAA's body.
    return message(
        300,
        P | E,
        CX,
        avp(263, b"hss.example.com;1;2"),
        avp(264, b"hss.example.com"),
        avp(296, b"example.com"),
        avp(268, u32(3002)),
    )


def failed_uaa(failed: bytes) -> bytes:
    # RFC 6733 section 7.5: Failed-AVP holds the AVP as received, here a host
    # name no DiameterIdentity is and a copied Result-Code of 2001.
    return message(
        300,
        P | E,
        CX,
        avp(263, b"hss.example.com;1;2"),
        avp(264, b"hss.example.com"),
        avp(296, b"example.com"),
        avp(268, u32(3008)),
        avp(279, failed),
    )


def good_dwr() -> bytes:
    return message(280, R, 0, avp(264, b"peer.example.com"), avp(296, b"example.com"))


def _rules(out: Path, *options: str) -> Path:
    """`seanchai wireshark-plugin` with `options`, written to `out`."""
    done = CliRunner().invoke(main, ["wireshark-plugin", *options, "-o", str(out)])
    assert done.exit_code == 0, done.output
    return out


@pytest.fixture(scope="module")
def rules(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("rules") / "rules.lua"
    return _rules(out, "--application", "0", "--application", str(CX), "--rules-only")


# Gx and Rx too, for references into TS 29.061, TS 29.212 and TS 29.214.
_CITED = ("0", str(CX), str(RX), str(GX))


@pytest.fixture(scope="module")
def cited_rules(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("rules") / "rules.lua"
    options = [arg for each in _CITED for arg in ("--application", each)]
    return _rules(out, *options, "--rules-only")


@pytest.fixture(scope="module")
def unlinked_rules(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("rules") / "rules.lua"
    options = [arg for each in _CITED for arg in ("--application", each)]
    return _rules(out, *options, "--rules-only", "--explorer", "")


_RUNNER = """
local core = dofile(arg[1])
local rules = dofile(arg[2])
local function unhex(text)
  return (text:gsub("..", function(pair) return string.char(tonumber(pair, 16)) end))
end
local function reference(ref)
  if not ref then
    return "-"
  end
  return table.concat({ ref.document, ref.clause, tostring(ref.page),
    tostring(ref.table), ref.url or "-", ref.explorer or "-", ref.text }, "\\t")
end
for index = 3, #arg do
  local result = core.validate(rules, unhex(arg[index]), {})
  local command = result.command and result.command.document or "-"
  io.write("message ", command, " ", tostring(result.form), "\\n")
  io.write("ref ", reference(result.reference), "\\n")
  for _, each in ipairs(result.findings) do
    io.write(each.severity, " ", each.rule, " ", each.message, "\\n")
    io.write("ref ", reference(each.reference), "\\n")
  end
end
"""

_REFERENCE = ("document", "clause", "page", "table", "url", "explorer", "text")


def _reference(text: str) -> dict | None:
    if text == "-":
        return None
    fields = dict(zip(_REFERENCE, text.split("\t"), strict=True))
    return {
        key: None if value in {"nil", "-"} else value for key, value in fields.items()
    }


def _validate(lua: str, rules: Path, tmp_path: Path, *messages: bytes) -> list[dict]:
    runner = tmp_path / "runner.lua"
    runner.write_text(_RUNNER, "utf-8")
    done = subprocess.run(
        [lua, str(runner), str(CORE), str(rules)] + [each.hex() for each in messages],
        check=True,
        capture_output=True,
        text=True,
    )
    results: list[dict] = []
    for line in done.stdout.splitlines():
        kind, _, rest = line.partition(" ")
        if kind == "message":
            document, form = rest.split(" ")
            results.append(
                {"document": document, "form": form, "findings": [], "cited": []}
            )
        elif kind == "ref":
            if results[-1]["findings"]:
                results[-1]["cited"].append(_reference(rest))
            else:
                results[-1]["reference"] = _reference(rest)
        else:
            rule, _, text = rest.partition(" ")
            results[-1]["findings"].append((kind, rule, text))
    return results


def _rules_of(result: dict, severity: str = "error") -> set[str]:
    return {rule for kind, rule, _ in result["findings"] if kind == severity}


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_core_judges_each_message_by_its_command_and_form(lua, rules, tmp_path):
    truncated = good_dwr()[:-3]
    overrun = bytearray(good_uar())
    overrun[23] = 0xFF  # inside Session-Id's length, now past the message
    copied = avp(264, b"bad host!") + avp(268, u32(2001))

    uar, dwr, bad, answer, short, long, held, empty = _validate(
        lua,
        rules,
        tmp_path,
        good_uar(),
        good_dwr(),
        bad_uar(),
        error_uaa(),
        truncated,
        bytes(overrun),
        failed_uaa(copied),
        failed_uaa(b""),
    )

    assert uar["form"] == "command"
    assert uar["document"] in {"TS29.229", "3GPP2-X.S0013-006"}
    assert dwr["document"] == "RFC6733"
    for clean in (uar, dwr, answer, held):
        assert _rules_of(clean) == set(), clean
    # With the E bit, the answer-message, not UAA's body.
    assert answer["form"] == "answer-message"
    assert _rules_of(answer, "warn") == _rules_of(held, "warn") == set()
    assert _rules_of(bad) >= {
        "avp-missing",
        "avp-position",
        "flag-must",
        "diameter-identity",
    }
    assert "enum-value" in _rules_of(bad, "warn")
    missing = [text for _, rule, text in bad["findings"] if rule == "avp-missing"]
    assert any("Public-Identity" in text for text in missing)
    # Malformed octets are reported, not raised.
    assert "header-length" in _rules_of(short)
    assert "avp-length" in _rules_of(long)
    # Failed-AVP holds what was received, and at least one AVP.
    assert _rules_of(empty) == {"avp-missing"}


def _pcap(messages: list[bytes]) -> bytes:
    """Ethernet, IPv4 and TCP to port 3868, one message per segment."""
    out = struct.pack("!IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    seq = 1000
    for index, payload in enumerate(messages):
        tcp = struct.pack("!HHIIBBHHH", 40000, 3868, seq, 1, 5 << 4, 0x18, 65535, 0, 0)
        seq += len(payload)
        length = 20 + len(tcp) + len(payload)
        ip = struct.pack(
            "!BBHHHBBH4s4s",
            0x45,
            0,
            length,
            index,
            0,
            64,
            6,
            0,
            bytes([10, 0, 0, 1]),
            bytes([10, 0, 0, 2]),
        )
        frame = b"\0\1\2\3\4\5" + b"\0\1\2\3\4\6" + b"\x08\x00" + ip + tcp + payload
        out += struct.pack("!IIII", index, 0, len(frame), len(frame)) + frame
    return out


_TSHARK_FIELDS = (
    "frame.number",
    "seanchai.errors",
    "seanchai.rule",
    "seanchai.document",
    "seanchai.reference",
    "seanchai.url",
    "seanchai.explorer",
    "seanchai.corpus",
)


def _tshark(plugin: Path, capture: Path, *options: str) -> dict[int, dict]:
    """Each frame's seanchai fields, as tshark shows them through `plugin`."""
    fields = [arg for each in _TSHARK_FIELDS for arg in ("-e", each)]
    command = ["tshark", "-n", "-r", str(capture), "-X", f"lua_script:{plugin}"]
    done = subprocess.run(
        [*command, *options, "-T", "json", *fields],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Lua" not in done.stderr, done.stderr
    return {
        int(each["_source"]["layers"]["frame.number"][0]): each["_source"]["layers"]
        for each in json.loads(done.stdout)
    }


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("plugin") / "seanchai_diameter.lua"
    return _rules(out, "--application", "0", "--application", str(CX))


@pytest.fixture(scope="module")
def capture(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("capture") / "cx.pcap"
    out.write_bytes(_pcap([good_uar(), bad_uar(), error_uaa(), good_dwr()]))
    return out


_DWR_AT = "#rfc6733/5.5.1?name=Device-Watchdog-Request"


@pytest.mark.skipif(shutil.which("tshark") is None, reason="no tshark on PATH")
def test_tshark_reports_through_the_plugin(plugin, capture):
    frames = _tshark(plugin, capture)

    assert frames[1]["seanchai.errors"] == ["0"]
    assert int(frames[2]["seanchai.errors"][0]) >= 4
    assert "avp-missing" in frames[2]["seanchai.rule"]
    assert frames[3]["seanchai.errors"] == ["0"]
    assert frames[4]["seanchai.document"] == ["RFC6733"]
    # The command's definition, then each finding's rule, beneath it.
    assert frames[2]["seanchai.reference"][0].startswith("TS 29.229 clause 6.1.1,")
    assert "RFC 6733 section 4.3.1, page 44" in frames[2]["seanchai.reference"]
    assert frames[2]["seanchai.url"][0].startswith("https://www.etsi.org/")
    assert (
        "https://www.rfc-editor.org/rfc/rfc6733.html#section-4.3.1"
        in frames[2]["seanchai.url"]
    )
    assert frames[4]["seanchai.explorer"] == [wireshark.EXPLORER + _DWR_AT]


@pytest.mark.skipif(shutil.which("tshark") is None, reason="no tshark on PATH")
def test_the_explorer_preference_moves_or_drops_the_site_links(plugin, capture):
    moved = _tshark(
        plugin, capture, "-o", "seanchai.explorer_url:http://example.test/x/"
    )
    dropped = _tshark(plugin, capture, "-o", "seanchai.explorer_url:")

    assert moved[4]["seanchai.explorer"] == ["http://example.test/x/" + _DWR_AT]
    assert all(
        each.startswith("http://example.test/x/#")
        for frame in moved.values()
        for each in frame.get("seanchai.explorer", [])
    )
    assert not any("seanchai.explorer" in frame for frame in dropped.values())
    assert dropped[2]["seanchai.url"] == moved[2]["seanchai.url"]


_EXPLORER_LINE = re.compile(r'^local EXPLORER = "[^"\\]*" -- seanchai:explorer$')


def _marked(text: str) -> list[str]:
    return [line for line in text.splitlines() if _EXPLORER_LINE.match(line)]


def test_the_plugin_holds_one_explorer_line_and_one_versions_line(plugin):
    text = plugin.read_text("utf-8")
    unlinked = wireshark.generate(application_ids=[0], explorer="").text

    assert _marked(text) == [
        f'local EXPLORER = "{wireshark.EXPLORER}" -- seanchai:explorer'
    ]
    assert _marked(unlinked) == ['local EXPLORER = "" -- seanchai:explorer']
    # Near the top, and nowhere else: the rules leave the address to it.
    head = text.splitlines()[:8]
    assert _marked("\n".join(head))
    assert text.count(wireshark.EXPLORER) == 1
    (versions,) = [line for line in head if line.startswith("-- seanchai:versions ")]
    built = dictionary.build(
        model.Model.installed(), corpus_version=corpus.Corpus.installed().version
    )
    said = f"seanchai {built.seanchai_version}, corpus {built.corpus_version}"
    assert versions == f"-- seanchai:versions {said}"
    assert f"corpus={generator.lua_string(said)}" in text
    assert wireshark.VERSIONS_LINE.findall(text) == [said]
    assert wireshark.EXPLORER_LINE.findall(text) == [wireshark.EXPLORER]


@pytest.mark.parametrize("address", ['https://x/"', "https://x/\\", "https://x/\n"])
def test_an_explorer_address_the_marked_line_cannot_hold_is_refused(address):
    with pytest.raises(wireshark.PluginError):
        wireshark.generate(application_ids=[0], explorer=address)

    done = CliRunner().invoke(
        main, ["wireshark-plugin", "--explorer", address, "-o", "out.lua"]
    )
    assert done.exit_code == 2
    assert "--explorer" in done.output


@pytest.mark.skipif(shutil.which("tshark") is None, reason="no tshark on PATH")
def test_rewriting_the_explorer_line_moves_the_links(plugin, capture, tmp_path):
    rewritten = tmp_path / "seanchai_diameter.lua"
    # What a download page does: replace the one line, reading no Lua.
    lines = plugin.read_text("utf-8").splitlines(keepends=True)
    (index,) = [n for n, line in enumerate(lines) if _EXPLORER_LINE.match(line)]
    lines[index] = 'local EXPLORER = "https://mirror.test/e/" -- seanchai:explorer\n'
    rewritten.write_text("".join(lines), "utf-8")

    frames = _tshark(rewritten, capture)

    assert frames[4]["seanchai.explorer"] == ["https://mirror.test/e/" + _DWR_AT]
    assert (
        frames[4]["seanchai.corpus"] == _tshark(plugin, capture)[4]["seanchai.corpus"]
    )


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_a_diameter_uri_is_read_case_insensitively(lua):
    script = (
        f"local core = dofile({json.dumps(str(CORE))})\n"
        "for _, uri in ipairs({'AAA://Peer.Example.com:3868;transport=TCP',"
        " 'aaas://peer.example.com;protocol=diameter', 'http://peer'}) do\n"
        "  print(core.uri_problem(uri) or 'ok')\n"
        "end\n"
    )
    done = subprocess.run(
        [lua, "-e", script], check=True, capture_output=True, text=True
    )

    assert done.stdout.splitlines() == [
        "ok",
        "ok",
        "does not start with aaa:// or aaas://",
    ]


def gx_ccr() -> bytes:
    # 3GPP-User-Location-Info with the M bit, which TS 29.061 table 9a puts
    # under Must not.
    return message(
        272,
        R | P,
        GX,
        avp(263, b"pcef.example.com;1;2"),
        avp(258, u32(GX)),
        avp(264, b"pcef.example.com"),
        avp(296, b"example.com"),
        avp(283, b"example.com"),
        avp(416, u32(1)),
        avp(415, u32(0)),
        avp(22, b"\x82\x02\xf8\x10\x00\x01\x02\xf8\x10\x00\x00\x00\x01", vendor=TGPP),
    )


def rx_asr() -> bytes:
    # No Abort-Cause, which TS 29.214 clause 5.6.7's ASR requires.
    return message(
        274,
        R | P,
        RX,
        avp(263, b"pcrf.example.com;1;2"),
        avp(264, b"pcrf.example.com"),
        avp(296, b"example.com"),
        avp(283, b"example.com"),
        avp(293, b"af.example.com"),
        avp(258, u32(RX)),
    )


def _cited(result: dict, rule: str) -> list[dict]:
    return [
        reference
        for (_, each, _), reference in zip(
            result["findings"], result["cited"], strict=True
        )
        if each == rule
    ]


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_each_finding_cites_where_its_rule_is_written(lua, cited_rules, tmp_path):
    long_dwr = bytearray(good_dwr())
    long_dwr[3] += 4  # the header claims 4 octets the message lacks

    ccr, asr, dwr = _validate(
        lua, cited_rules, tmp_path, gx_ccr(), rx_asr(), bytes(long_dwr)
    )

    # A flag rule: the AVP-table row of the reading used.
    (flag,) = _cited(ccr, "flag-must-not")
    assert flag == {
        "document": "TS29.061",
        "clause": "16a.5",
        "page": "129",
        "table": "9a",
        "url": "https://www.etsi.org/deliver/etsi_ts/129000_129099/129061"
        "/19.01.00_60/ts_129061v190100p.pdf#page=129",
        "explorer": "https://sliva0.github.io/seanchai-explorer/#29061-j10/16a.5"
        "?name=3GPP-User-Location-Info",
        "text": "TS 29.061 clause 16a.5, table 9a, page 129",
    }
    assert any("(TS 29.061 table 9a)" in text for _, _, text in ccr["findings"])
    # A body's rule: the command's ABNF, which the command line cites too.
    assert asr["document"] == "TS29.214"
    missing = _cited(asr, "avp-missing")
    assert missing and all(each == asr["reference"] for each in missing)
    assert asr["reference"] == {
        "document": "TS29.214",
        "clause": "5.6.7",
        "page": "76",
        "table": None,
        "url": "https://www.etsi.org/deliver/etsi_ts/129200_129299/129214"
        "/19.03.00_60/ts_129214v190300p.pdf#page=76",
        "explorer": "https://sliva0.github.io/seanchai-explorer/#29214-j30/5.6.7"
        "?name=AS-Request",
        "text": "TS 29.214 clause 5.6.7, page 76",
    }
    # Framing: RFC 6733's section, at its anchor. The corpus places nothing
    # in section 3, so the explorer has nowhere to go.
    (length,) = _cited(dwr, "header-length")
    assert length == {
        "document": "RFC6733",
        "clause": "3",
        "page": "34",
        "table": None,
        "url": "https://www.rfc-editor.org/rfc/rfc6733.html#section-3",
        "explorer": None,
        "text": "RFC 6733 section 3, page 34",
    }


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
def test_an_empty_explorer_leaves_its_links_out(unlinked_rules, tmp_path):
    results = _validate(LUAS[-1], unlinked_rules, tmp_path, gx_ccr(), rx_asr())

    references = [
        each
        for result in results
        for each in (result["reference"], *result["cited"])
        if each is not None
    ]
    assert references
    assert all(each["explorer"] is None for each in references)
    assert all(each["url"] for each in references)


def test_every_reference_has_a_document_url_and_a_real_page():
    books = corpus.Corpus.installed()
    built_model = model.Model.build(books)
    places = generator.Places(books)
    rules = generator.rules_chunk(dictionary.build(built_model), built_model, places)

    assert places.citations and places.documents
    for entry, _ in places.documents.values():
        assert entry.spec.link or entry.spec.transcribed, entry.path
    for _, clause, page, _, _ in places.citations:
        assert clause
        assert page is None or (isinstance(page, int) and page > 0)
    # Every reading, command and answer-message the rules hold cites a place.
    for line in rules.splitlines():
        if line.startswith(("avps[", "answers[")):
            assert ",at=" in line, line[:120]
        if line.startswith("commands["):
            assert line.count(",at=") == line.count("abbreviation="), line[:120]
