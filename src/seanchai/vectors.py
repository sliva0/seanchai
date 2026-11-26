"""Test messages for a Diameter stack's own test suite, from the dictionary.

For each command of the selected applications, `build` encodes a `minimal`
message (the fixed and required members only, nested grouped AVPs filled the
same way), a `maximal` one (every optional member too, a repeatable one
twice), and `negative` ones, each breaking exactly one rule of the minimal or
maximal message: a required AVP missing, an AVP once too often, a fixed AVP
out of place, an M or V bit against its rule, a reserved or void Enumerated
value, a bit no document names, UTF-8 that is not, an integer of the wrong
length, an AVP the rule does not admit, an E-bit answer with a Result-Code
that is no protocol error, and each interpreted constraint the Wireshark
plugin checks (length, range, exclude, encoding, bits, the predicates of a
command's own members and of a grouped AVP's, and the members, unique and
values rules). An answer
whose rules read the request it answers carries the request (`Request`), and
each such rule gets a valid pair and one breaking it.

Values are valid for their type and every constraint read for the AVP: a
codec's layout (`seanchai.constraints`), a length, a range, a predicate's
siblings, a required grouped AVP's members its command's predicates name. A
member the corpus cannot complete is left out where optional;
where required, the command has no minimal message and is listed in
`skipped`. Every vector has its octets, a readable tree, the rule it breaks
with its document, clause and page, and the finding the plugin reports
(`seanchai.wireshark`'s rule names). `pcap` writes them as a capture.
"""

from __future__ import annotations

import dataclasses
import json
import struct
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Annotated, Any, Literal

import pydantic
from pydantic.json_schema import models_json_schema

from . import __version__, constraints, dictionary, elements
from .dad import ast
from .errors import SeanchaiError

__all__ = [
    "FORMAT_VERSION",
    "Breaks",
    "Expected",
    "Node",
    "Request",
    "Skipped",
    "Vector",
    "Vectors",
    "build",
    "dumps",
    "json_schema",
    "pcap",
]

# Changes when a reader would have to.
FORMAT_VERSION = 1

type Severity = Literal["error", "warn", "note"]


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class Node(_Model):
    """One AVP of a vector, as encoded: its name, code, vendor-id (null
    without the V bit), the flags set (`M`, `V`, `P`), and its data as hex,
    or `children` for a grouped AVP."""

    name: str
    code: int
    vendor_id: int | None
    flags: str
    data: str | None
    children: tuple[Node, ...]


class Breaks(_Model):
    """The rule a negative vector breaks, as `rule` says it, and where it is
    written."""

    rule: str
    reference: str
    version: str | None
    section: str | None
    page: int | None
    table: str | None


class Expected(_Model):
    """A finding the Wireshark plugin reports, by its rule name
    (`seanchai.rule`) and severity: `note` for a `constraint-` rule, which
    is interpreted."""

    rule: str
    severity: Severity


class Request(_Model):
    """The request an answer vector answers, sent before it with the same
    Hop-by-Hop and End-to-End identifiers: its octets in hex and its tree."""

    octets: str
    tree: tuple[Node, ...]


class Vector(_Model):
    """One message. `id` is `application/abbreviation/kind[/what]`; `kind`
    is `minimal`, `maximal` or `negative`. `octets` is the whole message in
    hex, its Hop-by-Hop and End-to-End identifiers the vector's own. An
    answer whose rules read the request it answers has the request in
    `request`, which a checker reads first: the pair is valid, or breaks
    one rule, as a whole. A valid vector has no `breaks` and expects
    nothing: the plugin reports no error or warning for it, and no note but
    what the corpus leaves it unable to check, a note of an interpreted rule
    never. A negative one breaks one rule and expects one finding, a note
    for an interpreted rule."""

    id: str
    kind: Literal["minimal", "maximal", "negative"]
    application_id: int | None
    command: str
    abbreviation: str
    command_code: int
    is_request: bool
    error_bit: bool
    document: str
    section: str
    octets: str
    tree: tuple[Node, ...]
    request: Request | None
    breaks: Breaks | None
    expected: tuple[Expected, ...]


class Skipped(_Model):
    """A command, or a rule of one, no vector could be built for, and why."""

    command: str
    what: str
    reason: str


class Vectors(_Model):
    """`seanchai vectors`' file: what produced it, the vectors in a fixed
    order and what was skipped."""

    format_version: Annotated[int, pydantic.Field(ge=FORMAT_VERSION, le=FORMAT_VERSION)]
    seanchai_version: str
    corpus_version: str | None
    application_ids: tuple[int, ...]
    vectors: tuple[Vector, ...]
    skipped: tuple[Skipped, ...]


# --- values ---------------------------------------------------------------

_FAILED_AVP = 279
_HEADER_FLAGS = {"R": 0x80, "P": 0x40, "E": 0x20, "T": 0x10}
_M, _V, _P = 0x40, 0x80, 0x20
_FIXED = {
    ast.DataType.INTEGER32: 4,
    ast.DataType.INTEGER64: 8,
    ast.DataType.UNSIGNED32: 4,
    ast.DataType.UNSIGNED64: 8,
    ast.DataType.FLOAT32: 4,
    ast.DataType.FLOAT64: 8,
    ast.DataType.TIME: 4,
    ast.DataType.ENUMERATED: 4,
}
_TEXT = {
    ast.DataType.OCTET_STRING: b"seanchai",
    ast.DataType.UTF8_STRING: b"seanchai",
    ast.DataType.DIAMETER_IDENTITY: b"host.example.com",
    ast.DataType.DIAMETER_URI: b"aaa://host.example.com",
    ast.DataType.IP_FILTER_RULE: b"permit in ip from any to any",
    ast.DataType.QOS_FILTER_RULE: b"tag in ip from any to any",
    ast.DataType.ADDRESS: b"\x00\x01\xc0\x00\x02\x01",
}
# A sample of each codec's layout, and how to make one of n digits.
_CODEC = {
    ast.Codec.PLMN_ID: b"\x21\xf3\x54",
    ast.Codec.PLMN_ID_PREFIX: b"\x21\xf3\x54\x00\x00\x01",
    ast.Codec.LABELS: b"example.org",
    ast.Codec.APN: b"internet",
    ast.Codec.PLMN_DOMAIN: b"mnc045.mcc123.3gppnetwork.org",
    ast.Codec.EPC_PLMN_DOMAIN: b"epc.mnc045.mcc123.3gppnetwork.org",
    ast.Codec.TIME_ZONE: b"+8",
    ast.Codec.MAC_ADDRESS: b"00-10-A4-23-19-C0",
    ast.Codec.BASE64: b"c2VhbmNoYWk=",
    ast.Codec.SESSION_ID: b"aaa.example.com;1876543210;523",
    # Addresses and one port at each end: what every restriction admits.
    ast.Codec.IP_FILTER: b"permit in 17 from 192.0.2.10 5060 to 198.51.100.7 5060",
    ast.Codec.IP_ADDRESS: b"\x00\x01\xc0\x00\x02\x01",
}
# What breaks a codec's layout without changing its length.
_BROKEN_CODEC = {
    ast.Codec.E164_TBCD: lambda good: bytes([good[0] | 0x0A]) + good[1:],
    ast.Codec.PLMN_ID: lambda good: b"\xaa" + good[1:],
    ast.Codec.PLMN_ID_PREFIX: lambda good: b"\xaa" + good[1:],
    ast.Codec.DIGITS: lambda good: b"x" + good[1:],
    ast.Codec.LABELS: lambda good: b"." * len(good),
    ast.Codec.APN: lambda good: b"." * len(good),
    ast.Codec.PLMN_DOMAIN: lambda good: b"x" * len(good),
    ast.Codec.EPC_PLMN_DOMAIN: lambda good: b"x" * len(good),
    ast.Codec.TIME_ZONE: lambda good: b"x" * len(good),
    ast.Codec.MAC_ADDRESS: lambda good: good.lower(),
    ast.Codec.BASE64: lambda good: b"!" + good[1:],
    ast.Codec.SESSION_ID: lambda good: b"-" + good[1:],
    ast.Codec.IP_FILTER: lambda good: b"deny  " + good[6:],
    ast.Codec.IP_ADDRESS: lambda good: b"\x00\x03" + good[2:],
}


def _tbcd(digits: str) -> bytes:
    nibbles = [int(d) for d in digits] + ([0xF] if len(digits) % 2 else [])
    return bytes(nibbles[i] | nibbles[i + 1] << 4 for i in range(0, len(nibbles), 2))


def _digits(codec: ast.Codec, count: int) -> bytes:
    digits = ("1234567890" * 2)[:count]
    return _tbcd(digits) if codec is ast.Codec.E164_TBCD else digits.encode()


def _integer(data_type: ast.DataType, value: int) -> bytes:
    size = _FIXED[data_type]
    signed = data_type in (
        ast.DataType.INTEGER32,
        ast.DataType.INTEGER64,
        ast.DataType.ENUMERATED,
    )
    return value.to_bytes(size, "big", signed=signed)


def _codec_of(rules: Sequence[dictionary.Rule]) -> ast.Codec | None:
    """The codec the rules give the payload, an element being none."""
    return next(
        (
            rule.codec
            for rule in rules
            if rule.kind == "encoding" and rule.codec is not ast.Codec.ELEMENT
        ),
        None,
    )


def _codec_sample(codec: ast.Codec, rules: Sequence[dictionary.Rule]) -> bytes:
    """A sample of `codec`'s layout the rules hold: an `ip-filter` of the
    direction one of them restricts it to."""
    sample = _CODEC[codec]
    if codec is ast.Codec.IP_FILTER and any(
        rule.filter is not None and rule.filter.direction is ast.IpFilterDirection.OUT
        for rule in rules
        if rule.kind == "encoding"
    ):
        return sample.replace(b"permit in ", b"permit out ", 1)
    return sample


def _element_of(rule: dictionary.Rule) -> elements.Element | None:
    """The registry's entry for an `encoding element` rule, where it checks
    something."""
    if rule.kind != "encoding" or rule.codec is not ast.Codec.ELEMENT:
        return None
    if rule.document is None:
        return None
    found = elements.lookup(rule.document, rule.clause, rule.element)
    return found if found is not None and found.checks else None


def _holds(
    rule: dictionary.Rule,
    payload: bytes,
    data_type: ast.DataType,
    codec: ast.Codec | None,
) -> bool:
    """Whether a value rule holds of `payload` as the plugin checks it; a rule
    it cannot tell, or a predicate, holds."""
    if rule.kind == "length":
        if rule.unit is ast.LengthUnit.OCTETS:
            count: int | None = len(payload)
        elif rule.unit is ast.LengthUnit.CHARACTERS:
            try:
                count = len(payload.decode("utf-8"))
            except UnicodeDecodeError:
                count = None
        else:
            count = None if codec is None else constraints.digit_count(codec, payload)
        return count is None or (
            (rule.low is None or count >= rule.low)
            and (rule.high is None or count <= rule.high)
        )
    if rule.kind in ("range", "exclude"):
        value = constraints.integer_value(data_type, payload)
        if value is None:
            return True
        if rule.kind == "exclude":
            return value not in rule.values
        return (rule.low is None or value >= rule.low) and (
            rule.high is None or value <= rule.high
        )
    if rule.kind == "encoding" and (entry := _element_of(rule)) is not None:
        return elements.problem(entry, payload, data_type) is None
    if rule.kind == "encoding" and rule.codec is not None:
        return constraints.codec_problem(rule.codec, payload, rule.filter) is None
    if rule.kind == "bits" and rule.relation is not None:
        value = constraints.bits_value(data_type, payload)
        if value is None:
            return True
        return constraints.bits_problem(rule.relation, rule.bits, value) is None
    return True


def _set_bits(rules: Sequence[dictionary.Rule]) -> int:
    """The number with the bits the `set` rules among `rules` name."""
    return sum(
        {
            1 << bit
            for rule in rules
            if rule.kind == "bits" and rule.relation is ast.BitsRelation.SET
            for bit in rule.bits
        }
    )


def _value_rules(rules: Sequence[dictionary.Rule]) -> list[dictionary.Rule]:
    return [
        rule
        for rule in rules
        if rule.kind in ("length", "range", "exclude", "encoding", "bits")
        and not (
            rule.kind == "encoding"
            and rule.codec is ast.Codec.ELEMENT
            and _element_of(rule) is None
        )
    ]


class _Values:
    """The dictionary's numbers: each reading's enumerated values, the result
    codes, bits and integer values its value tables name."""

    def __init__(self, built: dictionary.Dictionary) -> None:
        self.avps = {avp.id: avp for avp in built.avps}
        self.bits: dict[str, set[int]] = {}
        # An integer AVP's values a `values` table names, by identity.
        self.named: dict[str, set[int]] = {}
        self.bit_names: dict[str, dict[str, int]] = {}
        self.codes: dict[str, int] = {}
        # Each vendor's result codes, in the order the tables give them.
        self.vendor_codes: dict[int, list[int]] = {}
        for table in built.value_tables:
            if table.kind is ast.ValueKind.BITS:
                for identifier in table.avp_ids:
                    identity = identifier.partition("@")[0]
                    self.bits.setdefault(identity, set()).update(
                        row.value for row in table.rows
                    )
                    self.bit_names.setdefault(identity, {}).update(
                        {row.name: row.value for row in table.rows}
                    )
            elif table.kind is ast.ValueKind.VALUES:
                for identifier in table.avp_ids:
                    self.named.setdefault(identifier.partition("@")[0], set()).update(
                        row.value for row in table.rows
                    )
            elif table.kind is ast.ValueKind.RESULT_CODES:
                for row in table.rows:
                    self.codes.setdefault(row.name, row.value)
                    self.vendor_codes.setdefault(table.vendor_id, []).append(row.value)

    def number(self, avp: dictionary.Avp, value: int | str) -> int | None:
        if isinstance(value, int):
            return value
        for each in avp.values:
            if each.kind == "value" and each.name == value:
                return each.value
        return self.codes.get(value)

    def bit(self, avp: dictionary.Avp, bit: int | str | None) -> int | None:
        if bit is None or isinstance(bit, int):
            return bit
        return self.bit_names.get(_identity(avp), {}).get(bit)


