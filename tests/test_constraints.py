"""The codecs and value rules of interpreted constraints, over byte vectors:
`seanchai.constraints` in Python and the Wireshark plugin's `core.lua` under
every Lua on PATH must agree on each."""

import json
import shutil
import struct
import subprocess
from pathlib import Path
from typing import cast

import pytest

from seanchai import constraints, wireshark
from seanchai.dad import ast, parser
from seanchai.dad.ast import Codec, DataType

CORE = Path(wireshark.__file__).parent / "core.lua"


def _rule(text: str) -> ast.ConstraintRule:
    """One rule, as an interpreted-constraints block spells it."""
    spec = parser.parse(
        "; Specification: 3GPP TS 29.999\n; Vendor-ID: 10415\n\n\n"
        "; Type: Interpreted Constraints\n; AVP: Example\n; Section: 7.3.1\n"
        f'; Versions: *..*\n"Read."\n    {text}\n'
    )
    block = spec.sections[0]
    assert isinstance(block, ast.InterpretedConstraints)
    rule = block.body[1]
    assert not isinstance(rule, ast.Quote)
    return rule


LUAS = [name for name in ("lua5.1", "lua5.2", "lua5.3", "lua5.4") if shutil.which(name)]

# (codec, payload, whether the layout holds)
VECTORS = [
    # TS 29.002 TBCD: odd count, "1111" filling the last high nibble.
    pytest.param(Codec.E164_TBCD, b"\x21\x43\xf5", True, id="tbcd-odd"),
    pytest.param(Codec.E164_TBCD, b"\x21\x43\x65", True, id="tbcd-even"),
    pytest.param(Codec.E164_TBCD, b"\xf1", True, id="tbcd-one-digit"),
    pytest.param(Codec.E164_TBCD, b"\x21\xf3\x65", False, id="tbcd-filler-inside"),
    pytest.param(Codec.E164_TBCD, b"\x1f", False, id="tbcd-filler-low"),
    pytest.param(Codec.E164_TBCD, b"\x2a", False, id="tbcd-not-decimal"),
    pytest.param(Codec.E164_TBCD, bytes(8), False, id="tbcd-16-digits"),
    pytest.param(Codec.E164_TBCD, b"\x21" * 7 + b"\xf1", True, id="tbcd-15-digits"),
    pytest.param(Codec.E164_TBCD, b"", False, id="tbcd-empty"),
    # TS 29.272 table 7.3.9/1: MCC 262, MNC 01; MCC 310, MNC 260.
    pytest.param(Codec.PLMN_ID, b"\x62\xf2\x10", True, id="plmn-2-digit-mnc"),
    pytest.param(Codec.PLMN_ID, b"\x13\x00\x62", True, id="plmn-3-digit-mnc"),
    pytest.param(Codec.PLMN_ID, b"\x62\xe2\x10", False, id="plmn-bad-filler"),
    pytest.param(Codec.PLMN_ID, b"\x6a\xf2\x10", False, id="plmn-bad-mcc"),
    pytest.param(Codec.PLMN_ID, b"\x62\xf2\x1b", False, id="plmn-bad-mnc"),
    pytest.param(Codec.PLMN_ID, b"\x62\xf2", False, id="plmn-short"),
    pytest.param(Codec.PLMN_ID, b"\x62\xf2\x10\x00", False, id="plmn-long"),
    pytest.param(Codec.PLMN_ID_PREFIX, b"\x62\xf2\x10\x01\x02\x03", True, id="prefix"),
    pytest.param(Codec.PLMN_ID_PREFIX, b"\x62\xe2\x10\x00", False, id="prefix-bad"),
    pytest.param(Codec.DIGITS, b"35209900176148", True, id="digits"),
    pytest.param(Codec.DIGITS, b"3520990017614a", False, id="digits-letter"),
    pytest.param(Codec.DIGITS, b"", False, id="digits-empty"),
    pytest.param(Codec.DIGITS, b"\xff", False, id="digits-not-utf8"),
    pytest.param(Codec.LABELS, b"ims.mnc001.mcc001.gprs", True, id="labels"),
    pytest.param(Codec.LABELS, b"internet", True, id="labels-one"),
    pytest.param(Codec.LABELS, b"a..b", False, id="labels-empty-label"),
    pytest.param(Codec.LABELS, b".a", False, id="labels-leading-dot"),
    pytest.param(Codec.LABELS, b"*", True, id="labels-star"),
    pytest.param(Codec.APN, b"*", True, id="apn-wild-card"),
    pytest.param(Codec.APN, b"internet.example", True, id="apn"),
    pytest.param(Codec.APN, b"internet.", False, id="apn-trailing-dot"),
    pytest.param(
        Codec.PLMN_DOMAIN, b"mnc001.mcc001.3gppnetwork.org", True, id="domain"
    ),
    pytest.param(
        Codec.PLMN_DOMAIN, b"MNC01.MCC001.3gppnetwork.org", True, id="domain-case"
    ),
    pytest.param(
        Codec.PLMN_DOMAIN,
        b"epc.mnc001.mcc001.3gppnetwork.org",
        False,
        id="domain-prefixed",
    ),
    pytest.param(
        Codec.PLMN_DOMAIN, b"mnc1.mcc001.3gppnetwork.org", False, id="domain-short"
    ),
    pytest.param(
        Codec.EPC_PLMN_DOMAIN,
        b"epc.mnc001.mcc001.3gppnetwork.org",
        True,
        id="epc-domain",
    ),
    pytest.param(
        Codec.EPC_PLMN_DOMAIN,
        b"mnc001.mcc001.3gppnetwork.org",
        False,
        id="epc-domain-bare",
    ),
    pytest.param(Codec.IP_ADDRESS, b"\x00\x01" + bytes(4), True, id="ipv4"),
    pytest.param(Codec.IP_ADDRESS, b"\x00\x02" + bytes(16), True, id="ipv6"),
    pytest.param(Codec.IP_ADDRESS, b"\x00\x01" + bytes(16), False, id="ipv4-long"),
    pytest.param(Codec.IP_ADDRESS, b"\x00\x08" + bytes(4), False, id="e164-family"),
    pytest.param(Codec.IP_ADDRESS, b"\x01", False, id="no-family"),
    pytest.param(Codec.TIME_ZONE, b"+8", True, id="zone-ahead"),
    pytest.param(Codec.TIME_ZONE, b"-12", True, id="zone-behind"),
    pytest.param(Codec.TIME_ZONE, b"8", False, id="zone-unsigned"),
    pytest.param(Codec.TIME_ZONE, b"+8:00", False, id="zone-clock"),
    pytest.param(Codec.MAC_ADDRESS, b"00-10-A4-23-19-C0", True, id="mac"),
    pytest.param(Codec.MAC_ADDRESS, b"00-10-a4-23-19-c0", False, id="mac-lower"),
    pytest.param(Codec.MAC_ADDRESS, b"00:10:A4:23:19:C0", False, id="mac-colons"),
    pytest.param(Codec.MAC_ADDRESS, b"00-10-A4-23-19", False, id="mac-short"),
    pytest.param(Codec.ELEMENT, b"\xff\xff", True, id="element-unchecked"),
]


