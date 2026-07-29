"""Extractor: IETF RFC plain text → `.dad` AST.

A new input path into the same format: RFC 6733 §4.5 is the same kind of
table as a 3GPP AVP table, and its Attribute Name / AVP Code / Section
Defined / Data Type columns map onto `AvpTableRow` as it already stands. What
is different is the carrier — fixed-width text paginated with footers and
running headers, where a long name wraps across physical lines
(`Acct-` / `Interim-Interval`) and, once, the wrap carries the *data* cells
on the continuation line instead (`Inband-Security` / `-Id  299 …`).

Beyond the table, an RFC prints the same definitions a 3GPP spec does, in
prose-embedded forms this module also reads:

- a section titled with the command's long name whose body holds
  `<CER> ::= < Diameter Header: 257, REQ >` → `Message` — the heading carries
  the long name, the rule carries the abbreviation, the reverse of a 3GPP
  heading, which prints both;
- a section titled `Name AVP` holding `Name ::= < AVP Header: 284 >` (the
  name is sometimes itself angle-bracketed: `<Failed-AVP> ::=`) →
  `GroupedAvp`;
- a section titled `Name AVP` where the AVP table types `Name` as Enumerated,
  holding `VALUE_NAME  n` lines → `EnumeratedAvp`. Both printed layouts are
  read: the value alone on its line with the description indented below it
  (RFC 6733), and the description starting on the value's own line and
  wrapping (RFC 7944, 8583). Descriptions are dropped either way, for the
  docx extractor's reason: they are wrapped prose, not a one-line gloss, and
  `; Section:` points at the clause that holds them undamaged.

Anchoring every definition on its *section title* is what keeps the grammar
specification's own illustrations out: `Example-Request`, `Example-AVP` and
`<answer-message>` all sit in sections titled with prose ("Command Code
Format Specification", "Error Bit"), which no definition heading is.

Bodies an RFC prints for another document's AVPs are kept, the same
deliberate call as the docx extractor's: RFC 8581 and 8582 both reprint RFC
7683's `OC-OLR` with their own extension member added, and the file records
what the document printed — cross-file divergence is the linter's to report.
The one shape that is dropped, with a warning, is a value list for an AVP the
local table does not type as Enumerated (RFC 8581 §7.2.1 adds `PEER_REPORT 2`
to 7683's `OC-Report-Type`): `.dad` has no way to extend another document's
enum, so the warning is the honest form.

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
from . import sources
from .errors import ExtractionError, boundary

# Page furniture of the classic RFC rendering: a footer line ending in
# "[Page N]", a form feed, then a running header repeating the RFC number and
# title. Everything else is content.
_FOOTER_RE = re.compile(r"\[Page (?P<page>\d+)\]$")
_RFC_NUMBER_RE = re.compile(r"^Request for Comments:\s*(?P<number>\d+)")
# Section headings sit at column 0: "4.5.  Diameter Base Protocol AVPs".
_HEADING_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\.?\s+(?P<title>\S.*)$")
# A definition heading: the defined name, with or without the " AVP" suffix
# ("6.7.2.  Proxy-Info AVP", "5.3.1.  Capabilities-Exchange-Request"). Prose
# titles do not match, which is what excludes the CCF grammar's own examples.
_TITLE_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)(?P<avp_suffix> AVP)?$")
# Older application RFCs put the command abbreviation in the section title:
# "3.1.  AA-Request (AAR) Command".  Later ones often leave it in the prose
# immediately before the ABNF instead.
_COMMAND_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)"
    r"\s+\((?P<abbreviation>[A-Z]{2,5})\)(?: Command)?$"
)
_AVP_TITLE_WITH_ABBR_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)(?P<avp_suffix> AVP)"
    r"\s+\([A-Z][A-Z0-9_-]*\)$"
)
# The RFC dialect of the three rule forms. Same group names as the docx
# dialect's, which is what lets `abnf.avp_rule` read either.
_DIAMETER_HEADER_RE = re.compile(
    r"^<\s*(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*>\s*::=\s*"
    r"<\s*Diameter Header:\s*(?P<items>[^>]*?)\s*>$"
)
_AVP_HEADER_RE = re.compile(
    # The rule name is angle-bracketed in some clauses and bare in others —
    # RFC 6733 writes both `<Failed-AVP> ::=` and `Proxy-Info ::=`.
    r"^<?\s*(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)\s*>?\s*::=\s*"
    r"<\s*AVP(?: |-)[Hh]eader:\s*(?P<code>\d+)"
    r"(?:\s*,?\s+(?P<vendor>\d+))?\s*>$"
)
_ABNF_LINE_RE = re.compile(
    r"^(?:(?P<min>\d*)\*(?P<max>\d*))?\s*"
    r"(?P<open>[<{\[])\s*(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)\s*(?P<close>[>}\]])$"
)
# One enumerated value line, stripped: `REBOOTING    0` (RFC 6733, description
# indented below) or `PRIORITY_15 15  PRIORITY_15 is the lowest...` (RFC 7944,
# description on the value's own line; RFC 8581 writes `PEER_REPORT 2:`).
# Names are all-caps in every collected RFC, and requiring that is what keeps
# prose lines out; a wrapped description line never has digits as its second
# token, so continuations cannot match.
_ENUM_VALUE_RE = re.compile(
    r"^(?P<name>[A-Z][A-Z0-9_-]*)\s+(?P<value>\d+):?(?:\s+\S.*)?$"
)
_ENUM_VALUE_FIRST_RE = re.compile(
    r"^(?P<value>\d+)\s+(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)"
    r"(?:\s+\[[^\]]+\])?$"
)
_ENUM_VALUE_PIPE_RE = re.compile(r"^(?P<value>\d+)\s*\|\s*(?P<label>\S.*)$")
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
    # Diameter extension RFCs use "Value Type" and draw a box around the
    # complete table rather than only around the flag columns.
    ("AVP Section", "Attribute Name Code Defined Value Type"): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
    ),
    # RFC 5778 uses "Defined in" because its application tables mix local
    # clauses with AVPs imported from other RFCs.
    ("AVP Defined", "Attribute Name Code in Value Type"): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
    ),
    # RFC 8506 stacks "Defined / in" above "Section".
    ("Defined", "AVP in", "Attribute Name Code Section Data Type"): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
    ),
    # RFC 7155's per-category tables carry the clause and flag rules; code and
    # type remain in each AVP's defining prose.
    ("Attribute Name Section Defined",): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.SECTION,
    ),
    ("Section", "Attribute Name Defined"): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.SECTION,
    ),
}
# Flag-column labels, stacked vertically per pipe cell ("MUST" over "NOT"),
# are unambiguous and read generically.
_FLAG_COLUMNS = {
    "MUST": ast.AvpColumn.MUST,
    "MAY": ast.AvpColumn.MAY,
    "SHOULD NOT": ast.AvpColumn.SHOULD_NOT,
    "SHLD NOT": ast.AvpColumn.SHOULD_NOT,
    "MUST NOT": ast.AvpColumn.MUST_NOT,
    "ENCR": ast.AvpColumn.ENCRYPT,
    "MAY ENCR": ast.AvpColumn.ENCRYPT,
}


def _is_separator(text: str) -> bool:
    """The dashed rule closing the column labels and each page's chunk of
    rows: dashes filling the fixed-width area up to the first pipe. Judged on
    that area alone, because the boxed caption's own `|----+-----|` line is
    all dashes too once the pipes are ignored — but prints nothing left of
    its first pipe."""
    # RFC 8583 has one stray space inside a horizontal rule.  It is still
    # unambiguously box drawing (the field contains no character but dashes
    # and whitespace), so tolerate that publisher artefact here.
    left = "".join(text.split("|", 1)[0].split())
    return len(left) >= 3 and set(left) == {"-"}


def _table_text(text: str) -> str:
    """Normalize the two fixed-width table border styles used by RFCs.

    RFC 6733 leaves the name/code/type area open and boxes only the flag
    columns.  Later Diameter RFCs box the complete table, adding a leading
    ``|`` to label and data rows and using ``+`` at every separator
    intersection.  Replacing only that structural leading border, and the
    intersections on separator lines, presents both styles to the same row
    reader without changing any cell text or indentation.
    """
    indent = len(text) - len(text.lstrip())
    stripped = text[indent:]
    if stripped.startswith("|") and text.count("|") >= 4:
        return text[:indent] + " " + stripped[1:]
    if stripped.startswith("+") and stripped.count("+") >= 3:
        return text[:indent] + " " + stripped[1:].replace("+", "|")
    return text


# "Due to space constraints, the short form DiamIdent is used to represent
# DiameterIdentity" — RFC 6733 §4.5, which then also writes DiamURI. A
# document convention carrying information, so it is extractor code rather
# than an input patch per row.
_TYPE_SHORT_FORMS = {
    "DiamIdent": ast.DataType.DIAMETER_IDENTITY,
    "DiamURI": ast.DataType.DIAMETER_URI,
    "IPFiltrRule": ast.DataType.IP_FILTER_RULE,
    "IPFltrRule": ast.DataType.IP_FILTER_RULE,
    "QoSFltrRule": ast.DataType.QOS_FILTER_RULE,
}

# Every AVP an RFC defines is in the IETF's vendor space. Like the docx
# extractor's 10415, a fact about the publisher, stated rather than read.
IETF_VENDOR = ast.IETF_VENDOR

# The quirk vocabulary this extractor defines: readings heuristic enough to
# misfire on a document they were not written for, so each stays off unless
# the document's source declaration names it (see `sources.py`). What gates a
# behavior here is misfire risk, not rarity: the header-spelling maps above
# are also per-document knowledge, but an unrecognized spelling fails loudly
# on its own, where an unwanted prose harvest would succeed silently.
QUIRKS: dict[str, str] = {
    "prose-avp-codes": (
        "complete AVP table rows from each clause's defining sentence, for a"
        " document whose tables print no Code column — RFC 7155 inherits its"
        " codes from RADIUS and prints them only as prose ('AVP Code 5')"
    ),
    "clause-avp-table": (
        "build the AVP index from the defining sentences alone, for a"
        " document that prints no AVP table at all (RFC 4072, RFC 5447)"
    ),
    "radius-attribute-table": (
        "index RADIUS attributes cited as Diameter-compatible AVPs, reading"
        " each code from its attribute clause's Type field (RFC 4590)"
    ),
}


@dataclass
class _Line:
    """One content line: text after furniture removal and patching, the page
    it is printed on, and the section it falls under."""

    text: str
    page: int | None
    section: str | None


def _content_lines(
    raw: list[str], patcher: sources.Patcher
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
    cells_per_line = [line.replace("+", "|").split("|")[1:-1] for line in label_lines]
    widths = {len(cells) for cells in cells_per_line}
    if len(widths) != 1:
        raise ExtractionError(
            f"AVP table label lines disagree on flag-column count: {label_lines!r}"
        )
    labels = []
    for index in range(widths.pop()):
        parts = [cells[index].strip() for cells in cells_per_line]
        parts = ["" if part and set(part) == {"-"} else part for part in parts]
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
    spelled = tuple(
        collapsed
        for line in label_lines
        if (collapsed := " ".join(line.split("|", 1)[0].split()))
    )
    left_columns = _LEFT_HEADERS.get(spelled)
    if left_columns is None:
        raise ExtractionError(f"unrecognized AVP table header {spelled!r}")
    # Names start where the header's own fixed-width area does — the leftmost
    # label line indent (the "Attribute Name" line; the stacked upper labels
    # sit further right, over their own columns).
    indents = []
    for line in label_lines:
        left = line.split("|", 1)[0]
        if left.strip():
            indents.append(len(left) - len(left.lstrip()))
    name_indent = min(indents)
    columns = list(left_columns)
    flag_labels = _flag_labels(label_lines)
    for label in flag_labels:
        column = _FLAG_COLUMNS.get(label.upper())
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
    ignored: bool = False

    def add_left(self, tokens: list[str], line: str, shape: _Columns) -> None:
        if self.ignored:
            return
        if tokens[:4] == ["Rest", "of", "the", "AVPs"]:
            # RFC 5778 closes its application table with a prose catch-all
            # spanning three physical rows.  It is not an AVP definition.
            self.ignored = True
            return
        left_columns = shape.columns[: len(shape.columns) - shape.flag_count]
        if left_columns == (
            ast.AvpColumn.NAME,
            ast.AvpColumn.SECTION,
        ):
            if len(tokens) == 1:
                self.name_parts.append(tokens[0])
            elif len(tokens) == 2:
                self.name_parts.append(tokens[0])
                self._set_data(("", tokens[1], ""), line)
            elif tokens:
                raise ExtractionError(f"malformed AVP table row {line!r}")
        elif len(tokens) == 1:
            self.name_parts.append(tokens[0])
        elif len(tokens) == 2 and (
            tokens[1] in _TYPE_SHORT_FORMS
            or tokens[1] in {data_type.value for data_type in ast.DataType}
        ):
            # RFC 5778 puts Chargeable-User-'s type on the first line and its
            # remaining name/code/section cells on the continuation.
            self.name_parts.append(tokens[0])
            self._set_data(("", "", tokens[1]), line)
        elif (
            len(tokens) == 3
            and not tokens[0].isdigit()
            and self.data is not None
            and self.data[2]
        ):
            self.name_parts.append(tokens[0])
            self._set_data((tokens[1], tokens[2], ""), line)
        elif len(tokens) >= 4:
            self.name_parts.append(tokens[0])
            # "Defined in" cells may be two tokens ("RFC 5447", "Note 1").
            self._set_data((tokens[1], " ".join(tokens[2:-1]), tokens[-1]), line)
        elif len(tokens) == 3 and tokens[0].isdigit():
            self._set_data((tokens[0], tokens[1], tokens[2]), line)
        elif tokens:
            raise ExtractionError(f"malformed AVP table row {line!r}")

    def _set_data(self, tokens: tuple[str, str, str], line: str) -> None:
        if self.data is None:
            self.data = tokens
            return
        for old, new in zip(self.data, tokens, strict=True):
            if old and new:
                raise ExtractionError(
                    f"AVP table row {''.join(self.name_parts)!r} carries its"
                    f" code/section/type cells twice, second time in {line!r}"
                )
        self.data = (
            self.data[0] or tokens[0],
            self.data[1] or tokens[1],
            self.data[2] or tokens[2],
        )

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

    def finish(self, shape: _Columns) -> ast.AvpTableRow | None:
        if self.ignored:
            return None
        name = "".join(self.name_parts)
        if not name or self.data is None:
            raise ExtractionError(
                f"incomplete AVP table row {name!r}: a wrapped row lost"
                " its code/section/type cells"
            )
        code, section, data_type = self.data
        if code and not code.isdigit():
            raise ExtractionError(f"AVP table code cell {code!r}")
        # A mixed application table can also print imported rows as
        # "RFC 5447" or "Note 1".  Those are not definitions by this RFC and
        # must not masquerade as local AVPs in the corpus.
        if section and not re.fullmatch(
            r"([A-Za-z]+|\d+[A-Za-z]*)(\.\d+[A-Za-z]*)*", section
        ):
            return None
        flag_columns = shape.columns[len(shape.columns) - shape.flag_count :]
        flag_rules = {
            column: _flags_cell(cell)
            for column, cell in zip(flag_columns, self.flags, strict=True)
            if column is not ast.AvpColumn.ENCRYPT
        }
        encrypt = next(
            (
                cell
                for column, cell in zip(flag_columns, self.flags, strict=True)
                if column is ast.AvpColumn.ENCRYPT
            ),
            None,
        )
        if encrypt not in (None, "", "Y", "N"):
            raise ExtractionError(f"AVP table Encrypt cell {encrypt!r}")
        empty = frozenset[ast.AvpFlag]()
        return ast.AvpTableRow(
            name=name,
            code=int(code) if code else None,
            section=section or None,
            data_type=_data_type(data_type) if data_type else None,
            flag_rules=ast.AvpFlagRules(
                must=flag_rules.get(ast.AvpColumn.MUST, empty),
                may=flag_rules.get(ast.AvpColumn.MAY, empty),
                should_not=flag_rules.get(ast.AvpColumn.SHOULD_NOT, empty),
                must_not=flag_rules.get(ast.AvpColumn.MUST_NOT, empty),
            ),
            may_encrypt=None if not encrypt else encrypt == "Y",
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
        self.after_table_prose = False

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
        text = _table_text(line.text)
        if self.header_lines is not None:
            if _is_separator(text):
                if self.header_lines:
                    shape = _read_header(self.header_lines)
                    if self.shape is not None and shape != self.shape:
                        raise ExtractionError(
                            "AVP table continuation declares different columns"
                        )
                    self.shape = shape
                    self.header_lines = None
            elif "|" in text:
                left, *right = text.replace("+", "|").split("|")
                if right and right[-1] == "":
                    right.pop()
                has_right_labels = len(right) >= 2 and any(
                    any(character.isalpha() for character in cell) for cell in right
                )
                if left.strip() or has_right_labels:
                    self.header_lines.append(text)
            # Single-cell box captions ("| AVP Flag |") carry no labels.
            return
        if not text:
            return
        if "|" not in text:
            if set(text.strip()) <= {"+", "-"}:
                return
            # RFC 4004 omits the otherwise-empty flag cells on a handful of
            # wrapped name continuations.  Accept only a single token while a
            # row is pending; prose after the table cannot enter here.
            if self.pending is not None and len(text.split()) == 1:
                assert self.shape is not None
                self.pending.add_left(text.split(), text, self.shape)
            elif self.rows and self.pending is None:
                self.after_table_prose = True
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
        if (
            left.strip()
            and indent == self.shape.name_indent
            and not (self.pending is not None and self.pending.ignored)
        ):
            self._finish_pending()
        if self.pending is None:
            self.pending = _PendingRow()
        self.pending.add_left(left.split(), text, self.shape)
        self.pending.add_flags(cells, text)

    def _finish_pending(self) -> None:
        if self.pending is not None:
            assert self.shape is not None
            row = self.pending.finish(self.shape)
            if row is not None:
                self.rows.append(row)
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

    def result_optional(self) -> ast.AvpTable | None:
        """Return the table when this RFC prints one.

        Not every document in the Diameter RFC corpus defines AVPs.  Command
        allocations, applicability statements, and design guidance are still
        useful corpus nodes (and some table-less application RFCs contain
        command or grouped-AVP ABNF), so absence of a table is not itself an
        extraction error.  Once a header has been seen, however, ``result``
        remains strict about its shape and contents.
        """
        if self.shape is None and self.header_lines is None and self.source is None:
            return None
        return self.result()


@dataclass
class _DocSection:
    """One numbered heading with the content lines up to the next heading."""

    number: str
    title: str
    page: int | None
    texts: list[str] = field(default_factory=list)


def _doc_sections(lines: list[_Line], headings: dict[str, _Line]) -> list[_DocSection]:
    """The document as a flat list of numbered sections. Built after the
    furniture pass is complete, so every heading's page is final."""
    sections: list[_DocSection] = []
    for line in lines:
        heading = _HEADING_RE.match(line.text)
        if heading is not None and headings.get(heading["number"]) is line:
            sections.append(
                _DocSection(
                    number=heading["number"],
                    title=" ".join(heading["title"].split()),
                    page=line.page,
                )
            )
        elif sections:
            sections[-1].texts.append(line.text)
    return sections