def _identity(avp: dictionary.Avp) -> str:
    return f"{avp.vendor_id}:{avp.code}"


def _opaque(avp: dictionary.Avp) -> bool:
    """Whether `avp` is Failed-AVP, which RFC 6733 section 7.5 lets hold the
    failed AVP as received: a checker holds it to its `1* { AVP }` alone, so
    nothing inside it is broken for a negative vector (TS 29.338's ALA, its
    Failed-AVP holding a Vendor-Id)."""
    return avp.vendor_id == 0 and avp.code == _FAILED_AVP


def _payload(
    avp: dictionary.Avp, rules: Sequence[dictionary.Rule], values: _Values
) -> bytes | None:
    """A valid payload for a non-grouped `avp` under its value `rules`, or
    None where none satisfies them."""
    rules = _value_rules(rules)
    codec = _codec_of(rules)
    data_type = avp.data_type
    laid_out = [
        found
        for rule in rules
        if (entry := _element_of(rule)) is not None
        and (found := elements.sample(entry, data_type)) is not None
    ]
    candidates: list[bytes] = []
    if data_type in _FIXED:
        numbers: list[int] = []
        if avp.name == "Result-Code":
            numbers.append(2001)
        elif avp.name == "Experimental-Result-Code":
            numbers += [
                code
                for vendor, codes in sorted(values.vendor_codes.items())
                if vendor
                for code in codes
            ][:1]
        elif avp.name == "Vendor-Id":
            # The vendor of that first code, so that an Experimental-Result
            # holds a code of its Vendor-Id, as a rule on the code names it.
            numbers += [vendor for vendor in sorted(values.vendor_codes) if vendor][:1]
        if data_type is ast.DataType.ENUMERATED:
            numbers += [
                v.value for v in avp.values if v.kind == "value" and v.value is not None
            ]
            if not any(v.kind == "value" for v in avp.values):
                numbers.append(0)
        else:
            for rule in rules:
                if rule.kind == "range":
                    numbers += [n for n in (rule.low, rule.high) if n is not None]
                if (
                    rule.kind == "bits"
                    and rule.relation is ast.BitsRelation.AT_LEAST_ONE
                ):
                    numbers.insert(0, 1 << rule.bits[0])
            if required := _set_bits(rules):
                numbers.insert(0, required)
            # A value a table names before any other.
            numbers[:0] = sorted(values.named.get(_identity(avp), ()))
            numbers += [0, 1]
        for rule in rules:
            entry = _element_of(rule)
            for shape in () if entry is None else entry.checks:
                if isinstance(shape, elements.Integer):
                    numbers += [n for n in (shape.low, shape.high) if n is not None]
        if data_type in (ast.DataType.FLOAT32, ast.DataType.FLOAT64):
            return b"\0" * _FIXED[data_type]
        bounds = constraints.integer_bounds(data_type) or (0, 2**32 - 1)
        candidates = [
            _integer(data_type, n) for n in numbers if bounds[0] <= n <= bounds[1]
        ]
    elif codec is not None and codec is not ast.Codec.ELEMENT:
        lengths = [
            r for r in rules if r.kind == "length" and r.unit is ast.LengthUnit.DIGITS
        ]
        if codec in (ast.Codec.E164_TBCD, ast.Codec.DIGITS):
            counts = [r.low for r in lengths if r.low] + [
                r.high for r in lengths if r.high
            ]
            candidates = [_digits(codec, n) for n in [*counts, 10, 15, 1]]
        else:
            candidates = [_codec_sample(codec, rules)]
    elif data_type is ast.DataType.GROUPED:
        # Typed Grouped by a table that prints no rule for it: nothing in it.
        candidates = [b""]
    else:
        base = _TEXT.get(data_type, b"seanchai")
        candidates = [base]
        for rule in rules:
            if rule.kind == "length" and rule.unit in (
                ast.LengthUnit.OCTETS,
                ast.LengthUnit.CHARACTERS,
            ):
                size = rule.low if rule.low else (rule.high or len(base))
                filler = b"\x01" if data_type is ast.DataType.OCTET_STRING else b"a"
                candidates.insert(0, (base + filler * size)[:size])
        if data_type is ast.DataType.OCTET_STRING and any(
            rule.kind == "bits" for rule in rules
        ):
            # Octets holding no bit but those the rules set.
            size = len(candidates[0])
            required = _set_bits(rules)
            if required < 1 << 8 * size:
                candidates.insert(0, required.to_bytes(size, "big"))
        candidates[:0] = laid_out
    for payload in candidates:
        if all(_holds(rule, payload, data_type, codec) for rule in rules):
            return payload
    return None


def _variants(avp: dictionary.Avp, payload: bytes) -> Iterator[bytes]:
    """Other payloads of `avp` than `payload`, for a member a `unique` rule
    names: another of its values or numbers, or the text with a digit
    after it."""
    data_type = avp.data_type
    if data_type in _FIXED:
        value = constraints.integer_value(data_type, payload)
        bounds = constraints.integer_bounds(data_type)
        if value is None or bounds is None:
            return
        named = [
            v.value for v in avp.values if v.kind == "value" and v.value is not None
        ]
        numbers = named if data_type is ast.DataType.ENUMERATED else range(1, 10)
        for number in numbers:
            candidate = number if named else value + number
            if candidate != value and bounds[0] <= candidate <= bounds[1]:
                yield _integer(data_type, candidate)
        return
    for digit in "123456789":
        yield payload + digit.encode()


# --- messages as trees ------------------------------------------------------


@dataclasses.dataclass
class _Avp:
    """One AVP of a message being built."""

    avp: dictionary.Avp
    flags: int
    payload: bytes | None = None
    children: list[_Avp] = dataclasses.field(default_factory=list)
    # The member it fills, for predicates and positions.
    member: dictionary.Member | None = None

    def data(self) -> bytes:
        """The AVP's data: its payload, or its members encoded."""
        if self.payload is not None:
            return self.payload
        return b"".join(child.encode() for child in self.children)

    def encode(self) -> bytes:
        data = self.data()
        vendor = self.flags & _V
        length = (12 if vendor else 8) + len(data)
        out = struct.pack("!I", self.avp.code) + bytes([self.flags])
        out += length.to_bytes(3, "big")
        if vendor:
            out += struct.pack("!I", self.avp.vendor_id)
        out += data
        return out + b"\0" * (-len(out) % 4)

    def node(self) -> Node:
        return Node(
            name=self.avp.name,
            code=self.avp.code,
            vendor_id=self.avp.vendor_id if self.flags & _V else None,
            flags="".join(
                letter
                for letter, bit in (("V", _V), ("M", _M), ("P", _P))
                if self.flags & bit
            ),
            data=None if self.payload is None else self.payload.hex(),
            children=tuple(child.node() for child in self.children),
        )

    def copy(self) -> _Avp:
        return dataclasses.replace(
            self, children=[child.copy() for child in self.children]
        )


def _flags(avp: dictionary.Avp) -> int:
    rules = avp.flag_rules
    flags = 0
    if ast.AvpFlag.MANDATORY in rules.must:
        flags |= _M
    if avp.vendor_id != 0 or ast.AvpFlag.VENDOR in rules.must:
        flags |= _V
    return flags


class _Unbuildable(SeanchaiError):
    """A required member the corpus cannot complete, or no valid value."""


@dataclasses.dataclass(frozen=True)
class _Scope:
    """A body and the constraints its owner holds for its members, by name;
    for an answer whose rules read its request, the request's scope."""

    members: tuple[dictionary.Member, ...]
    rules: Mapping[str, tuple[dictionary.Constraint, ...]]
    name: str
    request: _Scope | None = None


def _terms(rule: dictionary.Rule) -> list[dictionary.Condition]:
    """Every condition of a rule's alternatives."""
    return [each for conjunction in rule.conditions for each in conjunction]


def _listed_holds(
    value: int, avp: dictionary.Avp, condition: dictionary.Condition, values: _Values
) -> bool:
    """Whether `value` is one of an `in` condition's values or ranges."""
    return any(
        listed.low <= value <= listed.high
        if isinstance(listed, dictionary.ValueRange)
        else value == values.number(avp, listed)
        for listed in condition.values
    )


def _positive(condition: dictionary.Condition) -> dictionary.Condition:
    """`condition` without its `not`."""
    return condition.model_copy(update={"negated": False})


def _deeper(condition: dictionary.Condition) -> dictionary.Condition:
    """`condition` from the grouped AVP its path names first."""
    return condition.model_copy(update={"root": None, "path": condition.path[1:]})


def _reads_request(rule: dictionary.Rule) -> bool:
    """Whether `rule` reads an AVP of the request its answer answers."""
    references: list[dictionary.Reference] = [*_terms(rule)]
    references += [
        each.value
        for each in _terms(rule)
        if isinstance(each.value, dictionary.Reference)
    ]
    if rule.reference is not None:
        references.append(rule.reference)
    return any(each.root is not None for each in references)


