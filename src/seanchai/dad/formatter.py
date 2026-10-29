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
from typing import Any, NamedTuple

from . import abnf, ast

# Free-text notes to attach to the lines a tree produces, keyed by
# `ast.TreePath`; a note is a reader's aid and never data.
Notes = Mapping[ast.TreePath, Sequence[str]]
_NO_NOTES: Notes = {}


def _comment(note: str) -> str:
    # An empty note is a bare `;;`: a trailing space would not parse back.
    return f";; {note}" if note else ";;"


class Comments(NamedTuple):
    """The `;;` lines to print with a tree, by placement: a file's own
    comments from `parser.parse_with_comments`, or the notes
    `corrections.notes` marks edits with.

    Each is keyed by an `ast.TreePath`, and every line a tree produces has a
    path of its own — a directive line the path of the field it states
    (`("sections", 3, "source", "page")`), a header rule its section's path,
    a body line its item's — so every line can carry notes and none can take
    another's. `trailing` notes are appended to the line, `standing` ones
    printed as whole lines before it, and `detached` ones as a block of
    their own; `format_spec` says where each lands.
    """

    trailing: Notes = _NO_NOTES
    standing: Notes = _NO_NOTES
    detached: Notes = _NO_NOTES

    def line(self, text: str, path: ast.TreePath, indent: str = "") -> list[str]:
        """The line `path` printed, after its standing notes and with its
        trailing ones appended."""
        trailing = "".join(f" {_comment(note)}" for note in self.trailing.get(path, ()))
        return [*self.standing_at(path, indent), text + trailing]

    def standing_at(self, path: ast.TreePath, indent: str = "") -> list[str]:
        """Whole-line notes before the line at `path`, indented like the
        lines of the block they stand in: a whole-line comment, or the note
        of an edit that left no line to append to. A deletion's note prints
        in the deleted line's place — before the sibling that moved up into
        it, or after the last sibling when the path is one past the end,
        because the end is where that line stood."""
        return [indent + _comment(note) for note in self.standing.get(path, ())]

    def detached_at(self, path: ast.TreePath) -> list[str]:
        """The block of notes before the section at `path`."""
        return [_comment(note) for note in self.detached.get(path, ())]


_NO_COMMENTS = Comments()


_MIN_COLUMN_WIDTH = 3
_COLUMN_GAP = 3


def _avp_line(rule: ast.AvpRule) -> str:
    open_bracket, close_bracket = abnf.brackets_for(rule.presence)
    qualifier = abnf.qualifier(rule.min_occurs, rule.max_occurs)
    return f"{qualifier:>7} {open_bracket} {rule.name} {close_bracket}"


def _abnf_body(
    avps: tuple[ast.AvpRule, ...], path: ast.TreePath, notes: Comments
) -> list[str]:
    """`; bold` markers sit one column past the longest rule *of this section*.
    A file-wide column would make one added AVP reflow every marker in the
    file, and the review workflow lives on raw-vs-raw diffs."""
    rules = [(rule, _avp_line(rule)) for rule in avps]
    bold_column = max((len(line) for _, line in rules), default=0) + 1
    lines = []
    for index, (rule, line) in enumerate(rules):
        if rule.bold:
            line = f"{line:<{bold_column}}; bold"
        lines.extend(notes.line(line, (*path, "avps", index)))
    lines.extend(notes.standing_at((*path, "avps", len(rules))))
    return lines


def _directives(
    section: ast.Section, name: str | None, path: ast.TreePath, notes: Comments
) -> list[str]:
    """A section's directive lines, in canonical order. Only tables carry a
    `; Table:` caption and only definitions a `; Name:`."""
    lines = notes.line(f"; Type: {section.type}", (*path, "type"))
    if name is not None:
        lines.extend(notes.line(f"; Name: {name}", (*path, "name")))
    lines.extend(
        notes.line(f"; Section: {section.source.section}", (*path, "source", "section"))
    )
    if isinstance(section, ast.AvpTable | ast.ReusedAvps) and section.table is not None:
        lines.extend(notes.line(f"; Table: {section.table}", (*path, "table")))
    if section.source.page is not None:
        lines.extend(
            notes.line(f"; Page: {section.source.page}", (*path, "source", "page"))
        )
    return lines


def _table(
    headers: list[str],
    rows: list[list[str]],
    prefix: str,
    path: ast.TreePath,
    notes: Comments,
) -> list[str]:
    """`rows` are the cells of the rows at `path` + `("rows", i)`. Notes are
    appended *after* the column widths are computed, so annotating a row
    cannot reflow the table; standing notes print as whole lines above
    their row — where a deleted row used to be."""
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
    lines = notes.line(header_line, (*path, "columns"))
    for index, row in enumerate(rows):
        line = ""
        for cell, start in zip(row, starts, strict=True):
            line += " " * (start - len(line)) + cell
        lines.extend(notes.line(line, (*path, "rows", index)))
    lines.extend(notes.standing_at((*path, "rows", len(rows))))
    return lines


def _format_message(
    message: ast.Message, path: ast.TreePath, notes: Comments
) -> list[str]:
    header_items = abnf.diameter_header_items(
        message.command_code, message.flags, message.application_id
    )
    return [
        *_directives(message, f"{message.name}, {message.abbreviation}", path, notes),
        # Section-level notes trail the header rule: it is the line that
        # carries the fields a correction to the section itself can touch.
        *notes.line(f"<{message.name}> ::= < Diameter Header: {header_items} >", path),
        *_abnf_body(message.avps, path, notes),
    ]