_SIMPLE_TABLE_HEADER_RE = re.compile(
    r"\|\s*Attribute Name\s+(?:AVP\s+)?Code\s+Defined\s+Data Type\s*\|",
    re.IGNORECASE,
)


def _simple_avp_tables(
    lines: list[_Line], headings: dict[str, _Line]
) -> tuple[ast.AvpTable, ...]:
    """Read IANA-style AVP allocation tables that have no flag columns.

    RFC 5777 prints one wide pipe-delimited table with Name, Code, Section,
    and Data Type.  It is every bit as authoritative as an application AVP
    flag table; it simply has fewer columns.
    """
    tables: list[ast.AvpTable] = []
    for index, line in enumerate(lines):
        if (
            line.text.count("|") != 2
            or _SIMPLE_TABLE_HEADER_RE.search(line.text) is None
        ):
            continue
        rows: list[ast.AvpTableRow] = []
        for candidate in lines[index + 1 :]:
            if _HEADING_RE.match(candidate.text):
                break
            text = candidate.text.strip()
            if not (text.startswith("|") and text.endswith("|")):
                continue
            tokens = text.strip("|").split()
            if len(tokens) != 4 or not tokens[1].isdigit():
                continue
            name, code, section, data_type = tokens
            rows.append(
                ast.AvpTableRow(
                    name=name,
                    code=int(code),
                    section=section,
                    data_type=_data_type(data_type),
                )
            )
        if not rows:
            raise ExtractionError(
                f"{line.section}: AVP allocation table contains no rows"
            )
        if line.section is None:
            raise ExtractionError("AVP allocation table before any numbered section")
        heading = headings.get(line.section or "")
        tables.append(
            ast.AvpTable(
                source=ast.SourceRef(
                    section=line.section,
                    page=heading.page if heading is not None else line.page,
                ),
                columns=(
                    ast.AvpColumn.NAME,
                    ast.AvpColumn.CODE,
                    ast.AvpColumn.SECTION,
                    ast.AvpColumn.TYPE,
                ),
                rows=tuple(rows),
            )
        )
    return tuple(tables)


