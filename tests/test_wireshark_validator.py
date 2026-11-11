"""The Wireshark validator: its core under every Lua found here, and the whole
plugin under tshark, over messages encoded below.

The core is plain Lua for Wireshark 4.2's Lua 5.2 and 4.4's 5.4 alike; each
interpreter on PATH runs it (5.1 standing in for the oldest), and a test is
skipped where none is. The tshark test runs the generated plugin over a pcap
of the same messages, skipped without tshark.
"""

import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VALIDATOR = ROOT / "integrations" / "wireshark" / "validator"
LUAS = [name for name in ("lua5.1", "lua5.2", "lua5.3", "lua5.4") if shutil.which(name)]
CX = 16777216

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


@pytest.fixture(scope="module")
def rules(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("rules") / "rules.lua"
    subprocess.run(
        [
            sys.executable,
            str(VALIDATOR / "generate.py"),
            "--application",
            "0",
            "--application",
            str(CX),
            "--rules-only",
            "-o",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


_RUNNER = """
local core = dofile(arg[1])
local rules = dofile(arg[2])
local function unhex(text)
  return (text:gsub("..", function(pair) return string.char(tonumber(pair, 16)) end))
end
for index = 3, #arg do
  local result = core.validate(rules, unhex(arg[index]), {})
  local command = result.command and result.command.document or "-"
  io.write("message ", command, " ", tostring(result.form), "\\n")
  for _, each in ipairs(result.findings) do
    io.write(each.severity, " ", each.rule, " ", each.message, "\\n")
  end
end
"""


def _validate(lua: str, rules: Path, tmp_path: Path, *messages: bytes) -> list[dict]:
    runner = tmp_path / "runner.lua"
    runner.write_text(_RUNNER, "utf-8")
    done = subprocess.run(
        [lua, str(runner), str(VALIDATOR / "core.lua"), str(rules)]
        + [each.hex() for each in messages],
        check=True,
        capture_output=True,
        text=True,
    )
    results: list[dict] = []
    for line in done.stdout.splitlines():
        kind, _, rest = line.partition(" ")
        if kind == "message":
            document, form = rest.split(" ")
            results.append({"document": document, "form": form, "findings": []})
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


@pytest.mark.skipif(shutil.which("tshark") is None, reason="no tshark on PATH")
def test_tshark_reports_through_the_plugin(tmp_path):
    plugin = tmp_path / "seanchai_diameter.lua"
    subprocess.run(
        [
            sys.executable,
            str(VALIDATOR / "generate.py"),
            "--application",
            "0",
            "--application",
            str(CX),
            "-o",
            str(plugin),
        ],
        check=True,
        capture_output=True,
    )
    capture = tmp_path / "cx.pcap"
    capture.write_bytes(_pcap([good_uar(), bad_uar(), error_uaa(), good_dwr()]))

    done = subprocess.run(
        [
            "tshark",
            "-n",
            "-r",
            str(capture),
            "-X",
            f"lua_script:{plugin}",
            "-T",
            "json",
            "-e",
            "frame.number",
            "-e",
            "seanchai.errors",
            "-e",
            "seanchai.rule",
            "-e",
            "seanchai.document",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Lua" not in done.stderr, done.stderr
    frames = {
        int(each["_source"]["layers"]["frame.number"][0]): each["_source"]["layers"]
        for each in json.loads(done.stdout)
    }

    assert frames[1]["seanchai.errors"] == ["0"]
    assert int(frames[2]["seanchai.errors"][0]) >= 4
    assert "avp-missing" in frames[2]["seanchai.rule"]
    assert frames[3]["seanchai.errors"] == ["0"]
    assert frames[4]["seanchai.document"] == ["RFC6733"]


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_a_diameter_uri_is_read_case_insensitively(lua):
    script = (
        f"local core = dofile({json.dumps(str(VALIDATOR / 'core.lua'))})\n"
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
