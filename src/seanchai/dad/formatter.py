"""Canonical formatter: AST → `.dad` text.

`format_spec(parse(text))` must be idempotent — the patch-based review workflow
depends on stable diffs. Canonical rules:

- sections separated by two blank lines; file ends with one newline;
- ABNF bodies: 8-space indent with the repetition qualifier right-aligned in
  front of it; `; bold` and `; strikethrough` markers aligned one column past
  the longest ABNF body line of their own section;
- enum bodies: a value name quoted exactly when it is not an identifier,
  with `"` and backslash escaped inside the quotes, `=` aligned per section
  (RESERVED and VENDOR-SPECIFIC count as names), a range's description
  one space past its numbers;
- tables: columns split by 3 spaces, each as wide as its widest cell or
  label (minimum 3), so labels sit at column starts. Both table kinds write
  their labels as a `; Columns:` directive, so the first label follows the
  directive, its column wide enough for both, and every later one lines up
  with its data. A mark column's cell quotes a mark that is not a plain
  token, as enum bodies quote names, and writes `""` for a blank cell.
- registries: a table, its text cells quoted as marks are and `-` for a
  blank cell; a reserved range is a `; RESERVED a..b` line among the rows,
  at column 0 and widening no column, its purpose always quoted.
- value tables: names at column 0, quoted as enum bodies quote them, `=` and
  a row's `;` aligned per section.
"""

import re
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


def avp_line(rule: ast.AvpRule) -> str:
    open_bracket, close_bracket = abnf.brackets_for(rule.presence)
    qualifier = abnf.qualifier(rule.min_occurs, rule.max_occurs)
    return f"{qualifier:>7} {open_bracket} {rule.name} {close_bracket}"


def _marker_column(avps: Sequence[ast.AvpRule]) -> int:
    """`; bold` and `; strikethrough` sit one column past the longest rule
    *of this section*. A file-wide column would make one added AVP reflow
    every marker in the file, and the review workflow lives on raw-vs-raw
    diffs."""
    return max((len(avp_line(rule)) for rule in avps), default=0) + 1


def _marked(rule: ast.AvpRule, column: int) -> str:
    """A rule's line with its markers at `column`, `; bold` first when the
    source both bolds and strikes a member."""
    line = avp_line(rule)
    markers = [
        f"; {marker}"
        for marker, present in (
            ("bold", rule.bold),
            ("strikethrough", rule.strikethrough),
        )
        if present
    ]
    return f"{line:<{column}}{' '.join(markers)}" if markers else line


def commented_avp_rule(rule: ast.AvpRule, avps: Sequence[ast.AvpRule]) -> str:
    """The note that stands, as a `;;` line, for `rule` commented out of an
    ABNF body: the line it would print there, its markers at the column
    `avps` would put them in, less the three columns `;; ` takes, so that its
    brackets line up with the members'. TS 32.299's struck members are
    written so (`struck-rules-unused`)."""
    line = _marked(rule, max(_marker_column(avps), len(avp_line(rule)) + 1))
    return line[3:] if line.startswith("   ") else line.lstrip()


def _abnf_body(
    avps: tuple[ast.AvpRule, ...], path: ast.TreePath, notes: Comments
) -> list[str]:
    column = _marker_column(avps)
    lines = []
    for index, rule in enumerate(avps):
        lines.extend(notes.line(_marked(rule, column), (*path, "avps", index)))
    lines.extend(notes.standing_at((*path, "avps", len(avps))))
    return lines