def _avp_header_items(code: int, vendor_id: int | None) -> str:
    return str(code) if vendor_id is None else f"{code} {vendor_id}"


def _format_grouped(
    avp: ast.GroupedAvp, path: ast.TreePath, notes: Comments
) -> list[str]:
    return [
        *_directives(avp, avp.name, path, notes),
        *notes.line(
            f"{avp.name} ::= < AVP header:"
            f" {_avp_header_items(avp.code, avp.vendor_id)} >",
            path,
        ),
        *_abnf_body(avp.avps, path, notes),
    ]


def _format_enumerated(
    avp: ast.EnumeratedAvp, path: ast.TreePath, notes: Comments
) -> list[str]:
    width = max(
        (
            len(value.name) if isinstance(value, ast.EnumValue) else len("RESERVED")
            for value in avp.values
        ),
        default=0,
    )
    lines = [
        *_directives(avp, avp.name, path, notes),
        *notes.line(
            f"{avp.name} ::= < Enumerated AVP header:"
            f" {_avp_header_items(avp.code, avp.vendor_id)} >",
            path,
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
    for index, value in enumerate(avp.values):
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
        lines.extend(notes.line(line, (*path, "values", index), indent=" " * 8))
    lines.extend(notes.standing_at((*path, "values", len(avp.values)), " " * 8))
    return lines


def avp_table_cell(row: ast.AvpTableRow, column: ast.AvpColumn) -> str:
    """One modelled cell, with `-` as the canonical empty. Meaningful only for
    columns the row's table declares, where a None is an empty source cell."""
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


def _format_avp_table(
    table: ast.AvpTable, path: ast.TreePath, notes: Comments
) -> list[str]:
    rows = [
        [avp_table_cell(row, column) for column in table.columns] for row in table.rows
    ]
    return [
        *_directives(table, None, path, notes),
        *_table(
            [column.value for column in table.columns], rows, "; Columns:", path, notes
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


def _format_reused(
    reused: ast.ReusedAvps, path: ast.TreePath, notes: Comments
) -> list[str]:
    rows = [
        [_reused_cell(row, column) for column in reused.columns] for row in reused.rows
    ]
    return [
        *_directives(reused, None, path, notes),
        *_table(
            [column.value for column in reused.columns], rows, "; Columns:", path, notes
        ),
    ]


# Keyed by exact type, not matched by isinstance: a subclass of `Message`
# would otherwise be written out as a plain `Message`, silently dropping
# whatever it added, and `.dad` output has to be exact.
_FORMATTERS: dict[type, Callable[[Any, ast.TreePath, Comments], list[str]]] = {
    ast.Message: _format_message,
    ast.GroupedAvp: _format_grouped,
    ast.EnumeratedAvp: _format_enumerated,
    ast.AvpTable: _format_avp_table,
    ast.ReusedAvps: _format_reused,
}


def _format_section(
    section: ast.Section, path: ast.TreePath, notes: Comments
) -> list[str]:
    formatter = _FORMATTERS.get(type(section))
    if formatter is None:
        raise TypeError(f"no formatter for {type(section).__name__}")
    return formatter(section, path, notes)


def format_spec(spec: ast.Specification, comments: Comments = _NO_COMMENTS) -> str:
    """Canonical text, optionally with `;;` comments on particular lines.

    Every comment is keyed by an `ast.TreePath`, and every line has a path of
    its own (see `Comments`). A `trailing` comment trails the line its path
    printed. A `standing` one is a whole line printed *before* that line —
    the shape a deletion needs, keyed by the position the deleted node stood
    in, so the note reads in the deleted line's place. A position one past a
    body's last item prints after it, and the root path `()` after the file
    header's lines. A `detached` one is a block of its own, spaced from its
    neighbours like the section it replaces — the shape a deleted
    *section's* note needs, keyed by the section position that follows the
    gap (one past the last section when the last one went): glued to the
    next section's lines it would read as being about that section. A
    `detached` comment at `()` is a block before the file header.

    `parse(text)` discards comments, so `format_spec(parse(text))` gives the
    file without them, while `parse_with_comments` keeps them:

        spec, comments = parse_with_comments(text)
        format_spec(spec, comments)  # the file back, comments in place

    Comments are a caller's choice rather than part of the canonical form,
    because the canonical form is what the parser reads.
    """
    header = [
        *comments.line(f"; Specification: {spec.specification}", ("specification",))
    ]
    if spec.version is not None:
        header.extend(comments.line(f"; Version: {spec.version}", ("version",)))
    header.extend(comments.line(f"; Vendor-ID: {spec.vendor_id}", ("vendor_id",)))
    if spec.bases:
        header.extend(comments.line(f"; Bases: {', '.join(spec.bases)}", ("bases",)))
    if spec.link is not None:
        header.extend(comments.line(f"; Link: {spec.link}", ("link",)))
    header.extend(comments.standing_at(()))

    parts = [comments.detached_at(()), header]
    for index, section in enumerate(spec.sections):
        parts.append(comments.detached_at(("sections", index)))
        parts.append(_format_section(section, ("sections", index), comments))
    parts.append(comments.detached_at(("sections", len(spec.sections))))
    return "\n\n\n".join("\n".join(part) for part in parts if part) + "\n"