_CLAUSE_AVP_RE = re.compile(
    r"\b(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*) AVP\s*"
    r"\((?P<identity>[^)]*?(?:Code|Type)\s+(?P<code>\d+)[^)]*)\)"
    # RFC 7155 cites the RADIUS document its attribute number comes from
    # between the identity and the type ("(AVP Code 8) [RFC2865] is of
    # type"). A citation *here* marks heritage, not an import — the AVP is
    # this document's, sitting in its tables with its own defining clause —
    # unlike one inside the parentheses, which `_clause_facts` excludes.
    r"(?:\s*\[RFC\d+\])?"
    r"\s+is of type\s+(?P<data_type>[A-Za-z0-9]+)",
    re.IGNORECASE,
)


@dataclass
class _ClauseFact:
    """One clause's defining sentence, reduced to the facts it states."""

    section: _DocSection
    name: str
    code: int
    data_type: ast.DataType


def _clause_facts(sections: list[_DocSection]) -> list[_ClauseFact]:
    """The Name/Code/Type facts stated by ` AVP`-titled defining clauses.

    Strictly anchored: the sentence must sit under a clause titled with the
    same name it defines. A code annotated with another RFC is an imported
    AVP and is deliberately excluded.
    """
    facts = []
    for section in sections:
        title = _TITLE_RE.match(section.title)
        if title is None or title["avp_suffix"] is None:
            continue
        prose = " ".join(text.strip() for text in section.texts)
        match = _CLAUSE_AVP_RE.search(prose)
        if match is None or match["name"].casefold() != title["name"].casefold():
            continue
        if "[RFC" in match["identity"].upper():
            continue
        facts.append(
            _ClauseFact(
                section=section,
                name=title["name"],
                code=int(match["code"]),
                data_type=_data_type(match["data_type"]),
            )
        )
    return facts