def _directives(
    section: ast.Section, name: str | None, path: ast.TreePath, notes: Comments
) -> list[str]:
    """A section's directive lines, in canonical order. Only tables carry a
    `; Table:` caption, only definitions a `; Name:`, and only an
    enumerated AVP a `; Values:`."""
    lines = notes.line(f"; Type: {section.type}", (*path, "type"))
    if isinstance(section, ast.Registry):
        lines.extend(notes.line(f"; Registry: {section.registry}", (*path, "registry")))
    if isinstance(section, ast.ValueTable):
        lines.extend(notes.line(f"; AVP: {section.avp}", (*path, "avp")))
        lines.extend(notes.line(f"; Kind: {section.kind}", (*path, "kind")))
        if section.feature_list_id is not None:
            lines.extend(
                notes.line(
                    f"; Feature-List-ID: {section.feature_list_id}",
                    (*path, "feature_list_id"),
                )
            )
        if section.application is not None:
            lines.extend(
                notes.line(
                    f"; Application: {section.application}", (*path, "application")
                )
            )
    if name is not None:
        lines.extend(notes.line(f"; Name: {name}", (*path, "name")))
    lines.extend(
        notes.line(f"; Section: {section.source.section}", (*path, "source", "section"))
    )
    if (
        isinstance(
            section, ast.AvpTable | ast.ReusedAvps | ast.Registry | ast.ValueTable
        )
        and section.table is not None
    ):
        lines.extend(notes.line(f"; Table: {section.table}", (*path, "table")))
    if section.source.page is not None:
        lines.extend(
            notes.line(f"; Page: {section.source.page}", (*path, "source", "page"))
        )
    if isinstance(section, ast.EnumeratedAvp) and section.values_source is not None:
        lines.extend(
            notes.line(f"; Values: {section.values_source}", (*path, "values_source"))
        )
    return lines


def _table(
    headers: list[str],
    rows: Sequence[list[str] | str],
    prefix: str,
    path: ast.TreePath,
    notes: Comments,
) -> list[str]:
    """`rows` are the cells of the rows at `path` + `("rows", i)`, or a line
    printed as it is (a registry's reserved range), which no column is
    widened for. Notes are appended *after* the column widths are computed,
    so annotating a row cannot reflow the table; standing notes print as
    whole lines above their row — where a deleted row used to be."""
    cells = [row for row in rows if not isinstance(row, str)]
    # A label counts toward its column's width, so every label sits at its
    # column's start; the first follows the directive, which it overruns.
    widths = [
        max(
            _MIN_COLUMN_WIDTH,
            len(header) + (len(prefix) + 1 if i == 0 else 0),
            max((len(row[i]) for row in cells), default=0),
        )
        for i, header in enumerate(headers)
    ]
    starts = [0]
    for width in widths[:-1]:
        starts.append(starts[-1] + width + _COLUMN_GAP)

    header_line = prefix
    for header, start in zip(headers, starts, strict=True):
        header_line += " " * max(start - len(header_line), 1) + header
    lines = notes.line(header_line, (*path, "columns"))
    for index, row in enumerate(rows):
        if isinstance(row, str):
            line = row
        else:
            line = ""
            for cell, start in zip(row, starts, strict=True):
                line += " " * (start - len(line)) + cell
        lines.extend(notes.line(line, (*path, "rows", index)))
    lines.extend(notes.standing_at((*path, "rows", len(rows))))
    return lines


def _format_application_scope(
    application: ast.ApplicationScope, path: ast.TreePath, notes: Comments
) -> list[str]:
    return [
        *_directives(application, application.name, path, notes),
        *notes.line(
            f"; Application-ID: {application.application_id}",
            (*path, "application_id"),
        ),
        *notes.line(
            f"; Applies-To: {', '.join(application.applies_to)}",
            (*path, "applies_to"),
        ),
        # No line states the block as a whole, so its own path is its end.
        *notes.standing_at(path),
    ]


def _format_undefined_avp(
    undefined: ast.UndefinedAvp, path: ast.TreePath, notes: Comments
) -> list[str]:
    lines = _directives(undefined, undefined.name, path, notes)
    if undefined.note is not None:
        lines.extend(notes.line(f"; Note: {undefined.note}", (*path, "note")))
    # No line states the block as a whole, so its own path is its end.
    lines.extend(notes.standing_at(path))
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


