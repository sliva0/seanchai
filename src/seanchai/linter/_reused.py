"""Cross-file rules comparing re-used AVPs, re-prints and cited result
codes against the origin document they name.
"""

from __future__ import annotations

from collections import defaultdict

from ..dad import ast, formatter
from ._findings import Finding, Severity
from ._index import _Index, _table_labels
from ._origins import _Origin


def _reused_avp_exists(index: _Index, origins: dict[str, _Origin]) -> list[Finding]:
    """Every re-used AVP is one the origin has.

    An origin that lacks the AVP is an error (`reused-avp-not-in-origin`);
    one that re-uses it from a third document is a note
    (`reused-origin-indirect`).
    """
    findings = []
    for name, origin in sorted(index.reused.items()):
        resolved = origins.get(origin)
        if resolved is None:
            continue
        if name in resolved.defined or name in resolved.tabled:
            continue
        theirs = resolved.reused.get(name)
        if theirs is not None:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "reused-origin-indirect",
                    f"{name} is listed as re-used from {origin}, which re-uses it"
                    f" from {theirs} rather than defining it",
                    paths=tuple(index.reused_paths[name]),
                )
            )
            continue
        # An RFC entry has no version to name; the specification string alone
        # already names the immutable document.
        origin_doc = resolved.spec.specification
        if resolved.spec.version is not None:
            origin_doc += f" {resolved.spec.version}"
        findings.append(
            Finding(
                Severity.ERROR,
                "reused-avp-not-in-origin",
                f"{name} is listed as re-used from {origin}, but {origin_doc}"
                " neither defines, tabulates nor re-uses it",
            )
        )
    return findings


def _reused_rows_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """A note where this file's table row for a re-used AVP disagrees with
    every one of the origin's rows.

    Only what both sides state is compared: type and encrypt where both
    tables have the column, and the M and V flags where both rows place them
    (the P bit is obsolete since RFC 6733). An origin definition types the
    AVP when no origin row does. The message names the side the model
    follows (`_followed_for_flag`). A re-used table's M-bit column is not
    compared; it states this interface's own setting. Codes are
    `reused-code-conflict`'s.
    """
    ours: dict[str, list[tuple[ast.AvpTable, ast.AvpTableRow]]] = defaultdict(list)
    for table in index.tables:
        for row in table.rows:
            ours[row.name].append((table, row))
    findings = []
    for name, origin in sorted(index.reused.items()):
        resolved = origins.get(origin)
        if resolved is None or name not in ours:
            continue
        theirs = [
            (table, row)
            for table in resolved.tables
            for row in table.rows
            if row.name == name
        ]
        definition = resolved.defined.get(name)
        for table, row in ours[name]:
            for label, flag, compared in _row_comparisons(
                table, row, theirs, definition
            ):
                if not compared or any(mine == other for mine, other, _ in compared):
                    continue
                spelled = "; ".join(
                    f"{other} in {where}" for _, other, where in compared
                )
                if flag is not None:
                    followed = _followed_for_flag(ours[name], row, flag)
                elif label == "encrypt":
                    followed = "neither, carrying no encrypt rule"
                elif any(each.name == name for each in index.definitions):
                    followed = "this file's definition"
                else:
                    followed = origin
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "reused-row-mismatch",
                        f"{name} is tabulated with {label} {compared[0][0]} in"
                        f" {_table_labels([table])}, but {origin}, which it is"
                        f" re-used from, reads {spelled}; the model follows"
                        f" {followed}",
                        paths=(index.path(row),),
                    )
                )
    return findings


def _followed_for_flag(
    ours: list[tuple[ast.AvpTable, ast.AvpTableRow]],
    row: ast.AvpTableRow,
    flag: ast.AvpFlag,
) -> str:
    """Name the row the model reads `flag` from, for a `reused-row-mismatch`
    message about `row`: the first of this file's rows that places the flag
    (`model._resolution._Resolver._own_flags`). That is `row` or an earlier
    row."""
    for table, each in ours:
        if each is row:
            return f"this row for {flag.value}"
        if _placement(table, each, flag) is not None:
            return f"an earlier row for {flag.value}, in {_table_labels([table])}"
    raise AssertionError(f"{row.name}'s row is not among its rows")