def _clause_avp_table(sections: list[_DocSection]) -> ast.AvpTable | None:
    """Build the AVP index for RFCs that define AVPs clause-by-clause.

    RFCs 4072 and 5447 have no summary table.  Their definition sentences are
    regular and carry the same Name/Code/Section/Type facts, so collect those
    facts into the format's AVP index.  Gated by the `clause-avp-table`
    quirk: which sentences are definitions rather than discussion is exactly
    the judgement a prose reading can get wrong on a document it was not
    written for.
    """
    facts = _clause_facts(sections)
    if not facts:
        return None
    rows = [
        ast.AvpTableRow(
            name=fact.name,
            code=fact.code,
            section=fact.section.number,
            data_type=fact.data_type,
        )
        for fact in facts
    ]
    first = facts[0].section
    return ast.AvpTable(
        source=ast.SourceRef(section=first.number, page=first.page),
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
        ),
        rows=tuple(rows),
    )


def _complete_rows_from_prose(
    tables: tuple[ast.AvpTable, ...],
    sections: list[_DocSection],
    quirks: sources.Quirks,
    warnings: list[str],
) -> tuple[ast.AvpTable, ...]:
    """Fill code and type into the rows of tables that print no Code column,
    from each row's own defining clause. The `prose-avp-codes` quirk.

    RFC 7155 inherits its AVP codes from RADIUS attribute numbers, so its
    per-category tables print only Name, Section and flag rules; the code and
    type appear once, in the defining sentence of the clause the row's
    Section cell already points at. Following that citation completes the
    row without inventing anything: the columns added to `; Columns:` record
    that this file's Code and Type cells were read from the clauses rather
    than from the printed table.
    """
    facts = {fact.name: fact for fact in _clause_facts(sections)}
    used: set[str] = set()
    completed = []
    for table in tables:
        if ast.AvpColumn.CODE in table.columns:
            completed.append(table)
            continue
        rows = []
        for row in table.rows:
            fact = facts.get(row.name)
            if fact is None:
                warnings.append(
                    f"{table.source.section}: no defining sentence found for"
                    f" table row {row.name!r} — its code and type stay unknown"
                )
                rows.append(row)
                continue
            used.add(row.name)
            quirks.fire("prose-avp-codes")
            rows.append(
                ast.AvpTableRow(
                    name=row.name,
                    code=fact.code,
                    section=row.section,
                    data_type=fact.data_type,
                    flag_rules=row.flag_rules,
                    may_encrypt=row.may_encrypt,
                )
            )
        columns: list[ast.AvpColumn] = []
        for column in table.columns:
            columns.append(column)
            if column is ast.AvpColumn.NAME:
                columns.append(ast.AvpColumn.CODE)
            elif column is ast.AvpColumn.SECTION:
                columns.append(ast.AvpColumn.TYPE)
        completed.append(
            ast.AvpTable(
                table=table.table,
                source=table.source,
                columns=tuple(columns),
                rows=tuple(rows),
            )
        )
    for name in sorted(facts.keys() - used):
        warnings.append(
            f"{facts[name].section.number}: defining sentence for {name!r}"
            f" (code {facts[name].code}) matches no code-less table row"
        )
    return tuple(completed)