class _Builder:
    def __init__(self, built: dictionary.Dictionary) -> None:
        self.built = built
        self.values = _Values(built)
        self.avps = self.values.avps
        # A reading's own constraints, and a grouped reading's for its members.
        self.own: dict[str, list[dictionary.Constraint]] = {}
        self.within: dict[str, dict[str, list[dictionary.Constraint]]] = {}
        # The application of the command being built, whose messages a
        # grouped AVP's rules read for one application hold in.
        self.application: int | None = None
        for each in built.constraints:
            if each.messages is not None:
                # Every answer's or request's: each command carries it.
                continue
            for identifier in each.avp_ids:
                if each.within is None:
                    self.own.setdefault(identifier, []).append(each)
                elif self.avps[identifier].name == each.within:
                    self.within.setdefault(identifier, {}).setdefault(
                        each.avp, []
                    ).append(each)

    def held_within(self, avp_id: str) -> dict[str, list[dictionary.Constraint]]:
        """The constraints a grouped reading holds for its members, by name, in
        the messages of `application`: those read for another application's
        left out (TS 29.273's Feature-List-ID within Supported-Features)."""
        return {
            name: kept
            for name, held in self.within.get(avp_id, {}).items()
            if (
                kept := [
                    each
                    for each in held
                    if each.application_id in (None, self.application)
                ]
            )
        }

    def scope_of(self, avp: dictionary.Avp) -> _Scope:
        return _Scope(
            avp.members,
            {k: tuple(v) for k, v in self.held_within(avp.id).items()},
            avp.name,
        )

    def admitted(
        self,
        scope: _Scope,
        member: dictionary.Member | None,
        each: dictionary.Constraint,
    ) -> str | None:
        """The reading to build for the subject of `each`, a constraint of
        `scope`: its member's, or where the body lists it not, the
        constraint's own where the body's `* [ AVP ]` admits it (TS 32.299's
        CCA, its Supported-Features), the reading the Wireshark plugin holds
        it to; None where neither can be built."""
        if member is not None:
            return member.avp
        if not any(m.kind == "wildcard" for m in scope.members) or not each.avp_ids:
            return None
        return each.avp_ids[0] if each.avp_ids[0] in self.avps else None

    def rules_for(
        self, avp: dictionary.Avp, scope: _Scope, name: str
    ) -> list[dictionary.Rule]:
        found = [
            rule
            for each in (*self.own.get(avp.id, ()), *scope.rules.get(name, ()))
            for reading in each.readings
            for rule in reading.rules
        ]
        return found

    def avp(
        self,
        avp: dictionary.Avp,
        scope: _Scope,
        member: dictionary.Member | None,
        maximal: bool,
        path: tuple[str, ...],
    ) -> _Avp:
        node = _Avp(avp, _flags(avp), member=member)
        if avp.kind == "grouped":
            if avp.id in path or len(path) > 24:
                raise _Unbuildable(f"{avp.name} holds itself")
            inner = self.scope_of(avp)
            node.children = self.body(inner, maximal, (*path, avp.id))
            rules = self.rules_for(avp, scope, member.name if member else avp.name)
            self.hold_members(inner, node.children, rules, (*path, avp.id))
            return node
        payload = _payload(
            avp,
            self.rules_for(avp, scope, member.name if member else avp.name),
            self.values,
        )
        if payload is None:
            raise _Unbuildable(f"no value of {avp.name} meets its rules")
        node.payload = payload
        return node

    def hold_members(
        self,
        inner: _Scope,
        children: list[_Avp],
        rules: Sequence[dictionary.Rule],
        path: tuple[str, ...],
    ) -> None:
        """Mend what the `members` rules among `rules` say of a grouped AVP's
        `children`: add a member one of which must be there, drop one that
        may not."""
        for rule in rules:
            if rule.kind != "members":
                continue
            if rule.relation is ast.BitsRelation.ONLY:
                for child in children:
                    name = child.member.name if child.member else child.avp.name
                    if (
                        name not in rule.members
                        and child.member
                        and (child.member.min_occurs)
                    ):
                        raise _Unbuildable(f"{name} is required and a rule forbids it")
                children[:] = [
                    child
                    for child in children
                    if (child.member.name if child.member else "") in rule.members
                ]
            elif not any(
                child.member is not None and child.member.name in rule.members
                for child in children
            ):
                for name in rule.members:
                    member = next((m for m in inner.members if m.name == name), None)
                    if member is None or member.avp is None:
                        continue
                    try:
                        children.append(
                            self.avp(self.avps[member.avp], inner, member, False, path)
                        )
                    except _Unbuildable:
                        continue
                    self.satisfy(inner, children, False)
                    break
                else:
                    raise _Unbuildable(f"none of {', '.join(rule.members)} is built")

    def vary(self, nodes: list[_Avp]) -> None:
        """Give each repeated grouped AVP of `nodes` its own value of a member
        a `unique` rule names."""
        seen: dict[tuple[str, str], set[bytes]] = {}
        for node in list(nodes):
            for name, held in self.held_within(node.avp.id).items():
                if not any(
                    rule.kind == "unique"
                    for each in held
                    for reading in each.readings
                    for rule in reading.rules
                ):
                    continue
                child = next(
                    (c for c in node.children if c.member and c.member.name == name),
                    None,
                )
                if child is None:
                    continue
                taken = seen.setdefault((node.avp.id, name), set())
                if child.data() in taken and not self.vary_one(
                    child, node.avp, name, taken
                ):
                    nodes.remove(node)
                    break
                taken.add(child.data())

    def vary_one(
        self, child: _Avp, parent: dictionary.Avp, name: str, taken: set[bytes]
    ) -> bool:
        """Give `child`, the member `name` of a `parent`, data none of `taken`
        holds: another value of its own, or for a grouped member another value
        of one of its members, as the plugin compares a grouped member's
        octets whole; False where no such value holds its rules."""
        for leaf, owner, member in self.leaves(child, parent, name):
            kept = leaf.payload
            assert kept is not None
            rules = _value_rules(self.rules_for(leaf.avp, self.scope_of(owner), member))
            codec = _codec_of(rules)
            for candidate in _variants(leaf.avp, kept):
                if not all(
                    _holds(r, candidate, leaf.avp.data_type, codec) for r in rules
                ):
                    continue
                leaf.payload = candidate
                if child.data() not in taken:
                    return True
            leaf.payload = kept
        return False

    def leaves(
        self, node: _Avp, parent: dictionary.Avp, name: str
    ) -> Iterator[tuple[_Avp, dictionary.Avp, str]]:
        """`node`, the member `name` of a `parent`, or else each AVP with a
        payload it holds at any depth, with the grouped AVP and member name
        holding it."""
        if node.payload is not None:
            yield node, parent, name
            return
        for each in node.children:
            if each.member is not None:
                yield from self.leaves(each, node.avp, each.member.name)

    def filler(self, scope: _Scope) -> _Avp:
        """An AVP the body does not list, for a `* { AVP }` that requires one:
        Failed-AVP's `1* { AVP }`."""
        listed = {
            _identity(self.avps[m.avp]) for m in scope.members if m.avp is not None
        }
        for avp in self.built.avps:
            if (
                avp.kind == "plain"
                and avp.vendor_id == 0
                and avp.data_type is ast.DataType.UNSIGNED32
                and _identity(avp) not in listed
                and avp.id not in self.own
                and avp.name not in ("Result-Code", "Experimental-Result-Code")
            ):
                payload = _payload(avp, (), self.values)
                if payload is not None:
                    return _Avp(avp, _flags(avp), payload)
        raise _Unbuildable(f"{scope.name} requires an AVP it does not list")

    def body(
        self,
        scope: _Scope,
        maximal: bool,
        path: tuple[str, ...] = (),
        request: Sequence[_Avp] | None = None,
    ) -> list[_Avp]:
        nodes: list[_Avp] = []
        for member in scope.members:
            if member.kind == "wildcard":
                nodes += [self.filler(scope) for _ in range(member.min_occurs)]
                continue
            count = member.min_occurs
            if maximal:
                high = member.max_occurs
                count = max(
                    count, 1 if high == 1 else 2 if high is None or high >= 2 else 1
                )
            if member.kind != "avp" or member.avp is None:
                if count and member.min_occurs:
                    raise _Unbuildable(
                        f"{member.name} is required and the corpus cannot complete it"
                    )
                continue
            avp = self.avps[member.avp]
            for _ in range(count):
                try:
                    nodes.append(self.avp(avp, scope, member, maximal, path))
                except _Unbuildable:
                    if member.min_occurs:
                        raise
                    break
        self.satisfy(scope, nodes, maximal, request)
        self.vary(nodes)
        return nodes

    # Predicates.

    def predicates(
        self, scope: _Scope
    ) -> Iterator[tuple[str, dictionary.Constraint, dictionary.Rule]]:
        """The predicates, `values` and `equals` rules the plugin checks in
        `scope`: those whose every name is a sibling's, or the request's
        member's, and every value or bit a number."""
        siblings = {
            m.name: self.avps[m.avp] for m in scope.members if m.avp is not None
        }
        asked = {
            m.name: self.avps[m.avp]
            for m in (scope.request.members if scope.request else ())
            if m.avp is not None
        }

        def resolves(reference: dictionary.Reference) -> dictionary.Avp | None:
            """The reading the path ends at, through each grouped AVP's
            members."""
            found = (asked if reference.root else siblings).get(reference.path[0])
            for name in reference.path[1:]:
                member = (
                    None
                    if found is None
                    else next(
                        (m for m in found.members if m.name == name and m.avp), None
                    )
                )
                found = None if member is None else self.avps.get(member.avp or "")
            return found

        for name, held in scope.rules.items():
            for each in held:
                for reading in each.readings:
                    for rule in reading.rules:
                        if rule.kind == "absent":
                            yield name, each, rule
                            continue
                        if rule.kind == "equals":
                            if rule.reference and resolves(rule.reference):
                                yield name, each, rule
                            continue
                        if rule.kind not in (
                            "present-if",
                            "absent-if",
                            "requires",
                            "excludes",
                            "values",
                        ):
                            continue
                        if all(
                            (avp := resolves(c)) is not None
                            and (
                                c.value is None
                                or (
                                    resolves(c.value) is not None
                                    if isinstance(c.value, dictionary.Reference)
                                    else self.values.number(avp, c.value) is not None
                                )
                            )
                            and (
                                c.bit is None or self.values.bit(avp, c.bit) is not None
                            )
                            and all(
                                isinstance(listed, dictionary.ValueRange)
                                or self.values.number(avp, listed) is not None
                                for listed in c.values
                            )
                            for c in _terms(rule)
                        ):
                            yield name, each, rule

    def reached(
        self,
        nodes: Sequence[_Avp],
        reference: dictionary.Reference,
        request: Sequence[_Avp] | None,
    ) -> list[_Avp]:
        """The AVPs `reference` names: of `nodes`, or of the request's, and
        on through each grouped AVP's members, every one of each name."""
        found = list(request or ()) if reference.root is not None else list(nodes)
        for depth, name in enumerate(reference.path):
            if depth:
                found = [child for node in found for child in node.children]
            found = [node for node in found if node.avp.name == name]
        return found

    def condition(
        self,
        nodes: Sequence[_Avp],
        condition: dictionary.Condition,
        request: Sequence[_Avp] | None = None,
    ) -> bool:
        found = self.reached(nodes, condition, request)
        if not found:
            return False
        if isinstance(condition.value, dictionary.Reference):
            others = {n.payload for n in self.reached(nodes, condition.value, request)}
            return any(n.payload in others for n in found)
        if condition.value is None and condition.bit is None and not condition.values:
            return True
        for held in found:
            value = constraints.integer_value(held.avp.data_type, held.payload or b"")
            if value is None:
                continue
            if condition.values:
                if _listed_holds(value, held.avp, condition, self.values):
                    return True
                continue
            if condition.value is not None:
                if value == self.values.number(held.avp, condition.value):
                    return True
                continue
            bit = self.values.bit(held.avp, condition.bit)
            if bit is not None and value >> bit & 1:
                return True
        return False

    def alternatives(
        self,
        nodes: Sequence[_Avp],
        alternatives: Sequence[Sequence[dictionary.Condition]],
        request: Sequence[_Avp] | None = None,
    ) -> bool:
        """Whether one of `alternatives` holds, each when every condition of
        it does, a negated one when it does not."""
        return any(
            all(self.condition(nodes, c, request) != c.negated for c in conjunction)
            for conjunction in alternatives
        )

    def broken(
        self,
        scope: _Scope,
        nodes: Sequence[_Avp],
        request: Sequence[_Avp] | None = None,
    ) -> list[tuple[str, str, dictionary.Constraint]]:
        """The predicates of `scope` that `nodes` break: name, kind,
        constraint. One reading the request is held to `request`, and with
        none is not evaluated, as the plugin leaves it."""
        return [
            (name, kind, each)
            for name, kind, each, _ in self.broken_rules(scope, nodes, request)
        ]

    def broken_rules(
        self,
        scope: _Scope,
        nodes: Sequence[_Avp],
        request: Sequence[_Avp] | None = None,
    ) -> list[tuple[str, str, dictionary.Constraint, dictionary.Rule]]:
        """`broken`, each with the rule broken: a block may hold several of a
        kind (TS 29.272's ULA's Subscription-Data, clause 5.2.1.1.3)."""
        found = []
        for name, each, rule in self.predicates(scope):
            if _reads_request(rule) and request is None:
                continue
            instances = [n for n in nodes if n.avp.name == name]
            if rule.kind == "absent":
                if instances:
                    found.append((name, rule.kind, each, rule))
                continue
            # Each instance in turn, a path starting at the AVP's name
            # reading that one alone, as the plugin reads it.
            if any(
                self.breaks(
                    [n for n in nodes if n.avp.name != name or n is instance],
                    name,
                    rule,
                    request,
                    instance is not None,
                )
                for instance in (instances or [None])
            ):
                found.append((name, rule.kind, each, rule))
        return found

    def breaking(
        self,
        nodes: Sequence[_Avp],
        name: str,
        rule: dictionary.Rule,
        request: Sequence[_Avp] | None,
    ) -> bool:
        """Whether `nodes` still break `rule` on the AVP `name`, of any
        instance: a mend for another rule of the pass may have kept it."""
        instances = [n for n in nodes if n.avp.name == name]
        return any(
            self.breaks(
                [n for n in nodes if n.avp.name != name or n is instance],
                name,
                rule,
                request,
                instance is not None,
            )
            for instance in (instances or [None])
        )

    def breaks(
        self,
        nodes: Sequence[_Avp],
        name: str,
        rule: dictionary.Rule,
        request: Sequence[_Avp] | None,
        subject: bool,
    ) -> bool:
        """Whether `nodes`, holding at most one AVP `name`, break `rule`."""
        if rule.kind == "equals":
            assert rule.reference is not None
            return subject and not self.equal(nodes, name, rule.reference, request)
        holds = self.alternatives(nodes, rule.conditions, request)
        return (
            (rule.kind == "present-if" and holds and not subject)
            or (rule.kind == "absent-if" and holds and subject)
            or (rule.kind == "requires" and subject and not holds)
            or (rule.kind == "excludes" and subject and holds)
            or (
                rule.kind == "values"
                and subject
                and holds
                and not self.allowed(nodes, name, rule)
            )
        )

    def equal(
        self,
        nodes: Sequence[_Avp],
        name: str,
        reference: dictionary.Reference,
        request: Sequence[_Avp] | None,
    ) -> bool:
        """Whether the AVP `name` of `nodes` holds the value of every one the
        reference names, or none is there to compare."""
        held = next(n for n in nodes if n.avp.name == name)
        others = self.reached(nodes, reference, request)
        return all(n.payload == held.payload for n in others)

    def allowed(self, nodes: Sequence[_Avp], name: str, rule: dictionary.Rule) -> bool:
        """Whether the AVP `name` of `nodes` holds one of a values rule's
        values, or a value the plugin cannot read."""
        held = next(n for n in nodes if n.avp.name == name)
        value = constraints.integer_value(held.avp.data_type, held.payload or b"")
        return value is None or value in rule.values

    def satisfy(
        self,
        scope: _Scope,
        nodes: list[_Avp],
        maximal: bool,
        request: Sequence[_Avp] | None = None,
        keep: frozenset[str] = frozenset(),
    ) -> None:
        """Mend what the predicates of `scope` say of `nodes`: drop an
        optional subject that may not be there, add one that must, give one
        the value it must hold. A subject in `keep`, which a predicate
        outside the scope wants, stays where an `excludes` forbids its
        siblings: they go instead."""
        optional = {m.name for m in scope.members if m.min_occurs == 0}
        for _ in range(8):
            broken = self.broken_rules(scope, nodes, request)
            if not broken:
                return
            for name, kind, each, rule in broken:
                if kind == "equals":
                    assert rule.reference is not None
                    other = self.reached(nodes, rule.reference, request)
                    if len({n.payload for n in other}) > 1:
                        raise _Unbuildable(f"{name} cannot take every value it echoes")
                    for held in [n for n in nodes if n.avp.name == name]:
                        if held.payload is None or other[0].payload is None:
                            raise _Unbuildable(
                                f"{name} cannot take the value it echoes"
                            )
                        held.payload = other[0].payload
                elif kind == "values":
                    for held in [n for n in nodes if n.avp.name == name]:
                        if held.avp.data_type not in _FIXED:
                            raise _Unbuildable(f"{name} holds no integer to set")
                        held.payload = _integer(held.avp.data_type, rule.values[0])
                elif kind == "present-if":
                    if any(n.avp.name == name for n in nodes):
                        # Added for another block on it in this pass.
                        continue
                    member = next((m for m in scope.members if m.name == name), None)
                    identifier = self.admitted(scope, member, each)
                    if identifier is None:
                        raise _Unbuildable(
                            f"{name} is to be present and cannot be built"
                            if member is not None
                            else f"{name} is to be present and the body does not"
                            " admit it"
                        )
                    nodes.append(
                        self.avp(self.avps[identifier], scope, member, False, ())
                    )
                elif kind == "excludes" and name in keep:
                    forbidden = {
                        c.path[0]
                        for conjunction in rule.conditions
                        for c in conjunction
                        if c.root is None
                        and len(c.path) == 1
                        and c.path[0] in optional
                        and c.value is None
                        and c.bit is None
                        and not c.values
                        and not c.negated
                    }
                    if not forbidden:
                        if self.mend_inside(nodes, name, kind, rule, request):
                            continue
                        raise _Unbuildable(
                            f"{name} is wanted and a predicate forbids it"
                        )
                    nodes[:] = [n for n in nodes if n.avp.name not in forbidden]
                elif kind in ("absent-if", "excludes") and (
                    other := self.lesser(scope, nodes, name, rule, request, keep)
                ):
                    nodes[:] = [n for n in nodes if n.avp.name != other]
                elif name in optional:
                    if kind != "requires" or not (
                        self.mend_inside(nodes, name, kind, rule, request)
                        or not self.breaking(nodes, name, rule, request)
                    ):
                        nodes[:] = [n for n in nodes if n.avp.name != name]
                elif not self.mend_inside(nodes, name, kind, rule, request):
                    raise _Unbuildable(f"{name} is required and a predicate forbids it")
        if self.broken(scope, nodes, request):
            raise _Unbuildable("the predicates cannot all hold")

    def lesser(
        self,
        scope: _Scope,
        nodes: Sequence[_Avp],
        name: str,
        rule: dictionary.Rule,
        request: Sequence[_Avp] | None,
        keep: frozenset[str],
    ) -> str | None:
        """The optional sibling to drop, rather than the optional AVP `name`,
        where an `absent-if` or `excludes` holds through it: one fewer of the
        scope's predicates read than `name`. A maximal answer keeps its
        Result-Code, which most rules read, beside an Experimental-Result
        whose code would set it aside (TS 29.272 clause 7.4.3). A sibling's
        readers are the other AVPs whose rules test it."""
        optional = {m.name for m in scope.members if m.min_occurs == 0}
        if name not in optional:
            return None
        readers: dict[str, set[str]] = {}
        for subject, _, predicate in self.predicates(scope):
            for c in _terms(predicate):
                if c.root is None and c.path[0] != subject:
                    readers.setdefault(c.path[0], set()).add(subject)

        def read(other: str) -> int:
            return len(readers.get(other, set()) - {name, other})

        for conjunction in rule.conditions:
            if not all(
                self.condition(nodes, c, request) != c.negated for c in conjunction
            ):
                continue
            for c in conjunction:
                other = c.path[0]
                if (
                    c.root is None
                    and not c.negated
                    and other != name
                    and other in optional
                    and other not in keep
                    and read(other) < read(name)
                ):
                    return other
        return None

    def mend_inside(
        self,
        nodes: list[_Avp],
        name: str,
        kind: str,
        rule: dictionary.Rule,
        request: Sequence[_Avp] | None,
    ) -> bool:
        """Mend a required grouped AVP `name` of `nodes` that a predicate's
        paths into its own members break: add the members an alternative of
        a `requires` wants present, or give one the number it wants (TS
        29.154's BTR, its Vendor-Specific-Application-Id holding Nt's
        Auth-Application-Id), or drop an optional member making an
        alternative of an `excludes` or `absent-if` hold (TS 29.336's SIR,
        its User-Identifier holding exactly one identifier). Whether it
        changed anything."""
        changed = False
        for held in [n for n in nodes if n.avp.name == name]:
            # Each instance as the rule reads it, a path from the AVP's name
            # reading that one alone.
            bound = [n for n in nodes if n.avp.name != name or n is held]
            changed = self.mend_one(bound, held, name, kind, rule, request) or changed
        return changed

    def mend_one(
        self,
        nodes: list[_Avp],
        held: _Avp,
        name: str,
        kind: str,
        rule: dictionary.Rule,
        request: Sequence[_Avp] | None,
    ) -> bool:
        """`mend_inside` of one instance, `held`, the only AVP `name` of
        `nodes`."""
        if held.avp.kind != "grouped":
            return False
        inner = self.scope_of(held.avp)

        def own(condition: dictionary.Condition) -> bool:
            # The presence of a member of the AVP itself, by a path from it.
            return (
                condition.root is None
                and len(condition.path) == 2
                and condition.path[0] == name
                and condition.value is None
                and condition.bit is None
                and not condition.values
                and not condition.negated
            )

        def number(condition: dictionary.Condition) -> int | None:
            # The number a member of the AVP itself is to hold, by a path from
            # it: a number, or a name its values give it.
            if (
                condition.root is not None
                or len(condition.path) != 2
                or condition.path[0] != name
                or condition.value is None
                or isinstance(condition.value, dictionary.Reference)
                or condition.bit is not None
                or condition.values
                or condition.negated
            ):
                return None
            if isinstance(condition.value, int):
                return condition.value
            member = next(
                (m for m in inner.members if m.name == condition.path[1]), None
            )
            if member is None or member.avp is None:
                return None
            return self.values.number(self.avps[member.avp], condition.value)

        def numbered(condition: dictionary.Condition) -> bool:
            # A member of the AVP itself holding a number, by a path from it.
            return number(condition) is not None

        if kind == "requires":
            for conjunction in rule.conditions:
                wanted = [
                    c
                    for c in conjunction
                    if self.condition(nodes, c, request) == c.negated
                ]
                if not wanted or not all(own(c) or numbered(c) for c in wanted):
                    continue
                members = [
                    next((m for m in inner.members if m.name == c.path[1]), None)
                    for c in wanted
                ]
                found = [m.avp for m in members if m is not None and m.avp is not None]
                if len(found) != len(members) or any(
                    numbered(c) and self.avps[avp].data_type not in _FIXED
                    for c, avp in zip(wanted, found, strict=True)
                ):
                    continue
                for c, member in zip(wanted, members, strict=True):
                    assert member is not None and member.avp is not None
                    child = next(
                        (n for n in held.children if n.avp.name == member.name),
                        None,
                    )
                    if child is None:
                        definition = self.avps[member.avp]
                        child = self.avp(definition, inner, member, False, ())
                        held.children.append(child)
                    if (wanted_number := number(c)) is not None:
                        child.payload = _integer(child.avp.data_type, wanted_number)
                wanted_names = frozenset(c.path[1] for c in wanted)
                self.satisfy(inner, held.children, False, keep=wanted_names)
                return True
            return False
        if kind in ("excludes", "absent-if"):
            optional = {m.name for m in inner.members if m.min_occurs == 0}
            for conjunction in rule.conditions:
                if not all(
                    self.condition(nodes, c, request) != c.negated for c in conjunction
                ):
                    continue
                for c in reversed(conjunction):
                    if own(c) and c.path[1] in optional:
                        held.children[:] = [
                            child
                            for child in held.children
                            if child.avp.name != c.path[1]
                        ]
                        return True
                    # A member holding the number the alternative wants takes
                    # the next one: an AMBR's two bandwidths, not both 0 (TS
                    # 29.272 clause 7.3.2).
                    if (wanted_number := number(c)) is not None:
                        child = next(
                            (n for n in held.children if n.avp.name == c.path[1]),
                            None,
                        )
                        if child is not None and child.avp.data_type in _FIXED:
                            child.payload = _integer(
                                child.avp.data_type, wanted_number + 1
                            )
                            return True
            return False
        return False


