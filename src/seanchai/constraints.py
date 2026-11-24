"""Checking an AVP's payload against interpreted constraints
(`model.Constraint`), and what each codec implies of the payload.

`check` tells whether one rule holds of a payload, as the Wireshark plugin
checks it: length, range, exclude, bits, every codec, and an `element` as
far as the element registry (`seanchai.elements`) reads its document. A
predicate, a `values`, `members` or `unique` rule needs the message around
the AVP, an element the registry does not have or checks nothing of its
document's layout, and `text-only` a reader, so `check` answers None for
them: unknown, never a guess. docs/constraints.md#codecs gives each codec's
clause, and docs/constraints.md#elements each element's.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import NamedTuple

from . import elements
from .dad import ast

__all__ = [
    "CODEC_TYPES",
    "Check",
    "bits_problem",
    "bits_value",
    "check",
    "codec_digits",
    "codec_octets",
    "codec_problem",
    "digit_count",
    "element_of",
    "element_problem",
    "integer_bounds",
    "integer_value",
]

_TEXT = frozenset(
    {
        ast.DataType.OCTET_STRING,
        ast.DataType.UTF8_STRING,
        ast.DataType.DIAMETER_IDENTITY,
    }
)

# The data types a codec can describe the payload of. An `element` is any.
CODEC_TYPES: dict[ast.Codec, frozenset[ast.DataType]] = {
    ast.Codec.E164_TBCD: frozenset({ast.DataType.OCTET_STRING}),
    ast.Codec.PLMN_ID: frozenset({ast.DataType.OCTET_STRING}),
    ast.Codec.PLMN_ID_PREFIX: frozenset({ast.DataType.OCTET_STRING}),
    ast.Codec.DIGITS: _TEXT,
    ast.Codec.LABELS: _TEXT,
    ast.Codec.APN: _TEXT,
    ast.Codec.PLMN_DOMAIN: _TEXT,
    ast.Codec.EPC_PLMN_DOMAIN: _TEXT,
    ast.Codec.TIME_ZONE: _TEXT,
    ast.Codec.IP_ADDRESS: frozenset({ast.DataType.ADDRESS}),
    ast.Codec.ELEMENT: frozenset(ast.DataType),
}

# The octet counts a codec's layout allows, inclusive; None for no bound.
_OCTETS: dict[ast.Codec, tuple[int, int | None]] = {
    # At most 15 digits (ITU-T E.164), two per octet.
    ast.Codec.E164_TBCD: (1, 8),
    ast.Codec.PLMN_ID: (3, 3),
    ast.Codec.PLMN_ID_PREFIX: (3, None),
}

# The digits a digit-carrying codec allows.
_DIGITS: dict[ast.Codec, tuple[int, int | None]] = {
    ast.Codec.E164_TBCD: (1, 15),
    ast.Codec.DIGITS: (1, None),
}


def codec_octets(codec: ast.Codec) -> tuple[int, int | None] | None:
    """The octet counts `codec`'s layout allows, or None where it bounds
    none."""
    return _OCTETS.get(codec)


def codec_digits(codec: ast.Codec) -> tuple[int, int | None] | None:
    """The digit counts a digit-carrying codec allows, or None for a codec
    carrying no digits."""
    return _DIGITS.get(codec)


def _tbcd_digits(payload: bytes) -> str | None:
    """A TBCD-string's decimal digits (TS 29.002 clause 17.7.8: the first
    digit in bits 1-4, "1111" filling bits 5-8 of the last octet after an odd
    count), or None if it is no such string of decimal digits."""
    found = []
    for index, octet in enumerate(payload):
        low, high = octet & 0x0F, octet >> 4
        if low > 9:
            return None
        found.append(str(low))
        if high == 0x0F and index == len(payload) - 1:
            break
        if high > 9:
            return None
        found.append(str(high))
    return "".join(found)


def _plmn_problem(payload: bytes) -> str | None:
    if len(payload) < 3:
        return f"a PLMN identity is 3 octets, not {len(payload)}"
    mcc = (payload[0] & 0x0F, payload[0] >> 4, payload[1] & 0x0F)
    mnc3, mnc = payload[1] >> 4, (payload[2] & 0x0F, payload[2] >> 4)
    if any(digit > 9 for digit in (*mcc, *mnc)):
        return "an MCC or MNC digit is no decimal digit"
    if mnc3 > 9 and mnc3 != 0x0F:
        return "MNC digit 3 is neither a digit nor the '1111' filler"
    return None


def _text(payload: bytes) -> str | None:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


_LABELS = re.compile(r"[^.]+(?:\.[^.]+)*")
_PLMN_DOMAIN = re.compile(r"mnc[0-9]{2,3}\.mcc[0-9]{3}\.3gppnetwork\.org", re.I)
_EPC_PLMN_DOMAIN = re.compile(r"epc\." + _PLMN_DOMAIN.pattern, re.I)
_TIME_ZONE = re.compile(r"[+-][0-9]+")


def codec_problem(codec: ast.Codec, payload: bytes) -> str | None:
    """Why `payload` is not laid out as `codec` says, or None if it is, or
    if `codec` is an `element`, whose layout `element_problem` checks."""
    match codec:
        case ast.Codec.E164_TBCD:
            if not 1 <= len(payload) <= 8:
                return f"a TBCD E.164 number is 1 to 8 octets, not {len(payload)}"
            digits = _tbcd_digits(payload)
            if digits is None:
                return (
                    "not a TBCD-string of decimal digits, '1111' filling only"
                    " the last octet's bits 5-8"
                )
            if len(digits) > 15:
                return f"an E.164 number has at most 15 digits, not {len(digits)}"
            return None
        case ast.Codec.PLMN_ID:
            if len(payload) != 3:
                return f"a PLMN identity is 3 octets, not {len(payload)}"
            return _plmn_problem(payload)
        case ast.Codec.PLMN_ID_PREFIX:
            return _plmn_problem(payload)
        case ast.Codec.IP_ADDRESS:
            if len(payload) < 2:
                return "an Address has a 2-octet family"
            family, size = int.from_bytes(payload[:2], "big"), len(payload) - 2
            if (family, size) not in ((1, 4), (2, 16)):
                return f"not an IPv4 or IPv6 address (family {family}, {size} octets)"
            return None
        case ast.Codec.ELEMENT:
            return None
    text = _text(payload)
    if text is None:
        return "not UTF-8 text"
    match codec:
        case ast.Codec.DIGITS:
            ok = bool(text) and all("0" <= char <= "9" for char in text)
            return None if ok else "not decimal digits"
        case ast.Codec.LABELS:
            return None if _LABELS.fullmatch(text) else "not labels separated by dots"
        case ast.Codec.APN:
            ok = text == "*" or _LABELS.fullmatch(text)
            return None if ok else "neither labels separated by dots nor '*'"
        case ast.Codec.PLMN_DOMAIN:
            ok = _PLMN_DOMAIN.fullmatch(text)
            return None if ok else "not mnc<MNC>.mcc<MCC>.3gppnetwork.org"
        case ast.Codec.EPC_PLMN_DOMAIN:
            ok = _EPC_PLMN_DOMAIN.fullmatch(text)
            return None if ok else "not epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org"
        case ast.Codec.TIME_ZONE:
            ok = _TIME_ZONE.fullmatch(text)
            return None if ok else "not a sign and a number of 15 minutes"
    raise AssertionError(codec)


def element_of(rule: ast.EncodingRule) -> elements.Element | None:
    """The registry's entry for the element an `encoding element` rule
    names, or None for another codec or an element it does not have."""
    return elements.of_rule(rule)


def element_problem(
    rule: ast.EncodingRule, payload: bytes, data_type: ast.DataType | None = None
) -> str | None:
    """Why `payload`, of `data_type`, is not the element `rule` names, as
    far as the registry checks it; None if it is, or where the registry has
    no entry or its entry checks nothing."""
    found = element_of(rule)
    return None if found is None else elements.problem(found, payload, data_type)


def digit_count(codec: ast.Codec, payload: bytes) -> int | None:
    """The digits `payload` carries under `codec`, or None where it carries
    none or is malformed."""
    if codec is ast.Codec.E164_TBCD:
        digits = _tbcd_digits(payload)
        return None if digits is None else len(digits)
    if codec is ast.Codec.DIGITS and codec_problem(codec, payload) is None:
        return len(payload)
    return None


_INTEGERS = {
    ast.DataType.INTEGER32: (4, True),
    ast.DataType.INTEGER64: (8, True),
    ast.DataType.UNSIGNED32: (4, False),
    ast.DataType.UNSIGNED64: (8, False),
    ast.DataType.ENUMERATED: (4, True),
}


def integer_value(data_type: ast.DataType, payload: bytes) -> int | None:
    """The integer an integer-typed payload holds (an Enumerated is an
    Integer32), or None for another type or a wrong length."""
    found = _INTEGERS.get(data_type)
    if found is None or len(payload) != found[0]:
        return None
    return int.from_bytes(payload, "big", signed=found[1])


def integer_bounds(data_type: ast.DataType) -> tuple[int, int] | None:
    """The values an integer type holds, or None for another type."""
    found = _INTEGERS.get(data_type)
    if found is None:
        return None
    bits = found[0] * 8
    return (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) if found[1] else (0, 2**bits - 1)


def bits_value(data_type: ast.DataType, payload: bytes) -> int | None:
    """The number a `bits` rule reads its bits from: an integer-typed
    payload's value, or an OctetString's octets read as one big-endian
    number, bit 0 the last octet's least significant; None for another type
    or a malformed integer."""
    if data_type is ast.DataType.OCTET_STRING:
        return int.from_bytes(payload, "big")
    return integer_value(data_type, payload)


def bits_problem(
    relation: ast.BitsRelation, bits: Sequence[int], value: int
) -> str | None:
    """Why a `bits` rule of `relation` on `bits` does not hold of the bits of
    `value`, or None if it does."""
    held = [bit for bit in bits if value >> bit & 1]
    named = ", ".join(map(str, bits))
    match relation:
        case ast.BitsRelation.AT_MOST_ONE if len(held) > 1:
            return f"bits {', '.join(map(str, held))} are all set"
        case ast.BitsRelation.AT_LEAST_ONE if not held:
            return f"none of bits {named} is set"
        case ast.BitsRelation.SET if len(held) < len(bits):
            unset = [bit for bit in bits if bit not in held]
            return f"bits {', '.join(map(str, unset))} are clear"
        case ast.BitsRelation.CLEAR if held:
            return f"bits {', '.join(map(str, held))} are set"
        case ast.BitsRelation.ONLY:
            others = [
                bit
                for bit in range(value.bit_length())
                if value >> bit & 1 and bit not in bits
            ]
            if others:
                return f"bits {', '.join(map(str, others))} are set, not only {named}"
    return None


class Check(NamedTuple):
    """Whether a rule holds of a payload: True, False with the reason, or
    None where the payload alone cannot tell."""

    holds: bool | None
    reason: str | None = None


def _within(count: int, low: int | None, high: int | None) -> bool:
    return (low is None or count >= low) and (high is None or count <= high)


def _bounds(low: int | None, high: int | None) -> str:
    if low == high:
        return str(low)
    if high is None:
        return f"at least {low}"
    if low is None:
        return f"at most {high}"
    return f"{low} to {high}"


def check(
    rule: ast.ConstraintRule,
    payload: bytes,
    data_type: ast.DataType,
    codec: ast.Codec | None = None,
) -> Check:
    """Whether `rule` holds of an AVP's data `payload`, the AVP being of
    `data_type` and, for a `digits` length, encoded as `codec`."""
    match rule:
        case ast.LengthRule(unit=ast.LengthUnit.OCTETS):
            count = len(payload)
        case ast.LengthRule(unit=ast.LengthUnit.CHARACTERS):
            text = _text(payload)
            if text is None:
                return Check(False, "not UTF-8 text")
            count = len(text)
        case ast.LengthRule():
            found = None if codec is None else digit_count(codec, payload)
            if found is None:
                return Check(None)
            count = found
        case ast.RangeRule() | ast.ExcludeRule():
            value = integer_value(data_type, payload)
            if value is None:
                return Check(None)
            if isinstance(rule, ast.ExcludeRule):
                if value in rule.values:
                    return Check(False, f"{value} is excluded")
                return Check(True)
            if _within(value, rule.low, rule.high):
                return Check(True)
            return Check(False, f"{value} is not {_bounds(rule.low, rule.high)}")
        case ast.EncodingRule():
            if rule.codec is ast.Codec.ELEMENT:
                found = element_of(rule)
                if found is None or not found.checks:
                    return Check(None)
                if found.integer and integer_value(data_type, payload) is None:
                    return Check(None)
                problem = elements.problem(found, payload, data_type)
                return Check(problem is None, problem)
            problem = codec_problem(rule.codec, payload)
            return Check(problem is None, problem)
        case ast.BitsRule():
            value = bits_value(data_type, payload)
            if value is None:
                return Check(None)
            problem = bits_problem(rule.relation, rule.bits, value)
            return Check(problem is None, problem)
        case _:
            return Check(None)
    if _within(count, rule.low, rule.high):
        return Check(True)
    return Check(False, f"{count} {rule.unit}, not {_bounds(rule.low, rule.high)}")
