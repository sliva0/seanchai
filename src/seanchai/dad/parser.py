"""Line-oriented parser for the `.dad` format, producing the `ast` tree.

The format is deliberately line-based, so this is hand-rolled: one pass
splitting the file into contiguous-line blocks (file header first, then one
block per section), then per-`; Type:` body parsers. Directives are grammar:
a malformed `; ...` line is a parse error, never silently skipped. `;;`
free-text comments — whole lines or the tail of a line — are discarded.
"""

import contextlib
import enum
import re
from typing import NamedTuple

import pydantic

from . import abnf, ast

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
    r"(?P<bold>\s*; bold)?\s*$"
)
_ENUM_VALUE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)\s*= (?P<value>\d+)"
    r"(?:\s+; (?P<description>\S.*))?$"
)
_RESERVED_RE = re.compile(r"^\s*; RESERVED\s*= (?P<first>\d+)(?:-(?P<last>\d+))?$")

# The file header's fields belong to three separate lines, so they are checked
# one directive at a time rather than by constructing the model.
_VERSION = pydantic.TypeAdapter(ast.Version)


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


def _blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    current: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.rstrip() != line:
            raise DadParseError(lineno, "trailing whitespace")
        # Everything from the first `;;` to the end of the line is comment;
        # inline values cannot contain `;;` (the AST rejects it), so nothing
        # meaningful is ever cut. A line left empty by its comment is skipped
        # rather than treated as the blank line that separates blocks.
        comment = line.find(";;")
        if comment != -1:
            line = line[:comment].rstrip()
            if not line:
                continue
        if line:
            current.append((lineno, line))
        elif current:
            blocks.append(_Block(current))
            current = []
    if current:
        blocks.append(_Block(current))
    return blocks


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
    try:
        return int(text)
    except ValueError:
        raise DadParseError(lineno, f"{label} must be a number, got {text!r}") from None


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
                rules.append(abnf.avp_rule(match, bold=match["bold"] is not None))
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
                        name=match["name"],
                        value=int(match["value"]),
                        description=match["description"],
                    )
                )
            else:
                raise DadParseError(
                    value_lineno, f"malformed enum value: {line.strip()!r}"
                )
    with _validated(name.lineno):
        return ast.EnumeratedAvp(
            name=name.value,
            source=source,
            code=code,
            vendor_id=vendor_id,
            values=tuple(values),
        )


def _cells(body: list[tuple[int, str]], count: int):
    for lineno, line in body:
        cells = line.split()
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


def _avp_table_row(
    columns: tuple[ast.AvpColumn, ...], cells: list[str], lineno: int
) -> ast.AvpTableRow:
    name: str | None = None
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
    if name is None or origin is None:  # both columns are required by the model
        raise DadParseError(lineno, "re-used row is missing a Name or From cell")
    with _validated(lineno):
        return ast.ReusedAvpRow(name=name, origin=origin, m_bit=m_bit)


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


_SECTION_PARSERS = {
    "Message": _parse_message,
    "Grouped AVP": _parse_grouped,
    "Enumerated AVP": _parse_enumerated,
    "AVP Table": _parse_avp_table,
    "Reused AVPs": _parse_reused,
}


def parse(text: str) -> ast.Specification:
    blocks = _blocks(text)
    if not blocks:
        raise DadParseError(1, "empty file")

    header = blocks[0]
    directives, body = _split_directives(header)
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
    _no_leftovers(directives, header.start)

    sections = []
    for block in blocks[1:]:
        directives, body = _split_directives(block)
        section_type = _pop(directives, "Type", block.start)
        parser = _SECTION_PARSERS.get(section_type.value)
        if parser is None:
            raise DadParseError(
                section_type.lineno, f"unknown section type {section_type.value!r}"
            )
        with _validated(block.start):
            sections.append(parser(directives, body, block.start))

    # The header directives are checked one at a time so each reports its
    # own line, then assembled — by then only the whole-model rules are left.
    if version is not None:
        with _validated(version.lineno):
            _VERSION.validate_python(version.value)
    parsed_link = None
    if link is not None:
        with _validated(link.lineno):
            parsed_link = pydantic.HttpUrl(link.value)
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
        return ast.Specification(
            specification=specification.value,
            version=None if version is None else version.value,
            vendor_id=vendor_id,
            bases=parsed_bases,
            link=parsed_link,
            sections=tuple(sections),
        )