# --- vectors ---------------------------------------------------------------


# The Hop-by-Hop and End-to-End identifiers of the first vector; each next
# vector's are one more, so that a capture pairs an answer with its own
# request alone.
_IDENTIFIERS = 0x5EA4C4A1


@dataclasses.dataclass
class _Message:
    application: dictionary.Application
    command: dictionary.Command
    nodes: list[_Avp]
    error_bit: bool = False
    # The request an answer answers, where its rules read one.
    request: _Message | None = None

    @property
    def asked(self) -> list[_Avp] | None:
        """The request's AVPs, None for no request."""
        return None if self.request is None else self.request.nodes

    def encode(self, identifiers: int = _IDENTIFIERS) -> bytes:
        flags = 0
        if self.command.is_request:
            flags |= _HEADER_FLAGS["R"]
        if "PXY" in self.command.flags:
            flags |= _HEADER_FLAGS["P"]
        if self.error_bit:
            flags |= _HEADER_FLAGS["E"]
        body = b"".join(node.encode() for node in self.nodes)
        application = self.command.application_id or 0
        return (
            bytes([1])
            + (20 + len(body)).to_bytes(3, "big")
            + bytes([flags])
            + self.command.command_code.to_bytes(3, "big")
            + struct.pack("!III", application, identifiers, identifiers)
            + body
        )

    def copy(self) -> _Message:
        return dataclasses.replace(
            self,
            nodes=[n.copy() for n in self.nodes],
            request=None if self.request is None else self.request.copy(),
        )


class _Pages:
    """Each clause's page in the corpus, by document, version and clause."""

    def __init__(self, pages: Mapping[tuple[str, str | None, str], int]) -> None:
        self.pages = pages
        self.newest: dict[tuple[str, str], int] = {}
        for (reference, _version, section), page in pages.items():
            self.newest.setdefault((reference, section), page)

    def __call__(
        self, reference: str, version: str | None, section: str | None
    ) -> int | None:
        if section is None:
            return None
        return self.pages.get((reference, version, section)) or self.newest.get(
            (reference, section)
        )


def _application_name(application: dictionary.Application) -> str:
    return application.name or (
        str(application.application_id)
        if application.application_id is not None
        else application.reference
    )


class _Generator:
    def __init__(
        self,
        built: dictionary.Dictionary,
        pages: Mapping[tuple[str, str | None, str], int],
    ) -> None:
        self.built = built
        self.builder = _Builder(built)
        self.pages = _Pages(pages)
        self.answers = {answer.id: answer for answer in built.answer_messages}
        self.vectors: list[Vector] = []
        self.skipped: list[Skipped] = []

    def run(self) -> Vectors:
        for application in self.built.applications:
            for command in application.commands:
                self.command(application, command)
        return Vectors(
            format_version=FORMAT_VERSION,
            seanchai_version=__version__,
            corpus_version=self.built.corpus_version,
            application_ids=self.built.application_ids,
            vectors=tuple(self.vectors),
            skipped=tuple(self.skipped),
        )

    def label(
        self, application: dictionary.Application, command: dictionary.Command
    ) -> str:
        return f"{_application_name(application)}/{command.abbreviation}"

    def scope(
        self,
        command: dictionary.Command,
        request: dictionary.Command | None = None,
    ) -> _Scope:
        rules: dict[str, list[dictionary.Constraint]] = {}
        for each in command.constraints:
            rules.setdefault(each.avp, []).append(each)
        return _Scope(
            command.members,
            {k: tuple(v) for k, v in rules.items()},
            command.name,
            None if request is None else self.scope(request),
        )

    def request_of(
        self, application: dictionary.Application, command: dictionary.Command
    ) -> dictionary.Command | None:
        """The request an answer's rules read, by the clause their
        constraints give it, or None where none reads one."""
        sections = {
            each.request_section
            for each in command.constraints
            if each.request_section is not None
            and any(
                _reads_request(rule)
                for reading in each.readings
                for rule in reading.rules
            )
        }
        if command.is_request or len(sections) != 1:
            return None
        (section,) = sections
        return next(
            (
                each
                for each in application.commands
                if each.is_request
                and each.command_code == command.command_code
                and each.section == section
            ),
            None,
        )

    def where(
        self, command: dictionary.Command, application: dictionary.Application
    ) -> dict[str, Any]:
        version = (
            application.version if command.defined_in == application.reference else None
        )
        return {
            "reference": command.defined_in,
            "version": version,
            "section": command.section,
            "page": self.pages(command.defined_in, version, command.section),
            "table": None,
        }

    def emit(
        self,
        message: _Message,
        kind: Literal["minimal", "maximal", "negative"],
        what: str | None = None,
        breaks: Breaks | None = None,
        expected: Iterable[Expected] = (),
    ) -> None:
        label = self.label(message.application, message.command)
        identifier = f"{label}/{kind}" + (f"/{what}" if what else "")
        identifiers = (_IDENTIFIERS + len(self.vectors)) % 2**32
        request = message.request
        self.vectors.append(
            Vector(
                id=identifier,
                kind=kind,
                application_id=message.command.application_id,
                command=message.command.name,
                abbreviation=message.command.abbreviation,
                command_code=message.command.command_code,
                is_request=message.command.is_request,
                error_bit=message.error_bit,
                document=message.command.defined_in,
                section=message.command.section,
                octets=message.encode(identifiers).hex(),
                tree=tuple(node.node() for node in message.nodes),
                request=None
                if request is None
                else Request(
                    octets=request.encode(identifiers).hex(),
                    tree=tuple(node.node() for node in request.nodes),
                ),
                breaks=breaks,
                expected=tuple(expected),
            )
        )

    def command(
        self, application: dictionary.Application, command: dictionary.Command
    ) -> None:
        label = self.label(application, command)
        self.builder.application = command.application_id
        asked = self.request_of(application, command)
        scope = self.scope(command, asked)
        # The request an answer's rules read: the fullest one buildable, so
        # that what it may carry is there for the rules to read.
        request = None
        if asked is not None and scope.request is not None:
            for maximal in (True, False):
                try:
                    request = _Message(
                        application, asked, self.builder.body(scope.request, maximal)
                    )
                    break
                except _Unbuildable:
                    continue
        built = {}
        for maximal in (False, True):
            try:
                nodes = self.builder.body(
                    scope, maximal, request=None if request is None else request.nodes
                )
            except _Unbuildable as error:
                self.skipped.append(
                    Skipped(
                        command=label,
                        what="maximal" if maximal else "minimal",
                        reason=str(error),
                    )
                )
                continue
            message = _Message(
                application,
                command,
                nodes,
                request=None if request is None else request.copy(),
            )
            built[maximal] = message
            self.emit(message, "maximal" if maximal else "minimal")
        if not built:
            return
        negatives = _Negatives(self, application, command, scope, built)
        negatives.run()


