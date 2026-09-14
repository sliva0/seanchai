"""Extractor: 3GPP .docx specification → `.dad` AST.

Pipeline stage one of two: this module walks the docx body (paragraphs and
tables in document order, grouped under numbered headings) and produces a
`Specification`. Pages are attached afterwards by `attach_pages`, which reads
only the bookmark outline of the matching ETSI PDF rendering.

All source text is normalized exactly once, while building the section model,
and input patches (see `patches.py`) are applied at that same point — so
patch application counting is exact, and every later parsing step sees
patched text.

What maps to what in a 3GPP Diameter spec docx:

- `x.y.z Name (ABBR) Command` headings with a `::= < Diameter Header: ... >`
  paragraph run → `Message`; per-run bold marks this-spec AVPs.
- `x.y.z Name AVP` headings with an `::= < AVP header: ... >` run → `GroupedAvp`.
- `x.y.z Name AVP` headings whose intro says "is of type Enumerated" with
  `B1`-style `ValueName (n)` items → `EnumeratedAvp`; `B2` items are value
  descriptions, `NO`-style "Value n is reserved" notes → reserved values,
  inserted in numeric order.
- The AVP-flags table (header "AVP Flag rules") → `AvpTable`; rows whose code
  cell is a NOTE reference get `code=None`, and note texts naming a defining
  RFC additionally produce `ReusedAvps` rows (the `note-defined-in-rfc`
  quirk).
- The "re-used Diameter AVPs" table → `ReusedAvps` rows with M-bit overrides.

The vendor-id for locally defined AVPs is not printed by enumerated-AVP
sections, so it is taken from the spec's grouped-AVP headers (3GPP: 10415).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import docx
import docx.document
import docx.table
import docx.text.paragraph
import pydantic
import pypdf

from ..dad import abnf, ast
from . import sources
from .errors import ExtractionError, boundary
from .sources import Patcher

_HEADING_RE = re.compile(
    r"^(?P<number>(?:[A-Za-z]+|\d+[A-Za-z]*)(?:\.\d+[A-Za-z]*)*)\t(?P<title>.+)$"
)
_COMMAND_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) Command$"
)
_COMMAND_INTRO_RE = re.compile(
    r"^The (?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) command,"
)
# The " AVP" suffix is spec-dependent: 29.329 titles are "MSISDN AVP",
# 29.272 mostly bare "Subscription-Data". Bare titles like "General" also
# match — harmless, since a section only becomes a definition when its body
# holds an AVP-header rule or an Enumerated intro with a known code.
_AVP_TITLE_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)( AVP)?$")
_DIAMETER_HEADER_RE = re.compile(
    # The rule name is normalized separately: source docx sometimes carries
    # stray spaces inside it ("< User-Data -Request>").
    r"^<\s*(?P<name>[A-Za-z -]+?)\s*> ::=\s*<\s*Diameter Header:"
    r"\s*(?P<items>[0-9A-Z, ]+?)\s*>$"
)
_AVP_HEADER_RE = re.compile(
    # code/vendor separator varies between specs: "700 10415" and "632, 10415";
    # rule names can carry spaces for hyphens ("Monitoring Event Report::=")
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9 _-]*?)\s*::=\s*<\s*AVP [Hh]eader:\s*(?P<code>\d+)"
    r"(?:\s*,?\s+(?P<vendor>\d+))?\s*>$"
)
_ABNF_LINE_RE = re.compile(
    r"^(?:(?P<min>\d*)\*(?P<max>\d*))?\s*"
    r"(?P<open>[<{\[])\s*(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)\s*(?P<close>[>}\]])$"
)
_ENUM_VALUE_RE = re.compile(r"^(?P<name>[A-Za-z0-9_-]+)\s*\((?P<value>\d+)\)$")
_RESERVED_NOTE_RE = re.compile(
    r"[Vv]alues? (?P<first>\d+)(?:\s*(?:-|to)\s*(?P<last>\d+))?\s+(?:is|are) reserved"
)
# 3GPP numbers its tables in at least five styles, and the corpus contains all
# of them: "Table 7.3.1/1" (29.229, 29.272, 29.329), "Table 6.3.1-1" (29.172,
# 29.283, 29.388, 29.389), "Table B.1.1" in annexes, and clause components that
# carry a letter, upper ("9A.2.1") or lower ("2a.1.1.1"). The label is inline
# text that only ever reaches `; Table:`, never anything that parses it, so
# this pattern's job is to recognise *that* a paragraph is a caption rather
# than to encode a numbering scheme — hence a general dotted token instead of a
# branch per style.
# The optional space before the colon is 29.061's "Table 20.5.1 : SGmb ...".
_TABLE_CAPTION_RE = re.compile(
    r"^Table (?P<label>[A-Za-z0-9]+(?:[.\-/][A-Za-z0-9]+)*) ?:"
)
# The spellings a table cell uses to point at a note below the table: bare
# "NOTE 1" (29.272 and most others) and parenthesized "(NOTE 3)" / "(Note 2)"
# (29.212, 29.214 name cells — 29.212 mixes both casings). The parenthesized
# form must strip as a whole, or "3GPP-RAT-Type (NOTE 3)" would be left as
# the non-name "3GPP-RAT-Type ()".
_NOTE_REF_RE = re.compile(
    r"\s*\(\s*(?:NOTE|Note)\s*(?P<number>\d+)\s*\)\s*"
    r"|\s*(?:NOTE|Note)\s*(?P<bare>\d+)\s*"
)
_NOTE_RFC_RE = re.compile(
    r"^NOTE\s*(?P<number>\d+):\s*The values? of th(?:is|ese) attributes? "
    r"is defined in IETF\s+RFC\s+(?P<rfc>\d+)"
)
_DOCX_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) V(?P<version>\d+(?:\.\d+)*)"
)
_PDF_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) version (?P<version>\d+(?:\.\d+)*)"
)
# The "3GPP" and "IETF" prefixes are conventional, not reliable: a re-used
# table's From cell is written by hand and 29.344 and 29.388 both spell it
# "TS 29.272 [10]", with the document's own bibliography number and no
# publisher. The number is what identifies the origin, so that is what these
# require.
# The series may be three digits with either separator: 29.212 spells an ETSI
# TISPAN document "3GPP TS 283 034", 29.214 spells one "3GPP TS 183.017".
_ORIGIN_TS_RE = re.compile(r"TS\s+(?P<series>\d{2,3})[. ](?P<number>\d{3})(?!\d)")
_ORIGIN_RFC_RE = re.compile(r"RFC\s+(?P<number>\d+)")
# 3GPP2 documents keep their publisher's numbering: "3GPP2 X.S0057 [24]".
_ORIGIN_3GPP2_RE = re.compile(r"3GPP2\s+(?P<number>[A-Z]\.[A-Z]\d{4})")
# A re-used table's From cell citing a clause of the same document
# ("6.4.2" in 29.336's S6t table, whose AVPs the S6m set defines).
_SECTION_REF_RE = re.compile(r"^(?:[A-Za-z]+|\d+[A-Za-z]*)(?:\.\d+[A-Za-z]*)*$")

# Every AVP a 3GPP specification defines is in 3GPP's vendor space. That is a
# fact about the publisher, not about any one document, so this extractor
# states it rather than reading it out of the text — the same way an RFC
# extractor will state the IETF's 0.
TGPP_VENDOR = 10415

_M_BIT_OVERRIDES = {
    "": None,
    # TS 29.338 uses the shorter forms in its re-used tables even though the
    # notes below those tables document only "Must set" and "Must not set".
    "Must": ast.MBitOverride.MUST,
    "Must set": ast.MBitOverride.MUST,
    "Must not": ast.MBitOverride.MUST_NOT,
    "Must not set": ast.MBitOverride.MUST_NOT,
}


def _normalize(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


@dataclass
class _Para:
    """A body paragraph: normalized+patched text, style name, and the docx
    paragraph (kept for run-level bold inspection)."""

    text: str
    style: str
    source: docx.text.paragraph.Paragraph


@dataclass
class _Row:
    cells: list[str]
    # The first cell's individual lines (normalized+patched) — merged
    # full-width NOTE rows hold one note per line.
    first_cell_lines: list[str]


@dataclass
class _Table:
    caption: str | None
    rows: list[_Row]


@dataclass
class _Section:
    """One numbered heading with the body content up to the next heading."""

    number: str
    title: str
    paragraphs: list[_Para] = field(default_factory=list)
    tables: list[_Table] = field(default_factory=list)


def _is_bold(paragraph: docx.text.paragraph.Paragraph) -> bool:
    # Word applies bold erratically to brackets/whitespace runs; only the runs
    # spelling the AVP name itself are trusted (`*{ `=True, `Data-Reference`=None,
    # ` }`=True occurs in real documents for a non-bold AVP).
    flags = {
        bool(run.bold)
        for run in paragraph.runs
        if any(char.isalnum() for char in run.text)
    }
    if len(flags) > 1:
        raise ExtractionError(f"mixed bold in ABNF line: {paragraph.text!r}")
    return flags.pop() if flags else False


def _sections(
    document: docx.document.Document,
    patcher: Patcher,
    quirks: sources.Quirks | None = None,
) -> list[_Section]:
    sections: list[_Section] = []
    current: _Section | None = None
    caption: str | None = None
    for item in document.iter_inner_content():
        number = current.number if current is not None else None
        if isinstance(item, docx.table.Table):
            if current is not None:
                rows = []
                spans: list[tuple[int, ...]] = []
                for row in item.rows:
                    # Merged cells appear repeatedly in row.cells (a full-width
                    # note row repeats one cell nine times); count each physical cell
                    # once. Per-line views of the first cell are duplicates of
                    # already-counted text, so they don't record either.
                    seen: dict[int, str] = {}
                    cells = []
                    row_spans = []
                    for cell in row.cells:
                        key = id(cell._tc)
                        if key not in seen:
                            seen[key] = patcher.apply(_normalize(cell.text), number)
                            row_spans.append(1)
                        else:
                            row_spans[-1] += 1
                        cells.append(seen[key])
                    spans.append(tuple(row_spans))
                    rows.append(
                        _Row(
                            cells=cells,
                            first_cell_lines=[
                                patcher.apply(_normalize(line), number, record=False)
                                for line in row.cells[0].text.splitlines()
                            ],
                        )
                    )
                # A table whose every row merges cells in the same pattern is
                # that many columns wide, full stop — 29.336's table 8.4.1-2
                # merges each of its four columns across two grid columns in
                # all 45 rows, so reading the grid would double every label
                # and cell. Collapsing only a table-wide uniform pattern keeps
                # the genuinely mixed cases intact: a full-width NOTE row or a
                # spanning header merges differently from its data rows, so
                # those tables keep their grid positions (and the positional
                # column mapping that relies on them).
                physical_reused = (
                    quirks is not None
                    and quirks.enabled("physical-reused-columns")
                    and "Reference" in rows[0].cells
                    and len({len(row.cells) for row in rows}) > 1
                )
                if physical_reused:
                    assert quirks is not None
                    quirks.fire("physical-reused-columns")
                if physical_reused or (
                    len(set(spans)) == 1 and any(span > 1 for span in spans[0])
                ):
                    for row, row_spans in zip(rows, spans, strict=True):
                        starts = []
                        position = 0
                        for span in row_spans:
                            starts.append(row.cells[position])
                            position += span
                        row.cells = starts
                current.tables.append(_Table(caption=caption, rows=rows))
            caption = None
            continue
        style = (item.style.name or "") if item.style else ""
        # TS 29.273 §6.2.2.1.1 uses the explicit H6 heading style.
        if style.startswith("Heading") or re.fullmatch(r"H[1-9]", style):
            match = _HEADING_RE.match(item.text.strip())
            if match:
                current = _Section(
                    number=match["number"],
                    title=patcher.apply(_normalize(match["title"]), match["number"]),
                )
                sections.append(current)
                continue
        text = patcher.apply(_normalize(item.text), number)
        if match := _TABLE_CAPTION_RE.match(text):
            caption = match["label"]
        if current is not None:
            current.paragraphs.append(_Para(text=text, style=style, source=item))
    return sections


def _abnf_body(
    paragraphs: list[_Para], start: int
) -> tuple[tuple[ast.AvpRule, ...], int]:
    """Parse `[qual] bracket Name bracket` lines starting at `start`."""
    rules = []
    index = start
    while index < len(paragraphs):
        paragraph = paragraphs[index]
        match = _ABNF_LINE_RE.match(paragraph.text)
        if match is None:
            break
        try:
            rules.append(abnf.avp_rule(match, bold=_is_bold(paragraph.source)))
        except abnf.AbnfError as error:
            raise ExtractionError(f"{error} in {paragraph.text!r}") from None
        index += 1
    return tuple(rules), index


def _find_rule_header(
    section: _Section, pattern: re.Pattern
) -> tuple[re.Match, int] | None:
    for index, paragraph in enumerate(section.paragraphs):
        if "::=" in paragraph.text:
            match = pattern.match(paragraph.text)
            if match is None:
                raise ExtractionError(
                    f"{section.number}: malformed rule header {paragraph.text!r}"
                )
            return match, index + 1
    return None


def _extract_messages(
    section: _Section,
    title: re.Match | None,
    warnings: list[str],
    quirks: sources.Quirks,
) -> list[ast.Message]:
    """A command section usually holds one ABNF, but can hold several — the
    same command under different application ids (TS 29.272 defines IDR/DSR/RSR
    once for S6a and once for S7a in one section)."""
    messages = []
    prose_title = title is None
    index = 0
    while index < len(section.paragraphs):
        text = section.paragraphs[index].text
        index += 1
        if prose_title and (intro := _COMMAND_INTRO_RE.match(text)):
            title = intro
        if "::=" not in text:
            continue
        header = _DIAMETER_HEADER_RE.match(text)
        if header is None:
            raise ExtractionError(f"{section.number}: malformed rule header {text!r}")
        if title is None:
            raise ExtractionError(
                f"{section.number}: command ABNF without a named intro"
            )
        if prose_title:
            quirks.fire("procedure-commands")
        rule_name = header["name"].replace(" ", "")
        if rule_name != title["name"]:
            # A real occurrence: TS 29.329 §6.1.8 heading says
            # "Push-Notifications-Answer", the rule "Push-Notification-Answer".
            # The rule name wins; the discrepancy is reported, not fatal.
            warnings.append(
                f"{section.number}: heading name {title['name']!r}"
                f" != rule name {rule_name!r}, using the rule name"
            )
        try:
            command_code, flags, application_id = abnf.diameter_header(header["items"])
        except abnf.AbnfError as error:
            raise ExtractionError(f"{section.number}: {error}") from None
        if application_id is None:
            warnings.append(
                f"{section.number}: {rule_name} header omits the application id"
            )
        avps, index = _abnf_body(section.paragraphs, index)
        messages.append(
            ast.Message(
                name=rule_name,
                abbreviation=title["abbr"],
                source=ast.SourceRef(section=section.number),
                command_code=command_code,
                flags=flags,
                application_id=application_id,
                avps=avps,
            )
        )
        if prose_title:
            title = None
    if not messages:
        # TS 29.273 §§4.2.2.4.3-4, 5.2.2.3.5-6 and 11.2.2.1.1-2
        # contain only a pointer to another clause, not a definition.
        paragraphs = [p.text for p in section.paragraphs if p.text]
        if (
            quirks.enabled("command-reference-only")
            and len(paragraphs) == 1
            and re.fullmatch(
                r"(?:Refer to|See) clause \d+(?:\.\d+)+"
                r"(?: of 3GPP TS \d{2}\.\d{3} \[\d+\])?\.?",
                paragraphs[0],
            )
        ):
            quirks.fire("command-reference-only")
            return []
        raise ExtractionError(f"{section.number}: command section without ABNF")
    return messages


def _extract_grouped(
    section: _Section, header: re.Match, body_start: int, name: str
) -> ast.GroupedAvp:
    vendor = header["vendor"]
    avps, _ = _abnf_body(section.paragraphs, body_start)
    return ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=int(header["code"]),
        vendor_id=None if vendor is None else int(vendor),
        avps=avps,
    )


def _extract_enumerated(
    section: _Section, name: str, code: int, vendor_id: int | None
) -> ast.EnumeratedAvp:
    values: list[ast.EnumValue] = []
    reserved: list[ast.ReservedValues] = []
    # A clause's explanatory prose is not captured as a value description; only
    # the value lines and the reserved-value notes are read.
    #
    # `EnumValue.description` is a one-line gloss, and a 3GPP clause does not
    # contain one. It contains paragraphs, with lead-ins ("This value is
    # used:"), nested bullet lists, NOTEs and caveats about the AVP rather than
    # about any one value. Any rule for flattening that onto a `;` comment
    # picks an arbitrary subset: the rule that used to live here took
    # paragraphs styled B1 or B2, which meant 29.272 §7.3.24 kept two bullets
    # while dropping the "This value is used:" that introduced them, and
    # 29.229 §6.3.15 kept "The request is generated in the following cases:"
    # and dropped the cases. `; Section:` points at the clause; a reader who
    # wants the prose reads it there, undamaged.
    for paragraph in section.paragraphs:
        text = paragraph.text
        if not text:
            continue
        if match := _ENUM_VALUE_RE.fullmatch(text):
            values.append(ast.EnumValue(name=match["name"], value=int(match["value"])))
        elif paragraph.style == "NO" and (match := _RESERVED_NOTE_RE.search(text)):
            first = int(match["first"])
            reserved.append(
                ast.ReservedValues(first=first, last=int(match["last"] or first))
            )
    merged = sorted(
        [*values, *reserved],
        key=lambda item: item.value if isinstance(item, ast.EnumValue) else item.first,
    )
    return ast.EnumeratedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=code,
        vendor_id=vendor_id,
        values=tuple(merged),
    )


def _strip_note_ref(text: str) -> tuple[str, str | None]:
    """Remove every note reference from a cell, keeping the first number —
    29.212 stacks two on one name cell ("Granted-Service-Unit (NOTE 5)
    (NOTE 7)")."""
    first: str | None = None
    while match := _NOTE_REF_RE.search(text):
        if first is None:
            first = match["number"] if match["number"] is not None else match["bare"]
        text = (text[: match.start()] + text[match.end() :]).strip()
    return text, first


# Clause cells in 29.061's tables annotate the number: "16.4.7 (see Note)",
# 37 times across two clauses in both spellings. A clause number has no
# syntax for parentheses, so a trailing parenthetical is almost certainly
# prose — but dropping text is a declared reading, the `clause-parenthetical`
# quirk, not an assumption.
_CLAUSE_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _clause_cell(text: str, quirks: sources.Quirks) -> str:
    if _CLAUSE_PARENTHETICAL_RE.search(text):
        if not quirks.enabled("clause-parenthetical"):
            raise ExtractionError(
                f"clause cell {text!r} carries a parenthetical, which this"
                " document's source declaration does not strip (the"
                " `clause-parenthetical` quirk)"
            )
        quirks.fire("clause-parenthetical")
        return _CLAUSE_PARENTHETICAL_RE.sub("", text)
    return text


# Both spellings of the Encrypt column, normalized to one on the way in. This
# is a document convention rather than a typo — TS 29.061, 29.212 and 29.214
# write "Y"/"N" throughout, the rest write "Yes"/"No" — and a convention is
# extractor code, not several hundred input patches.
_ENCRYPT_CELLS = {"Yes": True, "Y": True, "No": False, "N": False, "": None}


def _encrypt_cell(text: str) -> bool | None:
    if text not in _ENCRYPT_CELLS:
        raise ExtractionError(f"AVP table Encrypt cell {text!r}")
    return _ENCRYPT_CELLS[text]


def _data_type(text: str | None) -> ast.DataType | None:
    """Strict, like the flags cells: a type outside RFC 6733's closed set is a
    source typo ("Enumerate" in TS 29.272, "Enumarated" in TS 29.212), and
    typos are the input-patch layer's job."""
    if text is None:
        return None
    try:
        return ast.DataType(text)
    except ValueError:
        raise ExtractionError(f"AVP table Value Type cell {text!r}") from None


def _flags_cell(text: str, quirks: sources.Quirks) -> frozenset[ast.AvpFlag]:
    # Strict: typos like "M. V" or lowercase "v" are fixed by input patches,
    # not tolerated here. Space-less "M.V" is different — 29.061 writes it 11
    # times and 29.212 seven, so the period is those documents' separator
    # convention — but a convention is per-document, so reading it is the
    # declared `dotted-flags` quirk rather than a global rewrite.
    if not text:  # an empty table cell
        return frozenset()
    if "." in text and " " not in text:
        if not quirks.enabled("dotted-flags"):
            raise ExtractionError(
                f"flags cell {text!r} separates flags with periods, which"
                " this document's source declaration does not accept (the"
                " `dotted-flags` quirk)"
            )
        quirks.fire("dotted-flags")
        text = text.replace(".", ",")
    try:
        return abnf.avp_flags(text)
    except abnf.AbnfError as error:
        raise ExtractionError(str(error)) from None


# The nine columns 3GPP AVP tables share, keyed by the label they print. The
# same column is spelled differently across specifications — "Clause defined"
# and "Section defined", "May Encr." and "May Encrypt" — and the differences
# are typographic, not semantic.
_AVP_TABLE_COLUMNS = {
    "Attribute Name": ast.AvpColumn.NAME,
    "AVP Code": ast.AvpColumn.CODE,
    "Clause defined": ast.AvpColumn.SECTION,
    "Section defined": ast.AvpColumn.SECTION,
    "Value Type": ast.AvpColumn.TYPE,
    "Must": ast.AvpColumn.MUST,
    "May": ast.AvpColumn.MAY,
    "Should not": ast.AvpColumn.SHOULD_NOT,
    "Must not": ast.AvpColumn.MUST_NOT,
    "May Encr.": ast.AvpColumn.ENCRYPT,
    "May Encrypt": ast.AvpColumn.ENCRYPT,
}
# A column label may carry a note reference ("Value Type (NOTE 2)",
# "Applicability (notes 3, 9)"). The reference points at prose this format does
# not carry, so it is not part of the label.
_COLUMN_NOTE_RE = re.compile(r"\s*\((?:NOTE|Note|note)S?s?[^)]*\)$")


# Source columns the format has no counterpart for and does not want one for:
# they hold prose about how an AVP is used, which `.dad` does not carry.
# Dropping them silently is the point; anything *else* unmodelled gets a
# warning, because a column with machine-readable values is a reason to model
# it (see `ast._check_columns`).
_PROSE_COLUMNS = frozenset({"Comments", "Comment", "Description"})


def _map_columns[T](
    labels: list[str], known: dict[str, T], kind: str, warnings: list[str]
) -> tuple[tuple[T, ...], list[int]]:
    """Modelled columns in source order, plus the cell indices they sit at.

    A row is read positionally against the *source* table, so the indices are
    what lets unmodelled columns be skipped without disturbing the rest.
    """
    columns: list[T] = []
    positions: list[int] = []
    for index, label in enumerate(labels):
        stripped = _COLUMN_NOTE_RE.sub("", label).strip()
        if not stripped:
            # 29.212 prints one re-used table with a fourth, label-less
            # column whose cells are empty. Dropped like an unmodelled
            # column: visible in the warning, not fatal.
            warnings.append(f"{kind} column {index + 1} has no label and was dropped")
            continue
        if (column := known.get(stripped)) is not None:
            columns.append(column)
            positions.append(index)
        elif stripped not in _PROSE_COLUMNS:
            warnings.append(
                f"{kind} column {stripped!r} is not modelled and was dropped"
            )
    return tuple(columns), positions


def _walk_table[T](
    table: _Table,
    known: dict[str, T],
    kind: str,
    warnings: list[str],
    skip: Callable[[_Row], bool],
) -> tuple[tuple[T, ...], list[int], list[list[str]]]:
    """The row walk both table kinds share: the `Attribute Name` label row
    defines the columns, every later data row is width-checked against it.
    Returns the modelled columns, the cell indices they sit at, and every
    data row's cells. `skip` is the caller's row filter — spanning headers,
    NOTE rows — and never sees the label row, so a filter cannot silently
    leave the walk without columns.
    """
    columns: tuple[T, ...] | None = None
    positions: list[int] = []
    width = 0
    data_rows: list[list[str]] = []
    for row in table.rows:
        cells = row.cells
        if not cells:
            raise ExtractionError(f"{kind} row with no cells")
        if cells[0] == "Attribute Name":
            columns, positions = _map_columns(cells, known, kind, warnings)
            width = len(cells)
            continue
        if skip(row):
            continue
        if columns is None:
            raise ExtractionError(f"{kind} row before its column labels")
        # The width check comes before every other cell is read: a malformed
        # table must report its width, not an IndexError from column two.
        if len(cells) != width:
            raise ExtractionError(
                f"{kind} row with {len(cells)} cells for"
                f" {width} source columns: {cells!r}"
            )
        data_rows.append(cells)
    if columns is None:
        raise ExtractionError(f"{kind} without column labels")
    return columns, positions, data_rows


def _extract_avp_table(
    table: _Table, section_number: str, warnings: list[str], quirks: sources.Quirks
) -> tuple[ast.AvpTable, list[ast.ReusedAvpRow]]:
    """Column *order* has been identical in every 3GPP specification examined,
    but the set has not: TS 29.273's table has no Encrypt column, TS 29.212's
    has two the format does not model. Reading the labels rather than assuming
    nine positions is what lets those be extracted at all, and what keeps a
    missing column distinguishable from an empty cell."""
    rows: list[ast.AvpTableRow] = []
    note_refs: list[tuple[str, str]] = []  # (avp name, note number)
    note_rfcs: dict[str, str] = {}  # note number -> RFC number

    def skip(row: _Row) -> bool:
        cells = row.cells
        if cells[0].startswith("NOTE"):  # merged full-width row, 1 note per line
            for line in row.first_cell_lines:
                if match := _NOTE_RFC_RE.match(line):
                    # A note is prose; deriving a re-used AVP row from one is
                    # a prose harvest, declared like the RFC extractor's.
                    if not quirks.enabled("note-defined-in-rfc"):
                        raise ExtractionError(
                            f"table note {line!r} names a defining RFC, which"
                            " this document's source declaration does not"
                            " derive re-used rows from (the"
                            " `note-defined-in-rfc` quirk)"
                        )
                    quirks.fire("note-defined-in-rfc")
                    note_rfcs[match["number"]] = match["rfc"]
            return True
        # Spanning header rows (merged cells repeat the same text).
        return cells[0] == "" or cells[0] == cells[1]

    columns, positions, data_rows = _walk_table(
        table, _AVP_TABLE_COLUMNS, "AVP table", warnings, skip
    )
    for cells in data_rows:
        name = ""
        code_value: int | None = None
        section_value: str | None = None
        type_value: str | None = None
        encrypt: bool | None = None
        must = may = should_not = must_not = frozenset[ast.AvpFlag]()
        note: str | None = None
        for column, position in zip(columns, positions, strict=True):
            text = cells[position]
            match column:
                case ast.AvpColumn.NAME:
                    name, name_note = _strip_note_ref(text)
                    if " " in name:
                        # AVP names never contain spaces; line-wrap artifacts
                        # eating a hyphen (29.272 "MME-Location Information")
                        # are input-patched.
                        raise ExtractionError(
                            f"AVP table name cell {name!r} contains spaces"
                        )
                    note = name_note or note
                case ast.AvpColumn.CODE:
                    code, code_note = _strip_note_ref(text)
                    if code and not code.isdigit():
                        raise ExtractionError(f"AVP table code cell {code!r}")
                    code_value = int(code) if code else None
                    note = note or code_note
                case ast.AvpColumn.SECTION:
                    section_value = _clause_cell(text, quirks) or None
                case ast.AvpColumn.TYPE:
                    type_value = text or None
                case ast.AvpColumn.ENCRYPT:
                    encrypt = _encrypt_cell(text)
                case ast.AvpColumn.MUST:
                    must = _flags_cell(text, quirks)
                case ast.AvpColumn.MAY:
                    may = _flags_cell(text, quirks)
                case ast.AvpColumn.SHOULD_NOT:
                    should_not = _flags_cell(text, quirks)
                case ast.AvpColumn.MUST_NOT:
                    must_not = _flags_cell(text, quirks)
        if note is not None:
            note_refs.append((name, note))
        rows.append(
            ast.AvpTableRow(
                name=name,
                code=code_value,
                section=section_value,
                data_type=_data_type(type_value),
                flag_rules=ast.AvpFlagRules(
                    must=must, may=may, should_not=should_not, must_not=must_not
                ),
                may_encrypt=encrypt,
            )
        )
    if table.caption is None:
        raise ExtractionError("AVP table without a caption")
    reused = [
        ast.ReusedAvpRow(name=name, origin=f"RFC{note_rfcs[note]}")
        for name, note in note_refs
        if note in note_rfcs
    ]
    avp_table = ast.AvpTable(
        table=table.caption,
        columns=columns,
        rows=tuple(rows),
        source=ast.SourceRef(section=section_number),
    )
    return avp_table, reused


def _origin(reference: str, own_reference: str) -> str:
    if match := _ORIGIN_TS_RE.search(reference):
        return f"TS{match['series']}.{match['number']}"
    if match := _ORIGIN_RFC_RE.search(reference):
        return f"RFC{match['number']}"
    if match := _ORIGIN_3GPP2_RE.search(reference):
        return match["number"]
    # A bare clause number cites this document itself: 29.336's S6t re-used
    # table lists AVPs its own S6m set defines, with cells like "6.4.2". The
    # faithful origin is the document's own reference, not a parse failure —
    # the linter's origin-resolution rules treat a self-reference like any
    # other, so nothing downstream needs a special case.
    # 29.061 writes one self-reference as "Clause 20.5a.5".
    if _SECTION_REF_RE.match(reference.removeprefix("Clause ")):
        return own_reference
    raise ExtractionError(f"unrecognized origin reference {reference!r}")


_REUSED_TABLE_COLUMNS = {
    "Attribute Name": ast.ReusedColumn.NAME,
    "Reference": ast.ReusedColumn.FROM,
    "M-bit": ast.ReusedColumn.M_BIT,
}


def _extract_reused_table(
    table: _Table, warnings: list[str], own_reference: str
) -> tuple[list[ast.ReusedAvpRow], tuple[ast.ReusedColumn, ...]]:
    rows = []
    columns, positions, data_rows = _walk_table(
        table,
        _REUSED_TABLE_COLUMNS,
        "re-used AVPs",
        warnings,
        lambda row: row.cells[0] == "" or row.cells[0].startswith("NOTE"),
    )
    for cells in data_rows:
        name, _ = _strip_note_ref(cells[0])
        origin: str | None = None
        m_bit: ast.MBitOverride | None = None
        for column, position in zip(columns, positions, strict=True):
            text = cells[position]
            match column:
                case ast.ReusedColumn.NAME:
                    pass  # already read, so that the M-bit check can name it
                case ast.ReusedColumn.FROM:
                    origin = _origin(text, own_reference)
                case ast.ReusedColumn.M_BIT:
                    if text == cells[0]:
                        # Horizontally merged row: python-docx repeats the first
                        # cell's text in the missing position (TS 29.272
                        # Battery-Indicator row).
                        warnings.append(
                            f"re-used AVPs row {name!r} has a merged M-bit cell,"
                            " treating as empty"
                        )
                        text = ""
                    if text not in _M_BIT_OVERRIDES:
                        raise ExtractionError(
                            f"re-used AVPs row {name!r}:"
                            f" unrecognized M-bit cell {text!r}"
                        )
                    m_bit = _M_BIT_OVERRIDES[text]
        if origin is None:
            raise ExtractionError(f"re-used AVPs row {name!r} has no Reference column")
        rows.append(ast.ReusedAvpRow(name=name, origin=origin, m_bit=m_bit))
    return rows, columns


def _spec_and_version(document: docx.document.Document) -> tuple[str, str]:
    """The cover title, "3GPP TS 29.272 V18.6.0", read from wherever the
    template of the day put it: most specs print it in a cover-page table,
    but 29.061, 29.212, 29.213 and 29.214 print it as a plain paragraph."""
    for item in document.iter_inner_content():
        if isinstance(item, docx.table.Table):
            for row in item.rows:
                for cell in row.cells:
                    if match := _DOCX_COVER_RE.search(_normalize(cell.text)):
                        return f"3GPP {match['spec']}", match["version"]
        elif match := _DOCX_COVER_RE.search(_normalize(item.text)):
            return f"3GPP {match['spec']}", match["version"]
    raise ExtractionError("cannot find spec number/version on the cover page")


def _pdf_spec_and_version(reader: pypdf.PdfReader) -> tuple[str, str]:
    """An ETSI rendering prints its own title on the cover, with the 3GPP
    original in parentheses: "(3GPP TS 29.272 version 18.6.0 Release 18)"."""
    if not reader.pages:
        raise ExtractionError("PDF has no pages")
    cover = _normalize(reader.pages[0].extract_text())
    match = _PDF_COVER_RE.search(cover)
    if match is None:
        raise ExtractionError("cannot find spec number/version on the PDF cover page")
    return f"3GPP {match['spec']}", match["version"]


@dataclass(frozen=True)
class _ReusedTable:
    """A re-used AVPs table with the provenance the output block needs: its own
    caption and its own clause, which is not necessarily the AVP table's."""

    rows: list[ast.ReusedAvpRow]
    columns: tuple[ast.ReusedColumn, ...]
    label: str
    section: str


@dataclass(frozen=True)
class _CollectedAvpTable:
    """An AVP-flags table with the section it was found in and the re-used
    rows its own NOTEs derived — kept with their table so a document holding
    several definition sets attributes each note's rows to the right one."""

    table: ast.AvpTable
    section: str
    note_reused: list[ast.ReusedAvpRow]


@dataclass
class _Collected:
    """What one pass over the document found, before anything is cross-checked.

    Tables are kept as lists rather than as a single winner: 29.336 (S6m/S6n
    and S6t) and 29.338 (S6c and S6d) each carry a definition set per
    interface, and quietly keeping the last table would hide the rest.
    """

    messages: list[ast.Message] = field(default_factory=list)
    grouped: list[ast.GroupedAvp] = field(default_factory=list)
    # Sections that read like an enumerated AVP, with the name from the
    # heading. They cannot become definitions until the AVP table is known —
    # that is where their code comes from.
    pending_enums: list[tuple[_Section, str]] = field(default_factory=list)
    avp_tables: list[_CollectedAvpTable] = field(default_factory=list)
    reused_tables: list[_ReusedTable] = field(default_factory=list)


@dataclass
class _Resolved:
    """Definitions after cross-section resolution: every enumerated AVP has a
    code and a vendor-id, and external AVPs have been dropped."""

    messages: list[ast.Message]
    # Document order, one entry per definition set: the AVP table and the
    # re-used block accompanying it (synthesised, with the AVP table's own
    # label and section, when the document prints no re-used table).
    pairs: list[tuple[ast.AvpTable, _ReusedTable]]
    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp]
    independent_reused: list[_ReusedTable] = field(default_factory=list)


