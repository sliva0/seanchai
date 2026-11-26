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
from xml.etree import ElementTree

import pytest
from click.testing import CliRunner

from seanchai import corpus, dictionary, model, wireshark
from seanchai.cli import main
from seanchai.dad import ast
from seanchai.wireshark import _rules as generator

CORE = Path(wireshark.__file__).parent / "core.lua"
LUAS = [name for name in ("lua5.1", "lua5.2", "lua5.3", "lua5.4") if shutil.which(name)]
CX = 16777216
RX = 16777236
GX = 16777238
STA = 16777250
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
    # a warning, Auth-Session-State 7, which RFC 6733 section 8.11 does not
    # define.
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


# Gx, Rx and STa too, for references into TS 29.061, TS 29.212, TS 29.214 and
# TS 29.273.
_CITED = ("0", str(CX), str(RX), str(GX), str(STA))


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
    tostring(ref.table), ref.url or "-", ref.explorer or "-",
    ref.explorer_place or "-", ref.text }, "\\t")
end
for index = 3, #arg do
  local result = core.validate(rules, unhex(arg[index]), {})
  local command = result.command and result.command.document or "-"
  io.write("message ", command, " ", tostring(result.form), "\\n")
  io.write("ref ", reference(result.reference), "\\n")
  for _, each in ipairs(result.findings) do
    io.write(each.severity, " ", each.rule, " ", each.line, "\\n")
    io.write("ref ", reference(each.reference), "\\n")
  end
