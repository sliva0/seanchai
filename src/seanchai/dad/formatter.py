"""Canonical formatter: AST → `.dad` text.

`format_spec(parse(text))` must be idempotent — the patch-based review workflow
depends on stable diffs. Canonical rules:

- sections separated by two blank lines; file ends with one newline;
- ABNF bodies: 8-space indent with the repetition qualifier right-aligned in
  front of it; `; bold` markers aligned one column past the longest ABNF body
  line of their own section;
- enum bodies: `=` aligned per section (RESERVED counts as a name);
- tables: columns split by 3 spaces, widths from data cells only (minimum 3);
  labels sit at column starts, overflowing into gaps when wider than the
  column. Both table kinds write their labels as a `; Columns:` directive, so
  the first label follows the directive and every later one lines up with its
  data.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import abnf, ast

# Free-text notes to attach to the lines particular nodes produce, keyed by
# `id(node)`. Used to mark what the correction layer touched; `;;` comments
# are discarded on parse, so a note is a reader's aid and never data.
Notes = Mapping[int, Sequence[str]]
_NO_NOTES: Notes = {}


def _noted(line: str, node: Any, notes: Notes) -> str:
    """The node's notes appended as a trailing comment, on the line it marks."""
    return line + "".join(f" ;; {note}" for note in notes.get(id(node), ()))


def _notes_before(node: Any, notes: Notes) -> list[str]:
    """Whole-line notes, for a node whose edit left no line to append to — a
    deletion's note goes before the section the node disappeared from."""
    return [f";; {note}" for note in notes.get(id(node), ())]


_MIN_COLUMN_WIDTH = 3
_COLUMN_GAP = 3


def _avp_line(rule: ast.AvpRule) -> str:
    open_bracket, close_bracket = abnf.brackets_for(rule.presence)
    qualifier = abnf.qualifier(rule.min_occurs, rule.max_occurs)
    return f"{qualifier:>7} {open_bracket} {rule.name} {close_bracket}"


def _abnf_body(avps: tuple[ast.AvpRule, ...], notes: Notes = _NO_NOTES) -> list[str]:
    """`; bold` markers sit one column past the longest rule *of this section*.
    A file-wide column would make one added AVP reflow every marker in the
    file, and the review workflow lives on raw-vs-raw diffs."""
    rules = [(rule, _avp_line(rule)) for rule in avps]
    bold_column = max((len(line) for _, line in rules), default=0) + 1
    lines = []
    for rule, line in rules:
        if rule.bold:
            line = f"{line:<{bold_column}}; bold"
        lines.append(_noted(line, rule, notes))
    return lines


def _header_directives(name: str, source: ast.SourceRef) -> list[str]:
    lines = [f"; Name: {name}", f"; Section: {source.section}"]
    if source.page is not None:
        lines.append(f"; Page: {source.page}")
    return lines