def _collect(
    sections: list[_Section],
    warnings: list[str],
    own_reference: str,
    quirks: sources.Quirks,
) -> _Collected:
    """Walk the document once, classifying sections. Source-shaped work only:
    nothing here needs to know about another section."""
    collected = _Collected()
    for section in sections:
        if title := _COMMAND_TITLE_RE.match(section.title):
            collected.messages.extend(
                _extract_messages(section, title, warnings, quirks)
            )
            continue
        if quirks.enabled("procedure-commands") and any(
            _DIAMETER_HEADER_RE.match(p.text) for p in section.paragraphs
        ):
            collected.messages.extend(
                _extract_messages(section, None, warnings, quirks)
            )
            continue
        for table in section.tables:
            header = table.rows[0].cells
            # Substring, not membership: 29.214 titles the column group
            # "AVP Flag rules (Note 1)".
            if any("AVP Flag rules" in cell for cell in header):
                # TS 29.330 table 6.3.1-1 is a template with no definitions.
                # Recognise only the full header followed entirely by blank cells.
                labels = next(
                    (
                        i
                        for i, row in enumerate(table.rows)
                        if row.cells[0] == "Attribute Name"
                    ),
                    None,
                )
                if labels is not None and all(
                    not any(row.cells) for row in table.rows[labels + 1 :]
                ):
                    warnings.append(
                        f"{section.number}: AVP table {table.caption}"
                        " contains no definitions"
                    )
                    continue
                avp_table, note_reused = _extract_avp_table(
                    table, section.number, warnings, quirks
                )
                collected.avp_tables.append(
                    _CollectedAvpTable(
                        table=avp_table,
                        section=section.number,
                        note_reused=note_reused,
                    )
                )
            elif "Attribute Name" in header and "Reference" in header:
                # Keyed on Reference rather than on M-bit: TS 29.128, 29.173
                # and 29.336 print a re-used table with no M-bit column at all.
                if table.caption is None:
                    raise ExtractionError("re-used AVPs table without a caption")
                reused_rows, reused_columns = _extract_reused_table(
                    table, warnings, own_reference
                )
                collected.reused_tables.append(
                    _ReusedTable(
                        rows=reused_rows,
                        columns=reused_columns,
                        label=table.caption,
                        section=section.number,
                    )
                )
        if title := _AVP_TITLE_RE.match(section.title):
            found = _find_rule_header(section, _AVP_HEADER_RE)
            if found is not None:
                header, body_start = found
                rule_name = header["name"]
                if " " in rule_name:
                    # Spaces-for-hyphens rule names (29.272 §7.3.196
                    # "Monitoring Event Report") are input-patched.
                    raise ExtractionError(
                        f"{section.number}: rule name {rule_name!r} contains spaces"
                    )
                if rule_name != title["name"]:
                    warnings.append(
                        f"{section.number}: heading name"
                        f" {title['name']!r} != rule name {rule_name!r},"
                        " using the rule name"
                    )
                collected.grouped.append(
                    _extract_grouped(section, header, body_start, name=rule_name)
                )
            elif section.paragraphs and "type Enumerated" in section.paragraphs[0].text:
                collected.pending_enums.append((section, title["name"]))
    return collected


