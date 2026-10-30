"""Line-oriented parser for the `.dad` format, producing the `ast` tree.

The format is deliberately line-based, so this is hand-rolled: one pass
splitting the file into contiguous-line blocks (file header first, then one
block per section), then per-`; Type:` body parsers. Directives are grammar:
a malformed `; ...` line is a parse error, never silently skipped. `;;`
free-text comments — whole lines or the tail of a line — are discarded by
`parse`; `parse_with_comments` returns them keyed by where they attach, for
`formatter.format_spec` to print back in place.
"""

import contextlib
import enum
import re
from typing import NamedTuple

import pydantic

from . import abnf, ast, formatter

# Keys carry hyphens (`; Vendor-ID:`), so the charset is wider than letters.
# `; RESERVED = n` uses `=` rather than `:` and so is not a match either way.
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

# The file header's fields belong to three separate lines, so they are checked
# one directive at a time rather than by constructing the model.
_VERSION = pydantic.TypeAdapter(ast.Version)
_INLINE_TEXT = pydantic.TypeAdapter(ast.InlineText)
_UNSIGNED32 = pydantic.TypeAdapter(ast.Unsigned32)


class DadParseError(ValueError):
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
    """A directive's value with the line it was written on.

    The line travels with the value rather than being reduced away, so a value
    the AST rejects is reported at the line holding it: strict errors are only
    useful when they point at what has to be edited.
    """

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
    """Turn the AST's own validation failures into parse errors.

    The models carry the field-level rules — section-number shape, AVP name
    charset, unsigned ranges — so a bad value surfaces as a pydantic error
    from deep inside a constructor. Every malformed `.dad` file should report
    as `DadParseError` with a line, not as whatever the last layer raised.
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
    _no_leftovers(directives, lineno)
    header_name, code, vendor_id = _avp_header(body, "AVP", lineno)
    if header_name != name.value:
        raise DadParseError(
            body[0][0], f"Name directive {name.value!r} != rule name {header_name!r}"
        )
    avps = _avp_rules(body[1:])
    with _validated(name.lineno):
        return ast.GroupedAvp(
            name=name.value,
            source=source,
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
    values: list[ast.EnumValue | ast.ReservedValues] = []
    for value_lineno, line in body[1:]:
        with _validated(value_lineno):
            if match := _RESERVED_RE.match(line):
                first = int(match["first"])
                last = int(match["last"]) if match["last"] else first
                values.append(ast.ReservedValues(first=first, last=last))
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


def _columns[T: enum.StrEnum](directive: _Directive, known: type[T]) -> tuple[T, ...]:
    """The `; Columns:` directive: which columns the source table had, and in
    which order. Only modelled columns appear — see `ast._check_columns`."""
    columns: list[T] = []
    for token in directive.value.split():
        try:
            columns.append(known(token))
        except ValueError:
            known_names = ", ".join(member.value for member in known)
            raise DadParseError(
                directive.lineno,
                f"unknown column {token!r} (expected one of {known_names})",
            ) from None
    return tuple(columns)


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
    marks: dict[ast.MarkColumn, tuple[str, ...]],
    column: ast.AvpColumn | ast.ReusedColumn,
    cell: str,
    lineno: int,
) -> None:
    """A `MarkColumn` cell into `marks`: comma-separated marks, plain or
    quoted; `-` for a printed dash, no marks; `""` for a blank cell, no
    entry. The marks themselves are checked by the row's validation."""
    marked = ast.mark_column(column)
    assert marked is not None, f"{column.value} is no mark column"
    if cell == formatter.BLANK_CELL:
        return
    if cell == "-":
        marks[marked] = ()
        return
    if not _MARKS_RE.fullmatch(cell):
        raise DadParseError(lineno, f"malformed {column.value} cell {cell!r}")
    marks[marked] = tuple(
        _ESCAPE_RE.sub(r"\1", mark[1:-1]) if mark.startswith('"') else mark
        for mark in _MARK_RE.findall(cell)
    )