def _table(
    headers: list[str],
    rows: list[list[str]],
    prefix: str,
    row_notes: Sequence[Sequence[str]] | None = None,
) -> list[str]:
    """`row_notes` is parallel to `rows`. Notes are appended *after* the
    column widths are computed, so annotating a row cannot reflow the table."""
    widths = [
        max(_MIN_COLUMN_WIDTH, max(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    starts = [0]
    for width in widths[:-1]:
        starts.append(starts[-1] + width + _COLUMN_GAP)

    header_line = prefix
    for header, start in zip(headers, starts, strict=True):
        header_line += " " * max(start - len(header_line), 1) + header
    lines = [header_line]
    notes = row_notes if row_notes is not None else [()] * len(rows)
    for row, row_note in zip(rows, notes, strict=True):
        line = ""
        for cell, start in zip(row, starts, strict=True):
            line += " " * (start - len(line)) + cell
        lines.append(line + "".join(f" ;; {note}" for note in row_note))
    return lines


def _format_message(message: ast.Message, notes: Notes = _NO_NOTES) -> list[str]:
    header_items = abnf.diameter_header_items(
        message.command_code, message.flags, message.application_id
    )
    return [
        "; Type: Message",
        *_header_directives(f"{message.name}, {message.abbreviation}", message.source),
        # Section-level notes trail the header rule: it is the line that
        # carries the fields a correction to the section itself can touch.
        _noted(
            f"<{message.name}> ::= < Diameter Header: {header_items} >",
            message,
            notes,
        ),
        *_abnf_body(message.avps, notes),
    ]


def _avp_header_items(code: int, vendor_id: int | None) -> str:
    return str(code) if vendor_id is None else f"{code} {vendor_id}"


def _format_grouped(avp: ast.GroupedAvp, notes: Notes = _NO_NOTES) -> list[str]:
    return [
        "; Type: Grouped AVP",
        *_header_directives(avp.name, avp.source),
        _noted(
            f"{avp.name} ::= < AVP header:"
            f" {_avp_header_items(avp.code, avp.vendor_id)} >",
            avp,
            notes,
        ),
        *_abnf_body(avp.avps, notes),
    ]


def _format_enumerated(avp: ast.EnumeratedAvp, notes: Notes = _NO_NOTES) -> list[str]:
    width = max(
        (
            len(value.name) if isinstance(value, ast.EnumValue) else len("RESERVED")
            for value in avp.values
        ),
        default=0,
    )
    lines = [
        "; Type: Enumerated AVP",
        *_header_directives(avp.name, avp.source),
        _noted(
            f"{avp.name} ::= < Enumerated AVP header:"
            f" {_avp_header_items(avp.code, avp.vendor_id)} >",
            avp,
            notes,
        ),
    ]
    value_width = max(
        (
            len(str(value.value))
            for value in avp.values
            if isinstance(value, ast.EnumValue)
        ),
        default=0,
    )
    for value in avp.values:
        if isinstance(value, ast.EnumValue):
            line = f"        {value.name:<{width}} = {value.value:<{value_width}}"
            if value.description is not None:
                line += f" ; {value.description}"
            line = line.rstrip()
        else:
            numbers = (
                str(value.first)
                if value.first == value.last
                else f"{value.first}-{value.last}"
            )
            line = f"      ; {'RESERVED':<{width}} = {numbers}"
        lines.append(_noted(line, value, notes))
    return lines


def _avp_table_cell(row: ast.AvpTableRow, column: ast.AvpColumn) -> str:
    """One modelled cell, with `-` as the canonical empty. Only reached for
    columns the table declares, so a None here is an empty source cell."""
    match column:
        case ast.AvpColumn.NAME:
            return row.name
        case ast.AvpColumn.CODE:
            return "-" if row.code is None else str(row.code)
        case ast.AvpColumn.SECTION:
            return "-" if row.section is None else row.section
        case ast.AvpColumn.TYPE:
            return "-" if row.data_type is None else row.data_type.value
        case ast.AvpColumn.MUST:
            return abnf.avp_flags_cell(row.flag_rules.must)
        case ast.AvpColumn.MAY:
            return abnf.avp_flags_cell(row.flag_rules.may)
        case ast.AvpColumn.SHOULD_NOT:
            return abnf.avp_flags_cell(row.flag_rules.should_not)
        case ast.AvpColumn.MUST_NOT:
            return abnf.avp_flags_cell(row.flag_rules.must_not)
        case ast.AvpColumn.ENCRYPT:
            return (
                "-" if row.may_encrypt is None else "Yes" if row.may_encrypt else "No"
            )


def _format_avp_table(table: ast.AvpTable, notes: Notes = _NO_NOTES) -> list[str]:
    headers = [column.value for column in table.columns]
    rows = [
        [_avp_table_cell(row, column) for column in table.columns] for row in table.rows
    ]
    return [
        # A note on the table itself marks an edit that left no line of its
        # own — a deleted row — so it stands before the section.
        *_notes_before(table, notes),
        "; Type: AVP Table",
        f"; Section: {table.source.section}",
        *([] if table.table is None else [f"; Table: {table.table}"]),
        *([f"; Page: {table.source.page}"] if table.source.page is not None else []),
        *_table(
            headers,
            rows,
            prefix="; Columns:",
            row_notes=[notes.get(id(row), ()) for row in table.rows],
        ),
    ]


def _reused_cell(row: ast.ReusedAvpRow, column: ast.ReusedColumn) -> str:
    match column:
        case ast.ReusedColumn.NAME:
            return row.name
        case ast.ReusedColumn.FROM:
            return row.origin
        case ast.ReusedColumn.M_BIT:
            return row.m_bit.value if row.m_bit else "-"


def _format_reused(reused: ast.ReusedAvps, notes: Notes = _NO_NOTES) -> list[str]:
    rows = [
        [_reused_cell(row, column) for column in reused.columns] for row in reused.rows
    ]
    return [
        *_notes_before(reused, notes),
        "; Type: Reused AVPs",
        f"; Section: {reused.source.section}",
        f"; Table: {reused.table}",
        *([f"; Page: {reused.source.page}"] if reused.source.page is not None else []),
        *_table(
            [column.value for column in reused.columns],
            rows,
            prefix="; Columns:",
            row_notes=[notes.get(id(row), ()) for row in reused.rows],
        ),
    ]


# Keyed by exact type, not matched by isinstance: a subclass of `Message`
# would otherwise be written out as a plain `Message`, silently dropping
# whatever it added, and `.dad` output has to be exact.
_FORMATTERS: dict[type, Callable[[Any, Notes], list[str]]] = {
    ast.Message: _format_message,
    ast.GroupedAvp: _format_grouped,
    ast.EnumeratedAvp: _format_enumerated,
    ast.AvpTable: _format_avp_table,
    ast.ReusedAvps: _format_reused,
}


def _format_section(section: ast.Section, notes: Notes) -> list[str]:
    formatter = _FORMATTERS.get(type(section))
    if formatter is None:
        raise TypeError(f"no formatter for {type(section).__name__}")
    return formatter(section, notes)


def format_spec(spec: ast.Specification, notes: Notes = _NO_NOTES) -> str:
    """Canonical text, optionally with `;;` notes marking particular nodes.

    A note trails the line its node produced; only a note for an edit that
    left no line (a deletion) stands as a whole line before its section.
    Notes are the one thing here that does not round-trip: the parser discards
    `;;` comments, so `format_spec(parse(annotated))` gives the same file
    without them. That is the intended relation — an annotated file is
    canonical output plus a reader's aid — and it is why notes are a caller's
    choice rather than part of the canonical form.
    """
    header = [f"; Specification: {spec.specification}"]
    if spec.version is not None:
        header.append(f"; Version: {spec.version}")
    header.append(f"; Vendor-ID: {spec.vendor_id}")
    if spec.link is not None:
        header.append(f"; Link: {spec.link}")

    parts = [header, *(_format_section(section, notes) for section in spec.sections)]
    return "\n\n\n".join("\n".join(part) for part in parts) + "\n"
