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
    # RFC 6738 clause 5.1's IKESKR is six letters.
    r"\s+\((?P<abbreviation>[A-Z]{2,6})\)(?: Command)?$"
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
# "RFC 2617" opening a wrapped line is a citation, whatever follows it (RFC 4740
# clause 9.5.1: "RFC 2617 [RFC2617] Section 3.2.1.").
_ENUM_VALUE_RE = re.compile(
    r"^(?!RFC\s)(?P<name>[A-Z][A-Z0-9_-]*)\s+(?P<value>\d+):?(?:\s+\S.*)?$"
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
    # RFC 5580 clause 6 omits both the code and defining-clause columns.
    ("Attribute Name Value Type",): (ast.AvpColumn.NAME, ast.AvpColumn.TYPE),
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
    # RFC 6736 clauses 8.1, 8.5 and 8.6 print no defining-clause column for the
    # AVPs they re-use; its clause 8.7 shortens the column to "Sect.".
    ("AVP", "Attribute Name Code Data Type"): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.TYPE,
    ),
    ("AVP", "Attribute Name Code Sect. Data Type"): (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
    ),
}
# A table boxing every column (RFC 4740 tables 2 and 3, RFC 6736 tables 2 and
# 3) leaves only the name left of the first pipe, and prints its other data
# columns in cells of their own, labelled by these spellings, ahead of the flags.
_CELL_HEADER = ("Attribute Name",)
_CELL_COLUMNS = {
    "AVP Code": ast.AvpColumn.CODE,
    "Reference": ast.AvpColumn.SECTION,
    "Data- Type": ast.AvpColumn.TYPE,
    "Value Type": ast.AvpColumn.TYPE,
}
# Flag-column labels, stacked vertically per pipe cell ("MUST" over "NOT"),
# are unambiguous and read generically.
_FLAG_COLUMNS = {
    "MUST": ast.AvpColumn.MUST,
    "MAY": ast.AvpColumn.MAY,
    "SHOULD NOT": ast.AvpColumn.SHOULD_NOT,
    "SHLD NOT": ast.AvpColumn.SHOULD_NOT,
    "SHD NOT": ast.AvpColumn.SHOULD_NOT,
    "MUST NOT": ast.AvpColumn.MUST_NOT,
    "ENCR": ast.AvpColumn.ENCRYPT,
    "MAY ENCR": ast.AvpColumn.ENCRYPT,
}