end
"""

_REFERENCE = (
    "document",
    "clause",
    "page",
    "table",
    "url",
    "explorer",
    "shows",
    "text",
)


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
    assert _rules_of(bad) >= {"avp-missing", "avp-position", "flag-must"}
    assert {"enum-value", "diameter-identity"} <= _rules_of(bad, "warn")
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
    assert int(frames[2]["seanchai.errors"][0]) >= 3
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


def test_the_plugin_is_written_as_utf8_with_lf_line_endings(plugin):
    # `seanchai wireshark-plugin -o` writes through `Plugin.write`. A CR would
    # keep a tool matching the marked line from finding it.
    data = plugin.read_bytes()

    assert b"\r" not in data
    assert data.decode("utf-8") == plugin.read_text("utf-8")
    assert re.search(rb'^local EXPLORER = "[^"\\]*" -- seanchai:explorer\n', data, re.M)


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
        "not aaa:// or aaas://",
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


def rx_asr(destination: bytes = b"af.example.com") -> bytes:
    # No Abort-Cause, which TS 29.214 clause 5.6.7's ASR requires.
    return message(
        274,
        R | P,
        RX,
        avp(263, b"pcrf.example.com;1;2"),
        avp(264, b"pcrf.example.com"),
        avp(296, b"example.com"),
        avp(283, b"example.com"),
        avp(293, destination),
        avp(258, u32(RX)),
    )


def sta_aaa() -> bytes:
    # TS 29.273 clause 5.2.2.3.4's AAA with Subscription-Id under the M bit,
    # which TS 29.273 re-uses from RFC 4006 with "Must not" in table
    # 5.2.3.1/2's M-bit column, where RFC 4006 section 8's AVP table puts M in
    # Must.
    subscription = avp(450, u32(1)) + avp(444, b"user@example.com")
    return message(
        265,
        P,
        STA,
        avp(263, b"aaa.example.com;1;2"),
        avp(258, u32(STA)),
        avp(268, u32(2001)),
        avp(264, b"aaa.example.com"),
        avp(296, b"example.com"),
        avp(274, u32(1)),
        avp(443, subscription),
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

    ccr, asr, dwr, aaa, empty, short = _validate(
        lua,
        cited_rules,
        tmp_path,
        gx_ccr(),
        rx_asr(),
        bytes(long_dwr),
        sta_aaa(),
        rx_asr(destination=b""),
        good_dwr()[:12],
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
        "shows": None,
        "text": "TS 29.061 clause 16a.5, table 9a, page 129",
    }
    assert any(
        text.endswith(": M bit set, must not be [TS 29.061 table 9a]")
        for _, _, text in ccr["findings"]
    )
    # A flag rule a re-used row's M-bit cell states: that row, not the
    # origin's AVP table, which says the opposite.
    assert aaa["document"] == "TS29.273"
    (m_bit,) = [
        reference
        for (_, rule, text), reference in zip(
            aaa["findings"], aaa["cited"], strict=True
        )
        if rule == "flag-must-not" and text.startswith("Subscription-Id: M bit")
    ]
    assert m_bit is not None
    assert m_bit["document"] == "TS29.273" != "RFC4006"
    assert (m_bit["clause"], m_bit["table"], m_bit["page"]) == (
        "5.2.3.1",
        "5.2.3.1/2",
        "71",
    )
    assert m_bit["text"] == "TS 29.273 clause 5.2.3.1, table 5.2.3.1/2, page 71"
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
        "shows": None,
        "text": "TS 29.214 clause 5.6.7, page 76",
    }
    # Framing: RFC 6733's section, at its anchor. The corpus places nothing
    # in section 3, so the explorer shows the command's definition instead.
    (length,) = _cited(dwr, "header-length")
    assert length == {
        "document": "RFC6733",
        "clause": "3",
        "page": "34",
        "table": None,
        "url": "https://www.rfc-editor.org/rfc/rfc6733.html#section-3",
        "explorer": wireshark.EXPLORER + _DWR_AT,
        "shows": "Device-Watchdog-Request, RFC 6733 section 5.5.1",
        "text": "RFC 6733 section 3, page 34",
    }
    # With no command to show, the document.
    (truncated,) = _cited(short, "header-truncated")
    assert truncated["explorer"] == wireshark.EXPLORER + "#rfc6733"
    assert truncated["shows"] == "RFC 6733"
    # A data format: RFC 6733 section 4.3.1, which the explorer cannot show,
    # so it shows where the AVP's type is stated.
    (identity,) = _cited(empty, "diameter-identity")
    assert identity == {
        "document": "RFC6733",
        "clause": "4.3.1",
        "page": "44",
        "table": None,
        "url": "https://www.rfc-editor.org/rfc/rfc6733.html#section-4.3.1",
        "explorer": wireshark.EXPLORER + "#rfc6733/6.5?name=Destination-Host",
        "shows": "Destination-Host, RFC 6733 section 6.5",
        "text": "RFC 6733 section 4.3.1, page 44",
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


@pytest.fixture(scope="module")
def whole() -> tuple[corpus.Corpus, generator.Places, str]:
    """The rules for the whole corpus, with the places they cite."""
    books = corpus.Corpus.installed()
    built_model = model.Model.build(books)
    places = generator.Places(books)
    rules = generator.rules_chunk(dictionary.build(built_model), built_model, places)
    return books, places, rules


def test_every_reference_has_a_document_url_and_a_real_page(whole):
    _, places, rules = whole

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


_LUA_STRING = r'"((?:[^"\\]|\\.)*)"'
_READING = re.compile(
    r'^avps\["([^"]*)"\]=\{name="([^"]*)",.*?,flags=\{must="([MVP]*)",may="[MVP]*",'
    r'should_not="([MVP]*)",must_not="([MVP]*)",application="[MVP]*"\}'
    r"(?:,at=\d+)?(?:,flags_at=(\d+|\{[^}]*\}))?"
)
_DOC = re.compile(rf"^docs\[(\d+)\]=\{{{_LUA_STRING},{_LUA_STRING},{_LUA_STRING},")
_CITE = re.compile(
    rf"^cites\[(\d+)\]=\{{(\d+),{_LUA_STRING},(\d+|false)(?:,(?:false|{_LUA_STRING}))?"
)
_M_BIT = {"must": "MUST", "must_not": "MUST-NOT"}
_COLUMN = {"must": "must", "must_not": "must_not", "should_not": "should_not"}


def _says(section, name: str, letter: str, rule: str) -> list[bool]:
    """Whether each row of `section` for `name` that places `letter` puts it
    under `rule`, as the `.dad` file prints it."""
    said = []
    for row in section.rows:
        if row.name != name:
            continue
        if isinstance(section, ast.AvpTable):
            columns = [
                column
                for column in ("must", "may", "should_not", "must_not")
                if letter in {flag.value for flag in getattr(row.flag_rules, column)}
            ]
            said += [column == rule for column in columns]
        elif letter == "M" and row.m_bit is not None:
            said.append(row.m_bit.value == _M_BIT.get(rule))
    return said


def test_each_flag_rule_cites_a_place_that_states_it(whole):
    # Read back from the rules' text and checked against the parsed `.dad`
    # files: a cited table's rows for the name agree with every reported
    # rule, an IETF V under Must not no row places cites RFC 6733 section
    # 4.1.1, and anything else cites a clause with no table.
    books, _, rules = whole
    by_stem = {entry.path.stem: entry for entry in books}
    docs: dict[str, corpus.Entry] = {}
    cites: dict[str, tuple[corpus.Entry, str, int | None, str | None]] = {}
    readings = []
    for line in rules.splitlines():
        if found := _DOC.match(line):
            docs[found[1]] = by_stem[found[4]]
        elif found := _CITE.match(line):
            page = None if found[4] == "false" else int(found[4])
            cites[found[1]] = (docs[found[2]], found[3], page, found[5])
        elif line.startswith("avps["):
            found = _READING.match(line)
            assert found, line[:160]
            readings.append(found.groups())
    counts = {"row": 0, "default": 0, "clause": 0}
    for identity, name, must, should_not, must_not, flags_at in readings:
        reported = [
            (letter, rule)
            for rule, letters in (
                ("must", must),
                ("must_not", must_not),
                ("should_not", should_not),
            )
            for letter in letters
        ]
        if not reported:
            continue
        assert flags_at, identity
        if flags_at.startswith("{"):
            numbers = dict(each.split("=") for each in flags_at[1:-1].split(","))
        else:
            numbers = {letter: flags_at for letter, _ in reported}
        for letter, rule in reported:
            entry, clause, page, table = cites[numbers[letter]]
            said = [
                agrees
                for section in entry.spec.sections
                if isinstance(section, ast.AvpTable | ast.ReusedAvps)
                and (section.source.section, section.source.page, section.table)
                == (clause, page, table)
                for agrees in _says(section, name, letter, _COLUMN[rule])
            ]
            where = (identity, letter, rule, entry.reference, clause, table)
            if said:
                assert all(said), where
                counts["row"] += 1
            elif (entry.reference, clause) == ("RFC6733", "4.1.1"):
                assert (letter, rule) == ("V", "must_not"), where
                assert identity.startswith("0:"), where
                counts["default"] += 1
            else:
                assert table is None, where
                counts["clause"] += 1
    assert counts["row"] > 0
    print(f"flag rules cited: {counts}")


def _odd_messages() -> list[bytes]:
    """Messages breaking, between them, most rules the core checks."""
    padded = bytearray(avp(264, b"peer.example.co"))
    padded[-1] = 1  # a nonzero padding octet
    reserved = avp(296, b"example.com", flags=M | 0x01)
    # An answer with the T bit, and the E bit with a Result-Code of success.
    answer_t = message(
        280, E | 0x10, 0, avp(264, b"p.example.com"), avp(268, u32(2001))
    )
    return [
        good_dwr()[:12],
        message(280, R, 0, bytes(padded), reserved, avp(9999, b"", flags=M)),
        message(280, R, 0, avp(9998, b"", flags=0), avp(1, b"\xff")),
        message(999, R, 0),
        answer_t,
        error_uaa()[:-1],
        bad_uar(),
        failed_uaa(b""),
        gx_ccr(),
        rx_asr(destination=b""),
        sta_aaa(),
    ]


# No document defines what these report, so they cite nothing.
_UNCITED = {"unknown-command", "unknown-avp"}


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
def test_every_finding_has_an_explorer_link(cited_rules, tmp_path):
    results = _validate(LUAS[-1], cited_rules, tmp_path, *_odd_messages())

    seen = set()
    for result in results:
        for (_, rule, text), reference in zip(
            result["findings"], result["cited"], strict=True
        ):
            seen.add(rule)
            if rule in _UNCITED:
                assert reference is None, text
                continue
            assert reference and reference["explorer"], (rule, text)
            assert reference["explorer"].startswith(wireshark.EXPLORER + "#")
    assert (
        seen
        >= {
            "header-truncated",
            "header-length",
            "header-t-bit",
            "avp-padding",
            "avp-reserved-flags",
            "avp-missing",
            "unknown-mandatory",
            "utf8",
            "diameter-identity",
            "flag-must",
            "flag-must-not",
            "e-bit-unexpected",
        }
        | _UNCITED
    )


_EVERY_CITE = """
local core = dofile(arg[1])
local rules = dofile(arg[2])
local explorer = arg[3]
local missing = 0
local command = { at = nil, name = "X" }
for index = 4, #arg do
  local rule = arg[index]
  local cites = { false }
  for number in pairs(rules.cites) do
    cites[#cites + 1] = number
  end
  for _, cite in ipairs(cites) do
    for _, known in ipairs({ false, true }) do
      local found = { rule = rule, cite = cite or nil, cite_name = "X" }
      local result = { findings = { found } }
      if known then
        command.at = cite or nil
        result.command = command
      end
      core.cited(rules, result, { explorer = explorer })
      if found.reference and not found.reference.explorer then
        missing = missing + 1
        io.write(rule, " ", tostring(cite), "\\n")
      elseif not found.reference and cite then
        io.write("unread ", rule, " ", tostring(cite), "\\n")
      end
    end
  end
end
io.write("missing ", missing, "\\n")
"""


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
def test_no_finding_citing_any_place_lacks_an_explorer_link(whole, tmp_path):
    # Every rule core.lua can report, citing each place the whole corpus's
    # rules hold, or none (a base check fills in its RFC 6733 section), with
    # and without a command: wherever a reference is given, so is an
    # explorer link.
    _, _, chunk = whole
    kinds = sorted(
        set(
            re.findall(
                r'(?:ERROR|WARN|NOTE|severity), "([a-z0-9-]+)"', CORE.read_text()
            )
        )
    )
    assert len(kinds) > 30
    rules = tmp_path / "rules.lua"
    rules.write_text(chunk, "utf-8")
    script = tmp_path / "every.lua"
    script.write_text(_EVERY_CITE, "utf-8")
    done = subprocess.run(
        [LUAS[-1], str(script), str(CORE), str(rules), wireshark.EXPLORER, *kinds],
        check=True,
        capture_output=True,
        text=True,
    )

    assert done.stdout.splitlines() == ["missing 0"]


# TS 29.272's interpreted constraints, as S6a messages break them.
S6A = 16777251


def _s6a_base(origin: bytes) -> list[bytes]:
    return [
        avp(263, origin + b";1;2"),
        avp(260, avp(266, u32(TGPP)) + avp(258, u32(S6A))),
        avp(277, u32(1)),
        avp(264, origin + b".example.com"),
        avp(296, b"example.com"),
    ]


def s6a_ulr(visited: bytes, sgsn: bytes = b"\x21\x43\xf5") -> bytes:
    return message(
        316,
        R | P,
        S6A,
        *_s6a_base(b"mme"),
        avp(283, b"example.com"),
        avp(1, b"001010123456789"),
        avp(1032, u32(1004), vendor=TGPP),
        avp(1405, u32(0), vendor=TGPP),
        avp(1407, visited, vendor=TGPP),
        avp(1489, sgsn, vendor=TGPP),
    )


def s6a_ula(result: int) -> bytes:
    return message(
        316,
        P,
        S6A,
        avp(263, b"mme;1;2"),
        avp(260, avp(266, u32(TGPP)) + avp(258, u32(S6A))),
        avp(268, u32(result)),
        avp(277, u32(1)),
        avp(264, b"hss.example.com"),
        avp(296, b"example.com"),
        avp(1406, u32(0), vendor=TGPP),
    )


def s6a_dsr(flags: int, context: int) -> bytes:
    return message(
        320,
        R | P,
        S6A,
        *_s6a_base(b"hss"),
        avp(293, b"mme.example.com"),
        avp(283, b"example.com"),
        avp(1, b"001010123456789"),
        avp(1421, u32(flags), vendor=TGPP),
        avp(1423, u32(context), vendor=TGPP),
    )


@pytest.fixture(scope="module")
def s6a_rules(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("rules") / "rules.lua"
    return _rules(out, "--application", str(S6A), "--rules-only")


def _constraint_findings(result: dict) -> list[tuple[str, str]]:
    return [
        (rule, text)
        for kind, rule, text in result["findings"]
        if rule.startswith("constraint-") and kind == "note"
    ]


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_interpreted_constraints_are_checked_and_cited(lua, s6a_rules, tmp_path):
    clean = _validate(
        lua,
        s6a_rules,
        tmp_path,
        s6a_ulr(b"\x62\xf2\x10"),
        s6a_ula(2001),
        s6a_dsr(1 << 3, 5),
    )
    broken_plmn, broken_sgsn, failed_ula, broken_dsr = _validate(
        lua,
        s6a_rules,
        tmp_path,
        s6a_ulr(b"\x62\xe2\x10"),
        s6a_ulr(b"\x62\xf2\x10", sgsn=b"\x21\xf3\x65"),
        s6a_ula(5001),
        s6a_dsr(1, 0),
    )

    for result in clean:
        assert _constraint_findings(result) == [], result
    ((rule, text),) = _constraint_findings(broken_plmn)
    assert rule == "constraint-encoding"
    assert text == (
        "Visited-PLMN-Id: MNC digit 3 is neither a digit nor the '1111' filler"
        " [TS 29.272 7.3.9, interpreted]"
    )
    cited = _cited(broken_plmn, "constraint-encoding")
    assert [(each["clause"], each["page"]) for each in cited] == [("7.3.9", "103")]
    assert [rule for rule, _ in _constraint_findings(broken_sgsn)] == [
        "constraint-encoding"
    ]
    # RFC 6733 section 7.1.5's Failed-AVP holds in S6a's answers too:
    # DIAMETER_AVP_UNSUPPORTED (5001) without one breaks it.
    failed = dict(_constraint_findings(failed_ula))
    assert sorted(failed) == ["constraint-present-if", "constraint-requires"]
    assert "Result-Code = DIAMETER_SUCCESS" in failed["constraint-requires"]
    assert failed["constraint-present-if"].startswith("ULA: missing Failed-AVP")
    assert sorted(rule for rule, _ in _constraint_findings(broken_dsr)) == [
        "constraint-exclude",
        "constraint-requires",
    ]
    (table,) = {each["table"] for each in _cited(broken_dsr, "constraint-exclude")}
    assert table == "5.2.2.2.1/1"
    # A predicate names the member it is of, the conditions after it.
    assert sorted(text for _, text in _constraint_findings(broken_dsr))[1] == (
        "Context-Identifier: not allowed without DSR-Flags bit"
        ' "PDN subscription contexts Withdrawal" or "PDP contexts Withdrawal"'
        " [TS 29.272 5.2.2.2.1, interpreted]"
    )


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_a_finding_line_names_its_place_shortened_and_its_source(lua, s6a_rules):
    # A path past one parent keeps its last two names; an interpreted rule
    # says so after its source; a list of more than three members is cut
    # short on the line and given whole for the expert info.
    script = (
        f"local core = dofile({json.dumps(str(CORE))})\n"
        f"local rules = dofile({json.dumps(str(s6a_rules))})\n"
        "local deep = { rule = 'constraint-encoding', severity = 'note',\n"
        "  interpreted = true, message = 'not x', path = 'A > B > C > D' }\n"
        "local near = { rule = 'avp-missing', severity = 'error',\n"
        "  message = 'missing E', path = 'A > B' }\n"
        "local top = { rule = 'avp-truncated', severity = 'error', message = 'm' }\n"
        "local long = { rule = 'constraint-members', severity = 'note',\n"
        "  interpreted = true, message = 'short', detail = 'whole', path = 'G' }\n"
        "local found = { deep, near, top, long }\n"
        "core.cited(rules, { findings = found, label = 'ULR' }, {})\n"
        "for _, each in ipairs({ deep, near, top, long }) do\n"
        "  print(each.line)\n"
        "end\n"
        "print(long.full)\n"
    )
    done = subprocess.run(
        [lua, "-e", script], check=True, capture_output=True, text=True
    )

    assert done.stdout.splitlines() == [
        "… > C > D: not x [interpreted]",
        "A > B: missing E",
        "ULR: m [RFC 6733 4.1]",
        "G: short [interpreted]",
        "G: whole [interpreted]",
    ]


_PLACES = """
local core = dofile(arg[1])
local rules = dofile(arg[2])
local function unhex(text)
  return (text:gsub("..", function(pair) return string.char(tonumber(pair, 16)) end))
end
for index = 3, #arg do
  local result = core.validate(rules, unhex(arg[index]), {})
  for _, each in ipairs(result.findings) do
    print(table.concat({ each.severity, each.rule, each.offset, each.length,
      each.path, each.line }, "\\t"))
  end
end
"""


def _places(lua: str, rules: Path, tmp_path: Path, pdu: bytes) -> list[tuple]:
    """Each finding of `pdu` as (severity, rule, offset, length, path, line)."""
    runner = tmp_path / "places.lua"
    runner.write_text(_PLACES, "utf-8")
    done = subprocess.run(
        [lua, str(runner), str(CORE), str(rules), pdu.hex()],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        (severity, rule, int(offset), int(length), path, line)
        for severity, rule, offset, length, path, line in (
            each.split("\t") for each in done.stdout.splitlines()
        )
    ]


def _spans(pdu: bytes, first: int = 20, last: int | None = None) -> list[tuple]:
    """The AVPs of a run of `pdu`, each (code, offset, span), its span the
    AVP with its padding, as Wireshark's Diameter tree spans it."""
    last = len(pdu) if last is None else last
    found = []
    while first < last:
        code = int.from_bytes(pdu[first : first + 4])
        length = int.from_bytes(pdu[first + 5 : first + 8])
        span = min(length + -length % 4, last - first)
        found.append((code, first, span))
        first += span
    return found


def _inside(pdu: bytes, span: tuple) -> list[tuple]:
    """The members of the vendor-specific grouped AVP at `span`."""
    _, offset, octets = span
    return _spans(pdu, offset + 12, offset + octets)


def _features(*, vendor_flags: int = M, listed: bool = True, flags: int = 0) -> bytes:
    inner = avp(266, u32(TGPP), flags=vendor_flags) + avp(629, u32(1), vendor=TGPP)
    if listed:
        inner += avp(630, u32(1), vendor=TGPP)
    return avp(628, inner, vendor=TGPP, flags=flags)


def several_uar(origin: bytes = b"icscf.example.com") -> bytes:
    """A UAR with three Supported-Features, the first with a reserved flag,
    the second without its Feature-List, the third's Vendor-Id without the M
    bit; two Public-Identity, one allowed; no User-Name; and the one
    Visited-Network-Identifier without the M bit."""
    session, application, auth, _, realm = _base()
    return message(
        300,
        R | P,
        CX,
        session,
        application,
        auth,
        avp(264, origin),
        realm,
        avp(283, b"example.com"),
        _features(flags=0x01),
        _features(listed=False),
        _features(vendor_flags=0),
        avp(601, b"sip:user@example.com", vendor=TGPP),
        avp(601, b"sip:other@example.com", vendor=TGPP),
        avp(600, b"example.com", vendor=TGPP, flags=0),
    )


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_a_finding_names_its_instance_and_sits_on_its_octets(lua, rules, tmp_path):
    """Among several AVPs of one identity a path numbers each, from 1, the
    finding's own AVP as its parents; a sole one is named alone. A finding is
    on the octets of the AVP instance it is about, padding and all; one about
    what a grouped AVP lacks on that AVP's, and about what the message lacks
    on the message's."""
    pdu = several_uar()
    found = {
        (rule, path): (offset, length)
        for _, rule, offset, length, path, _ in _places(lua, rules, tmp_path, pdu)
    }
    top = _spans(pdu)
    features = [each for each in top if each[0] == 628]
    identities = [each for each in top if each[0] == 601]
    (visited,) = [each for each in top if each[0] == 600]
    vendor_id = _inside(pdu, features[2])[0]

    def at(span: tuple) -> tuple[int, int]:
        return span[1], span[2]

    assert found[("avp-reserved-flags", "Supported-Features[1]")] == at(features[0])
    assert found[("avp-missing", "Supported-Features[2]")] == at(features[1])
    assert found[("flag-must", "Supported-Features[3] > Vendor-Id")] == at(vendor_id)
    assert found[("avp-occurrences", "Public-Identity[2]")] == at(identities[1])
    assert found[("flag-must", "Visited-Network-Identifier")] == at(visited)
    assert found[("avp-missing", "UAR")] == (0, len(pdu))
    # Every finding's octets are those of an AVP instance of the message, or
    # the message's.
    instances = {at(each) for each in top}
    for each in features:
        instances |= {at(member) for member in _inside(pdu, each)}
    assert set(found.values()) <= instances | {(0, len(pdu))}


@pytest.mark.skipif(shutil.which("tshark") is None, reason="no tshark on PATH")
def test_tshark_puts_each_finding_on_its_avps_octets(plugin, tmp_path):
    """Each finding, and its expert info, spans the octets of the AVP
    Wireshark's own Diameter tree draws for the instance, so selecting it marks
    that AVP; one about what the message lacks spans the message."""
    capture = tmp_path / "several.pcap"
    capture.write_bytes(_pcap([several_uar()]))
    done = subprocess.run(
        [
            "tshark",
            "-n",
            "-r",
            str(capture),
            "-X",
            f"lua_script:{plugin}",
            "-T",
            "pdml",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    fields = list(ElementTree.fromstring(done.stdout).iter("field"))

    def span(field: ElementTree.Element) -> tuple[int, int]:
        return int(field.get("pos", "0")), int(field.get("size", "0"))

    avps = {span(each) for each in fields if each.get("name") == "diameter.avp"}
    (pdu,) = [
        (int(each.get("pos", "0")), int(each.get("size", "0")))
        for each in ElementTree.fromstring(done.stdout).iter("proto")
        if each.get("name") == "diameter"
    ]
    findings = [each for each in fields if each.get("name") == "seanchai.finding"]
    # "Error: place: problem [source]", the place holding no ": ".
    places = {each.get("show", "").split(": ")[1]: span(each) for each in findings}
    assert len(findings) >= 6
    for each in findings:
        assert span(each) in avps | {pdu}, each.get("show")
        (expert,) = [f for f in each if f.get("name") == "_ws.expert"]
        assert expert.get("pos") == each.get("pos")
    assert places["Supported-Features[3] > Vendor-Id"] in avps
    assert places["Supported-Features[2]"] in avps
    assert places["Public-Identity[2]"] in avps
    assert places["UAR"] == pdu


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_a_framing_finding_numbers_its_avp_among_the_run(lua, rules, tmp_path):
    """A finding parse_avps makes, before the body is read, numbers its AVP
    as the run's other findings do."""
    padded = bytearray(avp(264, b"peer.example.co"))
    padded[-1] = 1
    pdu = message(
        280,
        R,
        0,
        avp(264, b"peer.example.com"),
        bytes(padded),
        avp(296, b"example.com"),
    )
    found = [
        (rule, path, offset)
        for _, rule, offset, _, path, _ in _places(lua, rules, tmp_path, pdu)
    ]
    second = _spans(pdu)[1]

    assert ("avp-padding", "Origin-Host[2]", second[1]) in found


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_a_host_names_character_alone_is_a_warning(lua, rules, tmp_path):
    """RFC 6733 section 4.3.1 says "FQDN" and never lists its characters, and
    test tools name peers cx_emulator: such a character alone is a warning,
    while an empty label, beside it or not, is still an error, in a
    DiameterIdentity and a DiameterURI's host alike."""
    script = (
        f"local core = dofile({json.dumps(str(CORE))})\n"
        "for _, text in ipairs({'cx_emulator', 'cx_emulator..example.com',\n"
        "  'example..com'}) do\n"
        "  local problem, weak = core.identity_problem(text)\n"
        "  print(problem, tostring(weak))\n"
        "end\n"
        "for _, uri in ipairs({'aaa://cx_emulator.example.com;transport=tcp',\n"
        "  'aaa://cx_emulator.example.com:99999', 'aaa://a..b'}) do\n"
        "  local problem, weak = core.uri_problem(uri)\n"
        "  print(problem, tostring(weak))\n"
        "end\n"
    )
    done = subprocess.run(
        [lua, "-e", script], check=True, capture_output=True, text=True
    )
    shown = _places(lua, rules, tmp_path, good_uar_from(b"cx_emulator"))

    assert done.stdout.splitlines() == [
        "a character no host name holds\ttrue",
        "an empty label\tnil",
        "an empty label\tnil",
        "host: a character no host name holds\ttrue",
        "port above 65535\tnil",
        "host: an empty label\tnil",
    ]
    assert [(severity, rule, line) for severity, rule, _, _, _, line in shown] == [
        (
            "warn",
            "diameter-identity",
            "Origin-Host: a character no host name holds [RFC 6733 4.3.1]",
        )
    ]


def good_uar_from(origin: bytes) -> bytes:
    """`good_uar` sent by `origin`."""
    session, application, auth, _, realm = _base()
    return message(
        300,
        R | P,
        CX,
        session,
        application,
        auth,
        avp(264, origin),
        realm,
        avp(283, b"example.com"),
        avp(1, b"user@example.com"),
        avp(601, b"sip:user@example.com", vendor=TGPP),
        avp(600, b"example.com", vendor=TGPP),
    )


# TS 29.273's applications, each setting Feature-List-ID to 1 in a clause of
# its own (5.2.3.10 for STa, 7.2.3.2 for SWm).
SWM = 16777264


@pytest.fixture(scope="module")
def sta_swm_rules(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("rules") / "rules.lua"
    return _rules(
        out, "--application", str(STA), "--application", str(SWM), "--rules-only"
    )


def _aar(application: int, vendor: int, list_id: int) -> bytes:
    features = (
        avp(266, u32(vendor))
        + avp(629, u32(list_id), vendor=TGPP)
        + avp(630, u32(1), vendor=TGPP)
    )
    return message(
        265,
        R | P,
        application,
        avp(263, b"aaa.example.com;1;2"),
        avp(258, u32(application)),
        avp(264, b"gw.example.com"),
        avp(296, b"example.com"),
        avp(283, b"example.com"),
        avp(1, b"001010123456789@example.com"),
        avp(628, features, vendor=TGPP),
    )


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_a_grouped_avps_rule_read_for_one_application_holds_there(
    lua, sta_swm_rules, tmp_path
):
    """TS 29.273's Feature-List-ID 1, of the 3GPP list alone, is checked
    within Supported-Features in the messages of the application whose clause
    sets it, so an STa and an SWm AAR each break it once, citing their own
    clause, and another vendor's list numbered 2 breaks nothing."""
    sta, swm, vendor = _validate(
        lua,
        sta_swm_rules,
        tmp_path,
        _aar(STA, TGPP, 2),
        _aar(SWM, TGPP, 2),
        _aar(SWM, 9, 2),
    )
    for result, clause in ((sta, "5.2.3.10"), (swm, "7.2.3.2")):
        found = [
            text
            for rule, text in _constraint_findings(result)
            if "Feature-List" in text
        ]
        assert len(found) == 1, found
        assert found[0].startswith(
            "Supported-Features > Feature-List-ID: 2, but only 1"
        )
        assert [each["clause"] for each in _cited(result, "constraint-values")] == [
            clause
        ]
    assert not [text for _, text in _constraint_findings(vendor) if "Feature" in text]


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_base_protocols_rules_on_every_answer_hold_in_each(
    lua, s6a_rules, tmp_path
):
    """RFC 6733's "MUST NOT be present in answer messages" (section 6.5)
    holds in S6a's ULA, which TS 29.272 prints, and section 7.1.5's
    Failed-AVP in an <answer-message> with the E bit set."""
    destination = message(
        316,
        P,
        S6A,
        avp(263, b"mme;1;2"),
        avp(260, avp(266, u32(TGPP)) + avp(258, u32(S6A))),
        avp(268, u32(2001)),
        avp(277, u32(1)),
        avp(264, b"hss.example.com"),
        avp(296, b"example.com"),
        avp(293, b"mme.example.com"),
        avp(1406, u32(0), vendor=TGPP),
    )
    error = message(
        316,
        P | E,
        S6A,
        avp(263, b"mme;1;2"),
        avp(264, b"hss.example.com"),
        avp(296, b"example.com"),
        avp(268, u32(5004)),
    )
    # Two of them: broken by each alike, said once, without a number.
    twice = message(
        316,
        P,
        S6A,
        avp(263, b"mme;1;2"),
        avp(260, avp(266, u32(TGPP)) + avp(258, u32(S6A))),
        avp(268, u32(2001)),
        avp(277, u32(1)),
        avp(264, b"hss.example.com"),
        avp(296, b"example.com"),
        avp(293, b"mme.example.com"),
        avp(293, b"mme2.example.com"),
        avp(1406, u32(0), vendor=TGPP),
    )
    ula, answer, both = _validate(lua, s6a_rules, tmp_path, destination, error, twice)
    for each in (ula, both):
        absent = [f for f in _constraint_findings(each) if f[0] == "constraint-absent"]
        assert absent == [
            (
                "constraint-absent",
                "Destination-Host: not allowed [RFC 6733 6.5, interpreted]",
            )
        ]
    found = [
        text
        for rule, text in _constraint_findings(answer)
        if rule == "constraint-present-if"
    ]
    assert len(found) == 1 and "missing Failed-AVP" in found[0], found
    assert "[RFC 6733 7.1.5, interpreted]" in found[0]


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_e_bit_is_held_to_the_result_codes_class(lua, s6a_rules, tmp_path):
    """RFC 6733 sections 7.1.3 to 7.2: a protocol error only with the E bit,
    a transient failure and a success only without it, and a permanent
    failure either way, section 7.1.5 letting an <answer-message> carry it
    with the E bit."""

    def answer(flags: int, code: int) -> bytes:
        return message(
            316,
            flags,
            S6A,
            avp(263, b"mme;1;2"),
            avp(264, b"hss.example.com"),
            avp(296, b"example.com"),
            avp(268, u32(code)),
            avp(279, avp(1, b"001010123456789")),
        )

    results = _validate(
        lua,
        s6a_rules,
        tmp_path,
        answer(P | E, 5004),
        answer(P, 3002),
        answer(P | E, 3002),
        answer(P | E, 4001),
        answer(P | E, 2001),
    )

    def e_bit(result: dict) -> set[str]:
        return {rule for _, rule, _ in result["findings"] if rule.startswith("e-bit")}

    assert [e_bit(each) for each in results] == [
        set(),
        {"e-bit-missing"},
        set(),
        {"e-bit-transient"},
        {"e-bit-unexpected"},
    ]
    (transient,) = _cited(results[3], "e-bit-transient")
    assert transient["clause"] == "7.1.4"
