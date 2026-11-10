"""Cross-file rules comparing what a file re-uses, re-prints or cites a
result code from against the origin document it names.
"""

from __future__ import annotations

from collections import defaultdict

from ..dad import ast, formatter
from ._findings import Finding, Severity
from ._index import _Index, _table_labels
from ._origins import _Origin


def _reused_avp_exists(index: _Index, origins: dict[str, _Origin]) -> list[Finding]:
    """Every re-used AVP is something the origin actually has.

    Two outcomes, because "the origin never heard of this AVP" and "the origin
    borrows it too" are different sizes of wrong. TS 29.283 cites `Feature-Id`
    from TS 29.229, which has no such AVP — 29.229 defines `Feature-List-ID`,
    and no dictionary anywhere carries a `Feature-Id`. TS 29.172 cites
    `Service-Selection` from TS 29.272, which does carry it but as a re-used
    AVP of RFC 5778's; the AVP is real and the citation names a middleman.
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
    """A row this file tabulates for an AVP it re-uses reads the origin's way.

    The cross-file counterpart of `table-row-mismatch`, with the same
    discipline: only what both rows state is compared. Type and encrypt are
    compared where both tables declare the column and both cells say
    something; with no origin row typing the AVP, an origin definition types it
    Grouped or Enumerated. A flag is compared where both rows place it in a
    column: RFC 7683's table puts M in neither Must nor Must-not, which leaves
    a citing interface free to forbid it. A row agreeing with any of the
    origin's rows agrees, since the origin's own disagreements are its
    `table-row-mismatch`. A note, because a citing interface may set its own
    flag rule on purpose, and evidence either way: the message says which
    side the model follows, for the disputed flag the first of the citing
    file's rows placing it (`_followed_for_flag`; RFC 6733 sections 4.1 and
    4.5 leave flag rules to the application), the origin for the type
    unless this file defines the AVP itself. A
    re-used table's M-bit column is not compared: it states this
    interface's setting, which is what the column is for, and the model
    reads it so (`model.Model._own_m_bit`), below the citing file's rows.
    Codes are `reused-code-conflict`'s.

    Only M and V are compared. RFC 6733 clause 4.1 reserves the P bit ("the
    'P' bit SHOULD be set to 0"), so documents written since drop it while
    their origins (RFC 4005, 4006, 5778; TS 29.212) still print it: across two
    documents a P cell records which side of RFC 6733 each was written on.
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
    """The row the model reads `flag` of a re-used AVP from, as a
    `reused-row-mismatch` message names it, `row` being the reported one:
    the first of this file's rows placing the flag
    (`model.Model._own_flags`). `row` places it, being compared on it, so
    that is `row` or an earlier row, never a re-used row's M-bit or the
    origin, which rank below. A first row placing V alone says nothing of
    M, so a second row's M is what the model follows."""
    for table, each in ours:
        if each is row:
            return f"this row for {flag.value}"
        if _placement(table, each, flag) is not None:
            return f"an earlier row for {flag.value}, in {_table_labels([table])}"
    raise AssertionError(f"{row.name}'s row is not among its rows")


def _reused_row_vendors_agree_with_origin(
    index: _Index, own_vendor: int, origins: dict[str, _Origin]
) -> list[Finding]:
    """A row this file tabulates for an AVP it re-uses places it in the
    origin's vendor space.

    The row's vendor is the model's reading (`ast.AvpTableRow.stated_vendor`):
    its Vendor-ID cell where its table prints one, else IETF space for V
    under Must-not and the file's `; Vendor-ID:` for V under Must; a row
    stating none agrees with any. The origin's is its definition's header,
    no vendor-id being IETF space, or what its own rows state the same way
    in its file. TS 29.229's rows for RFC 4590's `Digest-*` AVPs put V under
    Must-not and agree with RFC 4590's vendor 0. Agreeing with any one origin
    reading agrees, as for `reused-row-mismatch`. An error, unlike that
    rule's notes: two vendors are two identities, so the row and its origin
    name two AVPs, as two codes do (`reused-code-conflict`).
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
    """A code this file's AVP table prints for an AVP it lists as re-used is the
    code the origin gives it.

    The claim that an AVP is another document's, a re-used table's row or a
    clause's "This AVP is defined in", is a claim about one identity: TS 29.283
    clause 7.3.21 says its Sequence-Number "is defined in the 3GPP TS 29.329",
    whose Sequence-Number is 716, while table 7.3.1-1 gives 4512. A code the
    origin does not give is `reused-code-conflict`, an error like any second
    code: one of the two statements names another AVP. A table printing a code
    is no evidence against the claim alone, since TS 29.140 and TS 29.329
    tabulate codes for the AVPs they re-use."""
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
    """A re-used table's own Code and Type cells read the origin's way.

    TS 29.172 table 7.4.1-2 and TS 32.299's tables 7.3.1-7.5.1 print the
    code, 29.172 the type too, of the AVPs they take from elsewhere. The
    origin states both, in its definition or its table rows; a code it does
    not give is `reused-code-conflict`, an error like any second code, and a
    type it does not give is `reused-row-mismatch`. Only what the origin
    states is compared, and agreeing with any of its readings agrees.
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
    """Per reading, the (this row, origin row, where) pairs that both state,
    with the flag a flag rule's reading compares."""
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
    """The flag-rule column a row puts `flag` in, or None if it states none."""
    for column, field_name in _FLAG_COLUMNS.items():
        if column in table.columns and flag in getattr(row.flag_rules, field_name):
            return column.value
    return None


def _result_codes_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """A result code whose text names the document defining it is that
    document's: it lists the code under the same AVP, and gives it the same
    name.

    The counterpart of `reused-avp-not-in-origin` and `reused-origin-indirect`
    for a code. An origin listing no such code is an error, as for an AVP. A
    name compared exactly, since a dictionary keys on it, is a note:
    TS 29.283 clause 7.4.3.9 prints `DIAMETER_ERROR_DATA OUT_OF_SYNC` for what
    TS 29.329 calls `DIAMETER_ERROR_TRANSPARENT_DATA OUT_OF_SYNC`, and only the
    origin's spelling is the code's. So is an origin re-using the code from a
    third document."""
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
    """Decide what a local-and-re-used AVP is actually doing.

    This is the answer the single-file `local-and-reused` note declines to
    give. The one thing that is unambiguously wrong is disagreeing on the
    *code*: an AVP is its `(vendor-id, code)`, so two codes are two AVPs and
    one of the documents is mistaken. Everything else is reported as what it
    is — identical, a superset, or neither — and left to a reader, because a
    body that differs is a fact about two documents rather than a defect in
    this one, and only the origin's editor knows which is current.
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
    """What a `Reprinted AVP` block says against the document it names.

    A re-print defines nothing, so it never meets the duplicate rules: TS 29.109
    prints RFC 6733's `Vendor-Specific-Application-Id` three times. Its claim is
    that it copies the origin, and that is what is checked. An origin that has
    never heard of the name, or two codes for one AVP, is an error, as for a
    re-used row. A body naming other members is a note: only the origin's editor
    knows which copy is current. Occurrence qualifiers are not compared, since TS
    29.109 prints `0*1 { Auth-Application-Id }`, the form RFC 3588 used, for what
    RFC 6733 writes `[ Auth-Application-Id ]`.
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
    """What a definition's body lists: member AVPs, or enumerated value names.
    Comparing these compares the two documents' idea of the AVP's contents."""
    if isinstance(definition, ast.GroupedAvp):
        return frozenset(rule.name for rule in definition.avps)
    return frozenset(
        value.name for value in definition.values if isinstance(value, ast.EnumValue)
    )


def _compare(mine, theirs, origin: str) -> tuple[str, str]:
    """The rule name and the finished message, as a pair."""
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
