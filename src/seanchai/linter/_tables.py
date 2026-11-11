"""Single-file rules over AVP identities and AVP tables: duplicate
`(vendor-id, code)`, rows against definitions and each other, and vendors
against headers and V flags.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from ..dad import ast, formatter
from ._findings import AvpIdentity, Finding, Severity
from ._index import _Index, _table_labels


def _identity(code: int, vendor_id: int | None) -> AvpIdentity:
    """Return the identity, reading no vendor as IETF space (vendor 0)."""
    return AvpIdentity(ast.IETF_VENDOR if vendor_id is None else vendor_id, code)


def _duplicate_identities(
    index: _Index,
    own_vendor: int,
    reused_vendor: Callable[[str], int | None] | None = None,
) -> list[Finding]:
    """No two AVPs share a `(vendor-id, code)`.

    A re-used row is in its origin's vendor space, which `reused_vendor`
    maps from the origin reference. Without it, or when it returns None,
    the row is skipped.
    """
    holders: dict[AvpIdentity, list[tuple[str, str]]] = defaultdict(list)
    for definition in index.definitions:
        identity = _identity(definition.code, definition.vendor_id)
        holders[identity].append(
            (definition.name, f"{definition.name} (clause {definition.source.section})")
        )
    for row in index.rows:
        if row.code is None:
            continue
        origin = index.reused.get(row.name)
        if origin is None:
            stated = row.stated_vendor(own_vendor)
            identity = AvpIdentity(own_vendor if stated is None else stated, row.code)
            claim = f"{row.name} (AVP table)"
        else:
            vendor = None if reused_vendor is None else reused_vendor(origin)
            if vendor is None:
                continue
            identity = AvpIdentity(vendor, row.code)
            claim = f"{row.name} (AVP table, re-used from {origin})"
        # A row whose own definition is in this file is the same AVP, not a
        # second claimant.
        if row.name in {name for name, _ in holders[identity]}:
            continue
        holders[identity].append((row.name, claim))

    findings = []
    for identity, claims in sorted(holders.items(), key=lambda item: item[0].code):
        if len(claims) > 1:
            names = ", ".join(text for _, text in claims)
            findings.append(
                Finding(
                    Severity.ERROR,
                    "duplicate-identity",
                    f"{identity} is claimed by {len(claims)} AVPs: {names}",
                )
            )
    return findings


def _rows_without_codes(index: _Index) -> list[Finding]:
    """Every row of a table with a Code column has a code.

    A code-less row is an error, usually a re-used AVP in the wrong table. A
    row with a clause and no code, flag or Encrypt cell is a note: it records
    a clause that states no code, and the model reports it as a hole.
    """
    findings = []
    for table in index.tables:
        if ast.AvpColumn.CODE not in table.columns:
            continue
        for row in table.rows:
            if row.code is not None:
                continue
            flags = row.flag_rules
            placed = flags.must | flags.may | flags.should_not | flags.must_not
            if row.section is not None and not placed and row.may_encrypt is None:
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "row-without-code",
                        f"{row.name} is tabulated with no AVP code: clause"
                        f" {row.section} states none, so it has no wire identity"
                        " in this document",
                        row.section,
                    )
                )
                continue
            findings.append(
                Finding(
                    Severity.ERROR,
                    "row-without-code",
                    f"{row.name} is tabulated with no AVP code, and an AVP"
                    " without a code has no wire identity; a re-used AVP"
                    " belongs in the re-used table instead",
                    row.section or table.source.section,
                )
            )
    return findings


def _table_agrees_with_definitions(index: _Index) -> list[Finding]:
    by_name = {d.name: d for d in index.definitions}
    findings = []
    for row in index.rows:
        definition = by_name.get(row.name)
        if definition is None:
            continue
        if row.code is not None and row.code != definition.code:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "table-definition-mismatch",
                    f"{row.name}: the AVP table says code {row.code},"
                    f" clause {definition.source.section} says {definition.code}",
                )
            )
        expected = (
            ast.DataType.GROUPED
            if isinstance(definition, ast.GroupedAvp)
            else ast.DataType.ENUMERATED
        )
        if row.data_type is not None and row.data_type != expected:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "table-definition-mismatch",
                    f"{row.name}: the AVP table says type {row.data_type.value},"
                    f" clause {definition.source.section} defines it as"
                    f" {expected.value.lower()}",
                )
            )
    return findings


# What `table-row-mismatch` compares, by the columns each reading spans. The
# Section column is left out: TS 29.273 points each interface's row at its
# own re-printed clause.
_ROW_READINGS = (
    ("vendor", (ast.AvpColumn.VENDOR,)),
    ("code", (ast.AvpColumn.CODE,)),
    ("type", (ast.AvpColumn.TYPE,)),
    (
        "flag rules",
        (
            ast.AvpColumn.MUST,
            ast.AvpColumn.MAY,
            ast.AvpColumn.SHOULD_NOT,
            ast.AvpColumn.MUST_NOT,
        ),
    ),
    ("encrypt", (ast.AvpColumn.ENCRYPT,)),
)


def _tables_agree_with_each_other(index: _Index) -> list[Finding]:
    """Rows naming one AVP in several of a file's AVP tables agree.

    Only columns every such table declares, and only non-blank cells, are
    compared. A code or vendor disagreement is an error; others are notes.
    A code disagreement is left to `table-definition-mismatch` when a clause
    defines the AVP.
    """
    placed: dict[str, list[tuple[ast.AvpTable, ast.AvpTableRow]]] = defaultdict(list)
    for table in index.tables:
        for row in table.rows:
            placed[row.name].append((table, row))
    defined = {definition.name for definition in index.definitions}

    findings = []
    for name, copies in placed.items():
        if len(copies) < 2:
            continue
        for label, columns in _ROW_READINGS:
            if label == "code" and name in defined:
                continue
            shared = [
                column
                for column in columns
                if all(column in table.columns for table, _ in copies)
            ]
            spelled = _disagreement(copies, shared)
            if spelled is None:
                continue
            findings.append(
                Finding(
                    Severity.ERROR if label in ("code", "vendor") else Severity.NOTE,
                    "table-row-mismatch",
                    f"{name} is tabulated with differing {label}: {spelled}",
                    paths=tuple(index.path(row) for _, row in copies),
                )
            )
    return findings


def _disagreement(
    copies: list[tuple[ast.AvpTable, ast.AvpTableRow]],
    columns: list[ast.AvpColumn],
) -> str | None:
    """Spell the rows' differing readings of `columns` for a message, or
    return None when every non-blank row agrees."""
    readings: dict[str, list[ast.AvpTable]] = defaultdict(list)
    for table, row in copies:
        cells = [formatter.avp_table_cell(row, column) for column in columns]
        if all(cell == "-" for cell in cells):
            continue
        reading = (
            cells[0]
            if len(columns) == 1
            else ", ".join(
                f"{column.value} {cell}"
                for column, cell in zip(columns, cells, strict=True)
            )
        )
        readings[reading].append(table)
    if len(readings) < 2:
        return None
    return "; ".join(
        f"{reading} in {_table_labels(tables)}" for reading, tables in readings.items()
    )


def _vendor_id_agrees_with_header(index: _Index, own_vendor: int) -> list[Finding]:
    """A definition's vendor-id agrees with its row's Vendor-ID cell where
    the table prints one, else with the file's `; Vendor-ID:`.

    A header with no vendor-id is an error only when the AVP's row requires
    the V flag. Re-used names are skipped.
    """
    rows = {row.name: row for row in index.rows}
    findings = []
    for definition in index.definitions:
        if definition.name in index.reused:
            # Vendor-less because it belongs to the origin's space, which this
            # file does not state. The cross-document rules settle these.
            continue
        clause = definition.source.section
        row = rows.get(definition.name)
        stated = None if row is None else row.vendor_id
        if stated is not None:
            if (definition.vendor_id or ast.IETF_VENDOR) == stated:
                continue
            printed = (
                "no vendor-id"
                if definition.vendor_id is None
                else f"vendor {definition.vendor_id}"
            )
            findings.append(
                Finding(
                    Severity.ERROR,
                    "vendor-id-mismatch",
                    f"{definition.name} is defined with {printed}, but the AVP"
                    f" table gives it vendor {stated}",
                    clause,
                )
            )
        elif definition.vendor_id is None:
            if row is None or ast.AvpFlag.VENDOR not in row.flag_rules.must:
                continue
            findings.append(
                Finding(
                    Severity.ERROR,
                    "vendor-id-mismatch",
                    f"{definition.name} is defined with no vendor-id, but the AVP"
                    f" table requires its V flag; the file is vendor {own_vendor}",
                    clause,
                )
            )
        elif definition.vendor_id != own_vendor:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "vendor-id-mismatch",
                    f"{definition.name} is defined with vendor"
                    f" {definition.vendor_id}, but the file states vendor"
                    f" {own_vendor}",
                    clause,
                )
            )
    return findings


def _vendors_agree_with_flags(index: _Index) -> list[Finding]:
    """A row's Vendor-ID cell and its V flag agree (RFC 6733 section 4.1.1).

    The model takes the vendor from the cell (`AvpTableRow.stated_vendor`).
    """
    return [
        Finding(
            Severity.ERROR,
            "vendor-flag-mismatch",
            f"{row.name} is tabulated with {conflict} in"
            f" {_table_labels([table])}; RFC 6733 section 4.1.1 sets V exactly"
            " when the header carries a vendor-id, which is never 0",
            row.section or table.source.section,
            paths=(index.path(row),),
        )
        for table in index.tables
        for row in table.rows
        if (conflict := row.vendor_flag_conflict()) is not None
    ]