@dataclasses.dataclass
class _Negatives:
    generator: _Generator
    application: dictionary.Application
    command: dictionary.Command
    scope: _Scope
    built: dict[bool, _Message]
    # How many `in` lists `make_hold` has met, choosing each one's value.
    _turn: int = 0

    @property
    def builder(self) -> _Builder:
        return self.generator.builder

    def base(self) -> _Message:
        return (self.built.get(False) or self.built[True]).copy()

    def full(self) -> _Message:
        return (self.built.get(True) or self.built[False]).copy()

    def abnf(self, rule: str) -> Breaks:
        return Breaks(rule=rule, **self.generator.where(self.command, self.application))

    def at_avp(self, avp: dictionary.Avp, rule: str) -> Breaks:
        return Breaks(
            rule=rule,
            reference=avp.read_through,
            version=avp.version,
            section=avp.section,
            page=self.generator.pages(avp.read_through, avp.version, avp.section),
            table=None,
        )

    def emit(
        self,
        message: _Message,
        what: str,
        breaks: Breaks,
        rule: str,
        severity: Severity,
        also: Iterable[Expected] = (),
    ) -> None:
        if (other := self.accepted_elsewhere(what, rule)) is not None:
            self.skip(
                what,
                f"the command's print in clause {other} holds no such rule, and"
                " a checker may hold the message to it",
            )
            return
        self.generator.emit(
            message,
            "negative",
            what,
            breaks,
            [Expected(rule=rule, severity=severity), *also],
        )

    def accepted_elsewhere(self, what: str, rule: str) -> str | None:
        """The clause of another print of the command under the application
        (TS 29.273's S6b AA-Answer, clauses 9.2.2.2.2 and 9.2.2.5.2) holding
        no rule of the kind a negative breaks on its AVP, which this print
        holds as its member's, or as the AVP's wherever read where it lists
        the member and the other leaves it to `* [ AVP ]` (TS 29.273's
        Visited-Network-Identifier in STa's and SWa's Diameter-EAP-Request):
        the plugin may hold the message to that print, which it breaks
        nothing of. None where no such print is."""
        if not rule.startswith("constraint-") or "/" not in what:
            return None
        kind, name = rule.removeprefix("constraint-"), what.split("/")[1]
        # An element's rule is an encoding's.
        kind = "encoding" if kind == "element" else kind

        def of_kind(each: dictionary.Constraint) -> bool:
            return any(
                each_rule.kind == kind
                for reading in each.readings
                for each_rule in reading.rules
            )

        # The AVP-wide rules of each reading of the AVP: a print listing the
        # member holds them, one leaving it to `* [ AVP ]` does not.
        wide = {
            avp_id
            for each in self.generator.built.constraints
            if each.avp == name
            and each.command is None
            and each.within is None
            and each.messages is None
            and of_kind(each)
            for avp_id in each.avp_ids
        }

        def holds(command: dictionary.Command) -> bool:
            return any(
                each.avp == name and of_kind(each) for each in command.constraints
            ) or any(
                member.name == name and member.avp in wide for member in command.members
            )

        if not holds(self.command):
            return None
        # Another interface's print counts too: TS 29.273 prints SWd's
        # Diameter-EAP-Answer under STa's application id.
        for other in (
            each
            for application in self.generator.built.applications
            for each in application.commands
            if each.application_id == self.command.application_id
        ):
            if (
                other is not self.command
                and other.command_code == self.command.command_code
                and other.is_request == self.command.is_request
                and other.section != self.command.section
                and not holds(other)
            ):
                return other.section
        return None

    def elsewhere(self, each: dictionary.Constraint) -> bool:
        """Whether `each` holds in every answer or request and is another
        document's than the command's: its negatives are its own document's
        commands', and every other command's valid vectors keep it."""
        return each.messages is not None and each.reference != self.command.defined_in

    def skip(self, what: str, reason: str) -> None:
        self.generator.skipped.append(
            Skipped(
                command=self.generator.label(self.application, self.command),
                what=what,
                reason=reason,
            )
        )

    def run(self) -> None:
        self.missing()
        self.occurrences()
        self.position()
        self.flags()
        self.values()
        self.not_allowed()
        self.error_bit()
        self.constraints()

    # The ABNF.

    def top_level(self, message: _Message) -> dict[str, list[_Avp]]:
        found: dict[str, list[_Avp]] = {}
        for node in message.nodes:
            found.setdefault(node.avp.name, []).append(node)
        return found

    def missing(self) -> None:
        message = self.base()
        for member in self.command.members:
            if member.min_occurs == 0 or member.avp is None:
                continue
            trial = message.copy()
            trial.nodes = [n for n in trial.nodes if n.avp.name != member.name]
            if self.builder.broken(self.scope, trial.nodes, trial.asked):
                continue
            bracket = "< >" if member.presence == "fixed" else "{ }"
            self.emit(
                trial,
                f"avp-missing/{member.name}",
                self.abnf(f"{bracket[0]} {member.name} {bracket[-1]} is required"),
                "avp-missing",
                "error",
            )
            return

    def occurrences(self) -> None:
        message = self.base()
        for member in self.command.members:
            # A fixed member's copy would move the fixed members after it.
            if (
                member.avp is None
                or member.max_occurs is None
                or member.presence == "fixed"
            ):
                continue
            present = [
                i for i, n in enumerate(message.nodes) if n.avp.name == member.name
            ]
            if not present:
                continue
            trial = message.copy()
            node = trial.nodes[present[0]]
            extra = member.max_occurs + 1 - len(present)
            for _ in range(extra):
                trial.nodes.insert(present[0] + 1, node.copy())
            high = "" if member.max_occurs == 1 else str(member.max_occurs)
            self.emit(
                trial,
                f"avp-occurrences/{member.name}",
                self.abnf(f"{member.name} occurs at most {high or 'once'}"),
                "avp-occurrences",
                "error",
            )
            return

    def position(self) -> None:
        message = self.base()
        leading = []
        for member in self.command.members:
            if member.presence != "fixed":
                break
            leading.append(member.name)
        if not leading or len(message.nodes) <= len(leading):
            return
        trial = message.copy()
        first = next(
            (i for i, n in enumerate(trial.nodes) if n.avp.name == leading[0]), None
        )
        other = next(
            (i for i, n in enumerate(trial.nodes) if n.avp.name not in leading), None
        )
        if first is None or other is None:
            return
        trial.nodes[first], trial.nodes[other] = trial.nodes[other], trial.nodes[first]
        self.emit(
            trial,
            f"avp-position/{leading[0]}",
            self.abnf(f"< {leading[0]} > is AVP 1"),
            "avp-position",
            "error",
        )

    # Flags.

    def flags(self) -> None:
        message = self.full()
        cleared = set_ = None
        for index, node in enumerate(message.nodes):
            rules = node.avp.flag_rules
            if cleared is None and ast.AvpFlag.MANDATORY in rules.must:
                cleared = index
            if (
                set_ is None
                and node.avp.vendor_id == 0
                and ast.AvpFlag.VENDOR in rules.must_not
            ):
                set_ = index
        if cleared is not None:
            trial = message.copy()
            node = trial.nodes[cleared]
            node.flags &= ~_M
            self.emit(
                trial,
                f"flag-must/{node.avp.name}/M",
                self.at_avp(node.avp, f"{node.avp.name}: the M bit must be set"),
                "flag-must",
                "error",
            )
        if set_ is not None:
            trial = message.copy()
            node = trial.nodes[set_]
            node.flags |= _V
            self.emit(
                trial,
                f"flag-must-not/{node.avp.name}/V",
                self.at_avp(node.avp, f"{node.avp.name}: the V bit must not be set"),
                "flag-must-not",
                "error",
            )

    # Values.

    def each_node(self, message: _Message) -> Iterator[tuple[_Avp, _Scope]]:
        """Every non-grouped AVP of `message` with its scope, depth first."""

        def walk(nodes: list[_Avp], scope: _Scope) -> Iterator[tuple[_Avp, _Scope]]:
            for node in nodes:
                if _opaque(node.avp):
                    continue
                if node.avp.kind == "grouped":
                    yield from walk(node.children, self.builder.scope_of(node.avp))
                else:
                    yield node, scope

        yield from walk(message.nodes, self.scope)

    def first(self, test) -> Iterator[tuple[_Message, _Avp, _Scope]]:
        message = self.full()
        for node, scope in self.each_node(message):
            if test(node):
                yield message, node, scope

    def compared(self, node: _Avp, scope: _Scope) -> bool:
        """Whether an `equals` rule holds `node` to another AVP's value."""
        return any(
            rule.kind == "equals"
            for rule in self.builder.rules_for(
                node.avp, scope, node.member.name if node.member else node.avp.name
            )
        )

    def keeps_rules(self, node: _Avp, scope: _Scope, payload: bytes) -> bool:
        rules = _value_rules(
            self.builder.rules_for(
                node.avp, scope, node.member.name if node.member else node.avp.name
            )
        )
        codec = _codec_of(rules)
        return all(_holds(rule, payload, node.avp.data_type, codec) for rule in rules)

    def values(self) -> None:
        # A reserved or void value.
        for message, node, scope in self.first(
            lambda n: (
                n.avp.data_type is ast.DataType.ENUMERATED
                and any(v.kind in ("reserved", "void") for v in n.avp.values)
            )
        ):
            withdrawn = next(
                v for v in node.avp.values if v.kind in ("reserved", "void")
            )
            assert withdrawn.first is not None
            payload = _integer(ast.DataType.ENUMERATED, withdrawn.first)
            if not self.keeps_rules(node, scope, payload):
                continue
            node.payload = payload
            self.emit(
                message,
                f"enum-value/{node.avp.name}",
                self.at_avp(
                    node.avp, f"{node.avp.name} {withdrawn.first} is {withdrawn.kind}"
                ),
                "enum-value",
                "error",
            )
            break
        # A bit no document names.
        for message, node, scope in self.first(
            lambda n: (
                n.avp.data_type is ast.DataType.UNSIGNED32
                and _identity(n.avp) in self.builder.values.bits
            )
        ):
            named = self.builder.values.bits[_identity(node.avp)]
            bit = next((b for b in range(32) if b not in named), None)
            if bit is None:
                continue
            payload = _integer(ast.DataType.UNSIGNED32, 1 << bit)
            if not self.keeps_rules(node, scope, payload):
                continue
            node.payload = payload
            self.emit(
                message,
                f"bits/{node.avp.name}/{bit}",
                self.at_avp(node.avp, f"{node.avp.name} names no bit {bit}"),
                "bits",
                "note",
            )
            break
        # A value no document names.
        for message, node, scope in self.first(
            lambda n: (
                n.avp.data_type is ast.DataType.UNSIGNED32
                and _identity(n.avp) in self.builder.values.named
            )
        ):
            named = self.builder.values.named[_identity(node.avp)]
            value = next(
                number for number in range(len(named) + 1) if number not in named
            )
            payload = _integer(ast.DataType.UNSIGNED32, value)
            if not self.keeps_rules(node, scope, payload):
                continue
            node.payload = payload
            self.emit(
                message,
                f"values/{node.avp.name}/{value}",
                self.at_avp(node.avp, f"{node.avp.name} names no value {value}"),
                "values",
                "note",
            )
            break
        # UTF-8 that is not, in an AVP no rule holds to another's value,
        # which the broken octets would break too.
        for message, node, scope in self.first(
            lambda n: n.avp.data_type is ast.DataType.UTF8_STRING
        ):
            payload = b"\xff" + (node.payload or b"")[1:]
            if not self.keeps_rules(node, scope, payload) or self.compared(node, scope):
                continue
            node.payload = payload
            self.emit(
                message,
                f"utf8/{node.avp.name}",
                Breaks(
                    rule=f"{node.avp.name} is UTF8String",
                    reference="RFC6733",
                    version=None,
                    section="4.3.1",
                    page=self.generator.pages("RFC6733", None, "4.3.1"),
                    table=None,
                ),
                "utf8",
                "error",
            )
            break
        # An integer of the wrong length.
        for message, node, _scope in self.first(
            lambda n: (
                n.avp.data_type in (ast.DataType.UNSIGNED32, ast.DataType.INTEGER32)
            )
        ):
            node.payload = (node.payload or b"\0\0\0\0")[:3]
            self.emit(
                message,
                f"data-length/{node.avp.name}",
                Breaks(
                    rule=f"{node.avp.name} is {node.avp.data_type}, 4 octets",
                    reference="RFC6733",
                    version=None,
                    section="4.2",
                    page=self.generator.pages("RFC6733", None, "4.2"),
                    table=None,
                ),
                "data-length",
                "error",
            )
            break

    def not_allowed(self) -> None:
        if any(m.kind == "wildcard" for m in self.command.members):
            return
        listed = {
            _identity(self.builder.avps[m.avp]) for m in self.command.members if m.avp
        }
        for avp in self.generator.built.avps:
            if (
                avp.kind != "plain"
                or _identity(avp) in listed
                or avp.data_type
                not in (ast.DataType.UNSIGNED32, ast.DataType.OCTET_STRING)
                or avp.id in self.builder.own
                or _identity(avp) in self.builder.values.bits
                or _identity(avp) in self.builder.values.named
                or avp.name in ("Result-Code", "Experimental-Result-Code")
            ):
                continue
            message = self.base()
            payload = _payload(avp, (), self.builder.values)
            if payload is None:
                continue
            message.nodes.insert(len(message.nodes), _Avp(avp, _flags(avp), payload))
            if self.command.members and self.command.members[-1].presence == "fixed":
                # The trailing fixed member stays last.
                message.nodes.insert(-1, message.nodes.pop())
            self.emit(
                message,
                f"avp-not-allowed/{avp.name}",
                self.abnf(f"{self.command.name} has no * [ AVP ]"),
                "avp-not-allowed",
                "error",
            )
            return

    def error_bit(self) -> None:
        if self.command.is_request or self.command.answer_message is None:
            return
        answer = self.generator.answers.get(self.command.answer_message)
        if answer is None:
            return
        rules: dict[str, list[dictionary.Constraint]] = {}
        for each in answer.constraints:
            rules.setdefault(each.avp, []).append(each)
        scope = _Scope(
            answer.members, {k: tuple(v) for k, v in rules.items()}, "answer-message"
        )
        try:
            nodes = self.builder.body(scope, False)
        except _Unbuildable as error:
            self.skip("e-bit-unexpected", str(error))
            return
        message = _Message(self.application, self.command, nodes, error_bit=True)
        self.emit(
            message,
            "e-bit-unexpected",
            Breaks(
                rule="the E bit is set on an answer whose Result-Code is no"
                " protocol error or permanent failure",
                reference="RFC6733",
                version=None,
                section="7.2",
                page=self.generator.pages("RFC6733", None, "7.2"),
                table=None,
            ),
            "e-bit-unexpected",
            "warn",
        )

    # Interpreted constraints.

    def at_constraint(self, constraint: dictionary.Constraint, rule: str) -> Breaks:
        return Breaks(
            rule=rule,
            reference=constraint.reference,
            version=constraint.version,
            section=constraint.section,
            page=constraint.page,
            table=constraint.table,
        )

    def constraints(self) -> None:
        done: set[tuple[str, str, str]] = set()
        # A value rule of an AVP the full message holds that no payload
        # breaks alone: listed in `skipped` once every holder is tried.
        missed: dict[tuple[str, str, str], str] = {}
        message = self.full()
        for index, (node, scope) in enumerate(list(self.each_node(message))):
            name = node.member.name if node.member else node.avp.name
            held = [
                *self.builder.own.get(node.avp.id, ()),
                *scope.rules.get(name, ()),
            ]
            for each in held:
                for reading in each.readings:
                    for rule in _value_rules(reading.rules):
                        key = (each.section, name, rule.kind)
                        if key in done:
                            continue
                        payload = self.breaking(node, scope, rule)
                        if payload is None:
                            kind = "element" if _element_of(rule) else rule.kind
                            missed[key] = f"constraint-{kind}/{name}/{each.section}"
                            continue
                        done.add(key)
                        trial = message.copy()
                        # The copy at the node's own place: another of its
                        # reading and value may sit in another grouped AVP
                        # (TS 29.273's PDN-Type in TWAN-Connectivity-Parameters
                        # and in APN-Configuration).
                        target, _ = list(self.each_node(trial))[index]
                        target.payload = payload
                        if self.builder.broken(self.scope, trial.nodes, trial.asked):
                            # Every value breaking it breaks a predicate on a
                            # path to it too.
                            self.skip(
                                f"constraint-{rule.kind}/{name}/{each.section}",
                                "the value breaking it breaks a predicate on it too",
                            )
                            continue
                        kind = "element" if _element_of(rule) else rule.kind
                        self.emit(
                            trial,
                            f"constraint-{kind}/{name}/{each.section}",
                            self.at_constraint(each, f"{name}: {_rule_text(rule)}"),
                            f"constraint-{kind}",
                            "note",
                            self.unnamed_code(target),
                        )
        for key, what in missed.items():
            if key not in done:
                self.skip(
                    what, "no value of the AVP breaks it and keeps its other rules"
                )
        self.predicate_vectors()
        self.request_vectors()
        self.grouped_vectors()

    def unnamed_code(self, node: _Avp) -> list[Expected]:
        """The warning a Result-Code no document numbers draws beside the
        rule its value breaks: TS 29.338's codes, which clause 7.3.1 keeps
        out of Result-Code, are none of the base protocol's."""
        if node.avp.name != "Result-Code" or node.payload is None:
            return []
        value = int.from_bytes(node.payload, "big")
        if value in self.builder.values.vendor_codes.get(0, ()):
            return []
        return [Expected(rule="result-code", severity="warn")]

    def each_grouped(
        self, message: _Message
    ) -> Iterator[tuple[_Avp, _Scope, list[_Avp]]]:
        """Every grouped AVP of `message` with its scope and the run holding
        it, depth first."""

        def walk(
            nodes: list[_Avp], scope: _Scope
        ) -> Iterator[tuple[_Avp, _Scope, list[_Avp]]]:
            for node in nodes:
                if node.avp.kind == "grouped" and not _opaque(node.avp):
                    yield node, scope, nodes
                    yield from walk(node.children, self.builder.scope_of(node.avp))

        yield from walk(message.nodes, self.scope)

    def grouped_vectors(self) -> None:
        """One vector per members, unique and nested values rule the plugin
        checks: a grouped AVP's members, two grouped AVPs beside each other, or
        a member against its siblings, broken."""
        done: set[tuple[str, str, str]] = set()
        message = self.full()
        for index, (node, scope, _run) in enumerate(self.each_grouped(message)):
            name = node.member.name if node.member else node.avp.name
            inner = self.builder.scope_of(node.avp)
            held = [*self.builder.own.get(node.avp.id, ()), *scope.rules.get(name, ())]
            for each in held:
                for reading in each.readings:
                    for rule in reading.rules:
                        key = (each.section, name, rule.kind)
                        if rule.kind != "members" or key in done:
                            continue
                        trial = message.copy()
                        target, outer, run = list(self.each_grouped(trial))[index]
                        # Breaking the rule must keep the predicates of the
                        # run holding the AVP whose paths reach into it: TS
                        # 29.336's CIR requires its User-Identifier to hold
                        # an External-Identifier or MSISDN.
                        if self.break_members(
                            target, inner, rule
                        ) and not self.builder.broken(outer, run):
                            done.add(key)
                            self.emit(
                                trial,
                                f"constraint-members/{name}/{each.section}",
                                self.at_constraint(each, f"{name}: {_rule_text(rule)}"),
                                "constraint-members",
                                "note",
                            )
            for member, rules in inner.rules.items():
                for each in rules:
                    for reading in each.readings:
                        for rule in reading.rules:
                            key = (each.section, member, rule.kind)
                            if rule.kind not in ("unique", "values") or key in done:
                                continue
                            trial = message.copy()
                            target, _, run = list(self.each_grouped(trial))[index]
                            if rule.kind == "unique":
                                broke = self.break_unique(target, run, member)
                            else:
                                broke = self.break_values(
                                    target.children, inner, member, rule
                                )
                            # Breaking a member's rule must keep the grouped
                            # AVP's own: a values rule made to fail by adding
                            # a member breaks a `members only` of TS 29.214's
                            # Media-Component-Description in
                            # Acceptable-Service-Info.
                            if broke and self.members_hold(target, held):
                                done.add(key)
                                self.emit(
                                    trial,
                                    f"constraint-{rule.kind}/{member}/{each.section}",
                                    self.at_constraint(
                                        each, f"{member}: {_rule_text(rule)}"
                                    ),
                                    f"constraint-{rule.kind}",
                                    "note",
                                )

    def all_members_hold(self, message: _Message) -> bool:
        """Whether each grouped AVP of `message` keeps the `members` rules on
        it, its own and its scope's."""
        for node, scope, _ in self.each_grouped(message):
            name = node.member.name if node.member else node.avp.name
            held = [*self.builder.own.get(node.avp.id, ()), *scope.rules.get(name, ())]
            if not self.members_hold(node, held):
                return False
        return True

    def members_hold(self, node: _Avp, held: Sequence[dictionary.Constraint]) -> bool:
        """Whether grouped `node`'s members keep the `members` rules of
        `held`, the constraints on the node itself."""
        names = {c.member.name for c in node.children if c.member}
        for each in held:
            for reading in each.readings:
                for rule in reading.rules:
                    if rule.kind != "members":
                        continue
                    if rule.relation is ast.BitsRelation.ONLY:
                        if not names <= set(rule.members):
                            return False
                    elif not names & set(rule.members):
                        return False
        return True

    def inner_holds(self, scope: _Scope, children: Sequence[_Avp]) -> bool:
        """Whether `children` keep their body's counts and predicates."""
        for member in scope.members:
            if member.avp is None:
                continue
            count = sum(
                1 for n in children if n.member and n.member.name == member.name
            )
            if count < member.min_occurs or (
                member.max_occurs is not None and count > member.max_occurs
            ):
                return False
        return not self.builder.broken(scope, children)

    def break_members(self, node: _Avp, inner: _Scope, rule: dictionary.Rule) -> bool:
        """Break a members rule in grouped `node`, and nothing else."""
        children = node.children
        if rule.relation is ast.BitsRelation.AT_LEAST_ONE:
            children[:] = [
                c for c in children if not (c.member and c.member.name in rule.members)
            ]
        else:
            listed = {c.member.name for c in children if c.member}
            for member in inner.members:
                if (
                    member.kind != "avp"
                    or member.avp is None
                    or member.name in rule.members
                    or member.name in listed
                ):
                    continue
                try:
                    children.append(
                        self.builder.avp(
                            self.builder.avps[member.avp], inner, member, False, ()
                        )
                    )
                except _Unbuildable:
                    continue
                break
            else:
                return False
        return self.inner_holds(inner, children)

    def break_unique(self, node: _Avp, run: list[_Avp], member: str) -> bool:
        """Give the member `member` of `node` the value another grouped AVP of
        its reading beside it holds."""
        mine = next(
            (c for c in node.children if c.member and c.member.name == member), None
        )
        for other in run:
            if other is node or other.avp.id != node.avp.id:
                continue
            theirs = next(
                (c for c in other.children if c.member and c.member.name == member),
                None,
            )
            if mine is None or theirs is None or theirs.payload is None:
                return False
            if mine.payload == theirs.payload:
                return False
            mine.payload = theirs.payload
            return True
        return False

    def break_values(
        self, children: list[_Avp], inner: _Scope, member: str, rule: dictionary.Rule
    ) -> bool:
        """Make a values rule's condition hold among `children`, a run of
        `inner`'s members, and its AVP `member` hold another value, and break
        nothing else."""
        if not all(
            self.builder.values.number(self.builder.avps[m.avp], c.value) is not None
            for c in _terms(rule)
            for m in inner.members
            if m.name == c.avp
            and m.avp is not None
            and c.value is not None
            and not isinstance(c.value, dictionary.Reference)
        ):
            return False
        if not all(self.make_hold(children, c, inner) for c in rule.conditions[0]):
            return False
        subject = self.sibling(children, member, inner)
        if subject is None or subject.avp.data_type not in _FIXED:
            return False
        candidates = [
            v.value
            for v in subject.avp.values
            if v.kind == "value" and v.value is not None
        ] or [0, 1, 2]
        for value in candidates:
            if value in rule.values:
                continue
            payload = _integer(subject.avp.data_type, value)
            if not self.keeps_rules(subject, inner, payload):
                continue
            subject.payload = payload
            broken = self.builder.broken(inner, children)
            return [(n, k) for n, k, _ in broken] == [(member, "values")] and (
                self.inner_holds(_Scope(inner.members, {}, inner.name), children)
            )
        return False

    def breaking(
        self, node: _Avp, scope: _Scope, rule: dictionary.Rule
    ) -> bytes | None:
        """A payload breaking `rule` and no other value rule of the AVP."""
        good = node.payload or b""
        data_type = node.avp.data_type
        rules = _value_rules(
            self.builder.rules_for(
                node.avp, scope, node.member.name if node.member else node.avp.name
            )
        )
        codec = _codec_of(rules)
        candidates: list[bytes] = []
        if rule.kind == "length":
            counts = [
                n
                for n in ((rule.high or 0) + 1, (rule.low or 0) - 1)
                if n >= 0 and (rule.high is not None or n < (rule.low or 0))
            ]
            for count in counts:
                if rule.unit is ast.LengthUnit.DIGITS and codec is not None:
                    candidates.append(_digits(codec, count))
                elif rule.unit is ast.LengthUnit.CHARACTERS:
                    candidates.append((good * (count + 1))[:count] or b"")
                else:
                    candidates.append((good + b"\x01" * count)[:count])
        elif rule.kind == "range":
            bounds = constraints.integer_bounds(data_type)
            if bounds is not None:
                for value in ((rule.high or 0) + 1, (rule.low or 0) - 1):
                    if bounds[0] <= value <= bounds[1] and (
                        (rule.high is not None and value > rule.high)
                        or (rule.low is not None and value < rule.low)
                    ):
                        candidates.append(_integer(data_type, value))
        elif rule.kind == "bits" and (
            data_type in _FIXED or data_type is ast.DataType.OCTET_STRING
        ):
            held = constraints.bits_value(data_type, good) or 0
            named = sorted(self.builder.values.bits.get(_identity(node.avp), ()))
            match rule.relation:
                case ast.BitsRelation.AT_MOST_ONE:
                    values = [sum(1 << each for each in rule.bits)]
                case ast.BitsRelation.SET:
                    values = [held & ~(1 << each) for each in rule.bits]
                case ast.BitsRelation.CLEAR:
                    values = [held | 1 << each for each in rule.bits]
                case ast.BitsRelation.ONLY:
                    values = [
                        held | 1 << each
                        for each in [*named, *range(64)]
                        if each not in rule.bits
                    ][:8]
                case _:
                    values = [0]
            for value in values:
                if data_type is ast.DataType.OCTET_STRING:
                    if good and value < 1 << 8 * len(good):
                        candidates.append(value.to_bytes(len(good), "big"))
                elif value < 1 << 8 * _FIXED[data_type]:
                    candidates.append(_integer(data_type, value))
        elif rule.kind == "exclude":
            candidates += [
                _integer(data_type, value)
                for value in rule.values
                if data_type in _FIXED
            ]
        elif rule.kind == "encoding" and (entry := _element_of(rule)) is not None:
            candidates += elements.breaking(entry, good, data_type)
        elif (
            rule.kind == "encoding"
            and (broken := _BROKEN_CODEC.get(rule.codec) if rule.codec else None)
            and good
        ):
            candidates.append(broken(good))
        for payload in candidates:
            if _holds(rule, payload, data_type, codec):
                continue
            others = [r for r in rules if r is not rule]
            if not all(_holds(r, payload, data_type, codec) for r in others):
                continue
            if data_type is ast.DataType.ENUMERATED:
                value = constraints.integer_value(data_type, payload)
                if not any(
                    v.kind == "value" and v.value == value for v in node.avp.values
                ):
                    continue
            named = self.builder.values.named.get(_identity(node.avp))
            if (
                named is not None
                and constraints.integer_value(data_type, payload) not in named
            ):
                continue
            if data_type is ast.DataType.UTF8_STRING:
                try:
                    payload.decode("utf-8")
                except UnicodeDecodeError:
                    continue
            if data_type is ast.DataType.DIAMETER_IDENTITY and not _host(payload):
                continue
            if data_type in _FIXED and len(payload) != _FIXED[data_type]:
                continue
            if data_type is ast.DataType.ADDRESS and not _address(payload):
                continue
            if _identity(node.avp) in self.builder.values.bits:
                value = constraints.integer_value(data_type, payload) or 0
                named = self.builder.values.bits[_identity(node.avp)]
                if any(value >> b & 1 and b not in named for b in range(64)):
                    continue
            return payload
        return None

    def predicate_vectors(self) -> None:
        """One vector per predicate the plugin checks, of the command's own
        scope and of each grouped AVP's the full message holds: the subject
        placed, or not, against its conditions. One no vector breaks is
        listed in `skipped`, with why."""
        done: set[tuple[str, str, str]] = set()
        for name, each, rule in self.builder.predicates(self.scope):
            if _reads_request(rule):
                continue  # `request_vectors`
            if self.elsewhere(each):
                continue
            message = self.full()
            why = self.predicate_vector(
                message, message.nodes, self.scope, name, each, rule
            )
            if why is not None:
                self.skip(f"constraint-{rule.kind}/{name}/{each.section}", why)
        full = self.full()
        # Of a grouped AVP's, why the last occurrence tried could not.
        missed: dict[tuple[str, str, str], str] = {}
        for index, (node, _scope, _run) in enumerate(self.each_grouped(full)):
            inner = self.builder.scope_of(node.avp)
            for name, each, rule in self.builder.predicates(inner):
                key = (each.section, name, rule.kind)
                # A grouped AVP's values rules are `grouped_vectors`'.
                if key in done or rule.kind == "values" or _reads_request(rule):
                    continue
                message = full.copy()
                target, _, _ = list(self.each_grouped(message))[index]
                why = self.predicate_vector(
                    message, target.children, inner, name, each, rule
                )
                if why is None:
                    done.add(key)
                else:
                    missed[key] = why
        for (section, name, kind), why in missed.items():
            if (section, name, kind) not in done:
                self.skip(f"constraint-{kind}/{name}/{section}", why)

    def predicate_vector(
        self,
        message: _Message,
        nodes: list[_Avp],
        scope: _Scope,
        name: str,
        each: dictionary.Constraint,
        rule: dictionary.Rule,
    ) -> str | None:
        """Break `rule` on `name` in `nodes`, the run of `message` `scope`
        reads, and nothing else, and emit the vector; why not where it
        cannot."""
        top = nodes is message.nodes
        if rule.kind == "absent":
            if not top:
                return "an absent rule within a grouped AVP is broken by no vector"
            if not self.add_absent(message, name, each):
                return "the AVP it keeps out cannot be added breaking nothing else"
        elif rule.kind == "values":
            if not self.break_values(nodes, scope, name, rule):
                return "no value it forbids keeps the message's other rules"
            if not top and self.builder.broken(
                self.scope, message.nodes, message.asked
            ):
                return "breaking it breaks a predicate on a path into it"
        else:
            member = next((m for m in scope.members if m.name == name), None)
            if member is None:
                return "the body admits the AVP only through * [ AVP ]"
            subject = [n for n in nodes if n.avp.name == name]
            if len(subject) > 1 and member.min_occurs <= 1:
                # One instance to break, so that the checker reports one.
                nodes[:] = [n for n in nodes if n.avp.name != name or n is subject[0]]
                subject = subject[:1]
            # An instance of the valid message, to keep the rule beside the
            # one made to break it.
            good = subject[0].copy() if subject else None
            if rule.kind in ("absent-if", "excludes", "present-if"):
                if not all(self.make_hold(nodes, c, scope) for c in rule.conditions[0]):
                    return "its conditions cannot be made to hold"
                if rule.kind == "present-if":
                    if member.min_occurs:
                        return "the AVP is required, so never absent"
                    nodes[:] = [n for n in nodes if n.avp.name != name]
                elif not any(n.avp.name == name for n in nodes):
                    # Making a condition on a path into the subject hold
                    # placed it (TS 29.272's AMBR, excluded with both its
                    # bandwidths 0).
                    if member.avp is None:
                        return "the corpus cannot complete the AVP"
                    nodes.append(
                        self.builder.avp(
                            self.builder.avps[member.avp], scope, member, False, ()
                        )
                    )
            else:  # requires
                if not subject:
                    if member.avp is None:
                        return "the corpus cannot complete the AVP"
                    nodes.append(
                        self.builder.avp(
                            self.builder.avps[member.avp], scope, member, False, ()
                        )
                    )
                if not all(
                    any(self.make_fail(nodes, c, scope) for c in conjunction)
                    for conjunction in rule.conditions
                ):
                    return "its conditions cannot be made to fail"
            # The rules reading the request too, which the plugin holds the
            # answer to where the capture has it.
            if top and not message.error_bit and self.protocol_error(nodes):
                # RFC 6733 section 7.1.3: such an answer sets the E bit and
                # is the <answer-message>, which no negative is built of.
                return "its conditions make a protocol error, sent with the E bit"
            broken = self.builder.broken(scope, nodes, message.asked if top else None)
            if [(n, k) for n, k, _ in broken] != [(name, rule.kind)]:
                return "breaking it breaks another predicate too"
            if not self.counts_hold(nodes, scope):
                return "breaking it breaks the body's occurrences"
            if not top and (
                self.builder.broken(self.scope, message.nodes, message.asked)
                or not self.counts_hold(message.nodes)
            ):
                return "breaking it breaks a rule on a path into its grouped AVP"
            if any(
                self.builder.broken(self.builder.scope_of(node.avp), node.children)
                for node, _, _ in self.each_grouped(message)
                if node.children is not nodes
            ):
                return "making its conditions hold breaks a grouped AVP's own rule"
            if (
                good is not None
                and rule.kind != "present-if"
                and _binds(rule, name)
                and (member.max_occurs is None or member.max_occurs > 1)
            ):
                self.beside(message, nodes, scope, name, rule, good, top)
        if not self.all_members_hold(message):
            # Adding the subject broke a `members` rule on the grouped AVP
            # holding it: TS 32.299's Multiple-Services-Credit-Control within
            # Offline-Charging, given a Reporting-Reason.
            return "placing the AVP breaks a members rule on the AVP holding it"
        self.emit(
            message,
            f"constraint-{rule.kind}/{name}/{each.section}",
            self.at_constraint(each, f"{name}: {_rule_text(rule)}"),
            f"constraint-{rule.kind}",
            "note",
        )
        return None

    def protocol_error(self, nodes: Sequence[_Avp]) -> bool:
        """Whether `nodes` hold a Result-Code of a protocol error (3xxx)."""
        return any(
            n.avp.name == "Result-Code"
            and n.payload is not None
            and 3000 <= int.from_bytes(n.payload, "big") < 4000
            for n in nodes
        )

    def beside(
        self,
        message: _Message,
        nodes: list[_Avp],
        scope: _Scope,
        name: str,
        rule: dictionary.Rule,
        good: _Avp,
        top: bool,
    ) -> None:
        """Put `good`, an instance of the AVP `name` keeping `rule`, before
        the one breaking it, where that breaks nothing else: a checker
        reading any instance for a path from the AVP would miss the break
        (RFC 4006 section 5.2, two Multiple-Services-Credit-Control of an
        initial request, one without its Requested-Service-Unit)."""
        request = message.asked if top else None
        alone = [n for n in nodes if n.avp.name != name] + [good]
        if self.builder.breaks(alone, name, rule, request, True):
            return
        if good.avp.kind == "grouped" and self.collides(good, nodes):
            # A copy would hold a member a `unique` rule keeps apart from the
            # instance it copies: TS 29.272's Context-Identifier in each
            # APN-Configuration of TS 29.273's Non-3GPP-User-Data.
            return
        index = next(i for i, n in enumerate(nodes) if n.avp.name == name)
        nodes.insert(index, good)
        broken = self.builder.broken(scope, nodes, request)
        kept = [(n, k) for n, k, _ in broken] == [(name, rule.kind)] and (
            self.counts_hold(nodes, scope)
        )
        if kept and not top:
            kept = not self.builder.broken(
                self.scope, message.nodes, message.asked
            ) and self.counts_hold(message.nodes)
        if not kept:
            nodes.remove(good)

    def collides(self, good: _Avp, run: Sequence[_Avp]) -> bool:
        """Whether grouped `good` holds a member a `unique` rule on its
        reading keeps apart, with the value another of its reading in `run`
        holds."""
        inner = self.builder.scope_of(good.avp)
        unique = {
            member
            for member, rules in inner.rules.items()
            if any(
                rule.kind == "unique"
                for each in rules
                for reading in each.readings
                for rule in reading.rules
            )
        }
        for member in unique:
            mine = {
                c.payload
                for c in good.children
                if c.member and c.member.name == member and c.payload is not None
            }
            for other in run:
                if other is good or other.avp.id != good.avp.id:
                    continue
                if mine & {
                    c.payload
                    for c in other.children
                    if c.member and c.member.name == member
                }:
                    return True
        return False

    def add_absent(
        self, message: _Message, name: str, each: dictionary.Constraint
    ) -> bool:
        """Add to `message` the AVP `name`, which an `absent` rule keeps out,
        a member of the body or one its `* [ AVP ]` admits, and break nothing
        else."""
        member = next((m for m in self.scope.members if m.name == name), None)
        identifier = self.builder.admitted(self.scope, member, each)
        if identifier is None or identifier not in self.builder.avps:
            return False
        try:
            node = self.builder.avp(
                self.builder.avps[identifier], self.scope, member, False, ()
            )
        except _Unbuildable:
            return False
        message.nodes.append(node)
        broken = self.builder.broken(self.scope, message.nodes, message.asked)
        return [(n, k) for n, k, _ in broken] == [(name, "absent")] and (
            self.counts_hold(message.nodes)
        )

    def request_vectors(self) -> None:
        """For each rule of the command's own scope reading the request: a
        valid pair, the rule's conditions met and the rule kept, and a
        negative pair breaking it and nothing else."""
        if self.scope.request is None:
            return
        for name, each, rule in self.builder.predicates(self.scope):
            if not _reads_request(rule) or self.elsewhere(each):
                continue
            what = f"{rule.kind}/{name}/{each.section}"
            made = self.pair(name, rule, each)
            if made is None:
                self.skip(
                    f"constraint-{what}",
                    "no request and answer meet the rule's conditions and keep"
                    " every other rule",
                )
                continue
            valid, negative = made
            self.generator.emit(valid, "maximal", f"request/{what}")
            self.emit(
                negative,
                f"constraint-{what}",
                self.at_constraint(each, f"{name}: {_rule_text(rule)}"),
                f"constraint-{rule.kind}",
                "note",
            )

    def run_of(
        self, message: _Message, reference: dictionary.Reference
    ) -> tuple[list[_Avp], _Scope] | None:
        """The run of AVPs `reference` names one of, and its scope: the
        answer's, or the request's."""
        if reference.root is None:
            return message.nodes, self.scope
        if message.request is None or self.scope.request is None:
            return None
        return message.request.nodes, self.scope.request

    def holds_but(self, message: _Message, broken: list[tuple[str, str]]) -> bool:
        """Whether `message` and its request break no rule but `broken`, the
        answer's predicates' names and kinds."""
        request = message.request
        if request is None or self.scope.request is None:
            return False
        found = self.builder.broken(self.scope, message.nodes, request.nodes)
        return (
            [(n, k) for n, k, _ in found] == broken
            and not self.builder.broken(self.scope.request, request.nodes)
            and self.counts_hold(message.nodes)
            and self.counts_hold(request.nodes, self.scope.request)
        )

    def pair(
        self, name: str, rule: dictionary.Rule, each: dictionary.Constraint
    ) -> tuple[_Message, _Message] | None:
        """A valid request and answer for `rule` on the answer's AVP `name`,
        its conditions met, and the same pair breaking the rule. The AVP is
        a member of the body or one its `* [ AVP ]` admits."""
        valid = self.full()
        member = next((m for m in self.scope.members if m.name == name), None)

        def present(message: _Message) -> _Avp | None:
            if member is not None:
                return self.sibling(message.nodes, name)
            held = next((n for n in message.nodes if n.avp.name == name), None)
            identifier = self.builder.admitted(self.scope, None, each)
            if held is not None or identifier is None:
                return held
            try:
                node = self.builder.avp(
                    self.builder.avps[identifier], self.scope, None, False, ()
                )
            except _Unbuildable:
                return None
            message.nodes.append(node)
            return node

        def absent(message: _Message) -> bool:
            if member is not None and member.min_occurs:
                return False
            message.nodes[:] = [n for n in message.nodes if n.avp.name != name]
            return True

        if rule.kind == "equals":
            assert rule.reference is not None
            found = self.run_of(valid, rule.reference)
            subject = present(valid)
            if found is None or subject is None or subject.payload is None:
                return None
            other = self.sibling(found[0], rule.reference.avp, found[1])
            if other is None or other.payload is None:
                return None
            if not self.keeps_rules(subject, self.scope, other.payload):
                return None
            subject.payload = other.payload
            negative = valid.copy()
            target = next(n for n in negative.nodes if n.avp.name == name)
            payload = next(
                (
                    each
                    for each in _variants(target.avp, other.payload)
                    if each != other.payload
                    and self.keeps_rules(target, self.scope, each)
                ),
                None,
            )
            if payload is None:
                return None
            target.payload = payload
        else:
            for condition in rule.conditions[0]:
                found = self.run_of(valid, condition)
                if found is None or not self.make_hold(found[0], condition, found[1]):
                    return None
            if rule.kind in ("present-if", "requires"):
                if present(valid) is None:
                    return None
            elif not absent(valid):
                return None
            negative = valid.copy()
            if rule.kind == "present-if":
                if not absent(negative):
                    return None
            elif rule.kind == "requires":
                for conjunction in rule.conditions:
                    if not any(
                        (found := self.run_of(negative, condition)) is not None
                        and self.make_fail(found[0], condition, found[1])
                        for condition in conjunction
                    ):
                        return None
            elif rule.kind in ("absent-if", "excludes"):
                if present(negative) is None:
                    return None
            else:
                return None
        if not self.holds_but(valid, []) or not self.holds_but(
            negative, [(name, rule.kind)]
        ):
            return None
        return valid, negative

    def counts_hold(self, nodes: Sequence[_Avp], scope: _Scope | None = None) -> bool:
        for member in (scope or self.scope).members:
            if member.avp is None:
                continue
            count = sum(1 for n in nodes if n.avp.name == member.name)
            if count < member.min_occurs or (
                member.max_occurs is not None and count > member.max_occurs
            ):
                return False
        return True

    def sibling(
        self, nodes: list[_Avp], name: str, scope: _Scope | None = None
    ) -> _Avp | None:
        scope = scope or self.scope
        held = next((n for n in nodes if n.avp.name == name), None)
        if held is not None:
            return held
        member = next((m for m in scope.members if m.name == name), None)
        if member is None or member.avp is None:
            return None
        try:
            node = self.builder.avp(
                self.builder.avps[member.avp], scope, member, False, ()
            )
        except _Unbuildable:
            return None
        nodes.append(node)
        return node

    def make_hold(
        self,
        nodes: list[_Avp],
        condition: dictionary.Condition,
        scope: _Scope | None = None,
    ) -> bool:
        if condition.negated:
            return self.make_fail(nodes, _positive(condition), scope)
        if isinstance(condition.value, dictionary.Reference):
            return False
        if len(condition.path) > 1:
            parent = self.sibling(nodes, condition.path[0], scope)
            if parent is None or parent.avp.kind != "grouped":
                return False
            return self.make_hold(
                parent.children, _deeper(condition), self.builder.scope_of(parent.avp)
            )
        node = self.sibling(nodes, condition.avp, scope)
        if node is None:
            return False
        if condition.value is None and condition.bit is None and not condition.values:
            return True
        if condition.values:
            # One of the list's values, a later one each time a list is met,
            # so that the vectors cover more than its first.
            listed = condition.values[self._turn % len(condition.values)]
            self._turn += 1
            number = (
                listed.low
                if isinstance(listed, dictionary.ValueRange)
                else self.builder.values.number(node.avp, listed)
            )
        elif condition.value is not None:
            number = self.builder.values.number(node.avp, condition.value)
        else:
            bit = self.builder.values.bit(node.avp, condition.bit)
            # The bit set beside those another condition of the conjunction
            # set or cleared (TS 29.329's Update-Eff-Enhance without
            # Update-Eff, bit 2 set and bit 1 clear).
            held = (
                constraints.integer_value(node.avp.data_type, node.payload or b"")
                if node.avp.data_type in _FIXED
                else None
            )
            number = None if bit is None else (held or 0) | 1 << bit
        if number is None or node.avp.data_type not in _FIXED:
            return False
        if (
            (condition.value is not None or condition.values)
            and node.avp.data_type is ast.DataType.ENUMERATED
            and number not in {v.value for v in node.avp.values if v.kind == "value"}
        ):
            # A number the AVP's values do not name, which a checker reports.
            return False
        node.payload = _integer(node.avp.data_type, number)
        return True

    def make_fail(
        self,
        nodes: list[_Avp],
        condition: dictionary.Condition,
        scope: _Scope | None = None,
    ) -> bool:
        scope = scope or self.scope
        if condition.negated:
            return self.make_hold(nodes, _positive(condition), scope)
        if isinstance(condition.value, dictionary.Reference):
            return False
        if len(condition.path) > 1:
            # Every one the path passes through, the condition holding of any.
            return all(
                parent.avp.kind == "grouped"
                and self.make_fail(
                    parent.children,
                    _deeper(condition),
                    self.builder.scope_of(parent.avp),
                )
                for parent in nodes
                if parent.avp.name == condition.path[0]
            )
        member = next((m for m in scope.members if m.name == condition.avp), None)
        if member is None:
            return False
        if condition.value is None and condition.bit is None and not condition.values:
            if member.min_occurs:
                return False
            nodes[:] = [n for n in nodes if n.avp.name != condition.avp]
            return True
        node = next((n for n in nodes if n.avp.name == condition.avp), None)
        if node is None:
            return True
        if node.avp.data_type not in _FIXED:
            return False
        if condition.value is not None or condition.values:
            if node.avp.name == "Result-Code":
                # Another code a document names, and no protocol error, which
                # the E bit would have to go with.
                candidates = [
                    code
                    for code in self.builder.values.vendor_codes.get(0, [])
                    if not 3000 <= code < 4000
                ]
            else:
                candidates = [
                    v.value
                    for v in node.avp.values
                    if v.kind == "value" and v.value is not None
                ] or (
                    [0, 1] if node.avp.data_type is not ast.DataType.ENUMERATED else []
                )
            # Another value, none the condition names, one the AVP's own
            # rules allow.
            named = condition.model_copy(
                update={"values": condition.values or (condition.value,), "value": None}
            )
            others = [
                value
                for value in candidates
                if not _listed_holds(value, node.avp, named, self.builder.values)
                and self.keeps_rules(node, scope, _integer(node.avp.data_type, value))
            ]
            if not others:
                return False
            node.payload = _integer(node.avp.data_type, others[0])
            return True
        bit = self.builder.values.bit(node.avp, condition.bit)
        held = constraints.integer_value(node.avp.data_type, node.payload or b"")
        # The bit cleared, those another condition set kept.
        node.payload = _integer(
            node.avp.data_type,
            0 if bit is None or held is None else held & ~(1 << bit),
        )
        return True