_RADIUS_ATTRIBUTE_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*) [Aa]ttribute$"
)


def _radius_attribute_table(sections: list[_DocSection]) -> ast.AvpTable | None:
    """Index RADIUS attributes cited as Diameter-compatible AVPs.

    RFC 4590 assigns the compatible code in each attribute's ``Type`` field
    but does not assign a Diameter data type, so the resulting source-shaped
    index deliberately carries only Name, Code, and Section.
    """
    rows: list[ast.AvpTableRow] = []
    first_source: ast.SourceRef | None = None
    for section in sections:
        title = _RADIUS_ATTRIBUTE_TITLE_RE.match(section.title)
        if title is None:
            continue
        code: int | None = None
        for index, text in enumerate(section.texts):
            if text.strip() != "Type":
                continue
            following = next(
                (
                    candidate.strip()
                    for candidate in section.texts[index + 1 :]
                    if candidate.strip()
                ),
                "",
            )
            if match := re.match(r"(?P<code>\d+)\s+for\b", following):
                code = int(match["code"])
            break
        if code is None:
            continue
        source = ast.SourceRef(section=section.number, page=section.page)
        first_source = first_source or source
        rows.append(
            ast.AvpTableRow(
                name=title["name"],
                code=code,
                section=section.number,
            )
        )
    if not rows or first_source is None:
        return None
    return ast.AvpTable(
        source=first_source,
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
        ),
        rows=tuple(rows),
    )