def _resolve(collected: _Collected, quirks: sources.Quirks | None = None) -> _Resolved:
    """Cross-section work: pair each AVP table with its re-used table, then
    turn pending enumerated sections into definitions using codes from the
    AVP tables."""
    quirks = quirks if quirks is not None else sources.Quirks([], None)
    if not collected.avp_tables:
        if (
            quirks.enabled("message-only")
            and collected.messages
            and not collected.grouped
            and all(
                name
                in {row.name for table in collected.reused_tables for row in table.rows}
                and not any(
                    _ENUM_VALUE_RE.fullmatch(p.text) for p in section.paragraphs
                )
                for section, name in collected.pending_enums
            )
        ):
            quirks.fire("message-only")
            return _Resolved(
                messages=collected.messages,
                pairs=[],
                definitions=[],
                independent_reused=collected.reused_tables,
            )
        raise ExtractionError("no AVP table found")
    # A document with several definition sets (29.336's S6m/S6n and S6t,
    # 29.338's S6c and S6d) prints one AVP table and one re-used table per
    # set, in the same document order — that adjacency is the only thing that
    # says which re-used block belongs to which set, so unequal counts leave
    # no defensible pairing and are rejected rather than guessed at. A single
    # AVP table without a re-used table stays legitimate: the re-used block is
    # synthesised for its NOTE-derived rows.
    independent = quirks.enabled("independent-avp-tables")
    if independent:
        quirks.fire("independent-avp-tables")
    if not independent and (
        len(collected.reused_tables) > len(collected.avp_tables)
        or (
            len(collected.avp_tables) > 1
            and len(collected.reused_tables) != len(collected.avp_tables)
        )
    ):
        avp_sections = ", ".join(entry.section for entry in collected.avp_tables)
        reused_labels = ", ".join(table.label for table in collected.reused_tables)
        raise ExtractionError(
            f"{len(collected.avp_tables)} AVP tables (sections {avp_sections}) with"
            f" {len(collected.reused_tables)} re-used tables"
            f" ({reused_labels or 'none'}): cannot pair them"
        )

    pairs = []
    for index, entry in enumerate(collected.avp_tables):
        # `AvpTable.table` is optional only for label-less RFC tables; this
        # extractor rejects a docx AVP table without a caption before here.
        assert entry.table.table is not None
        if not independent and index < len(collected.reused_tables):
            reused = collected.reused_tables[index]
        else:
            # Only NOTE-derived rows: they come from the AVP table, so that
            # is honestly where the block was found.
            reused = _ReusedTable(
                rows=[],
                columns=ast.REUSED_COLUMNS,
                label=entry.table.table,
                section=entry.section,
            )
        pairs.append(
            (
                entry.table,
                _ReusedTable(
                    rows=[*reused.rows, *entry.note_reused],
                    columns=reused.columns,
                    label=reused.label,
                    section=reused.section,
                ),
            )
        )

    codes: dict[str, int | None] = {}
    for entry in collected.avp_tables:
        for row in entry.table.rows:
            if row.name in codes and codes[row.name] != row.code:
                if quirks.enabled("conflicting-avp-codes"):
                    # TS 29.273 table 8.2.3.0/1 disagrees with
                    # clause 5.2.3.24 and the other tables. Keep both statements;
                    # no enum may derive its code from an ambiguous index.
                    quirks.fire("conflicting-avp-codes")
                    codes[row.name] = None
                    continue
                raise ExtractionError(
                    f"AVP table code conflict for {row.name!r}:"
                    f" {codes[row.name]} vs {row.code}"
                )
            codes[row.name] = row.code
    # An enumerated section whose values live in another spec has nothing to
    # emit: DRMP says "is of type Enumerated" and then prints no values,
    # because RFC 7944 defines them. Skipping it drops no information.
    #
    # Note the deliberate asymmetry with grouped AVPs. TS 29.272 §7.3.40
    # re-prints TS 29.212's Allocation-Retention-Priority in full while listing
    # it as re-used, and nine of its clauses do this. Those definitions are
    # kept: the document printed a body, so the file records it. That an AVP is
    # both defined locally and listed as re-used is a real inconsistency in the
    # source, and reporting it is the linter's job — resolving it by deleting
    # what the specification says is not this layer's call to make.
    external = {row.name for _, reused in pairs for row in reused.rows}
    if independent:
        external.update(
            row.name for table in collected.reused_tables for row in table.rows
        )
    local_enums = [
        (section, name)
        for section, name in collected.pending_enums
        if name not in external
    ]
    vendor_id = _enum_vendor_id(collected.grouped) if local_enums else None

    enumerated = []
    for section, name in local_enums:
        code = codes.get(name)
        if code is None:
            raise ExtractionError(
                f"{section.number}: enumerated AVP {name!r}"
                " has no code in the AVP table"
            )
        enumerated.append(_extract_enumerated(section, name, code, vendor_id))

    return _Resolved(
        messages=collected.messages,
        pairs=pairs,
        definitions=[*collected.grouped, *enumerated],
        independent_reused=collected.reused_tables if independent else [],
    )


