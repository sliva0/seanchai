"""Interpreted constraints against what the documents print: the AVPs and
commands a block names, whether its rules fit the AVP's type, the values and
bits its conditions name, and rules that cannot all hold."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from .. import constraints as checks
from .. import elements
from ..dad import ast, formatter
from ._elements import _application_id, _grouped
from ._findings import Finding, Severity
from ._index import _Index

# The rules this module reports; with a corpus, the documents the file cites
# answer for what it re-uses, and these replace the single-file findings.
CONSTRAINT_RULES = frozenset(
    {
        "constraint-avp-unknown",
        "constraint-command-unknown",
        "constraint-not-member",
        "constraint-type-mismatch",
        "constraint-value-unknown",
        "constraint-contradiction",
        "constraint-element-unknown",
        "constraint-request-unknown",
    }
)

_Cited = Callable[[str], ast.Specification | None]


def _held(spec: ast.Specification) -> set[str]:
    """Every AVP name `spec` holds: defined, tabulated, re-used, declared
    undefined, or named by a body or an information element."""
    held: set[str] = set()
    for section in spec.sections:
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp | ast.UndefinedAvp):
            held.add(section.name)
        if isinstance(section, ast.Message | ast.GroupedAvp | ast.AnswerMessage):
            held.update(rule.name for rule in section.avps)
        elif isinstance(section, ast.AvpTable | ast.ReusedAvps):
            held.update(row.name for row in section.rows)
        elif isinstance(section, ast.InformationElements):
            held.update(name for row in section.rows for name in row.avps)
    held.discard("AVP")
    return held


@dataclass
class _Facts:
    """What the documents print of one AVP: its type and the names of its
    values and bits, None where no document read says."""

    data_type: ast.DataType | None = None
    values: set[str] | None = None
    bits: dict[str, int] | None = None


def _documents(spec: ast.Specification, name: str, cited: _Cited | None) -> list:
    """`spec`, then the document its re-used row cites for `name`, then its
    bases, as far as `cited` reads them."""
    found = [spec]
    if cited is None:
        return found
    origins = [
        row.origin
        for section in spec.sections
        if isinstance(section, ast.ReusedAvps)
        for row in section.rows
        if row.name == name
    ]
    for reference in (*origins[:1], *spec.bases):
        document = cited(reference)
        if document is not None:
            found.append(document)
    return found


def _facts(spec: ast.Specification, name: str, cited: _Cited | None) -> _Facts:
    facts = _Facts()
    for document in _documents(spec, name, cited):
        for section in document.sections:
            if isinstance(section, ast.EnumeratedAvp) and section.name == name:
                facts.data_type = facts.data_type or ast.DataType.ENUMERATED
                if section.values and facts.values is None:
                    facts.values = {
                        value.name
                        for value in section.values
                        if isinstance(value, ast.EnumValue)
                    }
            elif ast.defines(section) and getattr(section, "name", None) == name:
                facts.data_type = facts.data_type or ast.DataType.GROUPED
            elif isinstance(section, ast.AvpTable):
                for row in section.rows:
                    if row.name == name and row.data_type is not None:
                        facts.data_type = facts.data_type or row.data_type
            elif isinstance(section, ast.ValueTable) and section.avp == name:
                if section.kind is ast.ValueKind.BITS and facts.bits is None:
                    facts.bits = {row.name: row.value for row in section.rows}
                elif section.kind in (
                    ast.ValueKind.RESULT_CODES,
                    ast.ValueKind.VALUES,
                ):
                    facts.values = (facts.values or set()) | {
                        row.name for row in section.rows
                    }
        if facts.data_type is not None and document is not spec:
            break
    return facts


def _body(
    spec: ast.Specification, block: ast.InterpretedConstraints, cited: _Cited | None
) -> tuple[tuple[ast.AvpRule, ...] | None, str | None]:
    """The printed body scoping `block`, and why there is none: an unknown
    command (a message) or none to read (None)."""
    if block.command is not None:
        found = [
            section
            for section in spec.sections
            if isinstance(section, ast.Message)
            and section.name == block.command
            and block.application_id in (None, _application_id(spec, section))
            and block.command_section in (None, section.source.section)
        ]
        if len(found) == 1:
            return found[0].avps, None
        if not found and block.command_section is not None:
            return None, (
                f"names command {block.command} at clause"
                f" {block.command_section}, which the file does not print there"
            )
        if not found:
            return None, f"names command {block.command}, which the file does not print"
        ids = sorted({_application_id(spec, each) or 0 for each in found})
        if len(ids) == 1:
            sections = ", ".join(each.source.section for each in found)
            return None, (
                f"names command {block.command}, which the file prints at"
                f" clauses {sections}; Command-Section names one"
            )
        return None, (
            f"names command {block.command}, which the file prints under"
            f" applications {', '.join(map(str, ids))}; Application-ID names one"
        )
    if block.within is not None:
        grouped = _grouped(_documents(spec, block.within, cited), block.within)
        return (None if grouped is None else grouped.avps), None
    return None, None


def _request_body(
    spec: ast.Specification, block: ast.InterpretedConstraints
) -> tuple[tuple[ast.AvpRule, ...] | None, str | None]:
    """The printed body of the request `block`'s rules read, and why there
    is none: the block's command is no answer, or the file prints no such
    request, or several with no `; Request-Section:` choosing one."""
    answers, requests = ast.request_prints(spec.sections, block)
    if len(answers) != 1:
        # The command itself is unknown or ambiguous: reported as such.
        return None, None
    answer = answers[0]
    if block.request_section is not None and not requests:
        return None, (
            f"reads the request, which Request-Section names at clause"
            f" {block.request_section}, where the file prints no request of"
            f" {block.command}"
        )
    if not requests:
        return None, (
            f"reads the request of {block.command}, command {answer.command_code},"
            " which the file does not print"
        )
    if len(requests) > 1:
        sections = ", ".join(each.source.section for each in requests)
        return None, (
            f"reads the request of {block.command}, which the file prints at"
            f" clauses {sections}; Request-Section names one"
        )
    return requests[0].avps, None


def _is_request(spec: ast.Specification, block: ast.InterpretedConstraints) -> bool:
    """Whether every print of the command `block` is scoped to is a request."""
    found = [
        section
        for section in spec.sections
        if isinstance(section, ast.Message) and section.name == block.command
    ]
    return bool(found) and all(ast.CommandFlag.REQUEST in each.flags for each in found)


# Integer kinds a value or a bit can be read from.
_INTEGERS = frozenset(
    {
        ast.DataType.INTEGER32,
        ast.DataType.INTEGER64,
        ast.DataType.UNSIGNED32,
        ast.DataType.UNSIGNED64,
        ast.DataType.ENUMERATED,
    }
)
_BITS = {ast.DataType.UNSIGNED32: 32, ast.DataType.UNSIGNED64: 64}
_SIZED = frozenset(
    {
        ast.DataType.OCTET_STRING,
        ast.DataType.UTF8_STRING,
        ast.DataType.DIAMETER_IDENTITY,
        ast.DataType.DIAMETER_URI,
        ast.DataType.ADDRESS,
        ast.DataType.IP_FILTER_RULE,
        ast.DataType.QOS_FILTER_RULE,
    }
)
_TEXTUAL = frozenset(
    {
        ast.DataType.OCTET_STRING,
        ast.DataType.UTF8_STRING,
        ast.DataType.DIAMETER_IDENTITY,
        ast.DataType.DIAMETER_URI,
        ast.DataType.IP_FILTER_RULE,
        ast.DataType.QOS_FILTER_RULE,
    }
)


def _type_problems(rule: ast.ConstraintRule, data_type: ast.DataType) -> Iterable[str]:
    """Why `rule` cannot hold of an AVP of `data_type`."""
    match rule:
        case ast.RangeRule() | ast.ExcludeRule():
            bounds = checks.integer_bounds(data_type)
            if bounds is None:
                yield f"a {rule.kind} needs an integer, not {data_type}"
                return
            numbers = (
                (rule.low, rule.high)
                if isinstance(rule, ast.RangeRule)
                else rule.values
            )
            for number in numbers:
                if number is not None and not bounds[0] <= number <= bounds[1]:
                    yield f"{number} is beyond what {data_type} holds"
        case ast.LengthRule(unit=ast.LengthUnit.OCTETS):
            if data_type not in _SIZED:
                yield f"an octet length needs an octet string, not {data_type}"
        case ast.LengthRule(unit=ast.LengthUnit.CHARACTERS):
            if data_type not in _TEXTUAL:
                yield f"a character length needs text, not {data_type}"
        case ast.EncodingRule():
            if data_type not in checks.CODEC_TYPES[rule.codec]:
                yield f"{rule.codec} does not encode {data_type}"
            entry = elements.of_rule(rule)
            types = None if entry is None else elements.data_types(entry)
            if entry is not None and types is not None and data_type not in types:
                yield f"element {entry.cited()} is checked as no {data_type}"
        case ast.DefaultRule():
            bounds = checks.integer_bounds(data_type)
            if bounds is None:
                yield f"a default needs an integer, not {data_type}"
            elif isinstance(rule.value, int) and not (
                bounds[0] <= rule.value <= bounds[1]
            ):
                yield f"{rule.value} is beyond what {data_type} holds"
        case ast.BitsRule():
            width = _BITS.get(data_type)
            if width is None and data_type is not ast.DataType.OCTET_STRING:
                yield (
                    "a bits rule needs an unsigned integer or an octet string,"
                    f" not {data_type}"
                )
            elif width is not None and any(each >= width for each in rule.bits):
                yield f"{data_type} has no bit {max(rule.bits)}"
        case ast.ValuesRule():
            bounds = checks.integer_bounds(data_type)
            if bounds is None:
                yield f"a values rule needs an integer, not {data_type}"
                return
            for number in rule.values:
                if not bounds[0] <= number <= bounds[1]:
                    yield f"{number} is beyond what {data_type} holds"
        case ast.MembersRule():
            if data_type is not ast.DataType.GROUPED:
                yield f"a members rule needs a grouped AVP, not {data_type}"
        case _:
            pass


def _intersection(
    ranges: Iterable[tuple[int | None, int | None]],
) -> tuple[int | None, int | None]:
    low: int | None = None
    high: int | None = None
    for each_low, each_high in ranges:
        if each_low is not None:
            low = each_low if low is None else max(low, each_low)
        if each_high is not None:
            high = each_high if high is None else min(high, each_high)
    return low, high


def _empty(bounds: tuple[int | None, int | None]) -> bool:
    return bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]


def _contradictions(rules: Sequence[ast.ConstraintRule]) -> Iterable[str]:
    """Why `rules`, all holding of one AVP in one place, cannot all hold."""
    codecs = {
        rule.codec
        for rule in rules
        if isinstance(rule, ast.EncodingRule) and rule.codec is not ast.Codec.ELEMENT
    }
    if len(codecs) > 1:
        yield f"encodings {', '.join(sorted(codecs))} cannot both hold"
    for unit in ast.LengthUnit:
        bounds = [
            (rule.low, rule.high)
            for rule in rules
            if isinstance(rule, ast.LengthRule) and rule.unit is unit
        ]
        if unit is ast.LengthUnit.OCTETS:
            bounds += [
                found for codec in codecs if (found := checks.codec_octets(codec))
            ]
        if unit is ast.LengthUnit.DIGITS:
            carrying = [
                found for codec in codecs if (found := checks.codec_digits(codec))
            ]
            if bounds and not carrying:
                yield "a digit length with no encoding carrying digits"
            bounds += carrying
        if _empty(_intersection(bounds)):
            yield f"the lengths in {unit} leave none"
    bits = [rule for rule in rules if isinstance(rule, ast.BitsRule)]
    required = {
        each
        for rule in bits
        if rule.relation is ast.BitsRelation.SET
        for each in rule.bits
    }
    for rule in bits:
        if rule.relation is ast.BitsRelation.CLEAR and required & set(rule.bits):
            yield f"bit {min(required & set(rule.bits))} is both set and clear"
        elif rule.relation is ast.BitsRelation.ONLY and required - set(rule.bits):
            yield f"bit {min(required - set(rule.bits))} is set, and not among only"
    ranges = [
        (rule.low, rule.high) for rule in rules if isinstance(rule, ast.RangeRule)
    ]
    low, high = _intersection(ranges)
    if _empty((low, high)):
        yield "the ranges leave no value"
    elif low is not None and high is not None and ranges:
        excluded = {
            value
            for rule in rules
            if isinstance(rule, ast.ExcludeRule)
            for value in rule.values
        }
        if set(range(low, high + 1)) <= excluded:
            yield "exclude leaves no value of the range"


def _constraints(
    spec: ast.Specification, index: _Index, cited: _Cited | None
) -> list[Finding]:
    """Check each Interpreted Constraints block of `spec`; `cited` resolves a
    document the file cites, None for a single file.

    `constraint-avp-unknown` (error): a name the block constrains, scopes or
    conditions on that the file does not hold. `constraint-command-unknown`
    (error): a command the file does not print, or prints for several
    applications with no `; Application-ID:`. `constraint-not-member`
    (error): an AVP, or one a rule reads, the printed body of its command or
    grouped AVP does not hold, or a `request/` name the request's body does
    not. `constraint-request-unknown` (error): a rule reading the request in
    a block scoped to a request, or to an answer whose request the file
    prints not once under its application with no `; Request-Section:`
    choosing one. `constraint-type-mismatch` (error): a rule no value of the
    AVP's type can meet, as a range on an OctetString or a codec for another
    type, a condition testing a value or bit of an AVP that has none, or two
    AVPs a rule compares of two types.
    `constraint-value-unknown` (error): a condition naming a value or bit
    the AVP's values, result codes or bit table do not name, and a default
    or bits rule naming a value or bit the AVP's own do not. A members rule
    naming a member the grouped AVP's body does not hold is
    `constraint-not-member`.
    `constraint-contradiction` (error): rules on one AVP in one place that
    cannot all hold. `constraint-element-unknown` (note): an `encoding
    element` rule naming an element the element registry
    (`seanchai.elements`) has no entry for, which nothing checks; another
    document's interpretations may name elements the registry has yet to
    learn. A type, value or bit no document read states is not judged."""
    findings: list[Finding] = []
    held = _held(spec)
    blocks = [
        section
        for section in spec.sections
        if isinstance(section, ast.InterpretedConstraints)
    ]

    def found(rule: str, block: ast.InterpretedConstraints, message: str) -> None:
        findings.append(
            Finding(
                Severity.ERROR,
                rule,
                f"{_scope(block)}: {message}",
                block.source.section,
                paths=(index.path(block),),
            )
        )

    for block in blocks:
        for rule in block.body:
            if (
                isinstance(rule, ast.EncodingRule)
                and rule.codec is ast.Codec.ELEMENT
                and elements.of_rule(rule) is None
            ):
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "constraint-element-unknown",
                        f"{_scope(block)}: the element registry has no"
                        f" {_element_text(rule)}; nothing checks it",
                        block.source.section,
                        paths=(index.path(block),),
                    )
                )

    facts: dict[str, _Facts] = {}

    def fact(name: str) -> _Facts:
        if name not in facts:
            facts[name] = _facts(spec, name, cited)
        return facts[name]

    for block in blocks:
        rules = [rule for rule in block.body if not isinstance(rule, ast.Quote)]
        conditions = [
            condition for rule in rules for condition in ast.conditions_of(rule)
        ]
        references = [
            reference for rule in rules for reference in ast.references_of(rule)
        ]
        listed = [
            name
            for rule in block.body
            if isinstance(rule, ast.MembersRule)
            for name in rule.members
        ]
        # A member a members rule names may be the grouped AVP's as another
        # document prints it (IMEI in TS 29.272's Terminal-Information, which
        # TS 29.273 re-uses): held, or the body read holds it.
        owner = (
            _grouped(_documents(spec, block.avp, cited), block.avp)
            if listed and block.avp in held
            else None
        )
        owned = set() if owner is None else {rule.name for rule in owner.avps}
        names = dict.fromkeys(
            [block.avp, *([block.within] if block.within else [])]
            + [reference.path[0] for reference in references]
            + [name for name in listed if name not in owned]
        )
        for name in names:
            if name not in held:
                found("constraint-avp-unknown", block, f"the file holds no AVP {name}")
        body, unknown = _body(spec, block, cited)
        if unknown is not None:
            found("constraint-command-unknown", block, unknown)
        request: tuple[ast.AvpRule, ...] | None = None
        if any(each.root is ast.Root.REQUEST for each in references):
            if _is_request(spec, block):
                found(
                    "constraint-request-unknown",
                    block,
                    f"reads the request, but {block.command} is a request",
                )
            elif unknown is None:
                request, problem = _request_body(spec, block)
                if problem is not None:
                    found("constraint-request-unknown", block, problem)
        if body is not None and block.avp in held:
            members = {rule.name for rule in body}
            # The `* [ AVP ]` wildcard admits any AVP as a member.
            if block.avp not in members and "AVP" not in members:
                where = block.command or block.within
                found(
                    "constraint-not-member",
                    block,
                    f"the body of {where} does not hold {block.avp}",
                )
        for reference in dict.fromkeys(references):
            first = reference.path[0]
            if first not in held:
                continue
            if reference.root is ast.Root.REQUEST:
                if request is not None and first not in {r.name for r in request}:
                    found(
                        "constraint-not-member",
                        block,
                        f"a rule reads {formatter.reference(reference)}, which"
                        " the body of the request does not hold",
                    )
            elif body is not None and not {first, "AVP"} & {r.name for r in body}:
                found(
                    "constraint-not-member",
                    block,
                    f"a rule reads {first}, which the body of"
                    f" {block.command or block.within} does not hold",
                )
            elif (
                body is None
                and block.command is None
                and block.within is None
                and len(reference.path) > 1
                and first != block.avp
            ):
                found(
                    "constraint-not-member",
                    block,
                    f"a rule reads {formatter.reference(reference)}: with no"
                    f" scope, a path starts at {block.avp}",
                )
            # On through the grouped AVPs the path names, as the documents
            # read print their bodies.
            for parent, name in itertools.pairwise(reference.path):
                grouped = _grouped(_documents(spec, parent, cited), parent)
                if grouped is None:
                    break
                if not {name, "AVP"} & {rule.name for rule in grouped.avps}:
                    found(
                        "constraint-not-member",
                        block,
                        f"a rule reads {formatter.reference(reference)}, but the"
                        f" body of {parent} does not hold {name}",
                    )
                    break
        if listed and block.avp in held:
            grouped = owner
            members = owned
            for name in dict.fromkeys(listed):
                if grouped is not None and name not in members:
                    found(
                        "constraint-not-member",
                        block,
                        f"a members rule names {name}, which the body of"
                        f" {block.avp} does not hold",
                    )
        own = fact(block.avp) if block.avp in held else _Facts()
        data_type = own.data_type
        for rule in block.body:
            if data_type is not None and not isinstance(rule, ast.Quote):
                for problem in _type_problems(rule, data_type):
                    found("constraint-type-mismatch", block, problem)
            if (
                isinstance(rule, ast.DefaultRule)
                and isinstance(rule.value, str)
                and own.values is not None
                and rule.value not in own.values
            ):
                found(
                    "constraint-value-unknown",
                    block,
                    f"{block.avp} names no value {rule.value!r}",
                )
            if isinstance(rule, ast.BitsRule) and own.bits is not None:
                numbered = set(own.bits.values())
                for each in rule.bits:
                    if each not in numbered:
                        found(
                            "constraint-value-unknown",
                            block,
                            f"{block.avp}'s bit table names no bit {each}",
                        )
        for condition in conditions:
            if condition.avp not in held:
                continue
            known = fact(condition.avp)
            if condition.value is not None and not isinstance(
                condition.value, ast.Reference
            ):
                if known.data_type is not None and known.data_type not in _INTEGERS:
                    found(
                        "constraint-type-mismatch",
                        block,
                        f"a condition tests a value of {condition.avp}, of type"
                        f" {known.data_type}",
                    )
                elif (
                    isinstance(condition.value, str)
                    and known.values is not None
                    and condition.value not in known.values
                ):
                    found(
                        "constraint-value-unknown",
                        block,
                        f"{condition.avp} names no value {condition.value!r}",
                    )
            if condition.bit is not None:
                width = None if known.data_type is None else _BITS.get(known.data_type)
                if known.data_type is not None and width is None:
                    found(
                        "constraint-type-mismatch",
                        block,
                        f"a condition tests a bit of {condition.avp}, of type"
                        f" {known.data_type}",
                    )
                elif isinstance(condition.bit, int):
                    if width is not None and condition.bit >= width:
                        found(
                            "constraint-type-mismatch",
                            block,
                            f"{condition.avp} has no bit {condition.bit}",
                        )
                elif known.bits is not None and condition.bit not in known.bits:
                    found(
                        "constraint-value-unknown",
                        block,
                        f"{condition.avp} names no bit {condition.bit!r}",
                    )
        if body is not None and any(isinstance(rule, ast.AbsentRule) for rule in rules):
            required = [
                rule
                for rule in body
                if rule.name == block.avp and rule.presence is not ast.Presence.OPTIONAL
            ]
            if required:
                found(
                    "constraint-contradiction",
                    block,
                    f"absent, but the body of {block.command or block.within}"
                    f" requires {block.avp}",
                )
        # Two AVPs a rule compares hold values of one type.
        pairs = [
            (block.avp, rule.reference.avp)
            for rule in rules
            if isinstance(rule, ast.EqualsRule)
        ] + [
            (condition.avp, condition.value.avp)
            for condition in conditions
            if isinstance(condition.value, ast.Reference)
        ]
        for one, other in pairs:
            if one not in held or other not in held:
                continue
            first, second = fact(one).data_type, fact(other).data_type
            if first is not None and second is not None and first != second:
                found(
                    "constraint-type-mismatch",
                    block,
                    f"a rule compares {one}, of type {first}, with {other}, of"
                    f" type {second}",
                )
    # Rules on one AVP in one place: its blocks there, with those holding
    # wherever the document reads it.
    places: dict[tuple[str, str | None, int | None, str | None, str | None], list] = {}
    for block in blocks:
        places.setdefault(
            (
                block.avp,
                block.command,
                block.application_id,
                block.command_section,
                block.within,
            ),
            [],
        ).append(block)
    for (avp, command, _, _, within), here in places.items():
        rules = [
            rule
            for block in here
            for rule in block.body
            if not isinstance(rule, ast.Quote)
        ]
        if command is not None or within is not None:
            rules += [
                rule
                for block in places.get((avp, None, None, None, None), ())
                for rule in block.body
                if not isinstance(rule, ast.Quote)
            ]
        for problem in dict.fromkeys(_contradictions(rules)):
            found("constraint-contradiction", here[0], problem)
    return findings


def _element_text(rule: ast.EncodingRule) -> str:
    """The element as the rule writes it: `TS29.002 17.7.8 "E-UTRAN-CGI"`."""
    parts = [str(rule.document)]
    if rule.clause is not None:
        parts.append(rule.clause)
    if rule.element is not None:
        parts.append(f'"{rule.element}"')
    return " ".join(parts)


def _scope(block: ast.InterpretedConstraints) -> str:
    where = block.command or block.within
    return f"{block.avp} in {where}" if where else block.avp