def _reused_row_vendors_agree_with_origin(
    index: _Index, own_vendor: int, origins: dict[str, _Origin]
) -> list[Finding]:
    """An error where this file's row for a re-used AVP states a vendor no
    origin reading gives; two vendors mean two AVPs.

    Vendors are read by `ast.AvpTableRow.stated_vendor`; a row stating none
    agrees with any. The origin's readings are its definition (no vendor-id
    is IETF space) and its own rows.
    """
    findings = []
    for name, origin in sorted(index.reused.items()):
        resolved = origins.get(origin)
        if resolved is None:
            continue
        readings: list[tuple[int, str]] = []
        definition = resolved.defined.get(name)
        if definition is not None:
            readings.append(
                (
                    ast.IETF_VENDOR
                    if definition.vendor_id is None
                    else definition.vendor_id,
                    f"its clause {definition.source.section}",
                )
            )
        for table in resolved.tables:
            for their_row in table.rows:
                if their_row.name != name:
                    continue
                stated = their_row.stated_vendor(resolved.spec.vendor_id)
                if stated is not None:
                    readings.append((stated, _table_labels([table])))
        if not readings:
            continue
        for table in index.tables:
            for row in table.rows:
                if row.name != name:
                    continue
                mine = row.stated_vendor(own_vendor)
                if mine is None or any(mine == other for other, _ in readings):
                    continue
                spelled = "; ".join(
                    f"vendor {other} in {where}" for other, where in readings
                )
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "reused-row-vendor-mismatch",
                        f"{name} is tabulated in vendor {mine} in"
                        f" {_table_labels([table])}, but {origin}, which it is"
                        f" re-used from, reads {spelled}",
                        paths=(index.path(row),),
                    )
                )
    return findings


def _reused_codes_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """An error (`reused-code-conflict`) where this file's AVP table prints a
    code for a re-used AVP that the origin does not give it."""
    findings = []
    for table in index.tables:
        for row in table.rows:
            origin = index.reused.get(row.name)
            if row.code is None or origin is None:
                continue
            resolved = origins.get(origin)
            if resolved is None:
                continue
            definition = resolved.defined.get(row.name)
            codes = {
                their.code
                for their_table in resolved.tables
                for their in their_table.rows
                if their.name == row.name and their.code is not None
            }
            if definition is not None:
                codes.add(definition.code)
            if codes and row.code not in codes:
                label = table.table or f"(clause {table.source.section})"
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "reused-code-conflict",
                        f"{row.name} is code {row.code} in table {label} and"
                        f" {', '.join(map(str, sorted(codes)))} in {origin},"
                        " which it is listed as re-used from",
                        table.source.section,
                        origin,
                        paths=(index.path(row),),
                    )
                )
    return findings


def _reused_cells_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """A re-used table's own Code and Type cells agree with the origin.

    A code the origin does not give is a `reused-code-conflict` error; a
    type is a `reused-row-mismatch` note. Matching any origin reading agrees.
    """
    findings = []
    for block, row in index.reused_cells:
        resolved = origins.get(row.origin)
        if resolved is None:
            continue
        definition = resolved.defined.get(row.name)
        theirs = [
            their_row
            for table in resolved.tables
            for their_row in table.rows
            if their_row.name == row.name
        ]
        codes = {their.code for their in theirs if their.code is not None}
        types = {their.data_type for their in theirs if their.data_type is not None}
        if definition is not None:
            codes.add(definition.code)
            if not types:
                types.add(
                    ast.DataType.GROUPED
                    if isinstance(definition, ast.GroupedAvp)
                    else ast.DataType.ENUMERATED
                )
        where = f"re-used table {block.table}"
        if row.code is not None and codes and row.code not in codes:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reused-code-conflict",
                    f"{row.name} is code {row.code} in {where} and"
                    f" {', '.join(map(str, sorted(codes)))} in {row.origin},"
                    " which it is re-used from",
                    block.source.section,
                    row.origin,
                )
            )
        if row.data_type is not None and types and row.data_type not in types:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "reused-row-mismatch",
                    f"{row.name} is typed {row.data_type.value} in {where}, but"
                    f" {row.origin}, which it is re-used from, reads"
                    f" {', '.join(sorted(each.value for each in types))};"
                    f" the model follows {row.origin}",
                    block.source.section,
                    row.origin,
                    paths=(index.path(row),),
                )
            )
    return findings