def _enum_vendor_id(grouped: list[ast.GroupedAvp]) -> int:
    """The vendor id shared by this spec's locally defined AVPs.

    Enumerated-AVP sections never print it, so it is read off the grouped-AVP
    headers, which normally do — one value per 3GPP spec (10415). TS 29.109
    defines enumerated AVPs but no grouped ones, so no header supplies the
    otherwise implicit value; in that case the publisher's vendor space is the
    only candidate. Several distinct header values remain a resolution error.
    """
    vendors = sorted({avp.vendor_id for avp in grouped if avp.vendor_id is not None})
    if not vendors:
        return TGPP_VENDOR
    if len(vendors) != 1:
        found = ", ".join(str(vendor) for vendor in vendors)
        raise ExtractionError(
            "cannot resolve the vendor id of this spec's enumerated AVPs:"
            f" its grouped-AVP headers give {found}"
        )
    return vendors[0]


def _assemble(resolved: _Resolved) -> tuple[ast.Section, ...]:
    """File order: messages, then each definition set's AVP table followed by
    its re-used table, then every definition in document order."""
    sections: list[ast.Section] = [*resolved.messages]
    for avp_table, reused in resolved.pairs:
        sections.append(avp_table)
        if reused.rows:
            sections.append(
                ast.ReusedAvps(
                    table=reused.label,
                    source=ast.SourceRef(section=reused.section),
                    columns=reused.columns,
                    rows=tuple(reused.rows),
                )
            )
    for reused in resolved.independent_reused:
        sections.append(
            ast.ReusedAvps(
                table=reused.label,
                source=ast.SourceRef(section=reused.section),
                columns=reused.columns,
                rows=tuple(reused.rows),
            )
        )
    sections.extend(
        sorted(
            resolved.definitions,
            key=lambda definition: _section_sort_key(definition.source.section),
        )
    )
    return tuple(sections)


