"""Reading the docx: the body walked in document order into numbered
`_Section`s, every text normalized and patched once (`_sections`); Word's
list numbering replayed where a number exists only as rendered
(`_ListNumbering`); smart tags unwrapped; and the cover page's
specification and version."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any

from ...errors import MissingExtraError
from .. import sources
from ..errors import ExtractionError
from ..sources import Patcher
from ._base import _Line, _normalize, _Para, _Row, _Section, _Table
from ._registries import _REGISTRY_KINDS

try:
    import docx
    import docx.document
    import docx.table
    import docx.text.hyperlink
    import docx.text.paragraph
    from docx.oxml.ns import qn
except ImportError as error:
    raise MissingExtraError(
        "reading source documents needs python-docx and pypdf"
    ) from error


_HEADING_RE = re.compile(
    r"^(?P<number>(?:[A-Za-z]+|\d+[A-Za-z]*)(?:\.\d+[A-Za-z]*)*)\t(?P<title>.+)$"
)
# Behind `spaced-heading-numbers`: a space before the tab, TS 29.234 V11.2.0's
# clause "4.5.2.2 \tInformation Element Contents". Declared, since a heading the
# plain reading misses leaves its body in the clause before.
_SPACED_HEADING_RE = re.compile(
    r"^(?P<number>(?:[A-Za-z]+|\d+[A-Za-z]*)(?:\.\d+[A-Za-z]*)*) +\t(?P<title>.+)$"
)


# A clause heading printed in a body style (TS 32.299 clause 7.2.135C), read
# only behind the `body-clause-headings` quirk.
_BODY_HEADING_RE = re.compile(
    r"^(?P<number>\d+(?:\.\d+[A-Za-z]*)+) (?P<title>[A-Za-z0-9][A-Za-z0-9_-]* AVP)$"
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


_DOCX_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) V(?P<version>\d+(?:\.\d+)*)"
)
# oneM2M's cover table: "Document Number | oneM2M-TS-0004-V2.35.0".
_ONEM2M_COVER_RE = re.compile(r"oneM2M-(?P<spec>TS-\d{4})-V(?P<version>\d+(?:\.\d+)*)")


_TABBED_NUMBER_RE = re.compile(r"\S(?:\t|[ \xa0]{2,})[\s\xa0]*\d+[\s\xa0]*$")
# A run holding only a repetition spells no name: TS 29.561 clause 12.6.3 prints
# a plain "0*16 " before a bold "[ 3GPP-UE-MAC-Address ]".
_REPETITION_RUN_RE = re.compile(r"\s*\d*\*\d*\s*")


def _lines(
    paragraph: docx.text.paragraph.Paragraph,
    style: str,
    patcher: Patcher,
    section: str | None,
) -> list[_Line]:
    """Split a paragraph at its manual line breaks (python-docx renders
    `<w:br/>` as "\\n"), keeping each line's run formatting. Blank lines
    inside a multi-line paragraph are dropped; a blank paragraph stays one
    blank line, which still ends an ABNF body as it always has."""
    texts: list[list[str]] = [[]]
    bold: list[set[bool]] = [set()]
    struck: list[set[bool]] = [set()]
    for item in paragraph.iter_inner_content():
        runs = item.runs if isinstance(item, docx.text.hyperlink.Hyperlink) else [item]
        for run in runs:
            for index, piece in enumerate(run.text.split("\n")):
                if index:
                    texts.append([])
                    bold.append(set())
                    struck.append(set())
                texts[-1].append(piece)
                if any(char.isalnum() for char in piece) and (
                    not _REPETITION_RUN_RE.fullmatch(piece)
                ):
                    bold[-1].add(bool(run.bold))
                    struck[-1].add(bool(run.font.strike or run.font.double_strike))
    lines = [
        _Line(
            # Not recorded: the paragraph's own text already counted.
            text=patcher.apply(_normalize("".join(text)), section, record=False),
            style=style,
            bold=frozenset(flags),
            struck=frozenset(strike),
            tabbed_number=bool(_TABBED_NUMBER_RE.search("".join(text))),
        )
        for text, flags, strike in zip(texts, bold, struck, strict=True)
    ]
    return [line for line in lines if line.text] or [
        _Line(text="", style=style, bold=frozenset(), struck=frozenset())
    ]


def _val(element: Any, tag: str) -> str | None:
    """The `w:val` of `element`'s child `tag`, or None."""
    child = None if element is None else element.find(qn(tag))
    return None if child is None else child.get(qn("w:val"))


