"""Single-file rules over AVP identities and the AVP tables: a
`(vendor-id, code)` claimed twice, rows against definitions and against
each other, and vendors against headers and V flags.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from ..dad import ast, formatter
from ._findings import AvpIdentity, Finding, Severity
from ._index import _Index, _table_labels


def _identity(code: int, vendor_id: int | None) -> AvpIdentity:
    """`.dad` writes an IETF-space AVP with no vendor; the wire format calls
    that vendor 0."""
    return AvpIdentity(ast.IETF_VENDOR if vendor_id is None else vendor_id, code)


def _duplicate_identities(
    index: _Index,
    own_vendor: int,
    reused_vendor: Callable[[str], int | None] | None = None,
) -> list[Finding]:
    """No two AVPs share a `(vendor-id, code)`.

    Not the same rule as "no duplicate names": TS 29.272's `Area-Scope` was
    printed with `Job-Type`'s code, so two differently-named AVPs had one
    identity while every name in the file stayed unique.

    A re-used AVP belongs to the origin's vendor space, which is that
    document's `; Vendor-ID:` to state — not this file's to guess. Two AVPs
    numbered 621 in TS 29.229 are 3GPP's and RFC 7683's, and a comparison that
    assumed one space would call them a collision. `reused_vendor` is the
    cross-document rules supplying that answer, origin reference → vendor-id;
    without it (single-file mode), and for any origin it cannot resolve, the
    row is skipped rather than guessed at.
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
    """A table that declares a Code column fills it in every row.

    An AVP is its `(vendor-id, code)`, so a row printing `-` for its code
    describes nothing a message could carry. Both real cases are the same
    editorial slip: TS 29.229 and TS 29.329 tabulate `Load` code-less among
    their own AVPs while their prose defines it only by reference to
    RFC 8583 — a re-used AVP printed in the wrong table. Only tables that
    declare a Code column are checked: RFC 7155's tables carry no such
    column at all, which is a statement about the document's layout rather
    than about any one AVP.

    A row with a clause and no code, flag or Encrypt cell is no such slip but
    the whole of what its clause states, inserted for a table omitting the
    AVP: TS 29.229's `Wildcarded-IMPU`, clause 6.3.43. The file cannot give
    the code it does not state, so that is a note, and the model's hole.
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
    """Rows naming one AVP in two of a file's AVP tables say the same thing.

    Per-interface tables re-print shared AVPs, and nothing keeps the copies in
    step: TS 29.061 tabulates `3GPP-IMSI` and six more with M in M.not in
    table 9a (clause 16a.5, Gi/SGi) and with M in Must in table 10 (clause
    17.7.0, Gmb). A note, because the per-interface flag rule may be
    deliberate and only the document's editor knows which; the model resolves
    a name to its first row (see `docs/consumers.md`).

    Compared only on columns every table carrying the row declares, and only
    where the cells say something, so a table without an Encrypt column (TS
    29.273's) or a blank type cell makes no claim to disagree with. A code
    or vendor disagreement is an error, since two identities are two AVPs; a
    code's is left to `table-definition-mismatch` when a clause defines the
    AVP, because that rule names which row is wrong.
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
    """The rows' readings of `columns` grouped by value and spelled for a
    message, or None when every row that says something agrees."""
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
    """A definition's vendor-id agrees with the file's `; Vendor-ID:`, or
    with its row's Vendor-ID cell where the table prints one.

    A clause header writes no vendor-id for an IETF-space AVP, and writes no
    vendor-id when the document simply forgot — the two look identical. What
    tells them apart is the rest of the file. TS 29.272 defines
    `WLAN-offloadability` (clause 7.3.181) with a bare `< AVP header: 1667 >`
    while its own AVP table marks the `V` flag mandatory for that row: the
    document says in one place that the AVP carries a vendor-id and in another
    that it has none. `MIP6-Agent-Info` in the same file is equally vendor-less
    and entirely correct, because it is RFC 5447's and listed as re-used.
    oneM2M TS-0004 prints `M2M-Information`'s header with no vendor-id
    (clause A.5.14) and its row in table A.4-1 with vendor 45687.
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
    """A row's Vendor-ID cell and its V flag say the same thing.

    RFC 6733 section 4.1.1 sets the V bit exactly when the header carries a
    Vendor-ID, which is never zero. oneM2M TS-0004 table A.4-1 prints
    vendor 45687 for its own AVPs, as clause A.4 assigns them ("AVPs defined
    for oneM2M specific usage are assigned Vendor-Id of 45687"), and puts V
    under Must-not in every one of those rows, as it does for its IETF rows.
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