def _abnf_body(texts: list[str], start: int) -> tuple[tuple[ast.AvpRule, ...], int]:
    """Parse `[qual] bracket Name bracket` lines starting at `start`. Blank
    lines inside the body are page-break residue and are skipped; the first
    non-blank line that is not a rule closes the body."""
    rules = []
    index = start
    while index < len(texts):
        text = texts[index].strip()
        if not text:
            index += 1
            continue
        # Some RFC ABNF blocks carry explanatory semicolon comments between
        # rule lines (notably RFC 5777's condition/action grouping).  They are
        # grammar annotations, not the end of the body.
        if text.startswith(";"):
            index += 1
            continue
        match = _ABNF_LINE_RE.match(text)
        if match is None:
            break
        try:
            rules.append(abnf.avp_rule(match))
        except abnf.AbnfError as error:
            raise ExtractionError(f"{error} in {text!r}") from None
        index += 1
    return tuple(rules), index


def _extract_definitions(
    sections: list[_DocSection],
    tables: tuple[ast.AvpTable, ...],
    warnings: list[str],
) -> tuple[list[ast.Message], list[ast.GroupedAvp | ast.EnumeratedAvp]]:
    """Messages, grouped and enumerated AVPs from the definition sections.

    Enumerated codes come from the AVP table, as in the docx extractor — a
    value list is only a definition when the table types its section's AVP as
    Enumerated. A value list under any other ` AVP`-titled section is dropped
    with a warning (RFC 8581 extending RFC 7683's `OC-Report-Type`); one
    under a plain prose-named section is not even that (RFC 6733 §7.1.x list
    Result-Code's values, and Result-Code is Unsigned32 by design).
    """
    messages: list[ast.Message] = []
    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp] = []
    enum_rows = {
        row.name: row
        for table in tables
        for row in table.rows
        if row.data_type is ast.DataType.ENUMERATED
    }
    defined_enums: set[str] = set()
    for section in sections:
        title = _TITLE_RE.match(section.title) or _AVP_TITLE_WITH_ABBR_RE.match(
            section.title
        )
        command_title = _COMMAND_TITLE_RE.match(section.title)
        if title is None and command_title is None:
            continue
        if command_title is not None:
            definition_name = command_title["name"]
        else:
            assert title is not None
            definition_name = title["name"]
        source = ast.SourceRef(section=section.number, page=section.page)
        found_rule = False
        index = 0
        while index < len(section.texts):
            text = section.texts[index].strip()
            index += 1
            if "::=" not in text:
                continue
            found_rule = True
            if "Diameter Header" in text:
                header = _DIAMETER_HEADER_RE.match(text)
                if header is None:
                    raise ExtractionError(
                        f"{section.number}: malformed rule header {text!r}"
                    )
                try:
                    code, flags, application_id = abnf.diameter_header(header["items"])
                except abnf.AbnfError as error:
                    raise ExtractionError(f"{section.number}: {error}") from None
                avps, index = _abnf_body(section.texts, index)
                messages.append(
                    ast.Message(
                        # The heading holds the long name, the rule the
                        # abbreviation — the reverse of a 3GPP heading, which
                        # prints both in "Name (ABBR) Command" form.
                        name=definition_name,
                        abbreviation=(
                            command_title["abbreviation"]
                            if command_title is not None
                            else _message_abbreviation(section, header["name"])
                        ),
                        source=source,
                        command_code=code,
                        flags=flags,
                        application_id=application_id,
                        avps=avps,
                    )
                )
            else:
                if title is None:
                    raise ExtractionError(
                        f"{section.number}: AVP rule under command-titled section"
                    )
                header = _AVP_HEADER_RE.match(text)
                if header is None:
                    raise ExtractionError(
                        f"{section.number}: malformed rule header {text!r}"
                    )
                if header["name"] != title["name"]:
                    warnings.append(
                        f"{section.number}: heading name {title['name']!r}"
                        f" != rule name {header['name']!r}, using the rule name"
                    )
                vendor = header["vendor"]
                avps, index = _abnf_body(section.texts, index)
                definitions.append(
                    ast.GroupedAvp(
                        name=header["name"],
                        source=source,
                        code=int(header["code"]),
                        vendor_id=None if vendor is None else int(vendor),
                        avps=avps,
                    )
                )
        if command_title is not None:
            continue
        assert title is not None
        if found_rule:
            continue
        values = [
            value
            for text in section.texts
            if (value := _enum_value(text.strip())) is not None
        ]
        if not values:
            continue
        row = enum_rows.get(title["name"])
        if row is None or row.code is None:
            if title["avp_suffix"]:
                warnings.append(
                    f"{section.number}: {title['name']!r} lists enumerated"
                    " values but is not an Enumerated row of this RFC's AVP"
                    " table — values dropped"
                )
            continue
        defined_enums.add(title["name"])
        definitions.append(
            ast.EnumeratedAvp(
                name=title["name"],
                source=source,
                code=row.code,
                vendor_id=None,
                values=tuple(values),
            )
        )
    for name in sorted(enum_rows.keys() - defined_enums):
        warnings.append(f"enumerated AVP {name!r}: no value list found in its clause")
    return messages, definitions