_CROSS_FILE_FLAGS = (ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR)
_FLAG_COLUMNS = {
    ast.AvpColumn.MUST: "must",
    ast.AvpColumn.MAY: "may",
    ast.AvpColumn.SHOULD_NOT: "should_not",
    ast.AvpColumn.MUST_NOT: "must_not",
}


def _row_comparisons(
    table: ast.AvpTable,
    row: ast.AvpTableRow,
    theirs: list[tuple[ast.AvpTable, ast.AvpTableRow]],
    definition: ast.GroupedAvp | ast.EnumeratedAvp | None,
) -> list[tuple[str, ast.AvpFlag | None, list[tuple[str, str, str]]]]:
    """Return, per compared field, its label, its flag (for flag rules) and
    the `(this row, origin row, where)` values both sides state."""
    out = []
    for label, column in (
        ("type", ast.AvpColumn.TYPE),
        ("encrypt", ast.AvpColumn.ENCRYPT),
    ):
        compared = [
            (mine, other, _table_labels([their_table]))
            for their_table, their_row in theirs
            if column in table.columns
            and column in their_table.columns
            and (mine := formatter.avp_table_cell(row, column)) != "-"
            and (other := formatter.avp_table_cell(their_row, column)) != "-"
        ]
        if (
            not compared
            and column is ast.AvpColumn.TYPE
            and definition is not None
            and column in table.columns
            and row.data_type is not None
        ):
            kind = (
                ast.DataType.GROUPED
                if isinstance(definition, ast.GroupedAvp)
                else ast.DataType.ENUMERATED
            )
            compared = [
                (
                    row.data_type.value,
                    kind.value,
                    f"its clause {definition.source.section}",
                )
            ]
        out.append((label, None, compared))
    for flag in _CROSS_FILE_FLAGS:
        mine = _placement(table, row, flag)
        compared = [
            (f"{flag.value} in {mine}", f"{flag.value} in {other}", _table_labels([t]))
            for t, their_row in theirs
            if mine is not None
            and (other := _placement(t, their_row, flag)) is not None
        ]
        out.append(("flag rule", flag, compared))
    return out


def _placement(
    table: ast.AvpTable, row: ast.AvpTableRow, flag: ast.AvpFlag
) -> str | None:
    """Return the flag-rule column a row puts `flag` in, or None."""
    for column, field_name in _FLAG_COLUMNS.items():
        if column in table.columns and flag in getattr(row.flag_rules, field_name):
            return column.value
    return None


def _result_codes_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """A result code whose text names its defining document is listed there,
    under the same AVP and name.

    A missing code is an error. A different name (compared exactly) and an
    origin that re-uses the code from a third document are notes."""
    findings = []
    for table, row in index.reused_values:
        assert row.origin is not None
        resolved = origins.get(row.origin)
        if resolved is None:
            continue
        clause = row.section or table.source.section
        theirs = [
            their
            for their_table in resolved.value_tables
            if their_table.kind is ast.ValueKind.RESULT_CODES
            and their_table.avp == table.avp
            for their in their_table.rows
            if their.value == row.value
        ]
        said = f"{row.name} (code {row.value}) is cited from {row.origin}"
        if not theirs:
            document = resolved.spec.specification
            if resolved.spec.version is not None:
                document += f" {resolved.spec.version}"
            findings.append(
                Finding(
                    Severity.ERROR,
                    "result-code-not-in-origin",
                    f"{said}, but {document} lists no {table.avp} {row.value}",
                    clause,
                    row.origin,
                    paths=(index.path(row),),
                )
            )
            continue
        names = list(dict.fromkeys(their.name for their in theirs))
        if row.name not in names:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "result-code-origin-name",
                    f"{said}, which names it {' and '.join(names)}",
                    clause,
                    row.origin,
                    paths=(index.path(row),),
                )
            )
        if all(their.origin is not None for their in theirs):
            via = ", ".join(dict.fromkeys(str(their.origin) for their in theirs))
            findings.append(
                Finding(
                    Severity.NOTE,
                    "result-code-origin-indirect",
                    f"{said}, which re-uses it from {via} rather than defining it",
                    clause,
                    row.origin,
                    paths=(index.path(row),),
                )
            )
    return findings


