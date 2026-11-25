"""Checking an AVP's payload against interpreted constraints
(`model.Constraint`), and what each codec implies of the payload.

`check` tells whether one rule holds of a payload, as the Wireshark plugin
checks it: length, range, exclude, bits, every codec, and an `element` as
far as the element registry (`seanchai.elements`) reads its document.
`holds` tells whether a predicate, an `absent`, a `values` or an `equals`
rule holds of
an AVP among the others of its run (`Avp`), and of the request its answer
answers where the rule reads one; `check` does too where the request alone
settles it, given the request. A rule reading the request with none given
is not evaluated, `Check.needs_request`. A `members` or `unique` rule, an
element the registry does not have or checks nothing of its document's
layout, and `text-only` a reader, so both answer None for them: unknown,
never a guess. docs/constraints.md#codecs gives each codec's clause, and
docs/constraints.md#elements each element's.
"""

from __future__ import annotations

import dataclasses
import ipaddress
import re
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from . import elements
from .dad import ast, formatter

__all__ = [
    "CODEC_TYPES",
    "Avp",
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
    "holds",
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

# An IPFilterRule's text, or an OctetString holding one.
_FILTER = frozenset({ast.DataType.IP_FILTER_RULE, ast.DataType.OCTET_STRING})

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
    ast.Codec.MAC_ADDRESS: _TEXT,
    ast.Codec.IP_FILTER: _FILTER,
    ast.Codec.IP_FILTER_OUT: _FILTER,
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
_MAC_ADDRESS = re.compile(r"[0-9A-F]{2}(?:-[0-9A-F]{2}){5}")


def _ip_filter_address(token: str) -> str | None:
    """Why `token` is no IPFilterRule address: `any`, `assigned`, or an IPv4
    or IPv6 number with an optional mask width valid for its version."""
    if token in ("any", "assigned"):
        return None
    number, slash, bits = token.partition("/")
    if "%" in number:
        return f"{token!r} is no address, 'any' or 'assigned'"
    try:
        address = ipaddress.ip_address(number)
    except ValueError:
        return f"{token!r} is no address, 'any' or 'assigned'"
    if slash:
        width = 32 if address.version == 4 else 128
        if not bits.isdigit() or not 0 <= int(bits) <= width:
            return f"{token!r} has no mask width 0 to {width}"
    return None


def _ip_filter_ports(token: str) -> bool:
    """Whether `token` is a list of ports and port ranges, 0 to 65535."""
    for part in token.split(","):
        low, dash, high = part.partition("-")
        if not low.isdigit() or (dash and not high.isdigit()):
            return False
        if int(low) > 65535 or (dash and not int(low) <= int(high) <= 65535):
            return False
    return True


def _ip_filter_problem(text: str, out_only: bool) -> str | None:
    """Why `text` is no IPFilterRule (RFC 6733 clause 4.3.1) as the
    documents restrict it: `permit`, a direction (`out` where `out_only`),
    a protocol number or `ip`, `from` a source and `to` a destination, each
    an address and optional ports, no options and no `!`."""
    if "!" in text:
        return "the invert modifier '!' is used"
    tokens = text.split()
    if not tokens or tokens[0] != "permit":
        return "the action is not 'permit'"
    if len(tokens) < 2 or tokens[1] not in (("out",) if out_only else ("in", "out")):
        return (
            "the direction is not 'out'" if out_only else "no direction 'in' or 'out'"
        )
    if len(tokens) < 3 or not (
        tokens[2] == "ip" or (tokens[2].isdigit() and int(tokens[2]) <= 255)
    ):
        return "no protocol number or 'ip'"
    position = 3
    for keyword in ("from", "to"):
        if len(tokens) <= position or tokens[position] != keyword:
            return f"no '{keyword}'"
        if len(tokens) <= position + 1:
            return f"no address after '{keyword}'"
        problem = _ip_filter_address(tokens[position + 1])
        if problem is not None:
            return problem
        position += 2
        if position < len(tokens) and tokens[position] != "to":
            if not _ip_filter_ports(tokens[position]):
                if keyword == "to":
                    return "options are used"
                return f"{tokens[position]!r} are no ports"
            position += 1
    if position != len(tokens):
        return "options are used"
    return None


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
        case ast.Codec.MAC_ADDRESS:
            ok = _MAC_ADDRESS.fullmatch(text)
            return None if ok else "not six upper-case hexadecimal octets joined by '-'"
        case ast.Codec.IP_FILTER | ast.Codec.IP_FILTER_OUT:
            return _ip_filter_problem(text, codec is ast.Codec.IP_FILTER_OUT)
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
    None where the payload alone cannot tell; `needs_request` where that is
    because the rule reads the request and none was given."""

    holds: bool | None
    reason: str | None = None
    needs_request: bool = False


_NEEDS_REQUEST = Check(None, "reads the request, which was not given", True)


@dataclasses.dataclass(frozen=True)
class Avp:
    """An AVP of a message as `holds` reads it: its name and data type, its
    payload, or a grouped AVP's `members`, and the numbers its values,
    result codes and bits are named by, which a condition may name."""

    name: str
    data_type: ast.DataType | None = None
    payload: bytes = b""
    members: tuple[Avp, ...] = ()
    values: Mapping[str, int] = dataclasses.field(default_factory=dict)
    bits: Mapping[str, int] = dataclasses.field(default_factory=dict)


def _reached(
    reference: ast.Reference, scope: Sequence[Avp], request: Sequence[Avp] | None
) -> list[Avp]:
    """The AVPs `reference` names: of `scope`, or of the request's, and on
    through each grouped AVP's members, every one of each name."""
    found = list((request or ()) if reference.root is ast.Root.REQUEST else scope)
    for depth, name in enumerate(reference.path):
        if depth:
            found = [member for avp in found for member in avp.members]
        found = [avp for avp in found if avp.name == name]
    return found


def _number(value: int | str, names: Mapping[str, int]) -> int | None:
    return value if isinstance(value, int) else names.get(value)


def _condition_holds(
    condition: ast.Condition, scope: Sequence[Avp], request: Sequence[Avp] | None
) -> bool | None:
    """Whether `condition` holds: True, False, or None where a value it tests
    cannot be read. Of the AVPs it names, any meeting it does."""
    found = _reached(condition, scope, request)
    if not found:
        return False
    if isinstance(condition.value, ast.Reference):
        others = {avp.payload for avp in _reached(condition.value, scope, request)}
        return any(avp.payload in others for avp in found)
    if condition.value is None and condition.bit is None:
        return True
    unknown = False
    for avp in found:
        value = (
            None if avp.data_type is None else integer_value(avp.data_type, avp.payload)
        )
        wanted = (
            _number(condition.value, avp.values)
            if condition.value is not None
            else None
            if condition.bit is None
            else _number(condition.bit, avp.bits)
        )
        if value is None or wanted is None:
            unknown = True
        elif value == wanted if condition.value is not None else value >> wanted & 1:
            return True
    return None if unknown else False


def _any_holds(
    alternatives: Sequence[Sequence[ast.Condition]],
    scope: Sequence[Avp],
    request: Sequence[Avp] | None,
) -> bool | None:
    """Whether one of `alternatives` holds, each when every condition of it
    does, a negated one when it does not; None where that rests on a value
    not read."""
    unknown = False
    for conjunction in alternatives:
        met: bool | None = True
        for condition in conjunction:
            found = _condition_holds(condition, scope, request)
            if found is not None and condition.negated:
                found = not found
            if found is False:
                met = False
                break
            if found is None:
                met = None
        if met:
            return True
        unknown = unknown or met is None
    return None if unknown else False


def holds(
    rule: ast.ConstraintRule,
    avp: str,
    scope: Sequence[Avp],
    request: Sequence[Avp] | None = None,
) -> Check:
    """Whether a predicate, a `values` or an `equals` rule on the AVP named
    `avp` holds of `scope`, the run of AVPs holding it (its command's, or its
    grouped AVP's members) and, for a rule reading the request, of
    `request`, the request's AVPs. With no request, such a rule is not
    evaluated (`needs_request`). Another kind is None: `check` reads it."""
    if ast.reads_request(rule) and request is None:
        return _NEEDS_REQUEST
    subject = next((each for each in scope if each.name == avp), None)
    match rule:
        case ast.AbsentRule():
            return Check(True) if subject is None else Check(False, "not allowed")
        case ast.EqualsRule():
            others = _reached(rule.reference, scope, request)
            if subject is None or not others:
                return Check(True)
            if any(other.payload == subject.payload for other in others):
                return Check(True)
            text = formatter.reference(rule.reference)
            return Check(False, f"not the value of {text}")
        case ast.PredicateRule() | ast.ValuesRule():
            met = _any_holds(rule.conditions, scope, request)
        case _:
            return Check(None)
    said = formatter.conditions(rule.conditions)
    match rule:
        case ast.PredicateRule(kind=ast.PredicateKind.PRESENT_IF) if (
            met and subject is None
        ):
            return Check(False, f"missing {avp}, required with {said}")
        case ast.PredicateRule(
            kind=ast.PredicateKind.ABSENT_IF | ast.PredicateKind.EXCLUDES
        ) if met and subject is not None:
            return Check(False, f"not allowed with {said}")
        case ast.PredicateRule(kind=ast.PredicateKind.REQUIRES) if (
            subject is not None and met is False
        ):
            return Check(False, f"not allowed without {said}")
        case ast.ValuesRule() if met and subject is not None:
            value = (
                None
                if subject.data_type is None
                else integer_value(subject.data_type, subject.payload)
            )
            if value is None:
                return Check(None)
            if value not in rule.values:
                listed = ", ".join(map(str, rule.values))
                return Check(False, f"{value}, but only {listed} with {said}")
    if met is None:
        return Check(None)
    return Check(True)


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
    request: Sequence[Avp] | None = None,
) -> Check:
    """Whether `rule` holds of an AVP's data `payload`, the AVP being of
    `data_type` and, for a `digits` length, encoded as `codec`. A rule
    reading only the request, and no other AVP of the AVP's own message, is
    held to `request`, the request's AVPs, as `holds` holds it; with none
    given it is not evaluated (`needs_request`)."""
    if ast.reads_request(rule):
        if request is None:
            return _NEEDS_REQUEST
        if all(each.root is ast.Root.REQUEST for each in ast.references_of(rule)):
            own = Avp("", data_type, payload)
            return holds(rule, "", (own,), request)
        return Check(None)
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
        case ast.AbsentRule():
            # A payload is an AVP present.
            return Check(False, "not allowed")
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