def _enum_value(text: str) -> ast.EnumValue | None:
    if match := _ENUM_VALUE_RE.match(text):
        return ast.EnumValue(name=match["name"], value=int(match["value"]))
    if match := _ENUM_VALUE_FIRST_RE.match(text):
        return ast.EnumValue(name=match["name"], value=int(match["value"]))
    if match := _ENUM_VALUE_PIPE_RE.match(text):
        label = match["label"]
        if parenthesized := re.search(r"\((?P<name>[A-Z][A-Z0-9_-]*)\)", label):
            name = parenthesized["name"]
        else:
            name = re.split(r"\s+-\s+", label, maxsplit=1)[0]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            return ast.EnumValue(name=name, value=int(match["value"]))
    return None


def _message_abbreviation(section: _DocSection, rule_name: str) -> str:
    """Find the 2-5 letter command abbreviation for a plain command title.

    Base-protocol RFCs put the abbreviation on the left-hand side of the rule
    (``<CER> ::=``).  Application RFCs commonly put the long name there and
    introduce ``(DER)`` or ``(MIR)`` in the prose above it.
    """
    if re.fullmatch(r"[A-Z]{2,5}", rule_name):
        return rule_name
    name = re.escape(section.title)
    prose = " ".join(text.strip() for text in section.texts)
    if match := re.search(rf"\b{name}\s+\((?P<abbr>[A-Z]{{2,5}})\)", prose):
        return match["abbr"]
    raise ExtractionError(
        f"{section.number}: cannot find an abbreviation for command {section.title!r}"
    )


