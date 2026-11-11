"""Single-file rules over definitions, enumerated values, value tables,
commands and application scopes.
"""

from __future__ import annotations

from collections import defaultdict

from ..dad import ast
from ._findings import Finding, Severity
from ._index import _Index, _repeats


def _duplicate_definitions(index: _Index) -> list[Finding]:
    by_name: dict[str, list[ast.GroupedAvp | ast.EnumeratedAvp]] = defaultdict(list)
    for definition in index.definitions:
        by_name[definition.name].append(definition)
    findings = []
    for name, group in sorted(by_name.items()):
        if len(group) > 1:
            clauses = ", ".join(d.source.section for d in group)
            findings.append(
                Finding(
                    Severity.ERROR,
                    "duplicate-definition",
                    f"{name} is defined {len(group)} times, in clauses {clauses}",
                    paths=tuple(index.path(definition) for definition in group),
                )
            )
    return findings


def _one_name_two_commands(index: _Index) -> list[Finding]:
    """One command name used for two command codes.

    A repeated message name with one code is normal (TS 29.272 defines IDR
    for both S6a and S7a), so this is separate from `_duplicate_definitions`.
    Case: TS 29.344 clauses 6.2.11/6.2.12.
    """
    by_name: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for message in index.messages:
        by_name[message.name][message.command_code].append(message.source.section)
    findings = []
    for name, codes in sorted(by_name.items()):
        if len(codes) > 1:
            spelled = ", ".join(
                f"{code} (clause{'s' if len(where) > 1 else ''} {', '.join(where)})"
                for code, where in sorted(codes.items())
            )
            findings.append(
                Finding(
                    Severity.ERROR,
                    "one-name-two-commands",
                    f"{name} is defined with {len(codes)} command codes: {spelled}",
                )
            )
    return findings


def _duplicate_enum_values(index: _Index) -> list[Finding]:
    findings = []
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        values = [v for v in definition.values if isinstance(v, ast.EnumValue)]
        for label, counts in (
            ("value", _repeats(v.value for v in values)),
            ("name", _repeats(v.name for v in values)),
        ):
            for repeated in counts:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "duplicate-enum-value",
                        f"{definition.name} uses the {label} {repeated!r} twice",
                        definition.source.section,
                    )
                )
    return findings


def _duplicate_values(index: _Index) -> list[Finding]:
    """One value table giving one number twice, whether the names agree or
    not."""
    findings = []
    for table in index.value_tables:
        by_value: dict[int, list[ast.ValueRow]] = defaultdict(list)
        for row in table.rows:
            by_value[row.value].append(row)
        for value, rows in by_value.items():
            if len(rows) > 1:
                names = ", ".join(repr(name) for name in {r.name: None for r in rows})
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "duplicate-value",
                        f"{table.avp}'s {table.kind} table gives {value} to {names},"
                        f" {len(rows)} rows",
                        table.source.section,
                        paths=tuple(index.path(row) for row in rows),
                    )
                )
    return findings


def _values_out_of_range(index: _Index) -> list[Finding]:
    """A bit number past what its AVP holds: 31 for Unsigned32 (the default),
    63 for an AVP the file's own table types Unsigned64."""
    typed = {row.name: row.data_type for row in index.rows if row.data_type}
    findings = []
    for table in index.value_tables:
        if table.kind is ast.ValueKind.RESULT_CODES:
            continue
        data_type = typed.get(table.avp, ast.DataType.UNSIGNED32)
        last = 63 if data_type is ast.DataType.UNSIGNED64 else 31
        findings.extend(
            Finding(
                Severity.ERROR,
                "value-bit-out-of-range",
                f"{table.avp}'s {table.kind} table numbers {row.name!r} bit"
                f" {row.value}, past the {last} a {data_type} holds",
                table.source.section,
                paths=(index.path(row),),
            )
            for row in table.rows
            if row.value > last
        )
    return findings


def _enum_entry_label(entry: ast.EnumEntry) -> str:
    if isinstance(entry, ast.EnumValue):
        return f"{entry.name!r} = {entry.value}"
    if isinstance(entry, ast.ReservedValues):
        kind = "reserved"
    elif isinstance(entry, ast.VoidValues):
        kind = "void"
    else:
        kind = "vendor-specific"
    return f"{kind} {entry.first}-{entry.last}"


def _vendor_specific_overlaps(index: _Index) -> list[Finding]:
    """A `; VENDOR-SPECIFIC` range covering a value the AVP names, a range it
    reserves or voids, or another vendor-specific range. No corpus case.
    """
    findings = []
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        entries = definition.values
        for position, vendor in enumerate(entries):
            if not isinstance(vendor, ast.VendorSpecificValues):
                continue
            for at, other in enumerate(entries):
                # A pair of vendor-specific ranges is reported once.
                if at == position or (
                    at < position and isinstance(other, ast.VendorSpecificValues)
                ):
                    continue
                first, last = (
                    (other.value, other.value)
                    if isinstance(other, ast.EnumValue)
                    else (other.first, other.last)
                )
                if vendor.first <= last and first <= vendor.last:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "vendor-specific-overlap",
                            f"{definition.name}'s {_enum_entry_label(vendor)}"
                            f" overlaps {_enum_entry_label(other)}",
                            definition.source.section,
                        )
                    )
    return findings


def _void_overlaps(index: _Index) -> list[Finding]:
    """A `; VOID` value the AVP also names or reserves, or a second `; VOID`
    over it. A vendor-specific range over one is `vendor-specific-overlap`'s.
    No corpus case.
    """
    findings = []
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        entries = definition.values
        for position, void in enumerate(entries):
            if not isinstance(void, ast.VoidValues):
                continue
            for at, other in enumerate(entries):
                # A pair of void lines is reported once.
                if (
                    at == position
                    or isinstance(other, ast.VendorSpecificValues)
                    or (at < position and isinstance(other, ast.VoidValues))
                ):
                    continue
                first, last = (
                    (other.value, other.value)
                    if isinstance(other, ast.EnumValue)
                    else (other.first, other.last)
                )
                if void.first <= last and first <= void.last:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "void-overlap",
                            f"{definition.name}'s {_enum_entry_label(void)}"
                            f" overlaps {_enum_entry_label(other)}",
                            definition.source.section,
                        )
                    )
    return findings


def _applications_agree_with_headers(index: _Index) -> list[Finding]:
    """A command sits in at most one application scope, and a header that
    prints an id prints the scope's. The model settles both silently.
    """
    findings = []
    for message in index.messages:
        blocks = [b for b in index.applications if b.covers(message.source.section)]
        if len(blocks) > 1:
            named = ", ".join(
                f"{b.name} ({b.application_id}, clause {b.source.section})"
                for b in blocks
            )
            findings.append(
                Finding(
                    Severity.ERROR,
                    "application-scope-overlap",
                    f"{message.name} is in the scope of {len(blocks)}"
                    f" applications: {named}",
                    message.source.section,
                )
            )
        for block in blocks:
            if message.application_id not in (None, block.application_id):
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "application-header-mismatch",
                        f"{message.name}'s header prints application"
                        f" {message.application_id}, but clause"
                        f" {block.source.section} gives {block.name}"
                        f" {block.application_id}",
                        message.source.section,
                    )
                )
    return findings