def _avp_table_row(
    columns: tuple[ast.AvpColumn, ...], cells: list[str], lineno: int
) -> ast.AvpTableRow:
    name: str | None = None
    marks: dict[ast.MarkColumn, tuple[str, ...]] = {}
    code: int | None = None
    section: str | None = None
    data_type: ast.DataType | None = None
    may_encrypt: bool | None = None
    must = may = should_not = must_not = frozenset[ast.AvpFlag]()
    for column, text in zip(columns, cells, strict=True):
        match column:
            case ast.AvpColumn.NAME:
                name = text
            case ast.AvpColumn.CODE:
                code = None if text == "-" else _number(text, lineno, "Code cell")
            case ast.AvpColumn.SECTION:
                section = None if text == "-" else text
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
            code=code,
            section=section,
            data_type=data_type,
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
    columns: tuple[ast.ReusedColumn, ...], cells: list[str], lineno: int
) -> ast.ReusedAvpRow:
    name: str | None = None
    origin: str | None = None
    m_bit: ast.MBitOverride | None = None
    code: int | None = None
    data_type: ast.DataType | None = None
    marks: dict[ast.MarkColumn, tuple[str, ...]] = {}
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
    table = _pop(directives, "Table", lineno)
    columns = _columns(_pop(directives, "Columns", lineno), ast.ReusedColumn)
    source = _source_ref(directives, lineno)
    _no_leftovers(directives, lineno)
    rows = []
    for row_lineno, cells in _cells(body, len(columns)):
        rows.append(_reused_row(columns, cells, row_lineno))
    with _validated(lineno):
        return ast.ReusedAvps(
            table=table.value, source=source, columns=columns, rows=tuple(rows)
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


def _registry_row(
    columns: tuple[ast.RegistryColumn, ...], cells: list[str], lineno: int
) -> ast.RegistryRow:
    code: int | None = None
    name: str | None = None
    abbreviation: str | None = None
    data_type: ast.DataType | None = None
    printed_type: str | None = None
    defined_in: tuple[str, ...] = ()
    for column, text in zip(columns, cells, strict=True):
        match column:
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
    assert code is not None, "a registry without a Code column is rejected first"
    with _validated(lineno):
        return ast.RegistryRow(
            code=code,
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
    columns = _columns(columns_directive, ast.RegistryColumn)
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


_SECTION_PARSERS = {
    "Application Scope": _parse_application_scope,
    "Message": _parse_message,
    "Grouped AVP": _parse_grouped,
    "Enumerated AVP": _parse_enumerated,
    "AVP Table": _parse_avp_table,
    "Reused AVPs": _parse_reused,
    "Registry": _parse_registry,
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
}
# An application scope has no body: a whole-line comment after its last
# line stands at the block's own path.
_BODIES = {
    "Application Scope": ("", 0),
    "Message": ("avps", 1),
    "Grouped AVP": ("avps", 1),
    "Enumerated AVP": ("values", 1),
    "AVP Table": ("rows", 0),
    "Reused AVPs": ("rows", 0),
    "Registry": ("rows", 0),
}


class _Layout(NamedTuple):
    """Which path each line printed, and where a whole-line comment after a
    block's last line stands: one past its body's last item, or `()` for
    the file header."""

    paths: dict[int, ast.TreePath]
    ends: list[ast.TreePath]


def parse(text: str) -> ast.Specification:
    """Parse a `.dad` file, discarding its `;;` comments."""
    return _parse(_blocks(_runs(text)))[0]


type _NoteMap = dict[ast.TreePath, list[str]]


def parse_with_comments(text: str) -> tuple[ast.Specification, formatter.Comments]:
    """Parse a `.dad` file and return its `;;` comments as the
    `formatter.Comments` `format_spec` takes, so formatting the pair writes
    each comment back where it stood.

    A trailing comment belongs to the line it ends. A whole-line comment
    belongs to the next line of its block, and prints before it; one after
    the block's last line stands at the block's end. A run of whole-line
    comments between blank lines is a block of its own, detached, and
    belongs to the section that follows it (to the position past the last
    section at the end of the file, to `()` before the file header).
    Consecutive comment blocks merge into one, and a comment's indentation
    and the blank lines around it are the formatter's to choose.
    """
    runs = _runs(text)
    spec, layout = _parse(_blocks(runs))
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
    return spec, formatter.Comments(trailing, standing, detached)


def _parse(blocks: list[_Block]) -> tuple[ast.Specification, _Layout]:
    if not blocks:
        raise DadParseError(1, "empty file")
    layout = _Layout({}, [()])

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
    link = directives.pop("Link", None)
    # Optional: only a file a person copied from a rendering carries it.
    transcribed = directives.pop("Transcribed", None)
    _no_leftovers(directives, header.start)

    sections = []
    for index, block in enumerate(blocks[1:]):
        directives, body = _split_directives(block)
        path: ast.TreePath = ("sections", index)
        for key, directive in directives.items():
            if key in _DIRECTIVE_PATHS:
                layout.paths[directive.lineno] = (*path, *_DIRECTIVE_PATHS[key])
        section_type = _pop(directives, "Type", block.start)
        parser = _SECTION_PARSERS.get(section_type.value)
        if parser is None:
            raise DadParseError(
                section_type.lineno, f"unknown section type {section_type.value!r}"
            )
        with _validated(block.start):
            sections.append(parser(directives, body, block.start))
        field, rules = _BODIES[section_type.value]
        for position, (lineno, _) in enumerate(body):
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
    parsed_bases: tuple[str, ...] = ()
    if bases is not None:
        parsed_bases = tuple(part.strip() for part in bases.value.split(","))
        with _validated(bases.lineno):
            for base in parsed_bases:
                if not ast.SPEC_REF_RE.match(base):
                    raise DadParseError(
                        bases.lineno,
                        f"Bases entry {base!r} does not name a supported"
                        " document (expected e.g. 'RFC6733' or 'TS29.272')",
                    )
    with _validated(specification.lineno):
        spec = ast.Specification(
            specification=specification.value,
            version=None if version is None else version.value,
            vendor_id=vendor_id,
            bases=parsed_bases,
            link=parsed_link,
            transcribed=parsed_transcribed,
            sections=tuple(sections),
        )
    return spec, layout
