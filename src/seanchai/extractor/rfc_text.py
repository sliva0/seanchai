"""Extractor: IETF RFC plain text → `.dad` AST.

A new input path into the same format: RFC 6733 §4.5 is the same kind of
table as a 3GPP AVP table, and its Attribute Name / AVP Code / Section
Defined / Data Type columns map onto `AvpTableRow` as it already stands. What
is different is the carrier — fixed-width text paginated with footers and
running headers, where a long name wraps across physical lines
(`Acct-` / `Interim-Interval`) and, once, the wrap carries the *data* cells
on the continuation line instead (`Inband-Security` / `-Id  299 …`).

The document model is deliberately smaller than the docx extractor's: what an
RFC contributes to the corpus today is its AVP-flags table, which is what
reference resolution needs (`Session-Id`, `Origin-Host` and the rest of the
base protocol resolve to AVP-table rows). Commands and grouped bodies are
also printed as ABNF and could be extracted later; nothing downstream asks
for them yet.

Two facts this extractor states rather than reads, both facts about the
publisher: every AVP an RFC defines is in the IETF's vendor space (0), and an
RFC number names one immutable document, so the specification has no version
and the emitted file carries no `; Version:` line.

Input patches are applied to every content line — after page furniture is
stripped, before anything is parsed — so a patch sees the physical line as
printed, scoped by the section the line falls under.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pydantic

from ..dad import abnf, ast
from .errors import ExtractionError, boundary
from .patches import Patcher

# Page furniture of the classic RFC rendering: a footer line ending in
# "[Page N]", a form feed, then a running header repeating the RFC number and
# title. Everything else is content.
_FOOTER_RE = re.compile(r"\[Page (?P<page>\d+)\]$")
_RFC_NUMBER_RE = re.compile(r"^Request for Comments:\s*(?P<number>\d+)")
# Section headings sit at column 0: "4.5.  Diameter Base Protocol AVPs".
_HEADING_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\.?\s+\S")
# The fixed-width labels cannot be tokenized: RFC 6733 prints "Code Defined"
# (two columns) and "Attribute Name" (one label) with the same single space,
# so only knowing the vocabulary tells them apart. Each entry maps the
# header's label lines — the text left of the first pipe, whitespace
# collapsed, top to bottom — onto the columns that header declares. A header
# spelled some other way fails loudly and earns its own entry, the same
# collected-cases discipline as the docx extractor's column maps.
_LEFT_HEADERS: dict[tuple[str, ...], tuple[ast.AvpColumn, ...]] = {
    # RFC 6733 §4.5: "AVP" over "Code", "Section" over "Defined".
    ("AVP Section", "Attribute Name Code Defined Data Type"): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
    ),
}
# Flag-column labels, stacked vertically per pipe cell ("MUST" over "NOT"),
# are unambiguous and read generically.
_FLAG_COLUMNS = {
    "MUST": ast.AvpColumn.MUST,
    "MAY": ast.AvpColumn.MAY,
    "SHOULD NOT": ast.AvpColumn.SHOULD_NOT,
    "MUST NOT": ast.AvpColumn.MUST_NOT,
}


def _is_separator(text: str) -> bool:
    """The dashed rule closing the column labels and each page's chunk of
    rows: dashes filling the fixed-width area up to the first pipe. Judged on
    that area alone, because the boxed caption's own `|----+-----|` line is
    all dashes too once the pipes are ignored — but prints nothing left of
    its first pipe."""
    left = text.split("|", 1)[0].strip()
    return len(left) >= 3 and set(left) == {"-"}


# "Due to space constraints, the short form DiamIdent is used to represent
# DiameterIdentity" — RFC 6733 §4.5, which then also writes DiamURI. A
# document convention carrying information, so it is extractor code rather
# than an input patch per row.
_TYPE_SHORT_FORMS = {
    "DiamIdent": ast.DataType.DIAMETER_IDENTITY,
    "DiamURI": ast.DataType.DIAMETER_URI,
}

# Every AVP an RFC defines is in the IETF's vendor space. Like the docx
# extractor's 10415, a fact about the publisher, stated rather than read.
IETF_VENDOR = ast.IETF_VENDOR


@dataclass
class _Line:
    """One content line: text after furniture removal and patching, the page
    it is printed on, and the section it falls under."""

    text: str
    page: int | None
    section: str | None


def _content_lines(
    raw: list[str], patcher: Patcher
) -> tuple[list[_Line], dict[str, _Line]]:
    """Strip page furniture, attach page numbers and sections, apply patches.

    A line's page is the number of the next footer below it — that is the
    page the line is printed on. The running header is recognised as the
    first non-blank line after a page break, not by its text, so a content
    line that happens to start with "RFC" is never eaten.

    Also returned: each section's heading line, because `; Page:` is where
    the *section* starts — the same convention as the docx extractor, where a
    table section can begin one page before the table itself. The heading
    lines are shared objects, so their pages are filled in as the footers
    arrive even though the mapping is built first.
    """
    lines: list[_Line] = []
    headings: dict[str, _Line] = {}
    pending: list[_Line] = []
    section: str | None = None
    after_break = False
    for text in raw:
        text = text.rstrip()
        if "\f" in text:
            after_break = True
            continue
        if match := _FOOTER_RE.search(text):
            page = int(match["page"])
            for line in pending:
                line.page = page
            lines.extend(pending)
            pending = []
            after_break = True
            continue
        if after_break and text:
            after_break = False
            continue  # the running header
        if heading := _HEADING_RE.match(text):
            section = heading["number"]
        line = _Line(patcher.apply(text, section), None, section)
        if heading:
            headings.setdefault(heading["number"], line)
        pending.append(line)
    lines.extend(pending)
    return lines, headings


@dataclass
class _Columns:
    """The table's shape, read off one boxed header."""

    columns: tuple[ast.AvpColumn, ...]
    flag_count: int
    name_indent: int  # column where the Attribute Name label (and names) start