def _run(
    lua: str, tmp_path: Path, script: str, arguments: list[str]
) -> subprocess.CompletedProcess[str]:
    runner = tmp_path / "runner.lua"
    runner.write_text(script, "utf-8")
    return subprocess.run(
        [lua, str(runner), *arguments], check=True, capture_output=True, text=True
    )


@pytest.mark.parametrize(("codec", "payload", "holds"), VECTORS)
def test_each_codec_reads_its_layout(codec, payload, holds):
    assert (constraints.codec_problem(codec, payload) is None) is holds


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_plugin_reads_each_layout_as_python_does(lua, tmp_path):
    cases = [
        (codec, payload, holds)
        for codec, payload, holds in (
            cast("tuple[Codec, bytes, bool]", each.values) for each in VECTORS
        )
        if codec is not Codec.ELEMENT
    ]
    script = (
        f"local core = dofile({json.dumps(str(CORE))})\n"
        "local function unhex(text)\n"
        "  return (text:gsub('..', function(pair)\n"
        "    return string.char(tonumber(pair, 16)) end))\n"
        "end\n"
        "for index = 1, #arg, 2 do\n"
        "  print(core.codec_problem(arg[index], unhex(arg[index + 1])) and 'no'"
        " or 'ok')\n"
        "end\n"
    )
    arguments = [part for codec, payload, _ in cases for part in (codec, payload.hex())]
    done = _run(lua, tmp_path, script, arguments)

    assert done.stdout.splitlines() == [
        "ok" if holds else "no" for _, _, holds in cases
    ]


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_plugin_counts_tbcd_digits_as_python_does(lua, tmp_path):
    payloads = [b"\x21\x43\xf5", b"\x21\x43\x65", b"\xf1"]
    script = (
        f"local core = dofile({json.dumps(str(CORE))})\n"
        "local function unhex(text)\n"
        "  return (text:gsub('..', function(pair)\n"
        "    return string.char(tonumber(pair, 16)) end))\n"
        "end\n"
        "for index = 1, #arg do\n"
        "  print(core.digit_count('e164-tbcd', unhex(arg[index])))\n"
        "end\n"
    )
    done = _run(lua, tmp_path, script, [each.hex() for each in payloads])

    assert done.stdout.split() == [
        str(constraints.digit_count(Codec.E164_TBCD, each)) for each in payloads
    ]