def _reprint_or_extension(index: _Index, origins: dict[str, _Origin]) -> list[Finding]:
    """Classify an AVP both defined here and re-used, against the origin.

    A different code is an error. Otherwise a note says whether the body is
    identical (`reused-reprint`), a superset (`reused-extension`) or neither
    (`reused-body-differs`).
    """
    findings = []
    for definition in sorted(index.definitions, key=lambda d: d.name):
        origin = index.reused.get(definition.name)
        if origin is None:
            continue
        resolved = origins.get(origin)
        if resolved is None:
            continue
        theirs = resolved.defined.get(definition.name)
        if theirs is None:
            # The origin has it only as a table row, so there is no body to
            # compare; `_reused_avp_exists` has already accepted it.
            continue
        where = definition.source.section
        if definition.code != theirs.code:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reused-code-conflict",
                    f"{definition.name} is code {definition.code} here and"
                    f" {theirs.code} in {origin} clause {theirs.source.section}",
                    where,
                )
            )
            continue
        rule, message = _compare(definition, theirs, origin)
        findings.append(
            Finding(
                Severity.NOTE, rule, message, where, paths=(index.path(definition),)
            )
        )
    return findings


def _reprints_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """Check a `Reprinted AVP` block against the document it names.

    An origin lacking the name, or a different code, is an error. Different
    member names are a note. Occurrence qualifiers are not compared, since
    older documents print RFC 3588's forms.
    """
    findings = []
    for reprint in index.reprints:
        origin = reprint.origin
        resolved = origins.get(origin)
        if resolved is None:
            continue
        where = reprint.source.section
        theirs = resolved.defined.get(reprint.name)
        row = resolved.tabled.get(reprint.name)
        if theirs is None and row is None:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reprint-not-in-origin",
                    f"{reprint.name} is printed as {origin}'s, which does not"
                    " define it",
                    where,
                    origin,
                )
            )
            continue
        code = theirs.code if theirs is not None else row.code if row else None
        if code is not None and code != reprint.code:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reused-code-conflict",
                    f"{reprint.name} is code {reprint.code} here and {code} in"
                    f" {origin}",
                    where,
                    origin,
                )
            )
            continue
        if not isinstance(theirs, ast.GroupedAvp):
            continue
        ours = {rule.name for rule in reprint.avps}
        base = {rule.name for rule in theirs.avps}
        if ours != base:
            added = ", ".join(sorted(ours - base)) or "nothing"
            dropped = ", ".join(sorted(base - ours)) or "nothing"
            findings.append(
                Finding(
                    Severity.NOTE,
                    "reprint-differs",
                    f"{reprint.name}'s body, against {origin}'s definition: adds"
                    f" {added}, missing {dropped}",
                    where,
                    origin,
                    paths=(index.path(reprint),),
                )
            )
    return findings


def _members(definition: ast.GroupedAvp | ast.EnumeratedAvp) -> frozenset[str]:
    """Return a definition's member AVP names, or its enumerated value names."""
    if isinstance(definition, ast.GroupedAvp):
        return frozenset(rule.name for rule in definition.avps)
    return frozenset(
        value.name for value in definition.values if isinstance(value, ast.EnumValue)
    )


def _compare(mine, theirs, origin: str) -> tuple[str, str]:
    """Return the rule name and message for a body comparison."""
    subject = f"{mine.name}'s body, against {origin}'s definition:"
    if type(mine) is not type(theirs):
        return "reused-body-differs", f"{subject} a different kind of AVP entirely"
    ours, base = _members(mine), _members(theirs)
    if ours == base:
        return "reused-reprint", f"{subject} identical, so this re-prints it"
    added = ", ".join(sorted(ours - base))
    dropped = ", ".join(sorted(base - ours))
    if base < ours:
        return "reused-extension", f"{subject} extended, adding {added}"
    if ours < base:
        return "reused-body-differs", f"{subject} missing {dropped}"
    return "reused-body-differs", f"{subject} adds {added}, missing {dropped}"