def _flag_labels(label_lines: list[str]) -> list[str]:
    """Flag-column labels, vertically merged per pipe cell: "MUST" over "NOT"
    reads back as "MUST NOT"."""
    cells_per_line = [line.split("|")[1:-1] for line in label_lines]
    widths = {len(cells) for cells in cells_per_line}
    if len(widths) != 1:
        raise ExtractionError(
            f"AVP table label lines disagree on flag-column count: {label_lines!r}"
        )
    labels = []
    for index in range(widths.pop()):
        parts = [cells[index].strip() for cells in cells_per_line]
        labels.append(" ".join(part for part in parts if part))
    return labels


def _read_header(label_lines: list[str]) -> _Columns:
    """The columns a boxed header declares, in source order.

    Strict on both sides: an unrecognised header is a table shape no
    collected RFC prints, and unlike the docx tables there are no known
    prose columns to drop.
    """
    if not label_lines:
        raise ExtractionError("AVP table header with no column labels")
    spelled = tuple(" ".join(line.split("|", 1)[0].split()) for line in label_lines)
    left_columns = _LEFT_HEADERS.get(spelled)
    if left_columns is None:
        raise ExtractionError(f"unrecognized AVP table header {spelled!r}")
    # Names start where the header's own fixed-width area does — the leftmost
    # label line indent (the "Attribute Name" line; the stacked upper labels
    # sit further right, over their own columns).
    indents = []
    for line in label_lines:
        left = line.split("|", 1)[0]
        indents.append(len(left) - len(left.lstrip()))
    name_indent = min(indents)
    columns = list(left_columns)
    flag_labels = _flag_labels(label_lines)
    for label in flag_labels:
        column = _FLAG_COLUMNS.get(label)
        if column is None:
            raise ExtractionError(f"unrecognized AVP flag column {label!r}")
        columns.append(column)
    return _Columns(
        columns=tuple(columns),
        flag_count=len(flag_labels),
        name_indent=name_indent,
    )


def _data_type(text: str) -> ast.DataType:
    if text in _TYPE_SHORT_FORMS:
        return _TYPE_SHORT_FORMS[text]
    try:
        return ast.DataType(text)
    except ValueError:
        raise ExtractionError(f"AVP table Data Type cell {text!r}") from None