def _host(payload: bytes) -> bool:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        return False
    return (
        bool(text)
        and all(
            label and not label.startswith("-") and not label.endswith("-")
            for label in text.rstrip(".").split(".")
        )
        and all(c.isalnum() or c in ".-" for c in text)
    )


def _address(payload: bytes) -> bool:
    if len(payload) < 2:
        return False
    family = int.from_bytes(payload[:2], "big")
    return {1: 4, 2: 16}.get(family, len(payload) - 2) == len(payload) - 2


def _binds(rule: dictionary.Rule, name: str) -> bool:
    """Whether a path of `rule` starts at the AVP `name` it is on, and so
    reads the instance checked."""
    references: list[dictionary.Reference] = [
        c for conjunction in rule.conditions for c in conjunction
    ]
    if rule.reference is not None:
        references.append(rule.reference)
    return any(
        each.root is None and len(each.path) > 1 and each.path[0] == name
        for each in references
    )


def _rule_text(rule: dictionary.Rule) -> str:
    if rule.kind == "length":
        return f"length {_span(rule.low, rule.high)} {rule.unit}"
    if rule.kind == "range":
        return f"range {_span(rule.low, rule.high)}"
    if rule.kind == "exclude":
        return "exclude " + ", ".join(map(str, rule.values))
    if rule.kind == "encoding" and rule.codec is ast.Codec.ELEMENT:
        named = [rule.document, rule.clause, rule.element and f'"{rule.element}"']
        return "encoding element " + " ".join(each for each in named if each)
    if rule.kind == "encoding":
        return f"encoding {rule.codec}"
    if rule.kind == "bits":
        return f"bits {rule.relation} {' '.join(map(str, rule.bits))}"
    if rule.kind == "members":
        return f"members {rule.relation} {' '.join(rule.members)}"
    if rule.kind in ("unique", "absent"):
        return rule.kind
    if rule.kind == "equals" and rule.reference is not None:
        return f"equals {_path(rule.reference)}"
    conditions = " or ".join(
        " and ".join(
            ("not " if c.negated else "")
            + _path(c)
            + (
                f" = {_path(c.value)}"
                if isinstance(c.value, dictionary.Reference)
                else f" = {c.value}"
                if c.value is not None
                else ""
            )
            + (f" bit {c.bit}" if c.bit is not None else "")
            + (
                " in "
                + ", ".join(
                    f"{v.low}..{v.high}"
                    if isinstance(v, dictionary.ValueRange)
                    else str(v)
                    for v in c.values
                )
                if c.values
                else ""
            )
            for c in conjunction
        )
        for conjunction in rule.conditions
    )
    if rule.kind == "values":
        return f"values {', '.join(map(str, rule.values))} if {conditions}"
    return f"{rule.kind} {conditions}"


