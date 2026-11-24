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
from seanchai.dad import ast
from seanchai.dad.ast import Codec, DataType
from seanchai.dad.interpret import (
    bits_at_least_one,
    bits_at_most_one,
    characters,
    default,
    digits,
    exclude,
    octets,
    range_of,
)

CORE = Path(wireshark.__file__).parent / "core.lua"
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
        pytest.param(octets(3), b"abc", DataType.OCTET_STRING, None, True, id="octets"),
        pytest.param(octets(3), b"ab", DataType.OCTET_STRING, None, False, id="short"),
        pytest.param(
            octets(1, None), b"", DataType.OCTET_STRING, None, False, id="at-least"
        ),
        pytest.param(
            characters(None, 2),
            "äö".encode(),
            DataType.UTF8_STRING,
            None,
            True,
            id="characters",
        ),
        pytest.param(
            digits(14, 15),
            b"35209900176148",
            DataType.UTF8_STRING,
            Codec.DIGITS,
            True,
            id="imei",
        ),
        pytest.param(
            digits(14, 15),
            b"3520990017614",
            DataType.UTF8_STRING,
            Codec.DIGITS,
            False,
            id="imei-short",
        ),
        pytest.param(
            digits(5),
            b"\x21\x43\xf5",
            DataType.OCTET_STRING,
            Codec.E164_TBCD,
            True,
            id="tbcd-digits",
        ),
        pytest.param(
            digits(5),
            b"\x21\x43\xf5",
            DataType.OCTET_STRING,
            None,
            None,
            id="digits-without-codec",
        ),
        pytest.param(
            range_of(0, 255), _u32(255), DataType.UNSIGNED32, None, True, id="range"
        ),
        pytest.param(
            range_of(0, 255),
            _u32(256),
            DataType.UNSIGNED32,
            None,
            False,
            id="range-above",
        ),
        pytest.param(
            range_of(-1, None),
            _u32(0xFFFFFFFF),
            DataType.INTEGER32,
            None,
            True,
            id="range-negative",
        ),
        pytest.param(
            range_of(-1, None),
            _u32(0xFFFFFFFE),
            DataType.INTEGER32,
            None,
            False,
            id="range-below",
        ),
        pytest.param(exclude(0), _u32(0), DataType.UNSIGNED32, None, False, id="zero"),
        pytest.param(exclude(0), _u32(1), DataType.UNSIGNED32, None, True, id="one"),
        pytest.param(
            exclude(0), b"\0", DataType.UNSIGNED32, None, None, id="exclude-malformed"
        ),
        pytest.param(
            ast.TextOnly(), b"", DataType.OCTET_STRING, None, None, id="text-only"
        ),
        pytest.param(
            bits_at_most_one(3, 6),
            _u32(8),
            DataType.UNSIGNED32,
            None,
            True,
            id="one-bit",
        ),
        pytest.param(
            bits_at_most_one(3, 6),
            _u32(8 | 64),
            DataType.UNSIGNED32,
            None,
            False,
            id="both-bits",
        ),
        pytest.param(
            bits_at_least_one(0, 1),
            _u32(4),
            DataType.UNSIGNED32,
            None,
            False,
            id="no-bit",
        ),
        pytest.param(default(0), b"", DataType.UNSIGNED32, None, None, id="default"),
    ],
)
def test_each_value_rule_holds_or_breaks(rule, payload, data_type, codec, holds):
    assert constraints.check(rule, payload, data_type, codec).holds is holds