def _section_sort_key(section: str) -> list[tuple[int, int, str]]:
    """Document order for section numbers: "6.3.10" sorts after "6.3.4",
    "6.3.7A" after "6.3.7", and annex clauses ("E.6.3.6") after every
    numbered clause, in annex-letter order."""
    key = []
    for part in section.split("."):
        digits = re.match(r"\d+", part)
        if digits is None:  # an annex letter — sorts after all numbers
            key.append((1, 0, part))
        else:
            key.append((0, int(digits[0]), part))
    return key


# The quirk vocabulary this extractor defines: name → what declaring it
# enables. The same criterion as the RFC extractor's (see `sources.py`):
# readings that would succeed silently on a document they were not written
# for. Closed vocabularies whose misreading is impossible stay global —
# "Y"/"N" Encrypt cells and 29.338's "Must"/"Must not" M-bit short forms
# cannot mean anything else, where a dotted flags cell or a prose note can.
QUIRKS: dict[str, str] = {
    "message-only": (
        "retain commands and re-used AVPs without a local AVP table"
        " (TS 29.330 clause 6.3.1)"
    ),
    "procedure-commands": (
        "read command names and abbreviations from intros under procedure"
        " headings (TS 29.273 clauses 8.2.2.1-4)"
    ),
    "conflicting-avp-codes": (
        "keep disagreeing table codes, refusing to derive an enum code"
        " from them (TS 29.273)"
    ),
    "physical-reused-columns": (
        "read physical cells in a re-used table with ragged grid spans (TS"
        " 29.273 table 8.2.3.0/2)"
    ),
    "independent-avp-tables": (
        "retain AVP and re-used tables independently instead of pairing"
        " them (TS 29.273 clauses 5-11)"
    ),
    "command-reference-only": (
        "accept command clauses containing only a clause reference, with"
        " no definition (TS 29.273)"
    ),
    "note-defined-in-rfc": (
        "derive re-used AVP rows from AVP-table notes reading 'The value of"
        " this attribute is defined in IETF RFC n' (TS 29.229, 29.329,"
        " 29.330)"
    ),
    "dotted-flags": (
        "read a space-less dotted flags cell ('M.V') with the period as the"
        " separator (TS 29.061, 29.212)"
    ),
    "clause-parenthetical": (
        "strip a trailing parenthetical from a clause cell as prose —"
        " '16.4.7 (see Note)' (TS 29.061); clause numbers have no syntax"
        " for parentheses, so the tail is almost certainly prose, but"
        " dropping text is declared, not assumed"
    ),
}