def _path(reference: dictionary.Reference) -> str:
    names = "/".join(reference.path)
    return names if reference.root is None else f"{reference.root}/{names}"


def _span(low: int | None, high: int | None) -> str:
    if low == high:
        return str(low)
    return f"{'*' if low is None else low}..{'*' if high is None else high}"


# --- the public face --------------------------------------------------------


def build(
    built: dictionary.Dictionary,
    pages: Mapping[tuple[str, str | None, str], int] | None = None,
) -> Vectors:
    """The vectors of every command `built` holds. `pages` gives each clause's
    page, by document, version and clause (`pages_of`), for `Breaks.page`."""
    return _Generator(_feature_bits(built), pages or {}).run()


def _feature_bits(built: dictionary.Dictionary) -> dictionary.Dictionary:
    """`built` with each condition's feature name (`Feature-List bit
    "Update-Eff"`) the bit it stands for in its constraint's feature list
    (`dictionary.feature_bit`), so that a condition reads it as a bit
    table's; a name standing for no one bit stays, and does not resolve."""

    def constraint(each: dictionary.Constraint) -> dictionary.Constraint:
        readings = []
        for reading in each.readings:
            rules = []
            for rule in reading.rules:
                conditions = tuple(
                    tuple(
                        c
                        if (bit := dictionary.feature_bit(built, each, conjunction, c))
                        is None
                        else c.model_copy(update={"bit": bit})
                        for c in conjunction
                    )
                    for conjunction in rule.conditions
                )
                rules.append(
                    rule
                    if conditions == rule.conditions
                    else rule.model_copy(update={"conditions": conditions})
                )
            readings.append(reading.model_copy(update={"rules": tuple(rules)}))
        return each.model_copy(update={"readings": tuple(readings)})

    return built.model_copy(
        update={
            "constraints": tuple(map(constraint, built.constraints)),
            "applications": tuple(
                application.model_copy(
                    update={
                        "commands": tuple(
                            command.model_copy(
                                update={
                                    "constraints": tuple(
                                        map(constraint, command.constraints)
                                    )
                                }
                            )
                            for command in application.commands
                        )
                    }
                )
                for application in built.applications
            ),
            "answer_messages": tuple(
                answer.model_copy(
                    update={"constraints": tuple(map(constraint, answer.constraints))}
                )
                for answer in built.answer_messages
            ),
        }
    )


