"""Line-oriented parser for the `.dad` format, producing the `ast` tree.

One pass splits the file into blocks of contiguous lines (the file header,
then one per section); a parser per `; Type:` reads each body. A malformed
`; ...` directive is a parse error. `parse` drops `;;` comments;
`parse_with_comments` returns them keyed by where they attach, for
`formatter.format_spec` to print back.
"""

import contextlib
import enum
import re
from collections.abc import Mapping
from typing import NamedTuple

import pydantic

from ..errors import SeanchaiError
from . import abnf, ast, formatter

__all__ = [
    "DadParseError",
    "Layout",
    "Placement",
    "avp_rule_line",
    "parse",
    "parse_interpretations",
    "parse_interpretations_with_comments",
    "parse_with_comments",
    "parse_with_layout",
]

# Keys carry hyphens (`; Vendor-ID:`), so the charset is wider than letters.
# `; RESERVED = n`, `; VOID = n` and `; VENDOR-SPECIFIC = n` use `=` rather than
# `:` and so are not a match either way.
_DIRECTIVE_RE = re.compile(r"^; (?P<key>[A-Za-z][A-Za-z-]*): (?P<value>.*)$")
_MESSAGE_HEADER_RE = re.compile(
    r"^<(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)> ::= "
    r"< Diameter Header: (?P<items>[0-9A-Z, ]+) >$"
)
_AVP_HEADER_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*) ::= "
    r"< (?P<kind>AVP|Enumerated AVP) header: (?P<code>\d+)(?: (?P<vendor>\d+))? >$"
)
_AVP_RULE_RE = re.compile(
    r"^\s*(?:(?P<min>\d*)\*(?P<max>\d*)\s*)?"
    r"(?P<open>[<{\[]) (?P<name>[A-Za-z0-9][A-Za-z0-9_-]*) (?P<close>[>}\]])"
    r"(?P<bold>\s*; bold)?(?P<strikethrough>\s*; strikethrough)?\s*$"
)
# A name is an identifier or a quoted string ("Virtual Private Network
# (VPN)"), inside which `\"` is a double quote and `\\` a backslash and
# nothing else is escapable, so a backslash before any other character, or
# before the closing quote, leaves the line no value line. Past that,
# `ast.EnumValueName` decides what the quotes may hold.
_ENUM_VALUE_RE = re.compile(
    r'^\s*(?:(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)|"(?P<quoted>(?:[^"\\]|\\["\\])*)")'
    r"\s*= (?P<value>\d+)"
    r"(?:\s+; (?P<description>\S.*))?$"
)
_ESCAPE_RE = re.compile(r'\\(["\\])')
_RESERVED_RE = re.compile(r"^\s*; RESERVED\s*= (?P<first>\d+)(?:-(?P<last>\d+))?$")
_VOID_RE = re.compile(r"^\s*; VOID\s*= (?P<first>\d+)(?:-(?P<last>\d+))?$")
# What the source calls the range follows as a value's description does.
_VENDOR_SPECIFIC_RE = re.compile(
    r"^\s*; VENDOR-SPECIFIC\s*= (?P<first>\d+)(?:-(?P<last>\d+))?"
    r"(?:\s+; (?P<description>\S.*))?$"
)

# The file header's fields belong to three separate lines, so they are checked
# one directive at a time rather than by constructing the model.
_VERSION = pydantic.TypeAdapter(ast.Version)
_INLINE_TEXT = pydantic.TypeAdapter(ast.InlineText)
_UNSIGNED32 = pydantic.TypeAdapter(ast.Unsigned32)
_SPEC_REF = pydantic.TypeAdapter(ast.SpecRef)
_SECTION_NUMBER = pydantic.TypeAdapter(ast.SectionNumber)
_VERSIONS_TEXT = pydantic.TypeAdapter(ast.VersionsText)


class DadParseError(SeanchaiError, ValueError):
    def __init__(self, lineno: int, message: str):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno


class _Block:
    """Contiguous non-blank lines with their 1-based line numbers."""

    def __init__(self, lines: list[tuple[int, str]]):
        self.lines = lines

    @property
    def start(self) -> int:
        return self.lines[0][0]


class _Line(NamedTuple):
    lineno: int
    # The line without its comment; empty for a line that is all comment.
    content: str
    # What follows `;;` and one space, or None for a line without a comment.
    comment: str | None


def _runs(text: str) -> list[list[_Line]]:
    """The file's lines between blank lines. A line that is all comment is
    not blank, so it belongs to the run it sits in."""
    runs: list[list[_Line]] = []
    current: list[_Line] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.rstrip() != line:
            raise DadParseError(lineno, "trailing whitespace")
        if not line:
            if current:
                runs.append(current)
                current = []
            continue
        # Everything from the first `;;` to the end of the line is comment;
        # inline values cannot contain `;;` (the AST rejects it), so nothing
        # meaningful is ever cut.
        comment = line.find(";;")
        if comment == -1:
            current.append(_Line(lineno, line, None))
        else:
            current.append(
                _Line(
                    lineno,
                    line[:comment].rstrip(),
                    line[comment + 2 :].removeprefix(" "),
                )
            )
    if current:
        runs.append(current)
    return runs


def _blocks(runs: list[list[_Line]]) -> list[_Block]:
    """The runs' content lines. A line left empty by its comment is skipped
    rather than treated as the blank line that separates blocks, so a run of
    nothing but comments is no block at all."""
    blocks = [
        [(line.lineno, line.content) for line in run if line.content] for run in runs
    ]
    return [_Block(lines) for lines in blocks if lines]


class _Directive(NamedTuple):
    """A directive's value with its line number, so an error can point at it."""

    lineno: int
    value: str


_Directives = dict[str, _Directive]


def _split_directives(block: _Block) -> tuple[_Directives, list[tuple[int, str]]]:
    """Leading `; Key: value` lines of a block, then the remaining body lines."""
    directives: _Directives = {}
    body = list(block.lines)
    while body:
        lineno, line = body[0]
        match = _DIRECTIVE_RE.match(line)
        if match is None:
            break
        key = match["key"]
        if key == "RESERVED":  # inline directive, belongs to the body
            break
        if key in directives:
            raise DadParseError(lineno, f"duplicate directive {key!r}")
        directives[key] = _Directive(lineno, match["value"])
        body.pop(0)
    return directives, body


def _pop(directives: _Directives, key: str, lineno: int) -> _Directive:
    try:
        return directives.pop(key)
    except KeyError:
        raise DadParseError(lineno, f"missing directive {key!r}") from None


def _no_leftovers(directives: _Directives, lineno: int) -> None:
    if directives:
        raise DadParseError(lineno, f"unexpected directives: {sorted(directives)}")


@contextlib.contextmanager
def _validated(lineno: int):
    """Re-raise the AST's pydantic validation errors as `DadParseError`
    with a line number.
    """
    try:
        yield
    except pydantic.ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
            for problem in error.errors()
        )
        raise DadParseError(lineno, problems) from None


def _number(text: str, lineno: int, label: str) -> int:
    # `int()` alone would also take `+1`, `1_000`, surrounding whitespace and
    # non-ASCII digits, silently normalising text the grammar (`1*DIGIT`)
    # rejects; the file must spell the number the way it is printed back.
    if not _ASCII_DIGITS.fullmatch(text):
        raise DadParseError(lineno, f"{label} must be a number, got {text!r}")
    return int(text)


_ASCII_DIGITS = re.compile(r"[0-9]+")


def _source_ref(directives: _Directives, lineno: int) -> ast.SourceRef:
    section = _pop(directives, "Section", lineno)
    page = directives.pop("Page", None)
    # Two constructions rather than one, so each directive's own line reports
    # its own value: with `; Section:` already known good, anything the second
    # rejects came from `; Page:`.
    with _validated(section.lineno):
        reference = ast.SourceRef(section=section.value)
    if page is None:
        return reference
    with _validated(page.lineno):
        return ast.SourceRef(
            section=section.value, page=_number(page.value, page.lineno, "Page")
        )


def _avp_rules(body: list[tuple[int, str]]) -> tuple[ast.AvpRule, ...]:
    rules = []
    for lineno, line in body:
        match = _AVP_RULE_RE.match(line)
        if match is None:
            raise DadParseError(lineno, f"malformed AVP rule: {line.strip()!r}")
        try:
            with _validated(lineno):
                rules.append(
                    abnf.avp_rule(
                        match,
                        bold=match["bold"] is not None,
                        strikethrough=match["strikethrough"] is not None,
                    )
                )
        except abnf.AbnfError as error:
            raise DadParseError(lineno, str(error)) from None
    return tuple(rules)