def _flags_cell(text: str) -> frozenset[ast.AvpFlag]:
    if not text:
        return frozenset()
    try:
        return abnf.avp_flags(text)
    except abnf.AbnfError as error:
        raise ExtractionError(str(error)) from None


@dataclass
class _PendingRow:
    """One logical row while its physical lines are still arriving.

    A wrapped name contributes fragments that concatenate back into the
    printed name ("Acct-" + "Interim-Interval"); the data cells and each
    flag cell must arrive on exactly one of the row's physical lines,
    whichever one that is — RFC 6733's Inband-Security-Id puts the name
    first and the data on the continuation.
    """

    name_parts: list[str] = field(default_factory=list)
    data: tuple[str, str, str] | None = None  # code, section, type as printed
    flags: list[str] = field(default_factory=list)

    def add_left(self, tokens: list[str], line: str) -> None:
        if len(tokens) == 1:
            self.name_parts.append(tokens[0])
        elif len(tokens) == 4:
            self.name_parts.append(tokens[0])
            self._set_data(tokens[1:], line)
        elif len(tokens) == 3 and tokens[0].isdigit():
            self._set_data(tokens, line)
        elif tokens:
            raise ExtractionError(f"malformed AVP table row {line!r}")

    def _set_data(self, tokens: list[str], line: str) -> None:
        if self.data is not None:
            raise ExtractionError(
                f"AVP table row {''.join(self.name_parts)!r} carries its"
                f" code/section/type cells twice, second time in {line!r}"
            )
        self.data = (tokens[0], tokens[1], tokens[2])

    def add_flags(self, cells: list[str], line: str) -> None:
        stripped = [cell.strip() for cell in cells]
        if not self.flags:
            self.flags = stripped
            return
        for index, cell in enumerate(stripped):
            if not cell:
                continue
            if self.flags[index]:
                raise ExtractionError(
                    f"AVP table row {''.join(self.name_parts)!r} carries flag"
                    f" cell {cell!r} twice, second time in {line!r}"
                )
            self.flags[index] = cell

    def finish(self, shape: _Columns) -> ast.AvpTableRow:
        name = "".join(self.name_parts)
        if not name or self.data is None:
            raise ExtractionError(
                f"incomplete AVP table row {name!r}: a wrapped row lost"
                " its code/section/type cells"
            )
        code, section, data_type = self.data
        if not code.isdigit():
            raise ExtractionError(f"AVP table code cell {code!r}")
        flag_columns = shape.columns[len(shape.columns) - shape.flag_count :]
        flag_rules: dict[ast.AvpColumn, frozenset[ast.AvpFlag]] = {
            column: _flags_cell(cell)
            for column, cell in zip(flag_columns, self.flags, strict=True)
        }
        empty = frozenset[ast.AvpFlag]()
        return ast.AvpTableRow(
            name=name,
            code=int(code),
            section=section,
            data_type=_data_type(data_type),
            flag_rules=ast.AvpFlagRules(
                must=flag_rules.get(ast.AvpColumn.MUST, empty),
                may=flag_rules.get(ast.AvpColumn.MAY, empty),
                should_not=flag_rules.get(ast.AvpColumn.SHOULD_NOT, empty),
                must_not=flag_rules.get(ast.AvpColumn.MUST_NOT, empty),
            ),
        )