def _is_separator(text: str, quirks: sources.Quirks) -> bool:
    """The dashed rule closing the column labels and each page's chunk of
    rows: dashes filling the fixed-width area up to the first pipe. Judged on
    that area alone, because the boxed caption's own `|----+-----|` line is
    all dashes too once the pipes are ignored — but prints nothing left of
    its first pipe."""
    left = text.split("|", 1)[0].strip()
    if len(left) >= 3 and set(left) == {"-"}:
        return True
    # RFC 8583 prints one stray space inside a horizontal rule. The field
    # holding no character but dashes and whitespace is still unambiguously
    # box drawing, but only where the document declares the publisher
    # artefact — the `ragged-separator` quirk.
    collapsed = "".join(left.split())
    if (
        len(collapsed) >= 3
        and set(collapsed) == {"-"}
        and quirks.enabled("ragged-separator")
    ):
        quirks.fire("ragged-separator")
        return True
    return False


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
# DiameterIdentity" — RFC 6733 §4.5, which then also writes DiamURI. The
# vocabulary lives here; *accepting* it is per-document, behind the
# `type-short-forms` quirk, so a new document's typo cannot ride in on
# another document's declared convention.
_TYPE_SHORT_FORMS = {
    "DiamIdent": ast.DataType.DIAMETER_IDENTITY,
    "DiamURI": ast.DataType.DIAMETER_URI,
    "IPFiltrRule": ast.DataType.IP_FILTER_RULE,
    "IPFltrRule": ast.DataType.IP_FILTER_RULE,
    "QoSFltrRule": ast.DataType.QOS_FILTER_RULE,
    # RFC 4740 clause 9's legend for its table 2.
    "DURI": ast.DataType.DIAMETER_URI,
    "E": ast.DataType.ENUMERATED,
    "G": ast.DataType.GROUPED,
    "OS": ast.DataType.OCTET_STRING,
    "UTF8S": ast.DataType.UTF8_STRING,
    "U32": ast.DataType.UNSIGNED32,
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
    "prose-avp-origins": (
        "read explicit AVP definition citations as re-used origins"
        " (RFC 8583 section 7.4's SourceID)"
    ),
    "prose-cleared-flags": (
        "read explicit cleared M/V bits in AVP clauses (RFC 6942 clauses 8.1-8.2)"
    ),
    "mixed-table-borders": (
        "retain open flag-only header lines above boxed rows (RFC 5580 clause 6)"
    ),
    "radius-avp-codes": (
        "complete Diameter table codes from RADIUS Type fields (RFC 5580 clause 6)"
    ),
    "parenthesized-enum-values": (
        "read whole Name (number) lines as enum values (RFC 6734 clause 3.1.1)"
    ),
    "worded-enum-values": (
        "read value names of several words, keeping their spaces: 'CHAP with"
        " MD5       5' (RFC 4005 clause 5.5, RFC 7155 clause 4.3.5), '2   ISDN"
        " Sync' with its wrapped lines (RFC 4005 clauses 4.4-7.3), and with"
        " `parenthesized-enum-values` 'Callback Login (3)' (RFC 7155 clause"
        " 4.4.1)"
    ),
    "parenthesized-value-first": (
        "read '(0): QoS-Desired' lines as enum values (RFC 5777 clause 5.4)"
    ),
    "cause-mapping-table": (
        "read an Enumerated row's clause that maps RADIUS causes onto the"
        " AVP's values in a 'Cause Value Name | RADIUS | Diameter' table,"
        " the Diameter column the value (RFC 4005 clause 9.3.5)"
    ),
    "registry-enum-values": (
        "read an Enumerated AVP's values from the IANA section that numbers"
        " them in a 'Token | Value | Description' table, and the values its"
        " policy reserves, where the defining clause names the values and"
        " numbers none (RFC 5778 clauses 6.20, 9.5)"
    ),
    "external-enum-values": (
        "read where an enumerated clause says its values are listed instead"
        " of listing them ('The supported values are listed in"
        " [RADIUSAttrVals].') into `; Values:` (RFC 4005, 5777, 5778, 6733,"
        " 7155)"
    ),
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
    "type-short-forms": (
        "accept the space-constrained Data Type spellings some RFC tables"
        " declare and print — DiamIdent, DiamURI, IPFiltrRule/IPFltrRule,"
        " QoSFltrRule (RFC 6733, 4004, 4005, 4006, 6736), and RFC 4740's DURI,"
        " E, G, OS, UTF8S, U32"
    ),
    "prose-catchall-row": (
        "ignore the 'Rest of the AVPs' prose catch-all RFC 5778 prints as"
        " three physical rows at the end of its application table"
    ),
    "bare-name-continuation": (
        "accept a wrapped name's continuation line printed without its"
        " otherwise-empty flag cells, outside the table box (RFC 4004)"
    ),
    "boxed-table-legend": (
        "skip the one-cell boxed rows printing a legend under a table's closing"
        " rule (RFC 5866 clause 7.2)"
    ),
    "split-avp-tables": (
        "join a table printing only flag rules onto the table before it, name"
        " by name, where a document prints codes and flags apart (RFC 4740"
        " tables 2 and 3)"
    ),
    "reused-avp-tables": (
        "read a table under a 'Reused ... AVPs' clause as a re-used block, its"
        " origin the reference after the clause's 'reused from' (RFC 6736"
        " clauses 8.1, 8.3-8.6)"
    ),
    "note-avp-origins": (
        "read a table's rows whose Defined cell cites 'Note 1' as re-used rows,"
        " their origin from the note's 'are defined in [RFC...]' (RFC 6738"
        " clause 8)"
    ),
    "bulleted-enum-values": (
        "read 'o  NAME (n)' list items as enum values, with what follows on the"
        " line as description (RFC 4740 clauses 9.4-9.13)"
    ),
    "ragged-separator": (
        "accept a horizontal rule with a stray space inside it as box"
        " drawing (RFC 8583)"
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
    # Every column boxed: the data columns printed in pipe cells of their own,
    # after the name (none in a table of names and flags alone).
    boxed: bool = False
    cell_columns: tuple[ast.AvpColumn, ...] = ()


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
    left_columns = () if spelled == _CELL_HEADER else _LEFT_HEADERS.get(spelled)
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
    flag_labels = _flag_labels(label_lines)
    cell_columns: tuple[ast.AvpColumn, ...] = ()
    if spelled == _CELL_HEADER:
        left_columns = (ast.AvpColumn.NAME,)
        count = 0
        while count < len(flag_labels) and flag_labels[count] in _CELL_COLUMNS:
            count += 1
        cell_columns = tuple(_CELL_COLUMNS[label] for label in flag_labels[:count])
        flag_labels = flag_labels[count:]
    columns = [*left_columns, *cell_columns]
    for label in flag_labels:
        column = _FLAG_COLUMNS.get(label.upper())
        if column is None:
            raise ExtractionError(f"unrecognized AVP flag column {label!r}")
        columns.append(column)
    return _Columns(
        columns=tuple(columns),
        flag_count=len(flag_labels),
        name_indent=name_indent,
        boxed=spelled == _CELL_HEADER,
        cell_columns=cell_columns,
    )


def _data_type(text: str, quirks: sources.Quirks) -> ast.DataType:
    if text in _TYPE_SHORT_FORMS:
        if quirks.enabled("type-short-forms"):
            quirks.fire("type-short-forms")
            return _TYPE_SHORT_FORMS[text]
        raise ExtractionError(
            f"AVP table Data Type cell {text!r} is a declared short form,"
            " which this document's source declaration does not accept"
            " (the `type-short-forms` quirk)"
        )
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

    quirks: sources.Quirks
    name_parts: list[str] = field(default_factory=list)
    data: tuple[str, str, str] | None = None  # code, section, type as printed
    flags: list[str] = field(default_factory=list)
    ignored: bool = False
    # Rows whose Defined cell cites a note, for `note-avp-origins`: the note,
    # name, code and type as printed. Shared with the table reader.
    noted: list[tuple[str, str, int | None, str]] = field(default_factory=list)

    def add_left(self, tokens: list[str], line: str, shape: _Columns) -> None:
        if self.ignored:
            return
        if tokens[:4] == ["Rest", "of", "the", "AVPs"]:
            # RFC 5778 closes its application table with a prose catch-all
            # spanning three physical rows.  It is not an AVP definition —
            # but dropping table lines on a text match is exactly the kind
            # of reading that must not run undeclared.
            if not self.quirks.enabled("prose-catchall-row"):
                raise ExtractionError(
                    f"prose catch-all row {line!r}, which this document's"
                    " source declaration does not ignore (the"
                    " `prose-catchall-row` quirk)"
                )
            self.quirks.fire("prose-catchall-row")
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
        elif len(tokens) == 3 and left_columns == (
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.TYPE,
        ):
            self.name_parts.append(tokens[0])
            self._set_data((tokens[1], "", tokens[2]), line)
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

    def add_cells(self, name: str, cells: list[str], shape: _Columns) -> None:
        """One physical line of a table boxing every column: the name cell,
        then its data cells, all blank on a wrapped name's continuation."""
        self.name_parts.append(name)
        printed = {
            column: cell.strip()
            for column, cell in zip(shape.cell_columns, cells, strict=True)
        }
        if self.data is not None and not any(printed.values()):
            return
        self._set_data(
            (
                printed.get(ast.AvpColumn.CODE, ""),
                # RFC 4740 table 2's Reference column: "Section 9.1".
                printed.get(ast.AvpColumn.SECTION, "").removeprefix("Section "),
                printed.get(ast.AvpColumn.TYPE, ""),
            ),
            name,
        )

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
            if re.fullmatch(r"Note \d+", section) and self.quirks.enabled(
                "note-avp-origins"
            ):
                self.noted.append(
                    (section, name, int(code) if code else None, data_type)
                )
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
            data_type=_data_type(data_type, self.quirks) if data_type else None,
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

    def __init__(self, quirks: sources.Quirks) -> None:
        self.quirks = quirks
        self.shape: _Columns | None = None
        self.rows: list[ast.AvpTableRow] = []
        self.pending: _PendingRow | None = None
        self.header_lines: list[str] | None = None
        self.source: tuple[str | None, int | None] | None = None
        self.closed = False
        self.after_table_prose = False
        self.row_indent: int | None = None
        self.noted: list[tuple[str, str, int | None, str]] = []

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
            if self.quirks.enabled(
                "mixed-table-borders"
            ) and line.text.lstrip().startswith("|"):
                # RFC 5580 clause 6 boxes the data but only the flags in the header.
                text = line.text
                self.quirks.fire("mixed-table-borders")
            if _is_separator(text, self.quirks):
                if self.header_lines:
                    shape = _read_header(self.header_lines)
                    if self.shape is not None and shape != self.shape:
                        raise ExtractionError(
                            "AVP table continuation declares different columns"
                        )
                    self.shape = shape
                    self.header_lines = None
                    self.row_indent = None
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
            # wrapped name continuations, printing the fragment outside the
            # table box. Only a single token while a row is pending can be
            # one — but reading loose text into a name is a declared quirk,
            # because on any other document it would silently mangle a name.
            if self.pending is not None and len(text.split()) == 1:
                if not self.quirks.enabled("bare-name-continuation"):
                    raise ExtractionError(
                        f"name continuation {text.strip()!r} printed outside"
                        " the table box, which this document's source"
                        " declaration does not accept (the"
                        " `bare-name-continuation` quirk)"
                    )
                self.quirks.fire("bare-name-continuation")
                assert self.shape is not None
                self.pending.add_left(text.split(), text, self.shape)
            elif self.rows and self.pending is None:
                self.after_table_prose = True
            return
        if _is_separator(text, self.quirks):
            self._finish_pending()
            return
        assert self.shape is not None
        left, *cells = text.split("|")
        if cells and cells[-1] == "":
            cells.pop()  # the trailing pipe
        count = len(self.shape.cell_columns)
        if len(cells) != count + self.shape.flag_count:
            if (
                len(cells) == 1
                and not left.strip()
                and self.pending is None
                and self.quirks.enabled("boxed-table-legend")
            ):
                self.quirks.fire("boxed-table-legend")
                return
            raise ExtractionError(
                f"AVP table row with {len(cells) - count} flag cells for"
                f" {self.shape.flag_count} flag columns: {text!r}"
            )
        data, flags = cells[:count], cells[count:]
        indent = len(left) - len(left.lstrip())
        # Names start where the first row does, which RFC 5866 clause 7.2 and
        # RFC 6736 print one column left of the header's label: flush against
        # the box, so that a wrapped name's continuation there sits at the
        # label's own column (`|NAT-Control-  602` over `| Binding-Template`).
        if self.row_indent is None and left.strip():
            self.row_indent = min(indent, self.shape.name_indent)
        if self.shape.boxed:
            # Every column boxed, a wrapped name's continuation is the line
            # with its other cells blank (RFC 6736 table 2).
            starts = bool(left.strip()) and any(
                cell.strip() for cell in [*data, *flags]
            )
        else:
            starts = (
                bool(left.strip())
                and self.row_indent is not None
                and indent <= self.row_indent
            )
        if starts and not (self.pending is not None and self.pending.ignored):
            self._finish_pending()
        if self.pending is None:
            self.pending = _PendingRow(self.quirks, noted=self.noted)
        if self.shape.boxed:
            self.pending.add_cells(left.strip(), data, self.shape)
        else:
            self.pending.add_left(left.split(), text, self.shape)
        self.pending.add_flags(flags, text)

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


# A boxed header naming no caption: RFC 4740's tables 2 and 3 are captioned
# below the table, and RFC 6736 stacks "AVP", "Flag", "rules" over its flags,
# so no line of theirs says "AVP Flag". What makes one a table of AVPs and not
# of occurrences (RFC 6736's `| Attribute Name  NCR  NCA |`) is its next cell.
_BOXED_HEADER_RE = re.compile(r"^\s*\|\s*Attribute Name\b[^|]*\|\s*(?:MUST|AVP)\b")
_SIMPLE_TABLE_HEADER_RE = re.compile(
    # RFC 5624 clause 5.1 heads the name column "AVP Name".
    r"\|\s*(?:Attribute|AVP) Name\s+(?:AVP\s+)?Code\s+Defined\s+Data Type\s*\|",
    re.IGNORECASE,
)


def _simple_avp_tables(
    lines: list[_Line], headings: dict[str, _Line], quirks: sources.Quirks
) -> tuple[ast.AvpTable, ...]:
    """Read IANA-style AVP allocation tables that have no flag columns.

    RFC 5777 and RFC 5624 print one wide pipe-delimited table with Name, Code,
    Section, and Data Type.  It is every bit as authoritative as an application AVP
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
                    data_type=_data_type(data_type, quirks),
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


# RFC 7075 clause 3.3 is titled "The Redirect-Realm AVP". Only a defining
# sentence reads this title: its clause holds no rule to anchor.
_CLAUSE_TITLE_RE = re.compile(
    r"^(?:The )?(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)(?: AVP)?$"
)
_CLAUSE_AVP_RE = re.compile(
    r"\b(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*) AVP\s*"
    # RFC 7075 clause 3.3 prints the code alone: "The Redirect-Realm AVP (620)".
    r"\((?P<identity>(?:[^)]*?(?:Code|Type)\s+)?(?P<code>\d+)[^)]*)\)"
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


def _clause_facts(
    sections: list[_DocSection], quirks: sources.Quirks
) -> list[_ClauseFact]:
    """The Name/Code/Type facts stated by name-titled defining clauses.

    Strictly anchored: the sentence must sit under a clause titled with the
    same name it defines. A code annotated with another RFC is an imported
    AVP and is deliberately excluded.
    """
    # RFC 6734 clause 3.1.5 titles Key-SPI without the optional AVP suffix.
    facts = []
    for section in sections:
        title = _CLAUSE_TITLE_RE.match(section.title)
        if title is None:
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
                data_type=_data_type(match["data_type"], quirks),
            )
        )
    return facts


def _clause_avp_table(
    sections: list[_DocSection], quirks: sources.Quirks
) -> ast.AvpTable | None:
    """Build the AVP index for RFCs that define AVPs clause-by-clause.

    RFCs 4072 and 5447 have no summary table.  Their definition sentences are
    regular and carry the same Name/Code/Section/Type facts, so collect those
    facts into the format's AVP index.  Gated by the `clause-avp-table`
    quirk: which sentences are definitions rather than discussion is exactly
    the judgement a prose reading can get wrong on a document it was not
    written for.
    """
    facts = _clause_facts(sections, quirks)
    if not facts:
        return None
    rows = []
    cleared = quirks.enabled("prose-cleared-flags")
    for fact in facts:
        flags = ast.AvpFlagRules()
        if cleared:
            prose = " ".join(text.strip() for text in fact.section.texts)
            if "This AVP has the 'M' and 'V' bits cleared." not in prose:
                raise ExtractionError(
                    f"{fact.section.number}: no explicit cleared M/V bits"
                )
            flags = ast.AvpFlagRules(
                must_not=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR})
            )
            quirks.fire("prose-cleared-flags")
        rows.append(
            ast.AvpTableRow(
                name=fact.name,
                code=fact.code,
                section=fact.section.number,
                data_type=fact.data_type,
                flag_rules=flags,
            )
        )
    first = facts[0].section
    return ast.AvpTable(
        source=ast.SourceRef(section=first.number, page=first.page),
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
            *((ast.AvpColumn.MUST_NOT,) if cleared else ()),
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
    facts = {fact.name: fact for fact in _clause_facts(sections, quirks)}
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


def _flags_only(table: ast.AvpTable) -> bool:
    """A table stating no fact of a row but its flag rules (RFC 4740 table 3)."""
    return not {
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
    } & set(table.columns)


def _join_split_tables(
    tables: tuple[ast.AvpTable, ...], quirks: sources.Quirks
) -> tuple[ast.AvpTable, ...]:
    """Fold a flags-only table onto the table before it, name by name (the
    `split-avp-tables` quirk). RFC 4740 prints codes, clauses and types in
    table 2 and "expands" them with flag rules in table 3, one AVP per row in
    both; read apart, neither is a whole row. Every name must be in both."""
    joined: list[ast.AvpTable] = []
    for table in tables:
        if not _flags_only(table):
            joined.append(table)
            continue
        if not quirks.enabled("split-avp-tables"):
            raise ExtractionError(
                f"{table.source.section}: a table of names and flag rules alone,"
                " which this document's source declaration does not join onto"
                " the table before it (the `split-avp-tables` quirk)"
            )
        if not joined:
            raise ExtractionError(
                f"{table.source.section}: a flag-rules table with no table before it"
            )
        target = joined[-1]
        flags = {row.name: row for row in table.rows}
        names = [row.name for row in target.rows]
        if sorted(flags) != sorted(names) or len(flags) != len(table.rows):
            raise ExtractionError(
                f"{table.source.section}: the flag-rules table's names differ from"
                f" those of the table in {target.source.section}:"
                f" {sorted(set(flags) ^ set(names))}"
            )
        quirks.fire("split-avp-tables")
        joined[-1] = target.model_copy(
            update={
                "columns": (*target.columns, *table.columns[1:]),
                "rows": tuple(
                    row.model_copy(
                        update={
                            "flag_rules": flags[row.name].flag_rules,
                            "may_encrypt": flags[row.name].may_encrypt,
                        }
                    )
                    for row in target.rows
                ),
            }
        )
    return tuple(joined)


# Behind `reused-avp-tables`, RFC 6736 clause 8.3: "the AVPs reused from the
# Diameter Network Access Server Application [RFC4005]". The reference tag is the
# clause's own; a tag naming a document by publisher is read into a reference.
_REUSED_TITLE_RE = re.compile(r"^Reused\b.*\bAVPs\b")
_REUSED_FROM_RE = re.compile(r"\bAVPs reused from\b[^.]*?\[(?P<tag>[^\]]+)\]")
_ETSI_TAG_RE = re.compile(r"^ETSI(?P<series>ES|TS)(?P<a>\d{3})(?P<b>\d{3})$")


def _origin_of_tag(tag: str) -> str:
    """The `SpecRef` a clause's reference tag names: `[ETSIES283034]` is
    `ETSI-ES283.034`, as a re-used row cites it."""
    if match := _ETSI_TAG_RE.match(tag):
        return f"ETSI-{match['series']}{match['a']}.{match['b']}"
    return tag


def _reused_row(
    name: str, origin: str, code: int | None, data_type: str, quirks: sources.Quirks
) -> ast.ReusedAvpRow:
    return ast.ReusedAvpRow(
        name=name,
        origin=origin,
        code=code,
        data_type=_data_type(data_type, quirks) if data_type else None,
    )


def _reused_tables(
    tables: tuple[ast.AvpTable, ...],
    sections: list[_DocSection],
    quirks: sources.Quirks,
) -> tuple[tuple[ast.AvpTable, ...], list[ast.ReusedAvps]]:
    """Move the tables under a `Reused ... AVPs` clause to re-used blocks (the
    `reused-avp-tables` quirk). What a row says of its AVP's code and type stays
    on the row, for the linter to compare; a re-used block has no column for
    the flags these tables restate, so they stay in the document."""
    by_number = {section.number: section for section in sections}
    own: list[ast.AvpTable] = []
    reused: list[ast.ReusedAvps] = []
    for table in tables:
        section = by_number.get(table.source.section)
        if section is None or not _REUSED_TITLE_RE.match(section.title):
            own.append(table)
            continue
        prose = " ".join(" ".join(text.split()) for text in section.texts)
        match = _REUSED_FROM_RE.search(prose)
        if match is None:
            raise ExtractionError(
                f"{section.number}: a re-used AVP table whose clause names no origin"
            )
        origin = _origin_of_tag(match["tag"])
        quirks.fire("reused-avp-tables")
        reused.append(
            ast.ReusedAvps(
                table=section.number,
                source=table.source,
                columns=(
                    ast.ReusedColumn.NAME,
                    ast.ReusedColumn.CODE,
                    ast.ReusedColumn.FROM,
                    ast.ReusedColumn.TYPE,
                ),
                rows=tuple(
                    ast.ReusedAvpRow(
                        name=row.name,
                        origin=origin,
                        code=row.code,
                        data_type=row.data_type,
                    )
                    for row in table.rows
                ),
            )
        )
    return tuple(own), reused


# Behind `note-avp-origins`, RFC 6738 clause 8: "Note 1: The Key, Keying-Material,
# Key-Lifetime, Key-SPI, and Key-Type AVPs are defined in [RFC6734]."
_NOTE_ORIGIN_RE = re.compile(
    r"(?P<note>Note \d+): The (?P<names>[^.]+?) AVPs? (?:is|are) defined in"
    r" \[(?P<origin>RFC\d+)\]"
)


def _noted_origins(
    reader: _TableReader,
    table: ast.AvpTable,
    sections: list[_DocSection],
    quirks: sources.Quirks,
) -> ast.ReusedAvps | None:
    """The rows a table's Defined column points at a note for, read as re-used
    (the `note-avp-origins` quirk). The note must name every such row."""
    if not reader.noted:
        return None
    section = next(s for s in sections if s.number == table.source.section)
    prose = " ".join(" ".join(text.split()) for text in section.texts)
    notes: dict[str, tuple[str, str]] = {}
    for match in _NOTE_ORIGIN_RE.finditer(prose):
        for name in re.split(r",\s*(?:and\s+)?|\s+and\s+", match["names"]):
            notes[name] = (match["note"], match["origin"])
    rows = []
    for note, name, code, data_type in reader.noted:
        if notes.get(name, (None, ""))[0] != note:
            raise ExtractionError(f"{section.number}: {note} does not name {name}")
        rows.append(_reused_row(name, notes[name][1], code, data_type, quirks))
        quirks.fire("note-avp-origins")
    return ast.ReusedAvps(
        table=section.number,
        source=table.source,
        columns=(
            ast.ReusedColumn.NAME,
            ast.ReusedColumn.CODE,
            ast.ReusedColumn.FROM,
            ast.ReusedColumn.TYPE,
        ),
        rows=tuple(rows),
    )


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
            if text.strip() not in ("Type", "Type:"):
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
            elif match := re.fullmatch(
                r"(?P<code>\d+) - " + re.escape(title["name"]) + r"(?: Attribute)?",
                following,
            ):
                # RFC 5580 clauses 4.1-4.7 explicitly label each Type number.
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
    quirks: sources.Quirks | None = None,
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
        values = []
        unread: list[str] = []
        index = 0
        while index < len(section.texts):
            text = section.texts[index]
            index += 1
            value = _enum_value(text.strip()) or _quirk_enum_value(text.strip(), quirks)
            if value is None and _VALUE_FIRST_LINE_RE.match(text):
                value, index = _worded_value_first(section.texts, index, quirks)
            if value is not None:
                values.append(value)
            elif _VALUE_FIRST_LINE_RE.match(text):
                unread.append(text.strip())
        row = enum_rows.get(title["name"])
        values_source = (
            _values_source(section, quirks)
            if row is not None and row.code is not None and quirks is not None
            else None
        )
        if not values and values_source is None:
            continue
        if row is None or row.code is None:
            if title["avp_suffix"]:
                warnings.append(
                    f"{section.number}: {title['name']!r} lists enumerated"
                    " values but is not an Enumerated row of this RFC's AVP"
                    " table — values dropped"
                )
            continue
        if unread:
            # A value-first list whose labels the readings above leave out
            # (RFC 4005's worded labels, before `worded-enum-values` read
            # them) is said aloud rather than left a silently partial list.
            warnings.append(
                f"{section.number}: enumerated AVP {title['name']!r}:"
                f" {len(unread)} value line(s) not read, first {unread[0]!r}"
            )
        defined_enums.add(title["name"])
        definitions.append(
            ast.EnumeratedAvp(
                name=title["name"],
                source=source,
                code=row.code,
                vendor_id=None,
                values_source=values_source,
                values=tuple(values),
            )
        )
    by_number = {section.number: section for section in sections}
    for name in sorted(enum_rows.keys() - defined_enums):
        row = enum_rows[name]
        clause = by_number.get(row.section or "")
        definition = None
        if quirks is not None and clause is not None and row.code is not None:
            definition = _mapped_values(
                name, row.code, clause, quirks
            ) or _registry_values(name, row.code, clause, sections, quirks)
        if definition is not None:
            definitions.append(definition)
            continue
        warnings.append(f"enumerated AVP {name!r}: no value list found in its clause")
    return messages, definitions


# Behind `cause-mapping-table`, RFC 4005 clause 9.3.5's table mapping RADIUS
# Acct-Terminate-Cause values onto Termination-Cause's: the cause in words,
# the RADIUS value, the Diameter value, and a closing reference tag on four
# rows (`Supplicant Restart | 19 | 29 |  [RAD802.1X]`), which is the row's
# citation, not its name.
_CAUSE_MAPPING_HEADER_RE = re.compile(
    r"^\s*Cause Value Name\s+\|\s*RADIUS\s*\|\s*Diameter\s*\|\s*$"
)
_CAUSE_MAPPING_ROW_RE = re.compile(
    r"^\s*(?P<name>\S.*?)\s+\|\s*(?P<radius>\d+)\s*\|\s*(?P<diameter>\d+)\s*\|"
    r"(?:\s*\[[^\]]+\])?\s*$"
)


def _table_rows(
    texts: list[str], header: re.Pattern[str], row: re.Pattern[str], where: str
) -> list[re.Match[str]]:
    """The rows of the one fixed-width table under `header` in a clause: the
    separator after the header is skipped, and every line up to the first
    blank or separator line must be a row."""
    starts = [index for index, text in enumerate(texts) if header.match(text)]
    if len(starts) != 1:
        return []
    rows: list[re.Match[str]] = []
    for text in texts[starts[0] + 1 :]:
        stripped = text.strip()
        if not rows and stripped.startswith("-"):
            continue
        if not stripped or stripped.startswith("-"):
            break
        match = row.match(text)
        if match is None:
            raise ExtractionError(f"{where}: unreadable table row {stripped!r}")
        rows.append(match)
    if not rows:
        raise ExtractionError(f"{where}: a table header with no rows")
    return rows


def _mapped_values(
    name: str, code: int, clause: _DocSection, quirks: sources.Quirks
) -> ast.EnumeratedAvp | None:
    """The values of an Enumerated row's clause that maps RADIUS causes onto
    them (`cause-mapping-table`): the worded cause the name, the Diameter
    column the value. The RADIUS column is the translation, not this AVP's."""
    if not quirks.enabled("cause-mapping-table"):
        return None
    rows = _table_rows(
        clause.texts, _CAUSE_MAPPING_HEADER_RE, _CAUSE_MAPPING_ROW_RE, clause.number
    )
    if not rows:
        return None
    quirks.fire("cause-mapping-table")
    return ast.EnumeratedAvp(
        name=name,
        source=ast.SourceRef(section=clause.number, page=clause.page),
        code=code,
        vendor_id=None,
        values=tuple(
            ast.EnumValue(name=row["name"], value=int(row["diameter"])) for row in rows
        ),
    )


# Behind `registry-enum-values`, RFC 5778 clause 9.5: "IANA has created a new
# registry, ... for use with the enumerated MIP6-Auth-Mode AVP", over a
# `Token | Value | Description` table.
_REGISTRY_FOR_RE = re.compile(r"for use with the enumerated (?P<name>\S+) AVP")
_REGISTRY_HEADER_RE = re.compile(r"^\s*Token\s+\|\s*Value\s+\|\s*Description\s*$")
_REGISTRY_ROW_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s+\|\s*(?P<value>\d+)\s*\|\s*\S.*$"
)
# The section's allocation policy reserving values the table does not list:
# "The value 0 (zero) is reserved, and the maximum value is 4294967295".
_REGISTRY_RESERVED_RE = re.compile(r"The value (?P<value>\d+)(?: \(\w+\))? is reserved")


def _registry_values(
    name: str,
    code: int,
    clause: _DocSection,
    sections: list[_DocSection],
    quirks: sources.Quirks,
) -> ast.EnumeratedAvp | None:
    """The values of an Enumerated AVP from the IANA section that numbers
    them (`registry-enum-values`). The definition's `; Section:` is the IANA
    one, where the values are printed; every token must be one the defining
    clause names, so the registry supplies numbers and no values of its own.
    A value the section reserves is a reserved range, in value order."""
    if not quirks.enabled("registry-enum-values"):
        return None
    found = []
    for section in sections:
        prose = " ".join(" ".join(text.split()) for text in section.texts)
        if any(match["name"] == name for match in _REGISTRY_FOR_RE.finditer(prose)):
            found.append(section)
    if not found:
        return None
    if len(found) > 1:
        raise ExtractionError(
            f"{name}: {len(found)} registries for its values:"
            f" {[section.number for section in found]}"
        )
    registry = found[0]
    rows = _table_rows(
        registry.texts, _REGISTRY_HEADER_RE, _REGISTRY_ROW_RE, registry.number
    )
    if not rows:
        raise ExtractionError(f"{registry.number}: no value table for {name}")
    prose = " ".join(clause.texts)
    for row in rows:
        if not re.search(rf"\b{re.escape(row['name'])}\b", prose):
            raise ExtractionError(
                f"{registry.number}: {row['name']!r} is not named in {name}'s"
                f" clause {clause.number}"
            )
    quirks.fire("registry-enum-values")
    registry_prose = " ".join(" ".join(text.split()) for text in registry.texts)
    values: list[ast.EnumEntry] = [
        ast.EnumValue(name=row["name"], value=int(row["value"])) for row in rows
    ]
    values += [
        ast.ReservedValues(first=int(match["value"]), last=int(match["value"]))
        for match in _REGISTRY_RESERVED_RE.finditer(registry_prose)
    ]
    return ast.EnumeratedAvp(
        name=name,
        source=ast.SourceRef(section=registry.number, page=registry.page),
        code=code,
        vendor_id=None,
        values=tuple(sorted(values, key=_value_order)),
    )


def _value_order(value: ast.EnumEntry) -> int:
    return value.value if isinstance(value, ast.EnumValue) else value.first


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


# A value-first list line (`2   ISDN Sync`, RFC 4005 clause 4.4): a number,
# then the label after two spaces or more. Only for reporting what
# `_enum_value` left unread inside an enumerated clause.
_VALUE_FIRST_LINE_RE = re.compile(r"^\s*\d+ {2,}\S")
_WORDED_NAME = r"[A-Za-z][A-Za-z0-9_-]*(?: [A-Za-z0-9_-]+)+"


# Behind `worded-enum-values`, a value-first line whose label is words, RFC
# 4005's informational lists: `2   ISDN Sync` (clause 4.4), `3  AppleTalk
# Remote Access Protocol (ARAP)` (6.10.1). A closing reference tag is the
# value's citation, not its name (`17  Authorize Only  [RADDynAuth]`, 6.1),
# as it is for a one-word label.
_WORDED_VALUE_FIRST_RE = re.compile(
    r"^(?P<indent>\s*)(?P<value>\d+)(?P<gap> {2,})(?P<label>\S.*?)"
    r"(?:\s+\[[^\]]+\])?$"
)


def _worded_value_first(
    texts: list[str], index: int, quirks: sources.Quirks | None
) -> tuple[ast.EnumValue | None, int]:
    """The worded value-first line at `index - 1`, with the lines that wrap
    its label: those indented past the label's first character (`12   ADSL-CAP
    - Asymmetric DSL, Carrierless Amplitude Phase` over `Modulation`, RFC 4005
    clause 4.4). Returns the value, or None, and where reading resumes."""
    if quirks is None or not quirks.enabled("worded-enum-values"):
        return None, index
    match = _WORDED_VALUE_FIRST_RE.match(texts[index - 1])
    if match is None:
        return None, index
    column = match.start("label")
    label = [match["label"]]
    while index < len(texts):
        text = texts[index]
        indent = len(text) - len(text.lstrip())
        if not text.strip() or indent <= column:
            break
        label.append(text.strip())
        index += 1
    quirks.fire("worded-enum-values")
    return ast.EnumValue(name=" ".join(label), value=int(match["value"])), index


def _quirk_enum_value(text: str, quirks: sources.Quirks | None) -> ast.EnumValue | None:
    """The value-line shapes read only where a quirk declares them. A line
    needing two quirks is read only with both."""
    if quirks is None:
        return None
    parenthesized = quirks.enabled("parenthesized-enum-values")
    worded = quirks.enabled("worded-enum-values")
    fired: tuple[str, ...] = ()
    match = None
    if parenthesized and (
        match := re.fullmatch(
            r"(?P<name>[A-Za-z][A-Za-z0-9_-]*) \((?P<value>\d+)\)", text
        )
    ):
        fired = ("parenthesized-enum-values",)
    elif (
        parenthesized
        and worded
        and (
            match := re.fullmatch(rf"(?P<name>{_WORDED_NAME}) \((?P<value>\d+)\)", text)
        )
    ):
        fired = ("parenthesized-enum-values", "worded-enum-values")
    elif worded and (
        match := re.fullmatch(rf"(?P<name>{_WORDED_NAME}) {{2,}}(?P<value>\d+)", text)
    ):
        fired = ("worded-enum-values",)
    elif quirks.enabled("bulleted-enum-values") and (
        match := re.fullmatch(
            r"o\s+(?P<name>[A-Z][A-Z0-9_-]*) \((?P<value>\d+)\)(?:\s+\S.*)?", text
        )
    ):
        fired = ("bulleted-enum-values",)
    elif quirks.enabled("parenthesized-value-first") and (
        match := re.fullmatch(
            r"\((?P<value>\d+)\): (?P<name>[A-Za-z][A-Za-z0-9_-]*)", text
        )
    ):
        fired = ("parenthesized-value-first",)
    if match is None:
        return None
    for name in fired:
        quirks.fire(name)
    return ast.EnumValue(name=match["name"], value=int(match["value"]))


# Behind `external-enum-values`: an enumerated clause saying where its values
# are listed, one pattern per wording, matched on the clause's prose joined
# into one line. What the source group holds is the document's own words up
# to the sentence's end, reference tags included.
_VALUES_SOURCE_RES = (
    # RFC 7155 clause 4.6.6: "The supported values are listed in
    # [RADIUSAttrVals]."; 4.2.4: "The currently supported values of the
    # NAS-Port-Type AVP are listed in [RADIUSAttrVals]."; RFC 4005 clause
    # 6.14.2: "... listed in [RADIUSTypes] and defined in [RADIUSExt]."; RFC
    # 6733 clause 8.15: "The currently assigned values for this AVP can be
    # found in the IANA registry for Termination-Cause AVP Values [IANATCV]."
    re.compile(
        r"The (?:currently )?(?:supported|assigned) values"
        r"(?: of the \S+ AVP| for this AVP)? (?:are|can be) (?:listed|defined|found)"
        r" in (?P<source>[^.]+)\."
    ),
    # RFC 7155 clause 4.4.1: "The complete list of defined values that the
    # Service-Type AVP can take can be found in [RFC2865] and the relevant
    # IANA registry [RADIUSAttrVals], but the following values require
    # further qualification here:"; RFC 4005 clause 6.1 without the clause.
    re.compile(
        r"The complete list of defined values(?: that the \S+ AVP can take)?"
        r" can be found in (?P<source>[^.,]+)[.,]"
    ),
    # RFC 5777 clauses 4.1.3, 4.1.8.1, 4.1.8.4, 4.1.8.7, 4.1.8.12, 4.1.8.13:
    # "The values are managed by IANA under the Differentiated Services Field
    # Codepoints registry as defined in [RFC2474]."
    re.compile(r"values (?:for this AVP )?are managed by (?P<source>IANA [^.]+)\."),
    # RFC 7155 clause 4.6.7: "(Note that this AVP is semantically equivalent,
    # and the supported values are identical, to the Microsoft
    # MS-Acct-Auth-Type vendor-specific RADIUS attribute [RFC2548])."
    re.compile(r"the supported values are identical, to (?P<source>[^.()]+)\)\."),
    # RFC 5778 clause 6.13: "Existing algorithm types are defined in
    # [RFC4004] that also fulfill current RFC 4285 requirements."
    re.compile(r"Existing algorithm types are defined in (?P<source>[^.]+)\."),
)


def _values_source(section: _DocSection, quirks: sources.Quirks) -> str | None:
    """Where the enumerated clause says its values are listed, if it says so
    in one of the wordings `_VALUES_SOURCE_RES` reads."""
    if not quirks.enabled("external-enum-values"):
        return None
    prose = " ".join(" ".join(text.split()) for text in section.texts if text.strip())
    found = [
        match["source"]
        for pattern in _VALUES_SOURCE_RES
        for match in pattern.finditer(prose)
    ]
    if len(found) > 1:
        raise ExtractionError(
            f"{section.number}: the clause names {len(found)} sources for its"
            f" values: {found}"
        )
    if not found:
        return None
    quirks.fire("external-enum-values")
    return found[0]


def _message_abbreviation(section: _DocSection, rule_name: str) -> str:
    """Find the 2-6 letter command abbreviation for a plain command title.

    Base-protocol RFCs put the abbreviation on the left-hand side of the rule
    (``<CER> ::=``).  Application RFCs commonly put the long name there and
    introduce ``(DER)`` or ``(MIR)`` in the prose above it.
    """
    if re.fullmatch(r"[A-Z]{2,6}", rule_name):
        return rule_name
    name = re.escape(section.title)
    prose = " ".join(text.strip() for text in section.texts)
    if match := re.search(rf"\b{name}\s+\((?P<abbr>[A-Z]{{2,6}})\)", prose):
        return match["abbr"]
    raise ExtractionError(
        f"{section.number}: cannot find an abbreviation for command {section.title!r}"
    )


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


def _prose_avp_origins(
    sections: list[_DocSection],
    tables: tuple[ast.AvpTable, ...],
    quirks: sources.Quirks,
) -> list[ast.ReusedAvps]:
    """Explicit definition citations, retaining the citing table's facts."""
    reused = []
    for table in tables:
        rows = []
        for row in table.rows:
            for section in sections:
                if section.number != row.section:
                    continue
                text = " ".join(line.strip() for line in section.texts)
                match = re.match(
                    rf"\s*The {re.escape(row.name)} AVP"
                    r"(?: \(AVP Code \d+\))? is defined in \[(RFC\d+)\]",
                    text,
                )
                if match is not None:
                    rows.append(ast.ReusedAvpRow(name=row.name, origin=match[1]))
                    quirks.fire("prose-avp-origins")
        if rows:
            reused.append(
                ast.ReusedAvps(
                    table=table.table or table.source.section,
                    source=table.source,
                    columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
                    rows=tuple(rows),
                )
            )
    return reused


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
        patcher, quirks = sources.load(declarations_path, None, QUIRKS, warnings)

        readers: list[_TableReader] = []
        reader: _TableReader | None = None
        lines, headings = _content_lines(raw, patcher)
        for number, line in enumerate(lines):
            caption = "avp flag" in line.text.casefold() and "|" in line.text
            boxed = _BOXED_HEADER_RE.match(line.text) is not None and (
                reader is None or reader.header_lines is None
            )
            if caption or boxed:
                # `; Page:` is where the section starts, not where the table
                # does — the two differ when a table opens on the next page.
                if reader is not None and reader.open and reader.after_table_prose:
                    reader.close()
                if reader is None or reader.closed:
                    reader = _TableReader(quirks)
                    readers.append(reader)
                heading = headings.get(line.section or "")
                reader.start_header(line, heading.page if heading else line.page)
                if caption:
                    continue
                # A label stacked above the first line this one opens with:
                # RFC 6736 prints "AVP" over "Code" there.
                above = lines[number - 1].text if number else ""
                if above.lstrip().startswith("|"):
                    reader.read(lines[number - 1])
                reader.read(line)
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
        noted = [
            origin
            for candidate in readers
            if (table := candidate.result_optional()) is not None
            and (origin := _noted_origins(candidate, table, document_sections, quirks))
            is not None
        ]
        tables = _join_split_tables(tables, quirks)
        moved: list[ast.ReusedAvps] = []
        if quirks.enabled("reused-avp-tables"):
            tables, moved = _reused_tables(tables, document_sections, quirks)
        tables += _simple_avp_tables(lines, headings, quirks)
        if quirks.enabled("prose-avp-codes"):
            tables = _complete_rows_from_prose(
                tables, document_sections, quirks, warnings
            )
        if quirks.enabled("clause-avp-table") and (
            clause_table := _clause_avp_table(document_sections, quirks)
        ):
            quirks.fire("clause-avp-table", len(clause_table.rows))
            tables += (clause_table,)
        if quirks.enabled("radius-attribute-table") and (
            radius_table := _radius_attribute_table(document_sections)
        ):
            quirks.fire("radius-attribute-table", len(radius_table.rows))
            tables += (radius_table,)
        if quirks.enabled("radius-avp-codes"):
            index = _radius_attribute_table(document_sections)
            if index is None:
                raise ExtractionError("no RADIUS attribute codes found")
            by_name = {row.name: row for row in index.rows}
            completed = []
            for table in tables:
                rows = []
                for row in table.rows:
                    fact = by_name.get(row.name)
                    if fact is None or row.code is not None:
                        raise ExtractionError(
                            f"cannot derive RADIUS code for {row.name}"
                        )
                    rows.append(
                        row.model_copy(
                            update={"code": fact.code, "section": fact.section}
                        )
                    )
                    quirks.fire("radius-avp-codes")
                completed.append(
                    table.model_copy(
                        update={
                            "rows": tuple(rows),
                            "columns": (
                                *table.columns,
                                ast.AvpColumn.CODE,
                                ast.AvpColumn.SECTION,
                            ),
                        }
                    )
                )
            tables = tuple(completed)
        messages, definitions = _extract_definitions(
            document_sections, tables, warnings, quirks
        )
        reused = (
            _prose_avp_origins(document_sections, tables, quirks)
            if quirks.enabled("prose-avp-origins")
            else []
        )
        quirks.finish()
        # File order matches the docx extractor's: messages in document order,
        # the AVP table, then every definition in document order.
        definitions.sort(
            key=lambda definition: ast.section_sort_key(definition.source.section)
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
                *moved,
                *noted,
                *reused,
                *definitions,
            ),
        )