def _parse_message(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.Message:
    name_directive = _pop(directives, "Name", lineno)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    try:
        name, abbreviation = (part.strip() for part in name_directive.value.split(","))
    except ValueError:
        raise DadParseError(
            name_directive.lineno, "message Name must be 'Long-Name, ABBR'"
        ) from None
    if not body:
        raise DadParseError(lineno, "message has no body")
    header_lineno, header = body[0]
    match = _MESSAGE_HEADER_RE.match(header)
    if match is None:
        raise DadParseError(header_lineno, f"malformed Diameter header: {header!r}")
    if match["name"] != name:
        raise DadParseError(
            header_lineno,
            f"Name directive {name!r} != rule name {match['name']!r}",
        )
    try:
        command_code, flags, application_id = abnf.diameter_header(match["items"])
    except abnf.AbnfError as error:
        raise DadParseError(header_lineno, str(error)) from None
    avps = _avp_rules(body[1:])
    with _validated(name_directive.lineno):
        return ast.Message(
            name=name,
            abbreviation=abbreviation,
            source=source,
            command_code=command_code,
            flags=flags,
            application_id=application_id,
            avps=avps,
        )


def _parse_answer_message(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.AnswerMessage:
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    if not body:
        raise DadParseError(lineno, "answer message has no body")
    header_lineno, header = body[0]
    if header != abnf.ANSWER_MESSAGE_RULE:
        raise DadParseError(
            header_lineno,
            f"malformed answer-message rule: {header!r}"
            f" (expected {abnf.ANSWER_MESSAGE_RULE!r})",
        )
    avps = _avp_rules(body[1:])
    with _validated(lineno):
        return ast.AnswerMessage(source=source, avps=avps)


def _parse_application_scope(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.ApplicationScope:
    name = _pop(directives, "Name", lineno)
    source = _source_ref(directives, lineno)
    application_id = _pop(directives, "Application-ID", lineno)
    applies_to = _pop(directives, "Applies-To", lineno)
    _no_leftovers(directives, lineno)
    # Every line of the block is a directive: the statement is the clause's
    # prose, which has no rule to mirror.
    if body:
        raise DadParseError(body[0][0], "unexpected content in application scope")
    with _validated(name.lineno):
        _INLINE_TEXT.validate_python(name.value)
    number = _number(application_id.value, application_id.lineno, "Application-ID")
    with _validated(application_id.lineno):
        _UNSIGNED32.validate_python(number)
    clauses = tuple(part.strip() for part in applies_to.value.split(","))
    for clause in clauses:
        # A bare clause is reserved for that clause alone, which nothing
        # reads yet; said here rather than as a pattern mismatch.
        if not clause.endswith(".*"):
            raise DadParseError(
                applies_to.lineno,
                f"Applies-To entry {clause!r} names no subclauses"
                f" (write {clause + '.*'!r} for the clause and its subclauses)",
            )
    with _validated(applies_to.lineno):
        return ast.ApplicationScope(
            name=name.value,
            source=source,
            application_id=number,
            applies_to=clauses,
        )


def _parse_undefined_avp(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.UndefinedAvp:
    name = _pop(directives, "Name", lineno)
    source = _source_ref(directives, lineno)
    # Optional: absent where the document says nothing of the name beyond
    # its ABNF.
    note = directives.pop("Note", None)
    _no_leftovers(directives, lineno)
    # The block states a finding, not a rule: nothing follows its directives.
    if body:
        raise DadParseError(body[0][0], "unexpected content in undefined AVP")
    if note is not None:
        with _validated(note.lineno):
            _INLINE_TEXT.validate_python(note.value)
    with _validated(name.lineno):
        return ast.UndefinedAvp(
            name=name.value,
            source=source,
            note=None if note is None else note.value,
        )


def _avp_header(
    body: list[tuple[int, str]], expected_kind: str, lineno: int
) -> tuple[str, int, int | None]:
    if not body:
        raise DadParseError(lineno, "section has no body")
    header_lineno, header = body[0]
    match = _AVP_HEADER_RE.match(header)
    if match is None or match["kind"] != expected_kind:
        raise DadParseError(
            header_lineno, f"malformed {expected_kind} header: {header!r}"
        )
    vendor = match["vendor"]
    return match["name"], int(match["code"]), None if vendor is None else int(vendor)


def _parse_grouped(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.GroupedAvp:
    name = _pop(directives, "Name", lineno)
    source = _source_ref(directives, lineno)
    # Optional: only a rule the clause says it copies names the document.
    reprints = directives.pop("Reprints", None)
    _no_leftovers(directives, lineno)
    header_name, code, vendor_id = _avp_header(body, "AVP", lineno)
    if header_name != name.value:
        raise DadParseError(
            body[0][0], f"Name directive {name.value!r} != rule name {header_name!r}"
        )
    avps = _avp_rules(body[1:])
    if reprints is not None:
        with _validated(reprints.lineno):
            _SPEC_REF.validate_python(reprints.value)
    with _validated(name.lineno):
        return ast.GroupedAvp(
            name=name.value,
            source=source,
            reprints=None if reprints is None else reprints.value,
            code=code,
            vendor_id=vendor_id,
            avps=avps,
        )


def _parse_enumerated(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.EnumeratedAvp:
    name = _pop(directives, "Name", lineno)
    source = _source_ref(directives, lineno)
    # Optional: present only where the clause says its values are defined
    # in another document or clause.
    values_source = directives.pop("Values", None)
    _no_leftovers(directives, lineno)
    header_name, code, vendor_id = _avp_header(body, "Enumerated AVP", lineno)
    if header_name != name.value:
        raise DadParseError(
            body[0][0], f"Name directive {name.value!r} != rule name {header_name!r}"
        )
    values: list[ast.EnumEntry] = []
    for value_lineno, line in body[1:]:
        with _validated(value_lineno):
            if match := _RESERVED_RE.match(line):
                first = int(match["first"])
                last = int(match["last"]) if match["last"] else first
                values.append(ast.ReservedValues(first=first, last=last))
            elif match := _VOID_RE.match(line):
                first = int(match["first"])
                last = int(match["last"]) if match["last"] else first
                values.append(ast.VoidValues(first=first, last=last))
            elif match := _VENDOR_SPECIFIC_RE.match(line):
                first = int(match["first"])
                last = int(match["last"]) if match["last"] else first
                values.append(
                    ast.VendorSpecificValues(
                        first=first, last=last, description=match["description"]
                    )
                )
            elif match := _ENUM_VALUE_RE.match(line):
                values.append(
                    ast.EnumValue(
                        name=match["name"] or _ESCAPE_RE.sub(r"\1", match["quoted"]),
                        value=int(match["value"]),
                        description=match["description"],
                    )
                )
            else:
                raise DadParseError(
                    value_lineno, f"malformed enum value: {line.strip()!r}"
                )
    if values_source is not None:
        with _validated(values_source.lineno):
            _INLINE_TEXT.validate_python(values_source.value)
    with _validated(name.lineno):
        return ast.EnumeratedAvp(
            name=name.value,
            source=source,
            code=code,
            vendor_id=vendor_id,
            values_source=None if values_source is None else values_source.value,
            values=tuple(values),
        )


# A table cell: a run of non-space characters, of which a quoted string,
# a mark that is not a plain token, may hold spaces (`"All (NOTE 5)"`).
_QUOTED = r'"(?:[^"\\]|\\["\\])*"'
_CELL_RE = re.compile(rf'(?:{_QUOTED}|[^\s"])+')
_ROW_RE = re.compile(rf"\s*{_CELL_RE.pattern}(?:\s+{_CELL_RE.pattern})*\s*")
# A mark cell's list: plain or quoted marks, separated by commas.
_MARK_RE = re.compile(rf'{_QUOTED}|[^\s,;"\\]+')
_MARKS_RE = re.compile(rf"(?:{_MARK_RE.pattern})(?:,(?:{_MARK_RE.pattern}))*")


def _cells(body: list[tuple[int, str]], count: int):
    for lineno, line in body:
        if not _ROW_RE.fullmatch(line):
            raise DadParseError(lineno, f"malformed table row: {line.strip()!r}")
        cells = _CELL_RE.findall(line)
        if len(cells) != count:
            raise DadParseError(lineno, f"expected {count} columns, got {len(cells)}")
        yield lineno, cells


def _columns[T: enum.StrEnum](
    directive: _Directive, known: type[T], marks: bool = True
) -> tuple[T | str, ...]:
    """The `; Columns:` directive: which columns the source table had, and in
    which order. Only modelled columns appear — see `ast._check_columns`. A
    token that is none of `known` is a mark column (`ast.MarkColumn`) where
    the table kind has them (`marks`)."""
    columns: list[T | str] = []
    for token in directive.value.split():
        if token in known:
            columns.append(known(token))
            continue
        if marks and _MARK_COLUMN_RE.fullmatch(token):
            with _validated(directive.lineno):
                columns.append(_MARK_COLUMN.validate_python(token))
            continue
        known_names = ", ".join(member.value for member in known)
        raise DadParseError(
            directive.lineno,
            f"unknown column {token!r} (expected one of {known_names}"
            + (", or a mark column's name)" if marks else ")"),
        )
    return tuple(columns)


_MARK_COLUMN_RE = re.compile(ast.MARK_COLUMN_PATTERN)
_MARK_COLUMN = pydantic.TypeAdapter(ast.MarkColumn)


def _flags(cell: str, lineno: int) -> frozenset[ast.AvpFlag]:
    if cell == "-":  # the canonical empty cell
        return frozenset()
    try:
        return abnf.avp_flags(cell)
    except abnf.AbnfError as error:
        raise DadParseError(lineno, str(error)) from None


def _data_type(cell: str, lineno: int) -> ast.DataType:
    try:
        return ast.DataType(cell)
    except ValueError:
        known = ", ".join(member.value for member in ast.DataType)
        raise DadParseError(
            lineno, f"data_type: unknown Diameter data type {cell!r} (expected {known})"
        ) from None


def _encrypt(cell: str, lineno: int) -> bool | None:
    if cell == "-":
        return None
    if cell not in ("Yes", "No"):
        raise DadParseError(lineno, f"malformed Encrypt cell {cell!r}")
    return cell == "Yes"


def _marks(
    marks: dict[str, tuple[str, ...]], column: str, cell: str, lineno: int
) -> None:
    """A `MarkColumn` cell into `marks`: comma-separated marks, plain or
    quoted; `-` for a printed dash, no marks; `""` for a blank cell, no
    entry. The marks themselves are checked by the row's validation."""
    marked = ast.mark_column(column)
    assert marked is not None, f"{column} is no mark column"
    if cell == formatter.BLANK_CELL:
        return
    if cell == "-":
        marks[marked] = ()
        return
    if not _MARKS_RE.fullmatch(cell):
        raise DadParseError(lineno, f"malformed {column} cell {cell!r}")
    marks[marked] = tuple(
        _ESCAPE_RE.sub(r"\1", mark[1:-1]) if mark.startswith('"') else mark
        for mark in _MARK_RE.findall(cell)
    )


def _avp_table_row(
    columns: tuple[ast.AvpColumn | str, ...], cells: list[str], lineno: int
) -> ast.AvpTableRow:
    name: str | None = None
    marks: dict[str, tuple[str, ...]] = {}
    vendor_id: int | None = None
    code: int | None = None
    section: str | None = None
    data_type: ast.DataType | None = None
    printed_type: str | None = None
    may_encrypt: bool | None = None
    must = may = should_not = must_not = frozenset[ast.AvpFlag]()
    for column, text in zip(columns, cells, strict=True):
        match column:
            case ast.AvpColumn.NAME:
                name = text
            case ast.AvpColumn.VENDOR:
                vendor_id = (
                    None if text == "-" else _number(text, lineno, "Vendor-ID cell")
                )
            case ast.AvpColumn.CODE:
                code = None if text == "-" else _number(text, lineno, "Code cell")
            case ast.AvpColumn.SECTION:
                section = None if text == "-" else text
            case ast.AvpColumn.TYPE if text.startswith('"'):
                # A type the closed set lacks, quoted as printed; a quoted
                # data type is that type.
                printed = _text_cell(text, lineno, "Type")
                if printed in ast.DataType:
                    data_type = ast.DataType(printed)
                else:
                    printed_type = printed
            case ast.AvpColumn.TYPE:
                data_type = None if text == "-" else _data_type(text, lineno)
            case ast.AvpColumn.ENCRYPT:
                may_encrypt = _encrypt(text, lineno)
            case ast.AvpColumn.MUST:
                must = _flags(text, lineno)
            case ast.AvpColumn.MAY:
                may = _flags(text, lineno)
            case ast.AvpColumn.SHOULD_NOT:
                should_not = _flags(text, lineno)
            case ast.AvpColumn.MUST_NOT:
                must_not = _flags(text, lineno)
            case _:
                _marks(marks, column, text, lineno)
    if name is None:  # `AvpTable` requires a Name column, so this is unreachable
        raise DadParseError(lineno, "table row has no Name cell")
    with _validated(lineno):
        return ast.AvpTableRow(
            name=name,
            vendor_id=vendor_id,
            code=code,
            section=section,
            data_type=data_type,
            printed_type=printed_type,
            flag_rules=ast.AvpFlagRules(
                must=must, may=may, should_not=should_not, must_not=must_not
            ),
            may_encrypt=may_encrypt,
            marks=marks,
        )


def _parse_avp_table(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.AvpTable:
    # Optional: RFC 6733 §4.5 prints no "Table N" caption, so an RFC file has
    # no label for `; Table:` to carry.
    table = directives.pop("Table", None)
    columns = _columns(_pop(directives, "Columns", lineno), ast.AvpColumn)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    rows = []
    for row_lineno, cells in _cells(body, len(columns)):
        rows.append(_avp_table_row(columns, cells, row_lineno))
    # Anchored on the block, not on `; Table:`: what is left to check here is
    # the section as a whole (an AVP table with no rows, rows disagreeing with
    # the declared columns), and the label's own line has nothing to do with it.
    with _validated(lineno):
        return ast.AvpTable(
            table=None if table is None else table.value,
            source=source,
            columns=columns,
            rows=tuple(rows),
        )


def _reused_row(
    columns: tuple[ast.ReusedColumn | str, ...], cells: list[str], lineno: int
) -> ast.ReusedAvpRow:
    name: str | None = None
    origin: str | None = None
    m_bit: ast.MBitOverride | None = None
    code: int | None = None
    data_type: ast.DataType | None = None
    marks: dict[str, tuple[str, ...]] = {}
    for column, text in zip(columns, cells, strict=True):
        match column:
            case ast.ReusedColumn.NAME:
                name = text
            case ast.ReusedColumn.FROM:
                origin = text
            case ast.ReusedColumn.M_BIT:
                if text != "-":
                    try:
                        m_bit = ast.MBitOverride(text)
                    except ValueError:
                        raise DadParseError(
                            lineno, f"malformed M-bit cell {text!r}"
                        ) from None
            case ast.ReusedColumn.CODE:
                code = None if text == "-" else _number(text, lineno, "Code cell")
            case ast.ReusedColumn.TYPE:
                data_type = None if text == "-" else _data_type(text, lineno)
            case _:
                _marks(marks, column, text, lineno)
    if name is None or origin is None:  # both columns are required by the model
        raise DadParseError(lineno, "re-used row is missing a Name or From cell")
    with _validated(lineno):
        return ast.ReusedAvpRow(
            name=name,
            origin=origin,
            m_bit=m_bit,
            code=code,
            data_type=data_type,
            marks=marks,
        )


def _parse_reused(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.ReusedAvps:
    # Optional: a clause's prose states origins in no table.
    table = directives.pop("Table", None)
    columns = _columns(_pop(directives, "Columns", lineno), ast.ReusedColumn)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    rows = []
    for row_lineno, cells in _cells(body, len(columns)):
        rows.append(_reused_row(columns, cells, row_lineno))
    with _validated(lineno):
        return ast.ReusedAvps(
            table=None if table is None else table.value,
            source=source,
            columns=columns,
            rows=tuple(rows),
        )


# A registry's reserved range: `; RESERVED 320..399 TS29.234 "TS 29.234"`,
# the documents and the purpose each optional.
_REGISTRY_RESERVED_RE = re.compile(
    rf"^\s*; RESERVED (?P<first>\d+)\.\.(?P<last>\d+)"
    rf'(?: (?P<documents>[^\s"]+))?(?: (?P<purpose>{_QUOTED}))?\s*$'
)
_PLAIN_TEXT_RE = re.compile(r'[^\s,;"\\]+')


def _text_cell(cell: str, lineno: int, label: str) -> str | None:
    """A registry text cell: a plain token or a quoted string, as a mark
    is written; `-` for a blank cell."""
    if cell == "-":
        return None
    if cell.startswith('"') and re.fullmatch(_QUOTED, cell):
        return _ESCAPE_RE.sub(r"\1", cell[1:-1])
    if _PLAIN_TEXT_RE.fullmatch(cell):
        return cell
    raise DadParseError(lineno, f"malformed {label} cell {cell!r}")


def _documents(cell: str, lineno: int) -> tuple[str, ...]:
    """A Defined-In cell: spec-refs separated by commas, `-` for none."""
    if cell == "-":
        return ()
    documents = tuple(cell.split(","))
    for document in documents:
        if not ast.SPEC_REF_RE.match(document):
            raise DadParseError(
                lineno,
                f"Defined-In entry {document!r} does not name a supported"
                " document (expected e.g. 'TS29.229' or 'TS29.228,TS29.229')",
            )
    return documents


def _registry_columns(directive: _Directive) -> tuple[ast.RegistryColumn, ...]:
    """A registry's `; Columns:`, which names no mark column."""
    return tuple(
        ast.RegistryColumn(column)
        for column in _columns(directive, ast.RegistryColumn, marks=False)
    )


def _registry_row(
    columns: tuple[ast.RegistryColumn, ...], cells: list[str], lineno: int
) -> ast.RegistryRow:
    code: int | None = None
    printed_code: str | None = None
    name: str | None = None
    abbreviation: str | None = None
    data_type: ast.DataType | None = None
    printed_type: str | None = None
    defined_in: tuple[str, ...] = ()
    for column, text in zip(columns, cells, strict=True):
        match column:
            case ast.RegistryColumn.CODE if text.startswith('"'):
                printed_code = _text_cell(text, lineno, "Code")
            case ast.RegistryColumn.CODE:
                code = _number(text, lineno, "Code cell")
            case ast.RegistryColumn.NAME:
                name = _text_cell(text, lineno, "Name")
            case ast.RegistryColumn.ABBREVIATION:
                abbreviation = _text_cell(text, lineno, "Abbreviation")
            case ast.RegistryColumn.TYPE if text.startswith('"'):
                # A type the closed set lacks, quoted as printed; a quoted
                # data type is that type.
                printed = _text_cell(text, lineno, "Type")
                if printed in ast.DataType:
                    data_type = ast.DataType(printed)
                else:
                    printed_type = printed
            case ast.RegistryColumn.TYPE:
                data_type = None if text == "-" else _data_type(text, lineno)
            case ast.RegistryColumn.DEFINED_IN:
                defined_in = _documents(text, lineno)
    assert code is not None or printed_code is not None, (
        "a registry without a Code column is rejected first"
    )
    with _validated(lineno):
        return ast.RegistryRow(
            code=code,
            printed_code=printed_code,
            name=name,
            abbreviation=abbreviation,
            data_type=data_type,
            printed_type=printed_type,
            defined_in=defined_in,
        )


def _registry_reservation(line: str, lineno: int) -> ast.RegistryReservation:
    match = _REGISTRY_RESERVED_RE.match(line)
    if match is None:
        raise DadParseError(lineno, f"malformed reserved range: {line.strip()!r}")
    purpose = match["purpose"]
    with _validated(lineno):
        return ast.RegistryReservation(
            first=_number(match["first"], lineno, "reserved range"),
            last=_number(match["last"], lineno, "reserved range"),
            defined_in=_documents(match["documents"] or "-", lineno),
            purpose=None if purpose is None else _ESCAPE_RE.sub(r"\1", purpose[1:-1]),
        )


def _parse_registry(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.Registry:
    kind = _pop(directives, "Registry", lineno)
    table = _pop(directives, "Table", lineno)
    columns_directive = _pop(directives, "Columns", lineno)
    columns = _registry_columns(columns_directive)
    # Before the rows, which each need their code.
    if ast.RegistryColumn.CODE not in columns:
        raise DadParseError(columns_directive.lineno, "registry has no Code column")
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    try:
        registry = ast.RegistryKind(kind.value)
    except ValueError:
        known = ", ".join(member.value for member in ast.RegistryKind)
        raise DadParseError(
            kind.lineno, f"unknown registry {kind.value!r} (expected one of {known})"
        ) from None
    rows: list[ast.RegistryRow | ast.RegistryReservation] = []
    for row_lineno, line in body:
        if line.lstrip().startswith("; RESERVED"):
            rows.append(_registry_reservation(line, row_lineno))
        else:
            ((_, cells),) = _cells([(row_lineno, line)], len(columns))
            rows.append(_registry_row(columns, cells, row_lineno))
    with _validated(lineno):
        return ast.Registry(
            registry=registry,
            table=table.value,
            source=source,
            columns=columns,
            rows=tuple(rows),
        )


# A result code's tail: its own clause, the document defining it, or both.
_RESULT_TAIL_RE = re.compile(
    r"^(?:(?P<section>\S+)(?: +|$))?(?:from (?P<origin>\S+))?$"
)


def _value_row(kind: ast.ValueKind, line: str, lineno: int) -> ast.ValueRow:
    """A value table's line, `name = number`, with what follows it by `kind`:
    a result code's clause and the document it is defined in, a feature's M/O
    mark, and after a bit nothing."""
    match = _ENUM_VALUE_RE.match(line)
    if match is None:
        raise DadParseError(lineno, f"malformed value row: {line.strip()!r}")
    tail = match["description"]
    section = mark = origin = None
    if tail is not None:
        if kind is ast.ValueKind.BITS:
            raise DadParseError(lineno, f"a bit takes no {tail!r}")
        if kind is ast.ValueKind.RESULT_CODES:
            parts = _RESULT_TAIL_RE.match(tail)
            if parts is None or parts["section"] == "from":
                raise DadParseError(
                    lineno,
                    "a result code's tail is its section and 'from' a document,"
                    f" not {tail!r}",
                )
            section, origin = parts["section"], parts["origin"]
        else:
            # `_text_cell` reads a dash as a blank cell, which here is no tail.
            if tail == "-":
                raise DadParseError(lineno, "a blank M/O cell is written as no mark")
            mark = _text_cell(tail, lineno, "M/O")
    with _validated(lineno):
        return ast.ValueRow(
            name=match["name"] or _ESCAPE_RE.sub(r"\1", match["quoted"]),
            value=int(match["value"]),
            section=section,
            mark=mark,
            origin=origin,
        )


def _parse_value_table(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.ValueTable:
    avp = _pop(directives, "AVP", lineno)
    kind = _pop(directives, "Kind", lineno)
    list_id = directives.pop("Feature-List-ID", None)
    application = directives.pop("Application", None)
    # Optional: result codes print under a heading, in no table.
    table = directives.pop("Table", None)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    try:
        value_kind = ast.ValueKind(kind.value)
    except ValueError:
        known = ", ".join(member.value for member in ast.ValueKind)
        raise DadParseError(
            kind.lineno, f"unknown kind {kind.value!r} (expected one of {known})"
        ) from None
    number = None
    if list_id is not None:
        number = _number(list_id.value, list_id.lineno, "Feature-List-ID")
        with _validated(list_id.lineno):
            _UNSIGNED32.validate_python(number)
    for directive in (application, table):
        if directive is not None:
            with _validated(directive.lineno):
                _INLINE_TEXT.validate_python(directive.value)
    rows = [_value_row(value_kind, line, row_lineno) for row_lineno, line in body]
    with _validated(lineno):
        return ast.ValueTable(
            avp=avp.value,
            kind=value_kind,
            feature_list_id=number,
            application=None if application is None else application.value,
            table=None if table is None else table.value,
            source=source,
            rows=tuple(rows),
        )


# A Command Result Codes row: a code's name, bare or quoted as a value's.
_RESULT_NAME_RE = re.compile(rf"^\s*(?P<name>{_QUOTED}|[A-Za-z0-9][A-Za-z0-9_-]*)$")


def _parse_command_result_codes(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.CommandResultCodes:
    # Optional, as an Information Elements block's: a correction names the
    # command where the extractor reads none.
    command = directives.pop("Command", None)
    application_id = directives.pop("Application-ID", None)
    command_section = directives.pop("Command-Section", None)
    origin = directives.pop("From", None)
    table = directives.pop("Table", None)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    number = None
    if application_id is not None:
        number = _number(application_id.value, application_id.lineno, "Application-ID")
    if table is not None:
        with _validated(table.lineno):
            _INLINE_TEXT.validate_python(table.value)
    if origin is not None:
        with _validated(origin.lineno):
            _SPEC_REF.validate_python(origin.value)
    if command_section is not None:
        with _validated(command_section.lineno):
            _SECTION_NUMBER.validate_python(command_section.value)
    rows = []
    for row_lineno, line in body:
        match = _RESULT_NAME_RE.match(line)
        if match is None:
            raise DadParseError(row_lineno, f"malformed result code: {line.strip()!r}")
        name = match["name"]
        if name.startswith('"'):
            name = _ESCAPE_RE.sub(r"\1", name[1:-1])
        with _validated(row_lineno):
            rows.append(ast.ResultCodeRow(name=name))
    with _validated(lineno):
        return ast.CommandResultCodes(
            command=None if command is None else command.value,
            application_id=number,
            command_section=None if command_section is None else command_section.value,
            origin=None if origin is None else origin.value,
            table=None if table is None else table.value,
            source=source,
            rows=tuple(rows),
        )


def _element_mapping(
    cell: str, lineno: int
) -> tuple[tuple[str, ...], bool, str | None]:
    """A Mapping to Diameter AVP cell: AVP names joined by `,` (carried
    together) or `/` (one of them), a quoted cell as printed, or `-` for a
    blank one. Returns the names, whether one of them is meant, and the
    printed text."""
    if cell == "-":
        return (), False, None
    if cell.startswith('"'):
        return (), False, _text_cell(cell, lineno, "AVP")
    either = "/" in cell
    names = tuple(cell.split("/" if either else ","))
    if not all(_AVP_NAME_RE.fullmatch(name) for name in names):
        raise DadParseError(
            lineno,
            f"malformed AVP cell {cell!r}: names joined by ',' or '/', a quoted"
            " cell, or '-'",
        )
    return names, either, None


_AVP_NAME_RE = re.compile(ast.AVP_NAME_PATTERN)
# The spaces setting an element row off under the row above, per level.
_ELEMENT_INDENT = 4


def _parse_information_elements(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.InformationElements:
    # Optional: where the document does not say which command in a way the
    # extractor reads, and where only one application prints it.
    command = directives.pop("Command", None)
    application_id = directives.pop("Application-ID", None)
    command_section = directives.pop("Command-Section", None)
    origin = directives.pop("From", None)
    avp = directives.pop("AVP", None)
    table = directives.pop("Table", None)
    columns = _pop(directives, "Columns", lineno)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    named = tuple(columns.value.split())
    if named not in (ast.ELEMENT_COLUMNS, ast.ELEMENT_AVP_COLUMNS):
        raise DadParseError(
            columns.lineno,
            "information elements have columns"
            f" {' '.join(ast.ELEMENT_COLUMNS)} or {' '.join(ast.ELEMENT_AVP_COLUMNS)}",
        )
    number = None
    if application_id is not None:
        number = _number(application_id.value, application_id.lineno, "Application-ID")
    if table is not None:
        with _validated(table.lineno):
            _INLINE_TEXT.validate_python(table.value)
    if origin is not None:
        with _validated(origin.lineno):
            _SPEC_REF.validate_python(origin.value)
    if command_section is not None:
        with _validated(command_section.lineno):
            _SECTION_NUMBER.validate_python(command_section.value)
    rows = []
    for (row_lineno, cells), (_, line) in zip(
        _cells(body, len(named)), body, strict=True
    ):
        indent = len(line) - len(line.lstrip(" "))
        if indent % _ELEMENT_INDENT:
            raise DadParseError(
                row_lineno,
                f"an element row is set off by multiples of {_ELEMENT_INDENT} spaces",
            )
        element = None
        if named == ast.ELEMENT_COLUMNS:
            element = _text_cell(cells[0], row_lineno, "Name")
            if element is None:
                raise DadParseError(row_lineno, "an information element has a name")
        *_, mapping, category = cells
        if category not in ast.Category and category != '""':
            raise DadParseError(row_lineno, f"malformed Cat cell {category!r}")
        avps, either, printed = _element_mapping(mapping, row_lineno)
        with _validated(row_lineno):
            rows.append(
                ast.ElementRow(
                    name=element,
                    avps=avps,
                    either=either,
                    printed=printed,
                    category=None if category == '""' else ast.Category(category),
                    depth=indent // _ELEMENT_INDENT,
                )
            )
    with _validated(lineno):
        return ast.InformationElements(
            command=None if command is None else command.value,
            application_id=number,
            command_section=None if command_section is None else command_section.value,
            origin=None if origin is None else origin.value,
            avp=None if avp is None else avp.value,
            table=None if table is None else table.value,
            source=source,
            rows=tuple(rows),
        )


_BOUND = r"-?[0-9]+|\*"
_BOUNDS = rf"(?P<low>{_BOUND})(?:\.\.(?P<high>{_BOUND}))?"
# A number ends where a name could not go on, so that a name beginning with a
# digit (TS 29.212's Event-Trigger value 3GPP_PS_DATA_OFF_CHANGE, clause
# 5.3.7) is read whole; a name of digits only is quoted, `"16"`.
_NAME_OR_NUMBER = rf"-?[0-9]+(?![A-Za-z0-9_-])|[A-Za-z0-9][A-Za-z0-9_-]*|{_QUOTED}"
_QUOTE_LINE_RE = re.compile(r'^"(?P<text>(?:[^"\\]|\\["\\])*)"$')
_LENGTH_RE = re.compile(rf"^length {_BOUNDS} (?P<unit>[a-z]+)$")
_RANGE_RE = re.compile(rf"^range {_BOUNDS}$")
_EXCLUDE_RE = re.compile(r"^exclude (?P<values>-?[0-9]+(?:, -?[0-9]+)*)$")
_ENCODING_RE = re.compile(
    r"^encoding (?P<codec>[a-z0-9-]+)"
    r"(?: (?P<document>[^\s\"]+)(?: (?P<clause>[^\s\"]+))?)?"
    rf"(?: (?P<element>{_QUOTED}))?$"
)
_PREDICATE_RE = re.compile(r"^(?P<kind>[a-z-]+) (?P<conditions>.+)$")
_DEFAULT_RE = re.compile(rf"^default (?P<value>{_NAME_OR_NUMBER})$")
_BITS_RE = re.compile(r"^bits (?P<relation>[a-z-]+) (?P<bits>[0-9]+(?: [0-9]+)*)$")
_MEMBERS_RE = re.compile(
    r"^members (?P<relation>[a-z-]+)"
    r" (?P<members>[A-Za-z0-9][A-Za-z0-9_-]*(?: [A-Za-z0-9][A-Za-z0-9_-]*)*)$"
)
_VALUES_RE = re.compile(
    r"^values (?P<values>-?[0-9]+(?:, -?[0-9]+)*) if (?P<conditions>.+)$"
)
# A path: AVP names joined by `/`, from the block's scope or a root
# (`request/User-Name`), a grouped AVP's member after it
# (`MIP6-Agent-Info/MIP-Home-Agent-Host`). A value read from another AVP
# starts at a root, so that a bare name stays a value's.
_PATH = r"(?:(?:request)/)?[A-Za-z0-9][A-Za-z0-9_-]*(?:/[A-Za-z0-9][A-Za-z0-9_-]*)*"
_ROOTED = r"(?:request)/[A-Za-z0-9][A-Za-z0-9_-]*(?:/[A-Za-z0-9][A-Za-z0-9_-]*)*"
# One of the values an `in` condition lists: a range of numbers, a number or
# a name.
_LISTED = rf"-?[0-9]+\.\.-?[0-9]+|{_NAME_OR_NUMBER}"
_CONDITION_RE = re.compile(
    rf"(?P<not>not )?(?P<path>{_PATH})"
    rf"(?: = (?P<value>{_ROOTED}|{_NAME_OR_NUMBER})| bit (?P<bit>{_NAME_OR_NUMBER})"
    rf"| in (?P<listed>(?:{_LISTED})(?:, (?:{_LISTED}))*))?"
)
_LISTED_RE = re.compile(_LISTED)
_RANGE_ITEM_RE = re.compile(r"(?P<low>-?[0-9]+)\.\.(?P<high>-?[0-9]+)")
_EQUALS_RE = re.compile(rf"^equals (?P<path>{_PATH})$")


# A rule line the formatter wraps goes on in lines indented past it.
_CONTINUED = " " * 8


def _continued(
    body: list[tuple[int, str]],
) -> tuple[list[tuple[int, str]], dict[int, int]]:
    """An interpreted-constraints body with each rule line's continuations,
    lines indented past it (`_CONTINUED`), joined to it with a space, and the
    position in the joined body of each line read."""
    joined: list[tuple[int, str]] = []
    owners: dict[int, int] = {}
    for lineno, line in body:
        if line.startswith(_CONTINUED) and line.strip() and joined:
            first, text = joined[-1]
            if not text.startswith(" "):
                raise DadParseError(lineno, "a continued line follows no rule")
            joined[-1] = (first, f"{text} {line.strip()}")
        else:
            joined.append((lineno, line))
        owners[lineno] = len(joined) - 1
    return joined, owners


def _bound(text: str | None) -> int | None:
    return None if text is None or text == "*" else int(text)


def _bounds(match: re.Match[str]) -> tuple[int | None, int | None]:
    """`3` is exactly 3, `1..*` at least 1, `*..15` at most 15."""
    low = _bound(match["low"])
    if match["high"] is None:
        return low, low
    return low, _bound(match["high"])


def _name_or_number(text: str | None) -> int | str | None:
    if text is None:
        return None
    if text.startswith('"'):
        return _ESCAPE_RE.sub(r"\1", text[1:-1])
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    return text


def _reference(text: str) -> ast.Reference:
    """A path: its root, where it names one, and its names."""
    names = text.split("/")
    if names[0] in ast.Root:
        return ast.Reference(root=ast.Root(names[0]), path=tuple(names[1:]))
    return ast.Reference(path=tuple(names))


def _value(text: str | None) -> int | str | ast.Reference | None:
    if text is not None and re.fullmatch(_ROOTED, text):
        return _reference(text)
    return _name_or_number(text)


def _listed(text: str | None) -> tuple[int | str | ast.ValueRange, ...]:
    """The values an `in` condition lists, in order: `A, 3, 5000..5999`."""
    if text is None:
        return ()
    found: list[int | str | ast.ValueRange] = []
    for match in _LISTED_RE.finditer(text):
        if bounds := _RANGE_ITEM_RE.fullmatch(match[0]):
            found.append(
                ast.ValueRange(low=int(bounds["low"]), high=int(bounds["high"]))
            )
        else:
            value = _name_or_number(match[0])
            assert value is not None
            found.append(value)
    return tuple(found)


def _conditions(text: str, lineno: int) -> tuple[tuple[ast.Condition, ...], ...]:
    """Alternatives joined by ` or `, each conditions joined by ` and `, which
    binds tighter, each read at its own position so a quoted name may hold
    either word."""
    alternatives: list[tuple[ast.Condition, ...]] = []
    conjunction: list[ast.Condition] = []
    position = 0
    while True:
        match = _CONDITION_RE.match(text, position)
        if match is None:
            raise DadParseError(lineno, f"malformed condition at {text[position:]!r}")
        with _validated(lineno):
            path = _reference(match["path"])
            conjunction.append(
                ast.Condition(
                    root=path.root,
                    path=path.path,
                    value=_value(match["value"]),
                    bit=_name_or_number(match["bit"]),
                    values=_listed(match["listed"]),
                    negated=match["not"] is not None,
                )
            )
        position = match.end()
        if position == len(text):
            alternatives.append(tuple(conjunction))
            return tuple(alternatives)
        if text.startswith(" or ", position):
            alternatives.append(tuple(conjunction))
            conjunction = []
            position += len(" or ")
        elif text.startswith(" and ", position):
            position += len(" and ")
        else:
            raise DadParseError(lineno, f"malformed condition at {text[position:]!r}")


def _constraint_rule(text: str, lineno: int) -> ast.ConstraintRule:
    """One rule line of an interpreted-constraints body, without its
    indentation."""
    if text == "text-only":
        return ast.TextOnly()
    if text == "unique":
        return ast.UniqueRule()
    if text == "absent":
        return ast.AbsentRule()
    with _validated(lineno):
        if match := _LENGTH_RE.match(text):
            if match["unit"] not in ast.LengthUnit:
                known = ", ".join(unit.value for unit in ast.LengthUnit)
                raise DadParseError(
                    lineno, f"unknown unit {match['unit']!r} (expected one of {known})"
                )
            low, high = _bounds(match)
            return ast.LengthRule(
                unit=ast.LengthUnit(match["unit"]), low=low, high=high
            )
        if match := _RANGE_RE.match(text):
            low, high = _bounds(match)
            return ast.RangeRule(low=low, high=high)
        if match := _EXCLUDE_RE.match(text):
            return ast.ExcludeRule(
                values=tuple(int(value) for value in match["values"].split(", "))
            )
        if match := _ENCODING_RE.match(text):
            if match["codec"] not in ast.Codec:
                known = ", ".join(codec.value for codec in ast.Codec)
                raise DadParseError(
                    lineno,
                    f"unknown codec {match['codec']!r} (expected one of {known})",
                )
            element = match["element"]
            return ast.EncodingRule(
                codec=ast.Codec(match["codec"]),
                document=match["document"],
                clause=match["clause"],
                element=None
                if element is None
                else _ESCAPE_RE.sub(r"\1", element[1:-1]),
            )
        if match := _DEFAULT_RE.match(text):
            value = _name_or_number(match["value"])
            assert value is not None
            return ast.DefaultRule(value=value)
        if match := _BITS_RE.match(text):
            if match["relation"] not in ast.BitsRelation:
                known = ", ".join(each.value for each in ast.BitsRelation)
                raise DadParseError(
                    lineno,
                    f"unknown relation {match['relation']!r} (expected one of {known})",
                )
            return ast.BitsRule(
                relation=ast.BitsRelation(match["relation"]),
                bits=tuple(int(each) for each in match["bits"].split()),
            )
        if match := _MEMBERS_RE.match(text):
            relations = (ast.BitsRelation.AT_LEAST_ONE, ast.BitsRelation.ONLY)
            if match["relation"] not in relations:
                known = ", ".join(each.value for each in relations)
                raise DadParseError(
                    lineno,
                    f"unknown relation {match['relation']!r} (expected one of {known})",
                )
            return ast.MembersRule(
                relation=ast.BitsRelation.ONLY
                if match["relation"] == ast.BitsRelation.ONLY
                else ast.BitsRelation.AT_LEAST_ONE,
                members=tuple(match["members"].split()),
            )
        if match := _EQUALS_RE.match(text):
            return ast.EqualsRule(reference=_reference(match["path"]))
        if match := _VALUES_RE.match(text):
            return ast.ValuesRule(
                values=tuple(int(value) for value in match["values"].split(", ")),
                conditions=_conditions(match["conditions"], lineno),
            )
        if (match := _PREDICATE_RE.match(text)) and match["kind"] in ast.PredicateKind:
            return ast.PredicateRule(
                kind=ast.PredicateKind(match["kind"]),
                conditions=_conditions(match["conditions"], lineno),
            )
    raise DadParseError(lineno, f"malformed rule {text!r}")


def _parse_interpreted_constraints(
    directives: _Directives, body: list[tuple[int, str]], lineno: int
) -> ast.InterpretedConstraints:
    avp = _pop(directives, "AVP", lineno)
    # Optional: a block holding wherever the document reads the AVP names no
    # scope.
    command = directives.pop("Command", None)
    application_id = directives.pop("Application-ID", None)
    command_section = directives.pop("Command-Section", None)
    request_section = directives.pop("Request-Section", None)
    within = directives.pop("Within", None)
    messages = directives.pop("Messages", None)
    table = directives.pop("Table", None)
    # Absent for a document with no version, an RFC.
    versions = directives.pop("Versions", None)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    number = None
    if application_id is not None:
        number = _number(application_id.value, application_id.lineno, "Application-ID")
    for section in (command_section, request_section):
        if section is not None:
            with _validated(section.lineno):
                _SECTION_NUMBER.validate_python(section.value)
    if table is not None:
        with _validated(table.lineno):
            _INLINE_TEXT.validate_python(table.value)
    kind = None
    if messages is not None:
        try:
            kind = ast.Messages(messages.value)
        except ValueError:
            raise DadParseError(
                messages.lineno,
                f"Messages is answers or requests, not {messages.value!r}",
            ) from None
    items: list[ast.Quote | ast.ConstraintRule] = []
    for item_lineno, line in body:
        if match := _QUOTE_LINE_RE.match(line):
            with _validated(item_lineno):
                items.append(ast.Quote(text=_ESCAPE_RE.sub(r"\1", match["text"])))
        elif line.startswith(" ") and line.strip():
            items.append(_constraint_rule(line.strip(), item_lineno))
        else:
            raise DadParseError(
                item_lineno,
                f"expected a quote or an indented rule, got {line.strip()!r}",
            )
    if versions is not None:
        with _validated(versions.lineno):
            _VERSIONS_TEXT.validate_python(versions.value)
    with _validated(lineno):
        return ast.InterpretedConstraints(
            avp=avp.value,
            command=None if command is None else command.value,
            application_id=number,
            command_section=None if command_section is None else command_section.value,
            request_section=None if request_section is None else request_section.value,
            within=None if within is None else within.value,
            messages=kind,
            table=None if table is None else table.value,
            source=source,
            versions=None if versions is None else versions.value,
            body=tuple(items),
        )


_SECTION_PARSERS = {
    "Application Scope": _parse_application_scope,
    "Message": _parse_message,
    "Answer Message": _parse_answer_message,
    "Grouped AVP": _parse_grouped,
    "Enumerated AVP": _parse_enumerated,
    "AVP Table": _parse_avp_table,
    "Reused AVPs": _parse_reused,
    "Registry": _parse_registry,
    "Undefined AVP": _parse_undefined_avp,
    "Value Table": _parse_value_table,
    "Information Elements": _parse_information_elements,
    "Command Result Codes": _parse_command_result_codes,
    "Interpreted Constraints": _parse_interpreted_constraints,
}

# Where each line's comments attach: the path of what the line states. A
# directive states one field, a header rule its section, a body line its
# item. `_BODIES` names each section type's body field and how many
# header-rule lines precede it.
_HEADER_PATHS: dict[str, ast.TreePath] = {
    "Specification": ("specification",),
    "Version": ("version",),
    "Vendor-ID": ("vendor_id",),
    "Bases": ("bases",),
    "Obsoletes": ("obsoletes",),
    "Link": ("link",),
    "Transcribed": ("transcribed",),
}
# `; Transcribed:` says how as well as from what, so a reader of the header
# sees that no extractor wrote the file.
_TRANSCRIBED_PREFIX = "by hand from "
_DIRECTIVE_PATHS: dict[str, ast.TreePath] = {
    "Type": ("type",),
    "Name": ("name",),
    "Section": ("source", "section"),
    "Page": ("source", "page"),
    "Table": ("table",),
    "Columns": ("columns",),
    "Values": ("values_source",),
    "Application-ID": ("application_id",),
    "Applies-To": ("applies_to",),
    "Registry": ("registry",),
    "Note": ("note",),
    "Reprints": ("reprints",),
    "Command": ("command",),
    "Command-Section": ("command_section",),
    "Request-Section": ("request_section",),
    "From": ("origin",),
    "AVP": ("avp",),
    "Kind": ("kind",),
    "Feature-List-ID": ("feature_list_id",),
    "Application": ("application",),
    "Within": ("within",),
    "Messages": ("messages",),
    "Versions": ("versions",),
    "Id": ("id",),
}
# An application scope and an undefined AVP have no body: a whole-line
# comment after the last line stands at the block's own path.
_BODIES = {
    "Application Scope": ("", 0),
    "Message": ("avps", 1),
    "Answer Message": ("avps", 1),
    "Grouped AVP": ("avps", 1),
    "Enumerated AVP": ("values", 1),
    "AVP Table": ("rows", 0),
    "Reused AVPs": ("rows", 0),
    "Registry": ("rows", 0),
    "Undefined AVP": ("", 0),
    "Value Table": ("rows", 0),
    "Information Elements": ("rows", 0),
    "Command Result Codes": ("rows", 0),
    "Interpreted Constraints": ("body", 0),
}


class _Layout(NamedTuple):
    """Which path each line printed, and where a whole-line comment after a
    block's last line stands: one past its body's last item, or `()` for
    the file header. `directives` holds each section's directives."""

    paths: dict[int, ast.TreePath]
    ends: list[ast.TreePath]
    directives: list[dict[str, tuple[int, str]]]


class Placement(NamedTuple):
    """Where one section of a file is printed, by 1-based line number.
    `first` is its `; Type:` line and `last` the last line of its run of
    lines, a whole-line comment included. `directives` holds each directive's
    line and value as printed, without a trailing comment, `Type` included."""

    first: int
    last: int
    directives: Mapping[str, tuple[int, str]]


class Layout(NamedTuple):
    """Where a file prints what its tree holds, by 1-based line number.

    `paths` gives the `TreePath` each line states, as comments attach to it:
    a directive its field, a header rule its section, a body line its item,
    each line of a rule wrapped over several. A line that is all comment has
    none. `sections` places each section, and
    `cells` holds each table row's cells as `(start, end)` offsets into its
    line, a quoted cell with its quotes.
    """

    paths: Mapping[int, ast.TreePath]
    sections: tuple[Placement, ...]
    cells: Mapping[int, tuple[tuple[int, int], ...]]


def parse(text: str) -> ast.Specification:
    """Parse a `.dad` file, discarding its `;;` comments."""
    return _parse(_blocks(_runs(text)))[0]


def parse_with_layout(text: str) -> tuple[ast.Specification, Layout]:
    """Parse a `.dad` file and return where each part of the tree is printed
    (`Layout`), for a reader that ties the tree to the file's lines."""
    runs = _runs(text)
    spec, layout = _parse(_blocks(runs))
    # A block is a run holding content; the first is the file header.
    lasts = [run[-1].lineno for run in runs if any(line.content for line in run)]
    sections = tuple(
        Placement(directives["Type"][0], last, directives)
        for directives, last in zip(layout.directives, lasts[1:], strict=True)
    )
    lines = text.splitlines()
    cells = {
        lineno: tuple(
            match.span()
            for match in _CELL_RE.finditer(lines[lineno - 1].split(";;")[0])
        )
        for lineno, path in layout.paths.items()
        if len(path) == 4
        and isinstance(
            ast.node_at(spec, path),
            ast.AvpTableRow | ast.ReusedAvpRow | ast.RegistryRow | ast.ElementRow,
        )
    }
    return spec, Layout(layout.paths, sections, cells)


def avp_rule_line(line: str) -> tuple[ast.AvpRule, str] | None:
    """The AVP rule a message or grouped body line prints, with its qualifier
    as printed (`1*`, `*2`, or empty), or None for a line printing none.
    `line` is without its comment; a struck member's whole-line comment, `;;
    [ Name ] ; strikethrough`, reads as the rule once `;;` is cut off."""
    match = _AVP_RULE_RE.match(line)
    if match is None:
        return None
    try:
        rule = abnf.avp_rule(
            match,
            bold=match["bold"] is not None,
            strikethrough=match["strikethrough"] is not None,
        )
    except (abnf.AbnfError, pydantic.ValidationError):
        return None
    qualifier = "" if match["min"] is None else f"{match['min']}*{match['max']}"
    return rule, qualifier


type _NoteMap = dict[ast.TreePath, list[str]]


def parse_with_comments(text: str) -> tuple[ast.Specification, formatter.Comments]:
    """Parse a `.dad` file and return its `;;` comments as the
    `formatter.Comments` that `format_spec` takes.

    A trailing comment belongs to its line. A whole-line comment belongs to
    the next line of its block, or to the block's end after its last line.
    A run of comment lines on its own belongs to the following section (or
    past the last section at the end of the file, or `()` before the file
    header). Adjacent comment blocks merge; the formatter chooses
    indentation and blank lines.
    """
    runs = _runs(text)
    spec, layout = _parse(_blocks(runs))
    return spec, _comments(runs, layout)


def _comments(runs: list[list[_Line]], layout: _Layout) -> formatter.Comments:
    trailing: _NoteMap = {}
    standing: _NoteMap = {}
    detached: _NoteMap = {}
    blocks = 0
    for run in runs:
        if not any(line.content for line in run):
            place = () if blocks == 0 else ("sections", blocks - 1)
            detached.setdefault(place, []).extend(
                line.comment for line in run if line.comment is not None
            )
            continue
        waiting: list[str] = []
        for line in run:
            if not line.content:
                if line.comment is not None:
                    waiting.append(line.comment)
                continue
            path = layout.paths[line.lineno]
            if waiting:
                standing.setdefault(path, []).extend(waiting)
                waiting = []
            if line.comment is not None:
                trailing.setdefault(path, []).append(line.comment)
        if waiting:
            standing.setdefault(layout.ends[blocks], []).extend(waiting)
        blocks += 1
    return formatter.Comments(trailing, standing, detached)


def parse_interpretations(
    text: str,
) -> tuple[ast.Interpretations, Mapping[ast.TreePath, int]]:
    """Parse a `.dadx` file, one document's interpretations, discarding its
    `;;` comments. Returns the tree and the 1-based line each path prints
    on, a rule wrapped over several lines at its first, so a check of a
    block can name the line it holds against.

    The file is a `; Interprets:` header, the document's title as its
    `; Specification:` reads, then Interpreted Constraints blocks, each with
    an `; Id:` and no `; Page:`, in the document's clause order.
    """
    tree, layout = _parse_interpretations(_blocks(_runs(text)))
    lines: dict[ast.TreePath, int] = {}
    for lineno, path in layout.paths.items():
        lines.setdefault(path, lineno)
    return tree, lines


def parse_interpretations_with_comments(
    text: str,
) -> tuple[ast.Interpretations, formatter.Comments]:
    """Parse a `.dadx` file and return its `;;` comments, as
    `parse_with_comments` does a `.dad` file's, for
    `formatter.format_interpretations`."""
    runs = _runs(text)
    tree, layout = _parse_interpretations(_blocks(runs))
    return tree, _comments(runs, layout)


def _parse_interpretations(
    blocks: list[_Block],
) -> tuple[ast.Interpretations, _Layout]:
    if not blocks:
        raise DadParseError(1, "empty file")
    layout = _Layout({}, [()], [])
    header = blocks[0]
    directives, body = _split_directives(header)
    if "Interprets" in directives:
        layout.paths[directives["Interprets"].lineno] = ("interprets",)
    if body:
        raise DadParseError(body[0][0], "unexpected content in file header")
    interprets = _pop(directives, "Interprets", header.start)
    _no_leftovers(directives, header.start)
    with _validated(interprets.lineno):
        _INLINE_TEXT.validate_python(interprets.value)
    try:
        ast.spec_ref(interprets.value)
    except ast.SpecRefError as error:
        raise DadParseError(interprets.lineno, str(error)) from None
    sections: list[ast.InterpretationBlock] = []
    seen: dict[str, int] = {}
    for index, block in enumerate(blocks[1:]):
        directives, body = _split_directives(block)
        path: ast.TreePath = ("sections", index)
        layout.directives.append(
            {
                key: (directive.lineno, directive.value)
                for key, directive in directives.items()
            }
        )
        for key, directive in directives.items():
            if key in _DIRECTIVE_PATHS:
                layout.paths[directive.lineno] = (*path, *_DIRECTIVE_PATHS[key])
        section_type = _pop(directives, "Type", block.start)
        if section_type.value != "Interpreted Constraints":
            raise DadParseError(
                section_type.lineno,
                "an interpretations file holds Interpreted Constraints blocks"
                f" only, not {section_type.value!r}",
            )
        identifier = _pop(directives, "Id", block.start)
        if "Page" in directives:
            raise DadParseError(
                directives["Page"].lineno,
                "a page is not written: it is read from each copy's source",
            )
        if identifier.value in seen:
            raise DadParseError(
                identifier.lineno,
                f"the id {identifier.value!r} names the block at line"
                f" {seen[identifier.value]} too",
            )
        seen[identifier.value] = block.start
        body, owners = _continued(body)
        with _validated(block.start):
            read = _parse_interpreted_constraints(directives, body, block.start)
        with _validated(identifier.lineno):
            parsed = ast.InterpretationBlock(id=identifier.value, **dict(read))
        if sections and ast.section_sort_key(
            parsed.source.section
        ) < ast.section_sort_key(sections[-1].source.section):
            raise DadParseError(
                block.start,
                f"clause {parsed.source.section} comes before clause"
                f" {sections[-1].source.section}, the block above it: the"
                " blocks follow the document's clause order",
            )
        sections.append(parsed)
        for lineno, position in owners.items():
            layout.paths[lineno] = (*path, "body", position)
        layout.ends.append((*path, "body", len(body)))
    with _validated(interprets.lineno):
        tree = ast.Interpretations(
            interprets=interprets.value, sections=tuple(sections)
        )
    return tree, layout


def _references(directive: _Directive | None, key: str) -> tuple[str, ...]:
    """A header directive listing documents, `; Bases:` or `; Obsoletes:`:
    spec-refs separated by commas."""
    if directive is None:
        return ()
    references = tuple(part.strip() for part in directive.value.split(","))
    for reference in references:
        if not ast.SPEC_REF_RE.match(reference):
            raise DadParseError(
                directive.lineno,
                f"{key} entry {reference!r} does not name a supported"
                " document (expected e.g. 'RFC6733' or 'TS29.272')",
            )
    return references


def _parse(blocks: list[_Block]) -> tuple[ast.Specification, _Layout]:
    if not blocks:
        raise DadParseError(1, "empty file")
    layout = _Layout({}, [()], [])

    header = blocks[0]
    directives, body = _split_directives(header)
    for key, directive in directives.items():
        if key in _HEADER_PATHS:
            layout.paths[directive.lineno] = _HEADER_PATHS[key]
    if body:
        raise DadParseError(body[0][0], "unexpected content in file header")
    specification = _pop(directives, "Specification", header.start)
    # Optional: an RFC names one immutable document and has no version axis,
    # so its file carries no `; Version:` line.
    version = directives.pop("Version", None)
    vendor = _pop(directives, "Vendor-ID", header.start)
    # Optional: absent means the document builds on nothing — RFC 6733, the
    # base of the tree, is the file with nothing to put in it.
    bases = directives.pop("Bases", None)
    # Optional: only a document whose header obsoletes others says so.
    obsoletes = directives.pop("Obsoletes", None)
    link = directives.pop("Link", None)
    # Optional: only a file a person copied from a rendering carries it.
    transcribed = directives.pop("Transcribed", None)
    _no_leftovers(directives, header.start)

    sections = []
    for index, block in enumerate(blocks[1:]):
        directives, body = _split_directives(block)
        path: ast.TreePath = ("sections", index)
        layout.directives.append(
            {
                key: (directive.lineno, directive.value)
                for key, directive in directives.items()
            }
        )
        for key, directive in directives.items():
            if key in _DIRECTIVE_PATHS:
                layout.paths[directive.lineno] = (*path, *_DIRECTIVE_PATHS[key])
        section_type = _pop(directives, "Type", block.start)
        parser = _SECTION_PARSERS.get(section_type.value)
        if parser is None:
            raise DadParseError(
                section_type.lineno, f"unknown section type {section_type.value!r}"
            )
        owners = {lineno: position for position, (lineno, _) in enumerate(body)}
        if section_type.value == "Interpreted Constraints":
            body, owners = _continued(body)
        with _validated(block.start):
            sections.append(parser(directives, body, block.start))
        field, rules = _BODIES[section_type.value]
        for lineno, position in owners.items():
            item = position - rules
            layout.paths[lineno] = path if item < 0 else (*path, field, item)
        layout.ends.append((*path, field, len(body) - rules) if field else path)

    # The header directives are checked one at a time so each reports its
    # own line, then assembled — by then only the whole-model rules are left.
    if version is not None:
        with _validated(version.lineno):
            _VERSION.validate_python(version.value)
    parsed_link = None
    if link is not None:
        with _validated(link.lineno):
            parsed_link = pydantic.HttpUrl(link.value)
    parsed_transcribed = None
    if transcribed is not None:
        if not transcribed.value.startswith(_TRANSCRIBED_PREFIX):
            raise DadParseError(
                transcribed.lineno,
                f"Transcribed must read {_TRANSCRIBED_PREFIX!r} and a URL",
            )
        with _validated(transcribed.lineno):
            parsed_transcribed = pydantic.HttpUrl(
                transcribed.value.removeprefix(_TRANSCRIBED_PREFIX)
            )
    with _validated(vendor.lineno):
        vendor_id = _number(vendor.value, vendor.lineno, "Vendor-ID")
    parsed_bases = _references(bases, "Bases")
    parsed_obsoletes = _references(obsoletes, "Obsoletes")
    with _validated(specification.lineno):
        spec = ast.Specification(
            specification=specification.value,
            version=None if version is None else version.value,
            vendor_id=vendor_id,
            bases=parsed_bases,
            obsoletes=parsed_obsoletes,
            link=parsed_link,
            transcribed=parsed_transcribed,
            sections=tuple(sections),
        )
    return spec, layout