class _TableReader:
    """Accumulates one AVP-flags table across page-broken chunks.

    The table opens at its first boxed header and closes at the next section
    heading; a header box met while open is the printed continuation after a
    page break and must declare the same columns."""

    def __init__(self) -> None:
        self.shape: _Columns | None = None
        self.rows: list[ast.AvpTableRow] = []
        self.pending: _PendingRow | None = None
        self.header_lines: list[str] | None = None
        self.source: tuple[str | None, int | None] | None = None
        self.closed = False

    @property
    def open(self) -> bool:
        return not self.closed and (
            self.shape is not None or self.header_lines is not None
        )

    def start_header(self, line: _Line, page: int | None) -> None:
        if self.closed:
            # Mirrors the docx extractor: which table wins is a policy no
            # collected document forces, and it must not be decided silently.
            raise ExtractionError("more than one AVP table found")
        self.header_lines = []
        if self.source is None:
            self.source = (line.section, page)

    def read(self, line: _Line) -> None:
        text = line.text
        if self.header_lines is not None:
            if _is_separator(text):
                shape = _read_header(self.header_lines)
                if self.shape is not None and shape != self.shape:
                    raise ExtractionError(
                        "AVP table continuation declares different columns"
                    )
                self.shape = shape
                self.header_lines = None
            elif "|" in text and text.split("|", 1)[0].strip():
                self.header_lines.append(text)
            # Box-drawing lines ("+----+", "| AVP Flag |") carry no labels.
            return
        if not text or "|" not in text:
            return
        if _is_separator(text):
            self._finish_pending()
            return
        assert self.shape is not None
        left, *cells = text.split("|")
        if cells and cells[-1] == "":
            cells.pop()  # the trailing pipe
        if len(cells) != self.shape.flag_count:
            raise ExtractionError(
                f"AVP table row with {len(cells)} flag cells for"
                f" {self.shape.flag_count} flag columns: {text!r}"
            )
        indent = len(left) - len(left.lstrip())
        if left.strip() and indent == self.shape.name_indent:
            self._finish_pending()
        if self.pending is None:
            self.pending = _PendingRow()
        self.pending.add_left(left.split(), text)
        self.pending.add_flags(cells, text)

    def _finish_pending(self) -> None:
        if self.pending is not None:
            assert self.shape is not None
            self.rows.append(self.pending.finish(self.shape))
            self.pending = None

    def close(self) -> None:
        self._finish_pending()
        self.closed = True

    def result(self) -> ast.AvpTable:
        if not self.closed:
            self.close()
        if self.shape is None or self.source is None:
            raise ExtractionError("no AVP table found")
        section, page = self.source
        if section is None:
            raise ExtractionError("AVP table before any numbered section")
        return ast.AvpTable(
            source=ast.SourceRef(section=section, page=page),
            columns=self.shape.columns,
            rows=tuple(self.rows),
        )


def _specification(raw: list[str]) -> str:
    """ "RFC 6733", from the "Request for Comments: 6733" line of the first
    page's header block."""
    for text in raw[:30]:
        if match := _RFC_NUMBER_RE.match(text.strip()):
            return f"RFC {match['number']}"
    raise ExtractionError("cannot find the RFC number in the document header")


def patch_file_name(specification: str) -> str:
    """Patch file name for an RFC title: "RFC 6733" → "RFC6733.toml"."""
    return f"{ast.spec_ref(specification)}.toml"


def extract(
    text_path: Path | str,
    link: str | None = None,
    warnings: list[str] | None = None,
    patches_dir: Path | None = None,
) -> ast.Specification:
    """Extract a `Specification` from an RFC's plain-text rendering.

    `; Page:` numbers are the RFC's own printed pages — the text is its sole
    rendering, so there is no separate PDF step. When `patches_dir` is given,
    input patches from `<patches_dir>/<SpecRef>.toml` (if present) are applied
    to every content line before parsing. `warnings` is accepted for symmetry
    with the docx extractor; no non-fatal inconsistency is reported yet.
    """
    with boundary(f"extracting {text_path}"):
        raw = Path(text_path).read_text(encoding="utf-8").splitlines()
        specification = _specification(raw)
        patch_path = (
            patches_dir / patch_file_name(specification)
            if patches_dir is not None
            else None
        )
        patcher = Patcher.load(patch_path, version=None)

        reader = _TableReader()
        lines, headings = _content_lines(raw, patcher)
        for line in lines:
            if "AVP Flag" in line.text and "|" in line.text:
                # `; Page:` is where the section starts, not where the table
                # does — the two differ when a table opens on the next page.
                heading = headings.get(line.section or "")
                reader.start_header(line, heading.page if heading else line.page)
                continue
            if reader.open:
                if _HEADING_RE.match(line.text):
                    reader.close()
                else:
                    reader.read(line)
        patcher.finish()
        return ast.Specification(
            specification=specification,
            version=None,
            vendor_id=IETF_VENDOR,
            link=None if link is None else pydantic.HttpUrl(link),
            sections=(reader.result(),),
        )