def pages_of(books: Any) -> dict[tuple[str, str | None, str], int]:
    """Each clause's page in a corpus's files, by reference, version and
    clause, a version of None for the copy in the corpus's release view, as
    the model names it: what `build` cites pages from."""
    found: dict[tuple[str, str | None, str], int] = {}
    for entry in books.newest():
        for section in entry.spec.sections:
            if section.source.page is not None:
                found.setdefault(
                    (entry.reference, None, section.source.section),
                    section.source.page,
                )
    for entry in books:
        for section in entry.spec.sections:
            if section.source.page is not None:
                found.setdefault(
                    (entry.reference, entry.spec.version, section.source.section),
                    section.source.page,
                )
    return found


def dumps(vectors: Vectors) -> str:
    """The file: compact JSON, keys sorted, one final newline."""
    return (
        json.dumps(
            vectors.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def json_schema() -> dict[str, Any]:
    """The JSON Schema of `Vectors`."""
    _, schema = models_json_schema(
        [(Vectors, "serialization")], title="seanchai vectors"
    )
    return schema


def pcap(vectors: Vectors) -> bytes:
    """Every vector as one capture: each message in its own TCP segment to
    port 3868, over IPv4 and Ethernet, in the file's order, an answer's
    request just before it."""
    out = struct.pack("!IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    sequence = 1000
    frames = 0
    messages = [
        bytes.fromhex(each)
        for vector in vectors.vectors
        for each in (
            *([vector.request.octets] if vector.request else []),
            vector.octets,
        )
    ]
    for index, message in enumerate(messages):
        # A message longer than a segment is split, as TCP would.
        for start in range(0, len(message), _SEGMENT):
            payload = message[start : start + _SEGMENT]
            tcp = struct.pack(
                "!HHIIBBHHH", 40000, 3868, sequence, 1, 5 << 4, 0x18, 65535, 0, 0
            )
            sequence = (sequence + len(payload)) % 2**32
            ip = struct.pack(
                "!BBHHHBBH4s4s",
                0x45,
                0,
                20 + len(tcp) + len(payload),
                frames % 2**16,
                0,
                64,
                6,
                0,
                bytes([10, 0, 0, 1]),
                bytes([10, 0, 0, 2]),
            )
            frame = b"\0\1\2\3\4\5\0\1\2\3\4\6\x08\x00" + ip + tcp + payload
            out += struct.pack("!IIII", index, frames, len(frame), len(frame)) + frame
            frames += 1
    return out


# The TCP payload of one frame.
_SEGMENT = 1400