def _format_reprinted(
    avp: ast.ReprintedAvp, path: ast.TreePath, notes: Comments
) -> list[str]:
    return [
        *_directives(avp, avp.name, path, notes),
        *notes.line(f"; From: {avp.origin}", (*path, "origin")),
        *notes.line(
            f"{avp.name} ::= < AVP header:"
            f" {_avp_header_items(avp.code, avp.vendor_id)} >",
            path,
        ),
        *_abnf_body(avp.avps, path, notes),
    ]


_IDENTIFIER_RE = re.compile(ast.AVP_NAME_PATTERN)


def value_name(name: str) -> str:
    """A value name as a file spells it: quoted exactly when it is not an
    identifier, so each name has one spelling, and inside the quotes a
    backslash and `"` escaped, the only two characters that are."""
    if _IDENTIFIER_RE.fullmatch(name):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _range_keyword(value: ast.ReservedValues | ast.VendorSpecificValues) -> str:
    if isinstance(value, ast.ReservedValues):
        return "RESERVED"
    return "VENDOR-SPECIFIC"


def _format_enumerated(
    avp: ast.EnumeratedAvp, path: ast.TreePath, notes: Comments
) -> list[str]:
    width = max(
        (
            len(value_name(value.name))
            if isinstance(value, ast.EnumValue)
            else len(_range_keyword(value))
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
            name = value_name(value.name)
            line = f"        {name:<{width}} = {value.value:<{value_width}}"
            if value.description is not None:
                line += f" ; {value.description}"
            line = line.rstrip()
        else:
            numbers = (
                str(value.first)
                if value.first == value.last
                else f"{value.first}-{value.last}"
            )
            line = f"      ; {_range_keyword(value):<{width}} = {numbers}"
            if (
                isinstance(value, ast.VendorSpecificValues)
                and value.description is not None
            ):
                line += f" ; {value.description}"
        lines.extend(notes.line(line, (*path, "values", index), indent=" " * 8))
    lines.extend(notes.standing_at((*path, "values", len(avp.values)), " " * 8))
    return lines


def avp_table_cell(row: ast.AvpTableRow, column: ast.AvpColumn) -> str:
    """One modelled cell, with `-` as the canonical empty. Meaningful only for
    columns the row's table declares, where a None is an empty source cell."""
    match column:
        case ast.AvpColumn.NAME:
            return row.name
        case ast.AvpColumn.VENDOR:
            return "-" if row.vendor_id is None else str(row.vendor_id)
        case ast.AvpColumn.CODE:
            return "-" if row.code is None else str(row.code)
        case ast.AvpColumn.SECTION:
            return "-" if row.section is None else row.section
        case ast.AvpColumn.TYPE if row.printed_type is not None:
            # Always quoted: bare, a Type cell is a Diameter data type.
            return _quoted(row.printed_type)
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
        case _:
            return marks_cell(row.marks, column)


# A mark a cell writes bare: no space, comma, semicolon, quote or backslash.
_PLAIN_MARK_RE = re.compile(r'[^\s,;"\\]+')

# The cell of a mark column the source left blank: an empty quoted mark,
# which no mark can be.
BLANK_CELL = '""'


def marks_cell(marks: ast.Marks, column: ast.AvpColumn | ast.ReusedColumn) -> str:
    """A `MarkColumn` cell: the row's marks joined by commas, each quoted
    exactly when it is not a plain token; `-` for a printed dash and `""`
    for a blank cell."""
    marked = ast.mark_column(column)
    assert marked is not None, f"{column.value} is no mark column"
    if marked not in marks:
        return BLANK_CELL
    return ",".join(map(_mark, marks[marked])) or "-"


def _mark(mark: str) -> str:
    if _PLAIN_MARK_RE.fullmatch(mark) and mark != "-":
        return mark
    escaped = mark.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
        case ast.ReusedColumn.CODE:
            return "-" if row.code is None else str(row.code)
        case ast.ReusedColumn.TYPE:
            return "-" if row.data_type is None else row.data_type.value
        case _:
            return marks_cell(row.marks, column)


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


def _text(text: str | None) -> str:
    """A registry text cell, quoted as a mark is; `-` for a blank one."""
    return "-" if text is None else _mark(text)


def _documents(documents: tuple[str, ...]) -> str:
    return ",".join(documents) or "-"


def _registry_cell(row: ast.RegistryRow, column: ast.RegistryColumn) -> str:
    match column:
        case ast.RegistryColumn.CODE:
            return str(row.code)
        case ast.RegistryColumn.NAME:
            return _text(row.name)
        case ast.RegistryColumn.ABBREVIATION:
            return _text(row.abbreviation)
        case ast.RegistryColumn.TYPE if row.printed_type is not None:
            # Always quoted, even a plain token: bare, a Type cell is a
            # Diameter data type.
            return _quoted(row.printed_type)
        case ast.RegistryColumn.TYPE:
            return "-" if row.data_type is None else row.data_type.value
        case ast.RegistryColumn.DEFINED_IN:
            return _documents(row.defined_in)


def _reservation(reservation: ast.RegistryReservation) -> str:
    """`; RESERVED 320..399 TS29.234 "TS 29.234"`: the purpose always
    quoted, so it cannot be read as the documents."""
    line = f"; RESERVED {reservation.first}..{reservation.last}"
    if reservation.defined_in:
        line += f" {_documents(reservation.defined_in)}"
    if reservation.purpose is not None:
        line += f" {_quoted(reservation.purpose)}"
    return line


def _quoted(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_registry(
    registry: ast.Registry, path: ast.TreePath, notes: Comments
) -> list[str]:
    rows = [
        _reservation(row)
        if isinstance(row, ast.RegistryReservation)
        else [_registry_cell(row, column) for column in registry.columns]
        for row in registry.rows
    ]
    return [
        *_directives(registry, None, path, notes),
        *_table(
            [column.value for column in registry.columns],
            rows,
            "; Columns:",
            path,
            notes,
        ),
    ]


def _format_value_table(
    table: ast.ValueTable, path: ast.TreePath, notes: Comments
) -> list[str]:
    width = max(len(value_name(row.name)) for row in table.rows)
    value_width = max(len(str(row.value)) for row in table.rows)
    lines = _directives(table, None, path, notes)
    for index, row in enumerate(table.rows):
        line = f"{value_name(row.name):<{width}} = {row.value:<{value_width}}"
        if row.section is not None:
            line += f" ; {row.section}"
        elif row.mark is not None:
            line += f" ; {_mark(row.mark)}"
        lines.extend(notes.line(line.rstrip(), (*path, "rows", index)))
    lines.extend(notes.standing_at((*path, "rows", len(table.rows))))
    return lines


# Keyed by exact type, not matched by isinstance: a subclass of `Message`
# would otherwise be written out as a plain `Message`, silently dropping
# whatever it added, and `.dad` output has to be exact.
_FORMATTERS: dict[type, Callable[[Any, ast.TreePath, Comments], list[str]]] = {
    ast.ApplicationScope: _format_application_scope,
    ast.Message: _format_message,
    ast.GroupedAvp: _format_grouped,
    ast.ReprintedAvp: _format_reprinted,
    ast.EnumeratedAvp: _format_enumerated,
    ast.AvpTable: _format_avp_table,
    ast.ReusedAvps: _format_reused,
    ast.Registry: _format_registry,
    ast.UndefinedAvp: _format_undefined_avp,
    ast.ValueTable: _format_value_table,
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
    if spec.transcribed is not None:
        header.extend(
            comments.line(
                f"; Transcribed: by hand from {spec.transcribed}", ("transcribed",)
            )
        )
    header.extend(comments.standing_at(()))

    parts = [comments.detached_at(()), header]
    for index, section in enumerate(spec.sections):
        parts.append(comments.detached_at(("sections", index)))
        parts.append(_format_section(section, ("sections", index), comments))
    parts.append(comments.detached_at(("sections", len(spec.sections))))
    return "\n\n\n".join("\n".join(part) for part in parts if part) + "\n"