def _section_sort_key(section: str) -> list[int]:
    """Document order for section numbers: "9.8.10" sorts after "9.8.4"."""
    return [int(part) for part in section.split(".")]


def _specification(raw: list[str]) -> str:
    """ "RFC 6733", from the "Request for Comments: 6733" line of the first
    page's header block."""
    for text in raw[:30]:
        if match := _RFC_NUMBER_RE.match(text.strip()):
            return f"RFC {match['number']}"
    raise ExtractionError("cannot find the RFC number in the document header")


def sources_file_name(specification: str) -> str:
    """Source-declaration file name for an RFC title:
    "RFC 6733" → "RFC6733.toml"."""
    return f"{ast.spec_ref(specification)}.toml"


def extract(
    text_path: Path | str,
    link: str | None = None,
    warnings: list[str] | None = None,
    sources_dir: Path | None = None,
) -> ast.Specification:
    """Extract a `Specification` from an RFC's plain-text rendering.

    `; Page:` numbers are the RFC's own printed pages — the text is its sole
    rendering, so there is no separate PDF step. When `sources_dir` is given,
    source declarations from `<sources_dir>/<SpecRef>.toml` (if present)
    apply: input patches to every content line before parsing, and quirks
    (see `QUIRKS`) to the readings this extractor uses. Non-fatal source
    inconsistencies are appended to `warnings` when a list is given.
    """
    warnings = warnings if warnings is not None else []
    with boundary(f"extracting {text_path}"):
        raw = Path(text_path).read_text(encoding="utf-8").splitlines()
        specification = _specification(raw)
        declarations_path = (
            sources_dir / sources_file_name(specification)
            if sources_dir is not None
            else None
        )
        patcher, quirks = sources.load(declarations_path, None, QUIRKS)

        readers: list[_TableReader] = []
        reader: _TableReader | None = None
        lines, headings = _content_lines(raw, patcher)
        for line in lines:
            if "avp flag" in line.text.casefold() and "|" in line.text:
                # `; Page:` is where the section starts, not where the table
                # does — the two differ when a table opens on the next page.
                if reader is not None and reader.open and reader.after_table_prose:
                    reader.close()
                if reader is None or reader.closed:
                    reader = _TableReader()
                    readers.append(reader)
                heading = headings.get(line.section or "")
                reader.start_header(line, heading.page if heading else line.page)
                continue
            if reader is not None and reader.open:
                if _HEADING_RE.match(line.text):
                    reader.close()
                else:
                    reader.read(line)
        patcher.finish()
        document_sections = _doc_sections(lines, headings)
        tables = tuple(
            table
            for candidate in readers
            if (table := candidate.result_optional()) is not None
        )
        tables += _simple_avp_tables(lines, headings)
        if quirks.enabled("prose-avp-codes"):
            tables = _complete_rows_from_prose(
                tables, document_sections, quirks, warnings
            )
        if quirks.enabled("clause-avp-table") and (
            clause_table := _clause_avp_table(document_sections)
        ):
            quirks.fire("clause-avp-table", len(clause_table.rows))
            tables += (clause_table,)
        if quirks.enabled("radius-attribute-table") and (
            radius_table := _radius_attribute_table(document_sections)
        ):
            quirks.fire("radius-attribute-table", len(radius_table.rows))
            tables += (radius_table,)
        quirks.finish()
        messages, definitions = _extract_definitions(
            document_sections, tables, warnings
        )
        # File order matches the docx extractor's: messages in document order,
        # the AVP table, then every definition in document order.
        definitions.sort(
            key=lambda definition: _section_sort_key(definition.source.section)
        )
        return ast.Specification(
            specification=specification,
            version=None,
            vendor_id=IETF_VENDOR,
            # RFC 6733 is the base of the tree and states no bases of its own.
            bases=()
            if ast.spec_ref(specification) == ast.BASE_PROTOCOL
            else (ast.BASE_PROTOCOL,),
            link=None if link is None else pydantic.HttpUrl(link),
            sections=(
                *messages,
                *tables,
                *definitions,
            ),
        )