def _counter_text(value: int, fmt: str) -> str:
    """A list counter as its level's `w:numFmt` writes it."""
    if fmt in ("decimal", "decimalZero"):
        return f"{value:02d}" if fmt == "decimalZero" else str(value)
    if fmt in ("upperLetter", "lowerLetter"):
        # Word continues past Z by repeating the letter: AA, BB.
        letter = chr(ord("A") + (value - 1) % 26) * ((value - 1) // 26 + 1)
        return letter if fmt == "upperLetter" else letter.lower()
    if fmt in ("upperRoman", "lowerRoman"):
        roman = ""
        for number, numeral in (
            (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
            (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"),
            (4, "IV"), (1, "I"),
        ):  # fmt: skip
            while value >= number:
                roman += numeral
                value -= number
        return roman if fmt == "upperRoman" else roman.lower()
    raise ExtractionError(f"list numbering format {fmt!r} is not read")


@dataclass(frozen=True)
class _Level:
    start: int
    fmt: str
    text: str
    # 1-based level after whose use this one restarts; 0 never restarts.
    restart: int | None
    legal: bool


def _list_level(element: Any, base: _Level | None = None) -> _Level:
    """A `w:lvl`, each property it leaves out taken from `base`: the
    abstract numbering's level, where a `w:lvlOverride` redefines one. A
    level with no `w:start` starts at 0 (ECMA-376 part 1, 17.9.25): TS
    32.299 V11.20.0's PoC-Server-Role list (clause 7.2.145) omits it, and
    the ETSI PDF prints "0 Participating PoC Server"."""
    base = base or _Level(start=0, fmt="decimal", text="", restart=None, legal=False)
    start = _val(element, "w:start")
    restart = _val(element, "w:lvlRestart")
    text = element.find(qn("w:lvlText"))
    legal = element.find(qn("w:isLgl"))
    return _Level(
        start=base.start if start is None else int(start),
        fmt=_val(element, "w:numFmt") or base.fmt,
        text=base.text if text is None else text.get(qn("w:val")) or "",
        restart=base.restart if restart is None else int(restart),
        legal=base.legal
        if legal is None
        else legal.get(qn("w:val")) not in ("0", "false"),
    )


@dataclass(frozen=True)
class _Num:
    """A `w:num`: its abstract numbering and what its `w:lvlOverride`s
    change, by level — a whole `w:lvl`, a `w:startOverride`, or both."""

    abstract: str
    levels: dict[int, Any]
    starts: dict[int, int]


class _ListNumbering:
    """Word's list numbering, replayed over a document's paragraphs.

    A heading's clause number is normally its text ("A.2.1\\tAccounting
    ..."). oneM2M TS-0004 prints none: its annex headings carry a `w:numPr`
    pointing at `word/numbering.xml`, whose level text (`A.%1.%2`) Word
    renders, so the number exists only once the counters are replayed —
    every numbered paragraph of the body in document order advancing its
    list's counter at its level, deeper levels restarting, as Word does.
    Counters belong to an abstract numbering, which every `w:num` naming it
    shares. A `w:num`'s `w:lvlOverride` redefines a level for the
    paragraphs using that `w:num`: an embedded `w:lvl` over the abstract
    level, property by property, and a `w:startOverride` over its start;
    the overridden level restarts at the first paragraph using the `w:num`,
    and whenever a level above restarts it, from that start. A paragraph's
    `w:numPr` gives its list and level each, and what it leaves out comes
    from its style's, through `w:basedOn`. Paragraphs inside tables are not
    replayed: no heading list continues into one.
    """

    def __init__(self, numbering: Any, styles: Any) -> None:
        self._abstract: dict[str, dict[int, _Level]] = {}
        links: dict[str, str] = {}
        for abstract in (
            numbering.findall(qn("w:abstractNum")) if numbering is not None else ()
        ):
            key = abstract.get(qn("w:abstractNumId"))
            if (link := _val(abstract, "w:numStyleLink")) is not None:
                links[key] = link
            self._abstract[key] = {
                int(level.get(qn("w:ilvl"))): _list_level(level)
                for level in abstract.findall(qn("w:lvl"))
            }
        self._styles: dict[str, tuple[str | None, Any]] = {}
        for style in styles.findall(qn("w:style")) if styles is not None else ():
            self._styles[style.get(qn("w:styleId"))] = (
                _val(style, "w:basedOn"),
                style.find(f"{qn('w:pPr')}/{qn('w:numPr')}"),
            )
        self._nums: dict[str, _Num] = {}
        for num in numbering.findall(qn("w:num")) if numbering is not None else ():
            levels: dict[int, Any] = {}
            starts: dict[int, int] = {}
            for override in num.findall(qn("w:lvlOverride")):
                ilvl = int(override.get(qn("w:ilvl")))
                if (level := override.find(qn("w:lvl"))) is not None:
                    levels[ilvl] = level
                if (start := _val(override, "w:startOverride")) is not None:
                    starts[ilvl] = int(start)
            abstract = _val(num, "w:abstractNumId")
            if abstract is not None:
                self._nums[num.get(qn("w:numId"))] = _Num(abstract, levels, starts)
        # A list style's abstract numbering points at the list style, whose
        # own `w:numPr` names the `w:num` holding the levels.
        for key, link in links.items():
            _, num_pr = self._styles.get(link, (None, None))
            target = self._nums.get(_val(num_pr, "w:numId") or "")
            if target is not None:
                self._abstract[key] = self._abstract.get(target.abstract, {})
        self._counters: dict[str, dict[int, int]] = {}
        self._used: set[str] = set()

    def _num_pr(self, paragraph: Any) -> tuple[str, int] | None:
        """The paragraph's (num id, level). Each is the paragraph's own
        where its `w:numPr` gives it, else the nearest style's that does: a
        heading may print only `w:ilvl` and number in its style's list."""
        p_pr = paragraph.find(qn("w:pPr"))
        num_pr = None if p_pr is None else p_pr.find(qn("w:numPr"))
        style = _val(p_pr, "w:pStyle")
        num_id = ilvl = None
        seen = set()
        while True:
            if num_pr is not None:
                num_id = num_id if num_id is not None else _val(num_pr, "w:numId")
                ilvl = ilvl if ilvl is not None else _val(num_pr, "w:ilvl")
            if num_id is not None and ilvl is not None:
                break
            if style is None or style in seen:
                break
            seen.add(style)
            style, num_pr = self._styles.get(style, (None, None))
        if num_id is None or num_id == "0":
            return None
        return num_id, int(ilvl or 0)

    def _levels(self, num: _Num) -> dict[int, _Level]:
        """The levels paragraphs of `num` number by: the abstract's, with
        the num's overrides applied."""
        levels = dict(self._abstract.get(num.abstract, {}))
        for ilvl, element in num.levels.items():
            levels[ilvl] = _list_level(element, levels.get(ilvl))
        for ilvl, start in num.starts.items():
            if ilvl in levels:
                levels[ilvl] = dataclasses.replace(levels[ilvl], start=start)
        return levels

    def advance(self, paragraph: Any) -> str | None:
        """Count `paragraph` and return the number Word renders before it,
        or None where it is unnumbered or its level prints nothing."""
        found = self._num_pr(paragraph)
        if found is None or found[0] not in self._nums:
            return None
        num_id, level = found
        num = self._nums[num_id]
        levels = self._levels(num)
        if level not in levels:
            return None
        counters = self._counters.setdefault(num.abstract, {})
        if num_id not in self._used:
            self._used.add(num_id)
            for overridden in {*num.levels, *num.starts}:
                # Unstarted: the next paragraph at the level takes its start.
                counters.pop(overridden, None)
        counters[level] = counters.get(level, levels[level].start - 1) + 1
        for deeper, definition in levels.items():
            restart = deeper if definition.restart is None else definition.restart
            if deeper > level and restart and level < restart:
                counters.pop(deeper, None)
        own = levels[level]
        if own.fmt == "none" or not own.text:
            return None

        def rendered(match: re.Match[str]) -> str:
            index = int(match[1]) - 1
            definition = levels.get(index)
            if definition is None:
                return ""
            value = counters.get(index, definition.start)
            return _counter_text(value, "decimal" if own.legal else definition.fmt)

        return re.sub(r"%([1-9])", rendered, own.text)


def _drop_unstarted_columns(rows: list[_Row], spans: list[tuple[int, ...]]) -> None:
    """Take out the grid columns no row's cell starts in, which hold nothing of
    their own. TS 29.153 V19.0.0 table 5.3.1.1, TS 29.217 V19.0.0's, TS 29.219
    V19.0.0's and TS 29.368 V19.0.0's merge the name column across two grid
    columns in every row and the spanning header's other cells differently, so
    read by the grid each data row would repeat its name and read as a header."""
    if len({sum(row_spans) for row_spans in spans}) != 1:
        return
    width = sum(spans[0])
    starts = set()
    for row_spans in spans:
        position = 0
        for span in row_spans:
            starts.add(position)
            position += span
    if len(starts) == width:
        return
    for row in rows:
        row.cells = [row.cells[position] for position in sorted(starts)]


def _sections(
    document: docx.document.Document,
    patcher: Patcher,
    quirks: sources.Quirks | None = None,
) -> list[_Section]:
    sections: list[_Section] = []
    current: _Section | None = None
    caption: str | None = None
    caption_text: str | None = None
    # Inside a clause a declared exclusion leaves out: nothing in it is looked
    # at, so no patch counts its text and no reading sees it.
    excluded = False
    numbering = (
        _ListNumbering(document.part.numbering_part.element, document.styles.element)
        if quirks is not None
        and (
            quirks.enabled("list-numbered-headings")
            or quirks.enabled("list-numbered-enum-values")
        )
        else None
    )
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
                            indented=row.cells[0].text.startswith("\t"),
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
                physical = len(set(spans)) == 1 and any(span > 1 for span in spans[0])
                # TS 29.273 table 8.2.3.0/2 changes the grid spans of its
                # Comments and M-bit columns partway through; TS 29.368 table
                # 6.5.1.1 and TS 29.219 table 5.4 put a 4-twip sliver column
                # between the name and Reference columns, which the header
                # merges into Reference and every data row into the name.
                # All three have one physical cell per label.
                if (
                    quirks is not None
                    and quirks.enabled("physical-reused-columns")
                    and "Reference" in rows[0].cells
                    and len(set(spans)) > 1
                ):
                    quirks.fire("physical-reused-columns")
                    physical = True
                # TS 32.299 table 7.2.0.1 spreads eleven columns over a
                # 42-column grid with eight different span patterns (the PDF
                # shows the CCR marks of the API-* rows off the grid too), so
                # only its physical cells line up with the labels. 313 of its
                # rows also end in an empty one-grid-column sliver the other
                # rows fold into "Must not"; the header ends in the same
                # empty sliver, so it is no column.
                sliver = False
                if (
                    quirks is not None
                    and quirks.enabled("physical-avp-columns")
                    and any("AVP Flag rules" in cell for cell in rows[0].cells)
                    and len(set(spans[1:])) > 1
                ):
                    quirks.fire("physical-avp-columns")
                    physical = True
                    sliver = spans[0][-1] == 1 and rows[0].cells[-1] == ""
                # TS 29.230's registry tables merge their columns across grid
                # columns in several patterns (table 7.1: four, besides its
                # full-width notes), so only physical cells line up with the
                # labels.
                if (
                    quirks is not None
                    and quirks.enabled("registry-tables")
                    and rows[0].cells[0] in _REGISTRY_KINDS
                ):
                    physical = True
                if physical:
                    for row, row_spans in zip(rows, spans, strict=True):
                        starts = []
                        position = 0
                        for span in row_spans:
                            starts.append(row.cells[position])
                            position += span
                        if sliver and row_spans[-1] == 1 and starts[-1] == "":
                            starts.pop()
                        row.cells = starts
                else:
                    _drop_unstarted_columns(rows, spans)
                current.tables.append(
                    _Table(caption=caption, rows=rows, caption_text=caption_text)
                )
            caption = caption_text = None
            continue
        style = (item.style.name or "") if item.style else ""
        label = None if numbering is None else numbering.advance(item._p)
        # TS 29.273 §6.2.2.1.1 uses the explicit H6 heading style.
        if style.startswith("Heading") or re.fullmatch(r"H[1-9]", style):
            heading = item.text.strip()
            if (
                label is not None
                and quirks is not None
                and not _HEADING_RE.match(heading)
            ):
                # oneM2M TS-0004's annex headings: the number is Word's.
                quirks.fire("list-numbered-headings")
                heading = f"{label}\t{heading}"
            match = _HEADING_RE.match(heading)
            if (
                match is None
                and quirks is not None
                and quirks.enabled("spaced-heading-numbers")
                and (match := _SPACED_HEADING_RE.match(heading))
            ):
                quirks.fire("spaced-heading-numbers")
            if match:
                excluded = patcher.excludes(match["number"])
                if excluded:
                    current = None
                    continue
                current = _Section(
                    number=match["number"],
                    title=patcher.apply(_normalize(match["title"]), match["number"]),
                )
                sections.append(current)
                continue
            # TS 29.329's clause 8 ends at "Annex A (informative):", which has
            # no number to read: what follows belongs to no clause, as what
            # precedes the first heading does.
            excluded = False
        if excluded:
            continue
        text = patcher.apply(_normalize(item.text), number)
        # TS 32.299 prints the heading of clause 7.2.135C as a Normal
        # paragraph inside 7.2.135B; without reading it, PC5-Radio-Technology's
        # values would land in the Integer32 AVP before it.
        if (
            quirks is not None
            and quirks.enabled("body-clause-headings")
            and (match := _BODY_HEADING_RE.match(text))
        ):
            quirks.fire("body-clause-headings")
            if patcher.excludes(match["number"]):
                excluded = True
                current = None
                continue
            current = _Section(number=match["number"], title=match["title"])
            sections.append(current)
            continue
        if match := _TABLE_CAPTION_RE.match(text):
            caption = match["label"]
            caption_text = text
        if current is not None:
            lines = _lines(item, style, patcher, number)
            current.paragraphs.append(
                _Para(text=text, style=style, lines=lines, label=label)
            )
    return sections


def _unwrap_smart_tags(document: docx.document.Document) -> None:
    """Put the runs of Word's smart tags back in their paragraphs.

    A `w:smartTag` marks a run Word recognised as a place or an abbreviation,
    and prints as that run. python-docx reads only a paragraph's direct runs
    and hyperlinks, so through it the tagged text does not exist: TS 29.338
    clause 5.3.2.6's heading reads "Alert-Service-Centre-Answer () Command",
    and TS 29.214's clause cells come out blank. Done once, on the tree."""
    for tag in list(document.element.body.iter(qn("w:smartTag"))):
        parent = tag.getparent()
        index = parent.index(tag)
        parent.remove(tag)
        # `w:smartTagPr` is the tag's own properties, which print nothing.
        kept = [child for child in tag if child.tag != qn("w:smartTagPr")]
        parent[index:index] = kept


def _spec_and_version(document: docx.document.Document) -> tuple[str, str]:
    """The cover title, "3GPP TS 29.272 V18.6.0", read from wherever the
    template of the day put it: most specs print it in a cover-page table,
    but 29.061, 29.212, 29.213 and 29.214 print it as a plain paragraph.
    oneM2M's cover table prints its document number, "oneM2M-TS-0004-V2.35.0",
    read as "oneM2M TS-0004"."""

    def cover(text: str) -> tuple[str, str] | None:
        if match := _DOCX_COVER_RE.search(text):
            return f"3GPP {match['spec']}", match["version"]
        if match := _ONEM2M_COVER_RE.search(text):
            return f"oneM2M {match['spec']}", match["version"]
        return None

    for item in document.iter_inner_content():
        if isinstance(item, docx.table.Table):
            for row in item.rows:
                for cell in row.cells:
                    if found := cover(_normalize(cell.text)):
                        return found
        elif found := cover(_normalize(item.text)):
            return found
    raise ExtractionError("cannot find spec number/version on the cover page")