def _u32(value: int) -> bytes:
    return struct.pack("!I", value)


@pytest.mark.parametrize(
    ("rule", "payload", "data_type", "codec", "holds"),
    [
        pytest.param(
            _rule("length 3 octets"),
            b"abc",
            DataType.OCTET_STRING,
            None,
            True,
            id="octets",
        ),
        pytest.param(
            _rule("length 3 octets"),
            b"ab",
            DataType.OCTET_STRING,
            None,
            False,
            id="short",
        ),
        pytest.param(
            _rule("length 1..* octets"),
            b"",
            DataType.OCTET_STRING,
            None,
            False,
            id="at-least",
        ),
        pytest.param(
            _rule("length *..2 characters"),
            "äö".encode(),
            DataType.UTF8_STRING,
            None,
            True,
            id="characters",
        ),
        pytest.param(
            _rule("length 14..15 digits"),
            b"35209900176148",
            DataType.UTF8_STRING,
            Codec.DIGITS,
            True,
            id="imei",
        ),
        pytest.param(
            _rule("length 14..15 digits"),
            b"3520990017614",
            DataType.UTF8_STRING,
            Codec.DIGITS,
            False,
            id="imei-short",
        ),
        pytest.param(
            _rule("length 5 digits"),
            b"\x21\x43\xf5",
            DataType.OCTET_STRING,
            Codec.E164_TBCD,
            True,
            id="tbcd-digits",
        ),
        pytest.param(
            _rule("length 5 digits"),
            b"\x21\x43\xf5",
            DataType.OCTET_STRING,
            None,
            None,
            id="digits-without-codec",
        ),
        pytest.param(
            _rule("range 0..255"),
            _u32(255),
            DataType.UNSIGNED32,
            None,
            True,
            id="range",
        ),
        pytest.param(
            _rule("range 0..255"),
            _u32(256),
            DataType.UNSIGNED32,
            None,
            False,
            id="range-above",
        ),
        pytest.param(
            _rule("range -1..*"),
            _u32(0xFFFFFFFF),
            DataType.INTEGER32,
            None,
            True,
            id="range-negative",
        ),
        pytest.param(
            _rule("range -1..*"),
            _u32(0xFFFFFFFE),
            DataType.INTEGER32,
            None,
            False,
            id="range-below",
        ),
        pytest.param(
            _rule("exclude 0"), _u32(0), DataType.UNSIGNED32, None, False, id="zero"
        ),
        pytest.param(
            _rule("exclude 0"), _u32(1), DataType.UNSIGNED32, None, True, id="one"
        ),
        pytest.param(
            _rule("exclude 0"),
            b"\0",
            DataType.UNSIGNED32,
            None,
            None,
            id="exclude-malformed",
        ),
        pytest.param(
            ast.TextOnly(), b"", DataType.OCTET_STRING, None, None, id="text-only"
        ),
        pytest.param(
            _rule("bits at-most-one 3 6"),
            _u32(8),
            DataType.UNSIGNED32,
            None,
            True,
            id="one-bit",
        ),
        pytest.param(
            _rule("bits at-most-one 3 6"),
            _u32(8 | 64),
            DataType.UNSIGNED32,
            None,
            False,
            id="both-bits",
        ),
        pytest.param(
            _rule("bits at-least-one 0 1"),
            _u32(4),
            DataType.UNSIGNED32,
            None,
            False,
            id="no-bit",
        ),
        pytest.param(
            _rule("bits set 1"), _u32(2), DataType.UNSIGNED32, None, True, id="set"
        ),
        pytest.param(
            _rule("bits set 0 1"), _u32(2), DataType.UNSIGNED32, None, False, id="unset"
        ),
        pytest.param(
            _rule("bits clear 0"), _u32(2), DataType.UNSIGNED32, None, True, id="clear"
        ),
        pytest.param(
            _rule("bits clear 0"),
            _u32(3),
            DataType.UNSIGNED32,
            None,
            False,
            id="not-clear",
        ),
        pytest.param(
            _rule("bits only 9"),
            _u32(1 << 9),
            DataType.UNSIGNED32,
            None,
            True,
            id="only",
        ),
        pytest.param(
            _rule("bits only 9"),
            _u32(1 << 9 | 1),
            DataType.UNSIGNED32,
            None,
            False,
            id="not-only",
        ),
        # An OctetString's octets as one big-endian number: TS 29.272 clause
        # 7.3.216's octet, its 4 most significant bits 0.
        pytest.param(
            _rule("bits clear 4 5 6 7"),
            b"\x05",
            DataType.OCTET_STRING,
            None,
            True,
            id="octet-clear",
        ),
        pytest.param(
            _rule("bits clear 4 5 6 7"),
            b"\x15",
            DataType.OCTET_STRING,
            None,
            False,
            id="octet-not-clear",
        ),
        pytest.param(
            _rule("bits set 8"),
            b"\x01\x00",
            DataType.OCTET_STRING,
            None,
            True,
            id="octets",
        ),
        pytest.param(
            _rule("bits clear 0"),
            b"",
            DataType.UTF8_STRING,
            None,
            None,
            id="bits-of-text",
        ),
        pytest.param(
            _rule("default 0"), b"", DataType.UNSIGNED32, None, None, id="default"
        ),
    ],
)
def test_each_value_rule_holds_or_breaks(rule, payload, data_type, codec, holds):
    assert constraints.check(rule, payload, data_type, codec).holds is holds


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_plugin_reads_bits_as_python_does(lua, tmp_path):
    cases = [
        (rule, payload, data_type)
        for relation in ast.BitsRelation
        for bits in ((0, 1), (4, 5, 6, 7), (9,), (8,))
        if len(bits) > 1 or relation not in ("at-most-one", "at-least-one")
        for rule in [ast.BitsRule(relation=relation, bits=bits)]
        for payload, data_type in (
            (_u32(0), DataType.UNSIGNED32),
            (_u32(3), DataType.UNSIGNED32),
            (_u32(1 << 9), DataType.UNSIGNED32),
            (_u32(1 << 9 | 1 << 31), DataType.UNSIGNED32),
            (b"\x05", DataType.OCTET_STRING),
            (b"\xf0", DataType.OCTET_STRING),
            (b"\x01\x00", DataType.OCTET_STRING),
            (b"\x02\x00", DataType.OCTET_STRING),
        )
    ]
    script = (
        f"local core = dofile({json.dumps(str(CORE))})\n"
        "local function unhex(text)\n"
        "  return (text:gsub('..', function(pair)\n"
        "    return string.char(tonumber(pair, 16)) end))\n"
        "end\n"
        "for index = 1, #arg, 4 do\n"
        "  local bits = {}\n"
        "  for each in arg[index + 1]:gmatch('%d+') do\n"
        "    bits[#bits + 1] = tonumber(each)\n"
        "  end\n"
        "  local rule = { r = arg[index], b = bits }\n"
        "  print(core.bits_problem(rule, arg[index + 2], unhex(arg[index + 3]))"
        " and 'no' or 'ok')\n"
        "end\n"
    )
    arguments = [
        part
        for rule, payload, data_type in cases
        for part in (
            rule.relation.value,
            ",".join(map(str, rule.bits)),
            data_type.value,
            payload.hex(),
        )
    ]
    done = _run(lua, tmp_path, script, arguments)

    assert done.stdout.splitlines() == [
        "ok" if constraints.check(rule, payload, data_type).holds else "no"
        for rule, payload, data_type in cases
    ]