def sources_file_name(specification: str) -> str:
    """Source-declaration file name for a cover-page spec title:
    "3GPP TS 29.272" → "TS29.272.toml"."""
    return f"{ast.spec_ref(specification)}.toml"


def extract(
    docx_path: Path | str,
    link: str | None = None,
    warnings: list[str] | None = None,
    sources_dir: Path | None = None,
) -> ast.Specification:
    """Extract a `Specification` from a 3GPP docx. Non-fatal source-document
    inconsistencies are appended to `warnings` when a list is given. When
    `sources_dir` is given, source declarations from
    `<sources_dir>/<SpecRef>.toml` (if present) apply: input patches to the
    normalized source text before parsing, and quirks to the readings the
    extractor uses."""
    warnings = warnings if warnings is not None else []
    with boundary(f"extracting {docx_path}"):
        document = docx.Document(str(docx_path))
        specification, version = _spec_and_version(document)
        declarations_path = (
            sources_dir / sources_file_name(specification)
            if sources_dir is not None
            else None
        )
        patcher, quirks = sources.load(declarations_path, version, QUIRKS, warnings)

        collected = _collect(
            _sections(document, patcher, quirks),
            warnings,
            ast.spec_ref(specification),
            quirks,
        )
        patcher.finish()
        sections = _assemble(_resolve(collected, quirks))
        quirks.finish()
        return ast.Specification(
            specification=specification,
            version=version,
            vendor_id=TGPP_VENDOR,
            bases=(ast.BASE_PROTOCOL,),
            link=None if link is None else pydantic.HttpUrl(link),
            sections=sections,
        )


