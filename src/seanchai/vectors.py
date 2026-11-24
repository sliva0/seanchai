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
plugin checks (length, range, exclude, encoding and the predicates).

Values are valid for their type and every constraint read for the AVP: a
codec's layout (`seanchai.constraints`), a length, a range, a predicate's
siblings. A member the corpus cannot complete is left out where optional;
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

from . import __version__, constraints, dictionary
from .dad import ast
from .errors import SeanchaiError

__all__ = [
    "FORMAT_VERSION",
    "Breaks",
    "Expected",
    "Node",
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
    (`seanchai.rule`) and severity."""

    rule: str
    severity: Severity


class Vector(_Model):
    """One message. `id` is `application/abbreviation/kind[/what]`; `kind`
    is `minimal`, `maximal` or `negative`. `octets` is the whole message in
    hex. A valid vector has no `breaks` and expects nothing but notes; a
    negative one breaks one rule and expects one finding."""

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
    return next((rule.codec for rule in rules if rule.kind == "encoding"), None)


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
    if rule.kind == "encoding" and rule.codec is not None:
        return constraints.codec_problem(rule.codec, payload) is None
    if rule.kind == "bits":
        value = constraints.integer_value(data_type, payload)
        if value is None:
            return True
        held = sum(1 for each in rule.bits if value >> each & 1)
        if rule.relation is ast.BitsRelation.AT_MOST_ONE:
            return held <= 1
        return held >= 1
    return True


def _value_rules(rules: Sequence[dictionary.Rule]) -> list[dictionary.Rule]:
    return [
        rule
        for rule in rules
        if rule.kind in ("length", "range", "exclude", "encoding", "bits")
        and not (rule.kind == "encoding" and rule.codec is ast.Codec.ELEMENT)
    ]


class _Values:
    """The dictionary's numbers: each reading's enumerated values, the result
    codes and bits its value tables name."""

    def __init__(self, built: dictionary.Dictionary) -> None:
        self.avps = {avp.id: avp for avp in built.avps}
        self.bits: dict[str, set[int]] = {}
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


def _payload(
    avp: dictionary.Avp, rules: Sequence[dictionary.Rule], values: _Values
) -> bytes | None:
    """A valid payload for a non-grouped `avp` under its value `rules`, or
    None where none satisfies them."""
    rules = _value_rules(rules)
    codec = _codec_of(rules)
    data_type = avp.data_type
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
            numbers += [0, 1]
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
            candidates = [_CODEC[codec]]
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
    for payload in candidates:
        if all(_holds(rule, payload, data_type, codec) for rule in rules):
            return payload
    return None


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

    def encode(self) -> bytes:
        data = (
            self.payload
            if self.payload is not None
            else b"".join(child.encode() for child in self.children)
        )
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
    """A body and the constraints its owner holds for its members, by name."""

    members: tuple[dictionary.Member, ...]
    rules: Mapping[str, tuple[dictionary.Constraint, ...]]
    name: str


class _Builder:
    def __init__(self, built: dictionary.Dictionary) -> None:
        self.built = built
        self.values = _Values(built)
        self.avps = self.values.avps
        # A reading's own constraints, and a grouped reading's for its members.
        self.own: dict[str, list[dictionary.Constraint]] = {}
        self.within: dict[str, dict[str, list[dictionary.Constraint]]] = {}
        for each in built.constraints:
            for identifier in each.avp_ids:
                if each.within is None:
                    self.own.setdefault(identifier, []).append(each)
                elif self.avps[identifier].name == each.within:
                    self.within.setdefault(identifier, {}).setdefault(
                        each.avp, []
                    ).append(each)

    def scope_of(self, avp: dictionary.Avp) -> _Scope:
        return _Scope(
            avp.members,
            {k: tuple(v) for k, v in self.within.get(avp.id, {}).items()},
            avp.name,
        )

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
            node.children = self.body(self.scope_of(avp), maximal, (*path, avp.id))
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
        self, scope: _Scope, maximal: bool, path: tuple[str, ...] = ()
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
        self.satisfy(scope, nodes, maximal)
        return nodes

    # Predicates.

    def predicates(
        self, scope: _Scope
    ) -> Iterator[tuple[str, dictionary.Constraint, dictionary.Rule]]:
        """The predicates the plugin checks in `scope`: those whose every
        condition names a sibling and, for a value or a bit, a number."""
        siblings = {
            m.name: self.avps[m.avp] for m in scope.members if m.avp is not None
        }
        for name, held in scope.rules.items():
            for each in held:
                for reading in each.readings:
                    for rule in reading.rules:
                        if rule.kind not in (
                            "present-if",
                            "absent-if",
                            "requires",
                            "excludes",
                        ):
                            continue
                        if all(
                            c.avp in siblings
                            and (
                                c.value is None
                                or self.values.number(siblings[c.avp], c.value)
                                is not None
                            )
                            and (
                                c.bit is None
                                or self.values.bit(siblings[c.avp], c.bit) is not None
                            )
                            for c in rule.conditions
                        ):
                            yield name, each, rule

    def condition(self, nodes: Sequence[_Avp], condition: dictionary.Condition) -> bool:
        held = next((n for n in nodes if n.avp.name == condition.avp), None)
        if held is None:
            return False
        if condition.value is None and condition.bit is None:
            return True
        value = constraints.integer_value(held.avp.data_type, held.payload or b"")
        if value is None:
            return False
        if condition.value is not None:
            return value == self.values.number(held.avp, condition.value)
        bit = self.values.bit(held.avp, condition.bit)
        return bit is not None and bool(value >> bit & 1)

    def broken(
        self, scope: _Scope, nodes: Sequence[_Avp]
    ) -> list[tuple[str, str, dictionary.Constraint]]:
        """The predicates of `scope` that `nodes` break: name, kind, constraint."""
        found = []
        for name, each, rule in self.predicates(scope):
            subject = any(n.avp.name == name for n in nodes)
            holds = any(self.condition(nodes, c) for c in rule.conditions)
            if (
                (rule.kind == "present-if" and holds and not subject)
                or (rule.kind == "absent-if" and holds and subject)
                or (rule.kind == "requires" and subject and not holds)
                or (rule.kind == "excludes" and subject and holds)
            ):
                found.append((name, rule.kind, each))
        return found

    def satisfy(self, scope: _Scope, nodes: list[_Avp], maximal: bool) -> None:
        """Mend what the predicates of `scope` say of `nodes`: drop an
        optional subject that may not be there, add one that must."""
        optional = {m.name for m in scope.members if m.min_occurs == 0}
        for _ in range(8):
            broken = self.broken(scope, nodes)
            if not broken:
                return
            for name, kind, _each in broken:
                if kind == "present-if":
                    member = next(m for m in scope.members if m.name == name)
                    if member.avp is None:
                        raise _Unbuildable(
                            f"{name} is to be present and cannot be built"
                        )
                    nodes.append(
                        self.avp(self.avps[member.avp], scope, member, False, ())
                    )
                elif name in optional:
                    nodes[:] = [n for n in nodes if n.avp.name != name]
                else:
                    raise _Unbuildable(f"{name} is required and a predicate forbids it")
        if self.broken(scope, nodes):
            raise _Unbuildable("the predicates cannot all hold")


# --- vectors ---------------------------------------------------------------


@dataclasses.dataclass
class _Message:
    application: dictionary.Application
    command: dictionary.Command
    nodes: list[_Avp]
    error_bit: bool = False

    def encode(self) -> bytes:
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
            + struct.pack("!III", application, 0x5EA4C4A1, 0x5EA4C4A1)
            + body
        )

    def copy(self) -> _Message:
        return dataclasses.replace(self, nodes=[n.copy() for n in self.nodes])


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

    def scope(self, command: dictionary.Command) -> _Scope:
        rules: dict[str, list[dictionary.Constraint]] = {}
        for each in command.constraints:
            rules.setdefault(each.avp, []).append(each)
        return _Scope(
            command.members, {k: tuple(v) for k, v in rules.items()}, command.name
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
                octets=message.encode().hex(),
                tree=tuple(node.node() for node in message.nodes),
                breaks=breaks,
                expected=tuple(expected),
            )
        )

    def command(
        self, application: dictionary.Application, command: dictionary.Command
    ) -> None:
        label = self.label(application, command)
        scope = self.scope(command)
        built = {}
        for maximal in (False, True):
            try:
                nodes = self.builder.body(scope, maximal)
            except _Unbuildable as error:
                self.skipped.append(
                    Skipped(
                        command=label,
                        what="maximal" if maximal else "minimal",
                        reason=str(error),
                    )
                )
                continue
            message = _Message(application, command, nodes)
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
    ) -> None:
        self.generator.emit(
            message, "negative", what, breaks, [Expected(rule=rule, severity=severity)]
        )

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
            if self.builder.broken(self.scope, trial.nodes):
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
        # UTF-8 that is not.
        for message, node, scope in self.first(
            lambda n: n.avp.data_type is ast.DataType.UTF8_STRING
        ):
            payload = b"\xff" + (node.payload or b"")[1:]
            if not self.keeps_rules(node, scope, payload):
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
        scope = _Scope(answer.members, {}, "answer-message")
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
                " protocol error",
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
        message = self.full()
        for node, scope in list(self.each_node(message)):
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
                            continue
                        done.add(key)
                        trial = message.copy()
                        target = self.find(trial, node)
                        target.payload = payload
                        self.emit(
                            trial,
                            f"constraint-{rule.kind}/{name}/{each.section}",
                            self.at_constraint(each, f"{name}: {_rule_text(rule)}"),
                            f"constraint-{rule.kind}",
                            "warn",
                        )
        self.predicate_vectors()

    def find(self, message: _Message, node: _Avp) -> _Avp:
        """`node`'s copy in `message`, by its place."""
        original = self.full()
        for (mine, _), (theirs, _) in zip(
            self.each_node(original), self.each_node(message), strict=True
        ):
            if mine.avp.id == node.avp.id and mine.payload == node.payload:
                return theirs
        raise LookupError(node.avp.name)

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
        elif rule.kind == "bits" and data_type in _FIXED:
            value = (
                sum(1 << each for each in rule.bits)
                if rule.relation is ast.BitsRelation.AT_MOST_ONE
                else 0
            )
            candidates.append(_integer(data_type, value))
        elif rule.kind == "exclude":
            candidates += [
                _integer(data_type, value)
                for value in rule.values
                if data_type in _FIXED
            ]
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
        """One vector per predicate of the command's own scope the plugin
        checks: the subject placed, or not, against its conditions."""
        for name, each, rule in self.builder.predicates(self.scope):
            message = self.full()
            nodes = message.nodes
            member = next(m for m in self.scope.members if m.name == name)
            subject = [n for n in nodes if n.avp.name == name]
            if rule.kind in ("absent-if", "excludes", "present-if"):
                if not self.make_hold(nodes, rule.conditions[0]):
                    continue
                if rule.kind == "present-if":
                    if member.min_occurs:
                        continue
                    nodes[:] = [n for n in nodes if n.avp.name != name]
                elif not subject:
                    if member.avp is None:
                        continue
                    nodes.append(
                        self.builder.avp(
                            self.builder.avps[member.avp], self.scope, member, False, ()
                        )
                    )
            else:  # requires
                if not subject:
                    if member.avp is None:
                        continue
                    nodes.append(
                        self.builder.avp(
                            self.builder.avps[member.avp], self.scope, member, False, ()
                        )
                    )
                if not all(self.make_fail(nodes, c) for c in rule.conditions):
                    continue
            broken = self.builder.broken(self.scope, nodes)
            if [(n, k) for n, k, _ in broken] != [(name, rule.kind)]:
                continue
            if not self.counts_hold(nodes):
                continue
            self.emit(
                message,
                f"constraint-{rule.kind}/{name}/{each.section}",
                self.at_constraint(each, f"{name}: {_rule_text(rule)}"),
                f"constraint-{rule.kind}",
                "warn",
            )

    def counts_hold(self, nodes: Sequence[_Avp]) -> bool:
        for member in self.scope.members:
            if member.avp is None:
                continue
            count = sum(1 for n in nodes if n.avp.name == member.name)
            if count < member.min_occurs or (
                member.max_occurs is not None and count > member.max_occurs
            ):
                return False
        return True

    def sibling(self, nodes: list[_Avp], name: str) -> _Avp | None:
        held = next((n for n in nodes if n.avp.name == name), None)
        if held is not None:
            return held
        member = next((m for m in self.scope.members if m.name == name), None)
        if member is None or member.avp is None:
            return None
        try:
            node = self.builder.avp(
                self.builder.avps[member.avp], self.scope, member, False, ()
            )
        except _Unbuildable:
            return None
        nodes.append(node)
        return node

    def make_hold(self, nodes: list[_Avp], condition: dictionary.Condition) -> bool:
        node = self.sibling(nodes, condition.avp)
        if node is None:
            return False
        if condition.value is None and condition.bit is None:
            return True
        if condition.value is not None:
            number = self.builder.values.number(node.avp, condition.value)
        else:
            bit = self.builder.values.bit(node.avp, condition.bit)
            number = None if bit is None else 1 << bit
        if number is None or node.avp.data_type not in _FIXED:
            return False
        node.payload = _integer(node.avp.data_type, number)
        return True

    def make_fail(self, nodes: list[_Avp], condition: dictionary.Condition) -> bool:
        member = next((m for m in self.scope.members if m.name == condition.avp), None)
        if member is None:
            return False
        if condition.value is None and condition.bit is None:
            if member.min_occurs:
                return False
            nodes[:] = [n for n in nodes if n.avp.name != condition.avp]
            return True
        node = next((n for n in nodes if n.avp.name == condition.avp), None)
        if node is None:
            return True
        if node.avp.data_type not in _FIXED:
            return False
        if condition.value is not None:
            number = self.builder.values.number(node.avp, condition.value)
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
            others = [value for value in candidates if value != number]
            if not others:
                return False
            node.payload = _integer(node.avp.data_type, others[0])
            return True
        node.payload = _integer(node.avp.data_type, 0)
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


def _rule_text(rule: dictionary.Rule) -> str:
    if rule.kind == "length":
        return f"length {_span(rule.low, rule.high)} {rule.unit}"
    if rule.kind == "range":
        return f"range {_span(rule.low, rule.high)}"
    if rule.kind == "exclude":
        return "exclude " + ", ".join(map(str, rule.values))
    if rule.kind == "encoding":
        return f"encoding {rule.codec}"
    if rule.kind == "bits":
        return f"bits {rule.relation} {' '.join(map(str, rule.bits))}"
    conditions = " or ".join(
        c.avp
        + (f" = {c.value}" if c.value is not None else "")
        + (f" bit {c.bit}" if c.bit is not None else "")
        for c in rule.conditions
    )
    return f"{rule.kind} {conditions}"


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
    return _Generator(built, pages or {}).run()


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
    port 3868, over IPv4 and Ethernet, in the file's order."""
    out = struct.pack("!IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    sequence = 1000
    frames = 0
    for index, vector in enumerate(vectors.vectors):
        message = bytes.fromhex(vector.octets)
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