def _answer_rule(text: str) -> ast.ConstraintRule:
    """One rule of a block scoped to an answer, which may read its request."""
    spec = parser.parse(
        "; Specification: 3GPP TS 29.999\n; Vendor-ID: 10415\n\n\n"
        "; Type: Interpreted Constraints\n; AVP: Example\n"
        "; Command: Example-Answer\n; Section: 7.3.1\n"
        f'; Versions: *..*\n"Read."\n    {text}\n'
    )
    block = spec.sections[0]
    assert isinstance(block, ast.InterpretedConstraints)
    rule = block.body[1]
    assert not isinstance(rule, ast.Quote)
    return rule


_FLAGS = constraints.Avp(
    "Example-Flags", DataType.UNSIGNED32, struct.pack("!I", 2), bits={"Asked": 1}
)
_NAME = constraints.Avp("User-Name", DataType.UTF8_STRING, b"alice")


@pytest.mark.parametrize(
    ("text", "scope", "asked", "holds"),
    [
        ("present-if request/Example-Flags bit Asked", [], [_FLAGS], False),
        ("present-if request/Example-Flags bit Asked", ["Example"], [_FLAGS], True),
        ("present-if request/Example-Flags bit 0", [], [_FLAGS], True),
        ("absent-if request/Example-Flags bit 1", ["Example"], [_FLAGS], False),
        ("requires request/User-Name", ["Example"], [], False),
        ("requires request/User-Name", ["Example"], [_NAME], True),
        ("excludes request/Example-Flags = 2", ["Example"], [_FLAGS], False),
        ("values 3 if request/Example-Flags = 2", ["Example"], [_FLAGS], False),
        ("equals request/User-Name", ["Example:alice"], [_NAME], True),
        ("equals request/User-Name", ["Example:bob"], [_NAME], False),
        ("equals request/User-Name", ["Example:bob"], [], True),
        ("absent", ["Example"], [], False),
        ("absent", ["User-Name"], [], True),
    ],
)
def test_a_rule_on_the_request_holds_of_the_request_given(text, scope, asked, holds):
    rule = _answer_rule(text)
    # Each entry an AVP of the answer, Example the rule's own, `:` giving
    # its payload as text.
    run = []
    for entry in scope:
        name, _, text_payload = entry.partition(":")
        run.append(
            constraints.Avp(
                name,
                DataType.UNSIGNED32 if name == "Example" else DataType.UTF8_STRING,
                text_payload.encode() if text_payload else struct.pack("!I", 1),
            )
        )
    found = constraints.holds(rule, "Example", run, asked)
    assert (found.holds, found.needs_request) == (holds, False), found
    # With no request, one reading it is not evaluated, and says so.
    missing = constraints.holds(rule, "Example", run)
    if ast.reads_request(rule):
        assert (missing.holds, missing.needs_request) == (None, True)
    else:
        assert missing == found


def test_check_reads_a_rule_on_the_request_alone_against_the_request():
    assert constraints.check(_answer_rule("absent"), b"x", DataType.OCTET_STRING) == (
        constraints.Check(False, "not allowed")
    )
    rule = _answer_rule("absent-if request/Example-Flags bit 1")
    assert constraints.check(rule, b"x", DataType.OCTET_STRING).needs_request
    broken = constraints.check(rule, b"x", DataType.OCTET_STRING, request=[_FLAGS])
    assert broken == constraints.Check(
        False, "not allowed with request/Example-Flags bit 1"
    )
    assert constraints.check(rule, b"x", DataType.OCTET_STRING, request=[]).holds
    # A rule reading the answer's own AVPs too needs them: unknown.
    both = _answer_rule("requires request/User-Name or Result-Code = 2001")
    assert constraints.check(both, b"x", DataType.OCTET_STRING, request=[]) == (
        constraints.Check(None)
    )