def attach_pages(
    spec: ast.Specification,
    pdf_path: Path | str,
    warnings: list[str] | None = None,
) -> ast.Specification:
    """Attach PDF page numbers to every section, from the ETSI PDF bookmark
    outline (section number → 1-based page of the first outline entry that
    starts with it).

    The PDF must render the same specification and version as `spec`: page
    numbers from a neighbouring version are wrong in a way nothing downstream
    can detect, and the downloader will happily fetch an earlier ETSI rendering
    when the exact one is not published yet.
    """
    warnings = warnings if warnings is not None else []
    with boundary(f"attaching pages from {pdf_path}"):
        reader = pypdf.PdfReader(str(pdf_path))
        specification, version = _pdf_spec_and_version(reader)
        if (specification, version) != (spec.specification, spec.version):
            raise ExtractionError(
                f"PDF renders {specification} V{version}, but the extracted"
                f" specification is {spec.specification} V{spec.version}"
                " — its page numbers do not apply"
            )
        pages: dict[str, int] = {}

        def walk(entries) -> None:
            for entry in entries:
                if isinstance(entry, list):
                    walk(entry)
                    continue
                match = re.match(r"^(\d+[A-Za-z]*(?:\.\d+[A-Za-z]*)*)\s", entry.title)
                if match is None:
                    continue
                # pypdf types an outline destination as `IndirectObject` and
                # `get_page_number` as optional; both resolve for a real outline.
                destination = entry.page or reader.pages[0]
                number = reader.get_page_number(destination)  # pyright: ignore[reportArgumentType]
                if number is not None:
                    # `setdefault`, not assignment: a section number bookmarked
                    # twice (a "6.3.1" continued after a page break) should keep
                    # the first entry, as documented, not the last.
                    pages.setdefault(match.group(1), number + 1)

        walk(reader.outline)
        if not pages:
            raise ExtractionError(
                "PDF bookmark outline has no numbered sections — wrong file, or a"
                " rendering without an outline"
            )

        def with_page(section):
            # Unconditionally, including when this PDF has no bookmark for the
            # section: returning it untouched would leave a page number from an
            # earlier `attach_pages` call in place, and the file would then
            # assert a page that the PDF it names does not put the section on.
            # That is the same wrong-rendering failure the version check above
            # exists to prevent, arriving through a second call instead of a
            # mismatched file.
            return section.model_copy(
                update={
                    "source": ast.SourceRef(
                        section=section.source.section,
                        page=pages.get(section.source.section),
                    )
                }
            )

        attached = tuple(with_page(section) for section in spec.sections)
        covered = sum(1 for section in attached if section.source.page is not None)
        if covered < len(attached):
            # Not fatal on its own — some sections legitimately have no bookmark —
            # but a low count means the outline and the docx disagree about section
            # numbering, which is worth seeing before the file gets committed.
            warnings.append(
                f"bookmark outline covered {covered}/{len(attached)} sections"
            )
        return spec.model_copy(update={"sections": attached})
