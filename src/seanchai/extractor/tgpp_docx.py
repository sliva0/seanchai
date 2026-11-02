"""Extractor: 3GPP .docx specification → `.dad` AST; also oneM2M TS-0004,
whose Diameter annex follows 3GPP's Word conventions.

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
  inserted in numeric order; behind `value-first-enums`, `a .. b` ranges
  reserved or left vendor-specific → reserved or vendor-specific values.
- The AVP-flags table (header "AVP Flag rules") → `AvpTable`; rows whose code
  cell is a NOTE reference get `code=None`, and note texts naming a defining
  RFC additionally produce `ReusedAvps` rows (the `note-defined-in-rfc`
  quirk).
- The "re-used Diameter AVPs" table → `ReusedAvps` rows with M-bit overrides.
- Columns marking where a row applies ("Acc. Type", "Applicability", "Used
  in", ...), in either table, → the row's marks, each behind its declared
  quirk.
- Behind `registry-tables`, TS 29.230's allocation tables → `Registry`, and
  behind `reserved-range-notes` their full-width notes → reserved ranges.

The vendor-id for locally defined AVPs is not printed by enumerated-AVP
sections, so it is taken from the spec's grouped-AVP headers (3GPP: 10415).
"""

import contextlib
import dataclasses
import enum
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docx
import docx.document
import docx.table
import docx.text.hyperlink
import docx.text.paragraph
import pydantic
import pypdf
from docx.oxml.ns import qn

from ..dad import abnf, ast, formatter
from . import sources
from .errors import ExtractionError, boundary
from .sources import Patcher

_HEADING_RE = re.compile(
    r"^(?P<number>(?:[A-Za-z]+|\d+[A-Za-z]*)(?:\.\d+[A-Za-z]*)*)\t(?P<title>.+)$"
)
# Behind `spaced-heading-numbers`: a space before the tab, TS 29.234 V11.2.0's
# clause "4.5.2.2 \tInformation Element Contents". Declared, since a heading the
# plain reading misses leaves its body in the clause before.
_SPACED_HEADING_RE = re.compile(
    r"^(?P<number>(?:[A-Za-z]+|\d+[A-Za-z]*)(?:\.\d+[A-Za-z]*)*) +\t(?P<title>.+)$"
)
# TS 29.343 clauses 6.6.2-6.6.5 lower-case the keyword
# ("ProXimity-Action-Request (PXR) command").
_COMMAND_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) [Cc]ommand$"
)
# TS 32.299 clauses 6.2.2-6.4.13: "Accounting-Request message",
# "Accounting-Answer (ACA) message"; oneM2M TS-0004 clauses A.2.1-A.2.2,
# "Accounting Request Command", once a patch joins the words; TS 32.299
# V11.20.0 capitalizes "Accounting-Request Message". Read behind
# `message-headings`.
_MESSAGE_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z-]+)(?: \((?P<abbr>[A-Z]{2,5})\))? (?:[Mm]essage|Command)$"
)
# A clause heading printed in a body style (TS 32.299 clause 7.2.135C), read
# only behind the `body-clause-headings` quirk.
_BODY_HEADING_RE = re.compile(
    r"^(?P<number>\d+(?:\.\d+[A-Za-z]*)+) (?P<title>[A-Za-z0-9][A-Za-z0-9_-]* AVP)$"
)
_COMMAND_INTRO_RE = re.compile(
    r"^The (?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) command,"
)
# The " AVP" suffix is spec-dependent: 29.329 titles are "MSISDN AVP",
# 29.272 mostly bare "Subscription-Data". Bare titles like "General" also
# match — harmless, since a section only becomes a definition when its body
# holds an AVP-header rule or an Enumerated intro with a known code.
_AVP_TITLE_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)( AVP)?$")
# TS 29.212 heads most of its AVP clauses with the access types the AVP
# applies to: "Event-Trigger AVP (All access types)", "Bearer-Operation AVP
# (Applicable access type 3GPP-GPRS)", "QoS-Upgrade AVP (3GPP-GPRS Access Type
# only)", once without " AVP" (5.3.44); 29.214 clause 5.3.69 once. Read
# behind `access-type-headings`.
_ACCESS_TYPE_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)(?: AVP)?"
    r" \((?:[^()]* )?[Aa]ccess [Tt]ypes?(?: [^()]*)?\)$"
)
_DIAMETER_HEADER_RE = re.compile(
    # The rule name is normalized separately: source docx sometimes carries
    # stray spaces inside it ("< User-Data -Request>").
    r"^<\s*(?P<name>[A-Za-z -]+?)\s*> ::=\s*<\s*Diameter Header:"
    r"\s*(?P<items>[0-9A-Z, ]+?)\s*>$"
)
_AVP_HEADER_RE = re.compile(
    # code/vendor separator varies between specs: "700 10415" and "632, 10415";
    # rule names can carry spaces for hyphens ("Monitoring Event Report::=");
    # TS 32.299 brackets some rule names ("<Event-Type>::=", "< Participant-Group >
    # ::="), as RFC 6733 does for `<Failed-AVP>`; TS 29.229 clause 6.3.13 writes
    # "AVP Header : 612".
    r"^(?P<open><\s*)?(?P<name>[A-Za-z0-9][A-Za-z0-9 _-]*?)\s*(?(open)>)"
    r"\s*::=\s*<\s*AVP [Hh]eader ?:\s*(?P<code>\d+)"
    r"(?:\s*,?\s+(?P<vendor>\d+))?\s*>$"
)
_ABNF_LINE_RE = re.compile(
    r"^(?:(?P<min>\d*)\*(?P<max>\d*))?\s*"
    r"(?P<open>[<{\[])\s*(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)\s*(?P<close>[>}\]])$"
)
# One member anywhere in a line, for lines holding several.
_ABNF_MEMBER_RE = re.compile(
    r"\s*(?:\d*\*\d*)?\s*[<{\[]\s*[A-Za-z0-9][A-Za-z0-9_-]*\s*[>}\]]"
)
_ENUM_VALUE_RE = re.compile(r"^(?P<name>[A-Za-z0-9_-]+)\s*\((?P<value>\d+)\)$")
# A value line in the shapes the quirks below read, each part optional so the
# reading can say which quirk a line needed. Prose can end in "(n)" too, so
# every departure from `NAME (n)` is declared per document:
# - `dashed-enum-values`: a list dash printed as text, "- AUDIO (0)" (TS 29.214
#   clause 5.3.19, 29.272 7.3.128, 29.338 5.3.3.2);
# - `worded-enum-values`: a label in words, "Device Trigger Request (1)" (TS
#   29.368 clause 6.4.6, 29.214 5.3.25);
# - `hex-enum-values`: "OTHER (0xFFFFFFFF)" (TS 29.214 clause 5.3.19);
# - `punctuated-enum-values`: a list's comma or full stop after the value,
#   "- ONLY_IMSI_REQUESTED (0)," (TS 29.338 clause 5.3.3.5);
# - `described-enum-values`: the value's gloss on its own line, "NO (0) The
#   sending node is not GBA_U aware" (TS 29.109 clause 6.3.1.8);
# - `label-after-enum-value`: no name before the value and the label after
#   it, "- (0) Private user identity." (TS 29.109 clause 6.3.1.13).
_LOOSE_ENUM_VALUE_RE = re.compile(
    r"(?P<dash>- )?"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*(?P<words>(?:,? [A-Za-z0-9_-]+)+)?)?"
    r"\s*\((?:(?P<value>\d+)|0x(?P<hex>[0-9A-Fa-f]+))\)"
    r"\s*(?P<rest>.*)"
)
# Several `NAME (n)` printed in one paragraph with nothing between, read behind
# `run-on-enum-values`: TS 29.229 clause 6.3.58's "NOT_PRIVILEDGED_SENDER
# (0)PRIVILEDGED_SENDER (1)", one run in the docx and one line in the PDF.
_RUN_ON_ENUM_VALUES_RE = re.compile(r"(?:[A-Za-z0-9_-]+\s*\(\d+\)\s*){2,}")
_RUN_ON_ENUM_VALUE_RE = re.compile(r"(?P<name>[A-Za-z0-9_-]+)\s*\((?P<value>\d+)\)")
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
# (29.212, 29.214 name cells — 29.212 mixes both casings, and V11.19.0's
# table 5a.4.1 writes "(note 2)" too). The parenthesized form must strip as
# a whole, or "3GPP-RAT-Type (NOTE 3)" would be left as the non-name
# "3GPP-RAT-Type ()".
_NOTE_REF_RE = re.compile(
    r"\s*\(\s*(?:NOTE|Note|note)\s*(?P<number>\d+)\s*\)\s*"
    r"|\s*(?:NOTE|Note)\s*(?P<bare>\d+)\s*"
)
_NOTE_RFC_RE = re.compile(
    r"^NOTE\s*(?P<number>\d+):\s*The values? of th(?:is|ese) attributes? "
    r"is defined in IETF\s+RFC\s+(?P<rfc>\d+)"
)
_DOCX_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) V(?P<version>\d+(?:\.\d+)*)"
)
# oneM2M's cover table: "Document Number | oneM2M-TS-0004-V2.35.0".
_ONEM2M_COVER_RE = re.compile(r"oneM2M-(?P<spec>TS-\d{4})-V(?P<version>\d+(?:\.\d+)*)")
_PDF_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) version (?P<version>\d+(?:\.\d+)*)"
)
# The "3GPP" and "IETF" prefixes are conventional, not reliable: a re-used
# table's From cell is written by hand and 29.344 and 29.388 both spell it
# "TS 29.272 [10]", with the document's own bibliography number and no
# publisher. The number is what identifies the origin, so that is what these
# require.
# A three-digit series is no 3GPP one: ETSI numbers its TISPAN documents
# so, and a cell may print one with either separator and the wrong publisher
# (29.212's "3GPP TS 283 034 [37]", 29.214's "3GPP TS 183.017 [15]").
_ORIGIN_TS_RE = re.compile(r"TS\s+(?P<series>\d{2,3})[. ](?P<number>\d{3})(?!\d)")
_ORIGIN_RFC_RE = re.compile(r"RFC\s+(?P<number>\d+)")
# Documents outside 3GPP and IETF keep their publisher's numbering, the
# publisher leading: "ETSI TS 283 034 [37]", "3GPP2 X.S0057 [24]", and in
# TS 32.299's clause 2 "OMA-DDS-Charging_Data: ..." and "oneM2M TS-0004: ...".
_ORIGIN_ETSI_RE = re.compile(
    r"ETSI\s+(?P<kind>TS|ES)\s+(?P<series>\d{3})[. ](?P<number>\d{3})(?!\d)"
)
_ORIGIN_3GPP2_RE = re.compile(r"3GPP2\s+(?P<number>[A-Z]\.[A-Z]\d{4})")
_ORIGIN_OMA_RE = re.compile(r"(?<![\w-])(?P<name>OMA(?:-[A-Za-z0-9_]+)+)")
_ORIGIN_ONEM2M_RE = re.compile(r"oneM2M\s+TS-(?P<number>\d{4})")
# A cell's clause-2 reference number: "[37]".
_ORIGIN_NUMBER_RE = re.compile(r"\[(?P<number>\d+)\]")
# A re-used table's From cell citing a clause of the same document
# ("6.4.2" in 29.336's S6t table, whose AVPs the S6m set defines).
_SECTION_REF_RE = re.compile(r"^(?:[A-Za-z]+|\d+[A-Za-z]*)(?:\.\d+[A-Za-z]*)*$")

# Every AVP a 3GPP specification defines is in 3GPP's vendor space. That is a
# fact about the publisher, not about any one document, so this extractor
# states it rather than reading it out of the text — the same way an RFC
# extractor will state the IETF's 0.
TGPP_VENDOR = 10415
# oneM2M TS-0004 clause A.4: "AVPs defined for oneM2M specific usage are
# assigned Vendor-Id of 45687."
ONEM2M_VENDOR = 45687


def _publisher_vendor(specification: str) -> int:
    """The vendor space a publisher defines its AVPs in."""
    return ONEM2M_VENDOR if specification.startswith("oneM2M ") else TGPP_VENDOR


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
class _Line:
    """One line of a paragraph, split at manual line breaks, with what its
    runs say about formatting.

    TS 32.299 prints whole ABNF bodies as one paragraph with a line break
    after every member (clauses 7.1.9, 7.2.124 and dozens more), so ABNF is
    read line by line, and bold and strikethrough belong to a line rather
    than to its paragraph."""

    text: str
    style: str
    # Bold state of the runs that spell a name: only those are trusted, since
    # Word bolds brackets and whitespace erratically.
    bold: frozenset[bool]
    # Strikethrough state of the same runs.
    struck: frozenset[bool]
    # Whether the line, as printed, ends in a number set off by a tab or a
    # run of spaces, which normalizing collapses: TS 32.299 V11.20.0's value
    # lines, "MONETARY<tabs>0" (clause 7.2.14), and no sentence's last word.
    tabbed_number: bool = False


@dataclass
class _Para:
    """A body paragraph: normalized+patched text, style name, and its lines."""

    text: str
    style: str
    lines: list[_Line]
    # The number Word's list numbering renders before the paragraph, where
    # the document declares a reading that needs it (`_ListNumbering`).
    label: str | None = None


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

    @property
    def lines(self) -> list[_Line]:
        return [line for paragraph in self.paragraphs for line in paragraph.lines]


def _is_bold(line: _Line) -> bool:
    # Word applies bold erratically to brackets/whitespace runs; only the runs
    # spelling the AVP name itself are trusted (`*{ `=True, `Data-Reference`=None,
    # ` }`=True occurs in real documents for a non-bold AVP).
    if len(line.bold) > 1:
        raise ExtractionError(f"mixed bold in ABNF line: {line.text!r}")
    return next(iter(line.bold), False)


_TABBED_NUMBER_RE = re.compile(r"\S(?:\t|[ \xa0]{2,})[\s\xa0]*\d+[\s\xa0]*$")


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
                if any(char.isalnum() for char in piece):
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


def _sections(
    document: docx.document.Document,
    patcher: Patcher,
    quirks: sources.Quirks | None = None,
) -> list[_Section]:
    sections: list[_Section] = []
    current: _Section | None = None
    caption: str | None = None
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
                current.tables.append(_Table(caption=caption, rows=rows))
            caption = None
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
                current = _Section(
                    number=match["number"],
                    title=patcher.apply(_normalize(match["title"]), match["number"]),
                )
                sections.append(current)
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
            current = _Section(number=match["number"], title=match["title"])
            sections.append(current)
            continue
        if match := _TABLE_CAPTION_RE.match(text):
            caption = match["label"]
        if current is not None:
            lines = _lines(item, style, patcher, number)
            current.paragraphs.append(
                _Para(text=text, style=style, lines=lines, label=label)
            )
    return sections


# The members commented out of a body behind `struck-rules-unused`, by the
# message or grouped AVP they were struck from: each the note standing for it,
# with the number of members before it.
type _Commented = list[tuple[ast.Message | ast.GroupedAvp, list[tuple[int, str]]]]


def _abnf_body(
    lines: list[_Line],
    start: int,
    rule: str,
    quirks: sources.Quirks,
    warnings: list[str],
) -> tuple[tuple[ast.AvpRule, ...], int, list[tuple[int, str]]]:
    """Parse `[qual] bracket Name bracket` lines starting at `start`.

    Also returns the members commented out behind `struck-rules-unused`,
    each as the note standing for it with the number of members before it."""
    rules: list[ast.AvpRule] = []
    struck: list[tuple[int, ast.AvpRule]] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.text:
            # TS 32.299 leaves blank lines between a message header and its
            # first member (clauses 6.2.2-6.4.5) and inside CCA's body
            # (6.4.3); a blank line followed by anything else ends the body.
            following = next((later for later in lines[index:] if later.text), None)
            if following is None or not _abnf_members(following.text):
                break
            index += 1
            continue
        matches = _abnf_members(line.text)
        if (
            not matches
            and quirks.enabled("abnf-comments")
            and (commented := _ABNF_COMMENT_RE.fullmatch(line.text))
            and (matches := _abnf_members(commented["rule"]))
        ):
            # TS 29.209 V6.8.0 clause 6.5.18: "{ Media-Component-Number } ;
            # Ordinal number of the media comp." The comment is RFC 5234's
            # (section 3.9) and prose, which a `.dad` body does not keep.
            quirks.fire("abnf-comments")
            line = dataclasses.replace(line, text=commented["rule"])
        if not matches:
            break
        index += 1
        if len(matches) > 1 and True in line.struck:
            raise ExtractionError(f"struck line with several members: {line.text!r}")
        for match in matches:
            member = _abnf_member(match, line, rule, quirks, warnings)
            if member.strikethrough and quirks.enabled("struck-rules-unused"):
                # TS 32.299 clauses 6.2.1.2 and 6.4.1.2 define the strike: "An
                # AVP in grey strikethrough in the message format ... is not
                # used by 3GPP". The document's own legend says the member is
                # not part of its rule, so it is no member; it stays in the
                # file as a comment, where the reader still sees it.
                quirks.fire("struck-rules-unused")
                struck.append((len(rules), member))
            else:
                rules.append(member)
    # Aligned over the struck members too, so a body's markers stay one
    # column whichever kind of line is longest.
    members = [*rules, *(member for _, member in struck)]
    commented = [
        (position, formatter.commented_avp_rule(member, members))
        for position, member in struck
    ]
    return tuple(rules), index, commented


# An ABNF line with a trailing comment, read behind `abnf-comments`.
_ABNF_COMMENT_RE = re.compile(r"(?P<rule>[^;]*\S) ?;.*")


def _abnf_members(text: str) -> list[re.Match]:
    """The members one ABNF line holds: normally one, but TS 32.299 clause
    7.2.154I prints "[ ProSe-Request-Timestamp ] [ PC3-Control-Protocol-Cause ]"
    on one line (the PDF too). A line counts only when members cover all of
    it."""
    if match := _ABNF_LINE_RE.match(text):
        return [match]
    pieces = _ABNF_MEMBER_RE.findall(text)
    if len(pieces) < 2 or "".join(pieces).replace(" ", "") != text.replace(" ", ""):
        return []
    found = [_ABNF_LINE_RE.match(piece.strip()) for piece in pieces]
    return [match for match in found if match is not None]


def _abnf_member(
    match: re.Match,
    line: _Line,
    rule: str,
    quirks: sources.Quirks,
    warnings: list[str],
) -> ast.AvpRule:
    """One member, struck through or not, which `; strikethrough` records as
    `; bold` records bold."""
    if False in line.struck and True in line.struck:
        raise ExtractionError(f"partly struck ABNF line: {line.text!r}")
    struck = True in line.struck
    if struck and not quirks.enabled("struck-rules-unused"):
        # A strike with no legend the extractor reads: the marker records
        # it, and the member stays, since nothing says what it means.
        warnings.append(f"{rule}: member {match['name']} is struck through")
    try:
        return abnf.avp_rule(match, bold=_is_bold(line), strikethrough=struck)
    except abnf.AbnfError as error:
        raise ExtractionError(f"{error} in {line.text!r}") from None


def _rule_text(text: str, quirks: sources.Quirks) -> str:
    """TS 32.299 spells the rule operator ":: =" in about ninety grouped
    rules (clause 7.2.0A onwards), TS 29.229 in four (6.3.13, 6.3.16, 6.3.19,
    6.3.64). A document convention rather than a typo, and per-document like
    `dotted-flags`, so the reading is declared; undeclared it fails, where it
    used to drop the definition silently."""
    if ":: =" not in text:
        return text
    if not quirks.enabled("spaced-rule-operator"):
        raise ExtractionError(
            f"rule operator spelled ':: =' in {text!r}, which this document's"
            " source declaration does not read (the `spaced-rule-operator` quirk)"
        )
    quirks.fire("spaced-rule-operator")
    return text.replace(":: =", "::=")


def _find_rule_header(
    section: _Section, pattern: re.Pattern, quirks: sources.Quirks
) -> tuple[re.Match, int] | None:
    for index, line in enumerate(section.lines):
        text = _rule_text(line.text, quirks)
        if "::=" in text:
            match = pattern.match(text)
            if match is None:
                raise ExtractionError(
                    f"{section.number}: malformed rule header {line.text!r}"
                )
            return match, index + 1
    return None


# Behind `rfc-command-rules`, the RFCs' names of the commands a procedure clause
# prints by rule alone, keyed by command code and whether the R bit is set: RFC
# 6733 section 3.1 (Re-Auth, Accounting, Abort-Session, Session-Termination),
# RFC 7155 section 3 (AA) and RFC 4072 section 3 (Diameter-EAP). TS 29.234
# V11.2.0 clause 4.4.2.2 prints "ABNF for the ASR and ASA commands are as
# follows:" over `<ASR> ::=`, and 4.4.2.1 `<Diameter-EAP-Request> ::=` under
# "DER and DEA Commands".
_RFC_COMMANDS = {
    (258, True): ("Re-Auth-Request", "RAR"),
    (258, False): ("Re-Auth-Answer", "RAA"),
    (265, True): ("AA-Request", "AAR"),
    (265, False): ("AA-Answer", "AAA"),
    (268, True): ("Diameter-EAP-Request", "DER"),
    (268, False): ("Diameter-EAP-Answer", "DEA"),
    (271, True): ("Accounting-Request", "ACR"),
    (271, False): ("Accounting-Answer", "ACA"),
    (274, True): ("Abort-Session-Request", "ASR"),
    (274, False): ("Abort-Session-Answer", "ASA"),
    (275, True): ("Session-Termination-Request", "STR"),
    (275, False): ("Session-Termination-Answer", "STA"),
}


def _rfc_command(
    section: _Section, header: re.Match, quirks: sources.Quirks
) -> re.Match | None:
    """What an intro would say of a rule no intro names, read as a title.
    None without the quirk, and an error for a code no RFC here defines or a
    rule abbreviating the command otherwise."""
    if not quirks.enabled("rfc-command-rules"):
        return None
    try:
        code, flags, _ = abnf.diameter_header(header["items"])
    except abnf.AbnfError as error:
        raise ExtractionError(f"{section.number}: {error}") from None
    known = _RFC_COMMANDS.get((code, ast.CommandFlag.REQUEST in flags))
    rule = header["name"].replace(" ", "")
    if known is None or (rule.isupper() and rule != known[1]):
        raise ExtractionError(
            f"{section.number}: rule {rule!r} over command {code} is none of"
            " the RFC commands `rfc-command-rules` reads"
        )
    quirks.fire("rfc-command-rules")
    return _COMMAND_INTRO_RE.match(f"The {known[0]} ({known[1]}) command,")


def _extract_messages(
    section: _Section,
    title: re.Match | None,
    warnings: list[str],
    quirks: sources.Quirks,
    commented: _Commented,
    message_heading: bool = False,
) -> list[ast.Message]:
    """A command section usually holds one ABNF, but can hold several — the
    same command under different application ids (TS 29.272 defines IDR/DSR/RSR
    once for S6a and once for S7a in one section).

    With `message_heading`, `title` is a "Name message" heading whose rule
    is spelled with the abbreviation (`<ACR> ::=`, TS 32.299 clauses
    6.2.2-6.4.5): the long name comes from the heading, as the RFC extractor
    takes it for RFC 6733's `<CER> ::=`."""
    messages = []
    prose_title = title is None
    lines = section.lines
    index = 0
    while index < len(lines):
        text = _rule_text(lines[index].text, quirks)
        index += 1
        if prose_title and (intro := _COMMAND_INTRO_RE.match(text)):
            title = intro
        if "::=" not in text:
            continue
        header = _DIAMETER_HEADER_RE.match(text)
        if header is None:
            raise ExtractionError(f"{section.number}: malformed rule header {text!r}")
        if title is None:
            title = _rfc_command(section, header, quirks)
        if title is None:
            raise ExtractionError(
                f"{section.number}: command ABNF without a named intro"
            )
        if prose_title:
            quirks.fire("procedure-commands")
        rule_name = header["name"].replace(" ", "")
        if prose_title and rule_name == title["abbr"]:
            # `<ASR> ::=`, as RFC 6733 prints it: the long name is the title's.
            rule_name = title["name"]
        if message_heading:
            quirks.fire("message-headings")
            if not re.fullmatch(r"[A-Z]{2,5}", rule_name) or (
                title["abbr"] is not None and title["abbr"] != rule_name
            ):
                raise ExtractionError(
                    f"{section.number}: message heading {title['name']!r} over"
                    f" rule {rule_name!r}, which is not its abbreviation"
                )
            abbreviation = rule_name
            rule_name = title["name"]
        else:
            abbreviation = title["abbr"]
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
        avps, index, struck = _abnf_body(lines, index, rule_name, quirks, warnings)
        message = ast.Message(
            name=rule_name,
            abbreviation=abbreviation,
            source=ast.SourceRef(section=section.number),
            command_code=command_code,
            flags=flags,
            application_id=application_id,
            avps=avps,
        )
        messages.append(message)
        if struck:
            commented.append((message, struck))
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


# Behind `prose-application-ids`: a 3GPP document stating the application id
# its command headers omit. The first two wordings are each used by several
# documents; the retired documents have wordings of their own.
_APPLICATION_ID_RES = (
    # TS 29.212 clause 5.1, and 29.154, 29.214, 29.215, 29.217 likewise:
    # "... and the Application-ID for the Gx Application in the present
    # release is 16777238." 29.212's Sd and St (5b.1, 5c.1) open a sentence
    # with it and drop "in the present release".
    re.compile(
        r"[Tt]he Application-ID for the (?P<name>\S+) [Aa]pplication"
        r"(?: in the present release)? is (?P<id>\d+)\b"
    ),
    # TS 29.219 clause 5.1.5, and 29.343, 29.368, 29.468 likewise: "The
    # Diameter application identifier assigned to the Sy interface
    # application is 16777302."
    re.compile(
        r"^The Diameter application identifier assigned to the (?P<name>\S+)"
        r" interface application(?: in the present release)? is (?P<id>\d+)\."
    ),
    # TS 29.209 V6.8.0 clause 6.1: "The Gq application is defined as an IETF
    # vendor specific Diameter application with application ID 16777222".
    re.compile(
        r"^The (?P<name>\S+) application is defined as an IETF vendor specific"
        r" Diameter application with application ID (?P<id>\d+)\b"
    ),
    # TS 29.210 V6.7.0 clauses 6.1 and 6.2: "The Auth-Application-Id for the
    # Gx over Gy Application is 16777225 as allocated by IANA."; TS 29.211
    # V6.4.0 clause 7.1: "The Application Identifier for the Rx application is
    # 16777229 as allocated by IANA."
    re.compile(
        r"The (?:Auth-Application-Id|Application Identifier) for the"
        r" (?P<name>.+?) [Aa]pplication is (?P<id>\d+) as allocated by IANA"
    ),
    # TS 29.234 V11.2.0 clauses 6.2 and 11.2: "The Wx reference point shall be
    # Diameter based and shall have an application ID defined for it. ... The
    # application identifier is to 16777219."
    re.compile(
        r"^The (?P<name>\S+) [Rr]eference [Pp]oint shall be Diameter based and"
        r" shall have an application ID defined for it\..*"
        r"The application identifier is to (?P<id>\d+)\."
    ),
)


def _stated_applications(
    section: _Section, quirks: sources.Quirks
) -> list[ast.ApplicationScope]:
    """The applications a clause states the ids of, each applying to the
    interface clause the statement sits in: Gx's clause 5.1 speaks for the
    commands of clause 5 (`5.*`), S9a's A.7.1 for those of A.7 (`A.7.*`)."""
    found = []
    for paragraph in section.paragraphs:
        for pattern in _APPLICATION_ID_RES:
            if match := pattern.search(paragraph.text):
                quirks.fire("prose-application-ids")
                found.append(
                    ast.ApplicationScope(
                        name=match["name"],
                        source=ast.SourceRef(section=section.number),
                        application_id=int(match["id"]),
                        applies_to=(f"{ast.interface_clause(section.number)}.*",),
                    )
                )
    return found


def _extract_grouped(
    section: _Section,
    header: re.Match,
    body_start: int,
    name: str,
    quirks: sources.Quirks,
    warnings: list[str],
    commented: _Commented,
) -> ast.GroupedAvp:
    vendor = header["vendor"]
    avps, _, struck = _abnf_body(section.lines, body_start, name, quirks, warnings)
    grouped = ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=int(header["code"]),
        vendor_id=None if vendor is None else int(vendor),
        avps=avps,
    )
    if struck:
        commented.append((grouped, struck))
    return grouped


def _extract_enumerated(
    section: _Section,
    name: str,
    code: int,
    vendor_id: int | None,
    quirks: sources.Quirks,
    warnings: list[str],
) -> ast.EnumeratedAvp:
    values: list[ast.EnumValue] = []
    ranges: list[ast.ReservedValues | ast.VendorSpecificValues] = []
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
    #
    # The one exception is a description printed on the value's own line
    # after a colon (TS 32.299 clause 7.2.132, "2 High priority: Lower than
    # Pre-emptive priority"): that is the document's own one-line gloss.
    for paragraph in section.paragraphs:
        text = paragraph.text
        if not text:
            continue
        if (
            quirks.enabled("list-numbered-enum-values")
            and paragraph.label is not None
            and (number := _LIST_VALUE_RE.fullmatch(paragraph.label))
        ):
            # TS 32.299 V11.20.0 clauses 7.2.132-7.2.151: the value is the
            # number Word's list renders before the label ("0 Participating
            # PoC Server", "1. Moderator" in the ETSI PDF), which the text
            # does not carry.
            match = _VALUE_FIRST_RE.fullmatch(f"{number['value']} {text}")
            if match is None:
                raise ExtractionError(
                    f"{section.number}: list-numbered value {text!r} is no value"
                )
            quirks.fire("list-numbered-enum-values")
            values.append(_value_first(match, section.number))
        elif match := _ENUM_VALUE_RE.fullmatch(text):
            values.append(ast.EnumValue(name=match["name"], value=int(match["value"])))
        elif value := _loose_enum_value(text, section.number, quirks):
            values.append(value)
        elif quirks.enabled("run-on-enum-values") and _RUN_ON_ENUM_VALUES_RE.fullmatch(
            text
        ):
            quirks.fire("run-on-enum-values")
            values.extend(
                ast.EnumValue(name=match["name"], value=int(match["value"]))
                for match in _RUN_ON_ENUM_VALUE_RE.finditer(text)
            )
        elif paragraph.style == "NO" and (match := _RESERVED_NOTE_RE.search(text)):
            first = int(match["first"])
            ranges.append(
                ast.ReservedValues(first=first, last=int(match["last"] or first))
            )
        elif any(
            quirks.enabled(name)
            for name in (
                "value-first-enums",
                "value-last-enums",
                "bracketed-enum-values",
                "dotted-enum-values",
            )
        ):
            for line in paragraph.lines:
                if (
                    quirks.enabled("value-last-enums")
                    and line.tabbed_number
                    and (match := _VALUE_LAST_RE.fullmatch(line.text))
                ):
                    quirks.fire("value-last-enums")
                    values.append(_value_first(match, section.number))
                elif quirks.enabled("bracketed-enum-values") and (
                    match := _BRACKETED_VALUE_RE.fullmatch(line.text)
                ):
                    quirks.fire("bracketed-enum-values")
                    values.append(_value_first(match, section.number))
                elif quirks.enabled("dotted-enum-values") and (
                    match := _DOTTED_VALUE_RE.fullmatch(line.text)
                ):
                    quirks.fire("dotted-enum-values")
                    values.append(_value_first(match, section.number))
                elif not quirks.enabled("value-first-enums"):
                    continue
                elif match := _VALUE_RANGE_RE.fullmatch(line.text):
                    # SM-Service-Type (TS 32.299 clause 7.2.213) closes its
                    # list with "11 .. 99 Reserved for 3GPP defined SM
                    # services" and "100 .. 199 Vendor specific SM services",
                    # oneM2M TS-0004's Protocol-Type (A.5.17) with "100 ..
                    # 199 Operator and vendor specific protocol types". The
                    # first is a reserved range, the others vendor-specific
                    # ones, which keep the words. Vendor wording decides
                    # before "Reserved" does: values reserved for vendor use
                    # are allocated to vendors. Any negation in the words
                    # ("Not for vendor-specific services") leaves the range
                    # unread, as does a range allocated otherwise, which
                    # names no value `.dad` can hold and is reported instead.
                    quirks.fire("value-first-enums")
                    first, last = int(match["first"]), int(match["last"])
                    label = match["label"]
                    vendor = _VENDOR_SPECIFIC_LABEL_RE.search(label)
                    if vendor and not _NEGATION_RE.search(label):
                        ranges.append(
                            ast.VendorSpecificValues(
                                first=first, last=last, description=label
                            )
                        )
                    elif not vendor and label.startswith("Reserved"):
                        ranges.append(ast.ReservedValues(first=first, last=last))
                    else:
                        warnings.append(
                            f"{section.number}: value range {first}..{last}"
                            f" {match['label']!r} names no value and was not"
                            " recorded"
                        )
                elif match := _VALUE_FIRST_RE.fullmatch(line.text):
                    quirks.fire("value-first-enums")
                    values.append(_value_first(match, section.number))
    if quirks.enabled("prose-enum-values"):
        for paragraph in section.paragraphs:
            for match in _PROSE_ENUM_VALUE_RE.finditer(paragraph.text):
                quirks.fire("prose-enum-values")
                values.append(
                    ast.EnumValue(name=match["name"], value=int(match["value"]))
                )
    values_source = _values_source(section, quirks)
    if not values and not ranges and values_source is None:
        # Kept empty rather than dropped: the clause still says the AVP is
        # enumerated, and a value line in a shape no declared reading takes
        # shows up here rather than as a silently shorter list.
        warnings.append(f"{section.number}: enumerated AVP {name} lists no values")
    merged = sorted(
        [*values, *ranges],
        key=lambda item: item.value if isinstance(item, ast.EnumValue) else item.first,
    )
    return ast.EnumeratedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=code,
        vendor_id=vendor_id,
        values_source=values_source,
        values=tuple(merged),
    )


# A value named in a sentence, read behind `prose-enum-values`: oneM2M TS-0004
# clause A.5.3, "The following value is currently defined for the
# Accounting-Record-Type AVP: EVENT_RECORD (value 1) for an Event Based
# request."
_PROSE_ENUM_VALUE_RE = re.compile(
    r"\b(?P<name>[A-Z][A-Z0-9_]*) \(value (?P<value>\d+)\)"
)


# Behind `external-enum-values`: an enumerated clause naming the document or
# clause its values are defined in, one lead-in per document's wording. What
# follows the lead-in is the source as printed, reference number included.
_VALUES_SOURCE_RES = (
    # TS 29.272 clauses 7.3.67, 7.3.137 and ten more: "The possible values
    # are those defined in TS 32.422 [23] for Trace Depth."
    re.compile(r"The possible values are those defined in (?P<source>.+?)\.?$"),
    # TS 29.212 clause 5.3.120: "The values defined in the Default-Access AVP
    # are the same as the ones defined in IP-CAN-Type AVP."
    re.compile(
        r"The values defined in the \S+ AVP are the same as the ones defined in"
        r" (?P<source>.+?)\.?$"
    ),
    # TS 29.061 clause 17.7.25: "The enumeration values are defined in 3GPP
    # TS 25.413 [92]."
    re.compile(r"The enumeration values are defined in (?P<source>.+?)\.?$"),
    # TS 32.299 clause 7.2.238: "The values are taken from OMNA WSP Content
    # Type Numbers [210]."
    re.compile(r"The values are taken from (?P<source>.+?)\.?$"),
    # oneM2M TS-0004 clause A.5.22: "... the type of operation requested.
    # The values are defined in Table 6.3.4.2.5-6.", A.5.25 likewise.
    re.compile(r"(?:^|\. )The values are defined in (?P<source>.+?)\.?$"),
    # TS 32.299 clause 7.2.20eA: "... and holds the identifier of the network
    # element as defined in TS 23.682[243], that triggers the API
    # notification." TS 23.682 V18.0.0 names the network elements but
    # numbers none of them.
    re.compile(
        r"holds the identifier of the network element as defined in"
        r" (?P<source>[^,]+),"
    ),
)


def _values_source(section: _Section, quirks: sources.Quirks) -> str | None:
    """Where the clause says its values are defined, if it says so in one of
    the wordings `_VALUES_SOURCE_RES` reads."""
    if not quirks.enabled("external-enum-values"):
        return None
    found = [
        match["source"]
        for paragraph in section.paragraphs
        for pattern in _VALUES_SOURCE_RES
        if (match := pattern.search(paragraph.text))
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


# TS 32.299 writes its value lists value first, and labels values in words:
# "0 PS to CS Transfer" (clause 7.2.1B). The label ends at the first colon;
# what follows is the line's description ("2 High priority: Lower than
# Pre-emptive priority", clause 7.2.132).
_VALUE_RANGE_RE = re.compile(r"(?P<first>\d+) ?\.\. ?(?P<last>\d+) (?P<label>.+)")
# A range's words allocating it to vendors or operators: "Vendor specific SM
# services" (TS 32.299 clause 7.2.213), "Operator and vendor specific
# protocol types" (oneM2M TS-0004 clause A.5.17).
_VENDOR_SPECIFIC_LABEL_RE = re.compile(r"\b(?:vendor|operator)[ -]specific\b", re.I)
# Words that turn the allocation around: "Not for vendor-specific services".
_NEGATION_RE = re.compile(r"\b(?:not|no|never|except)\b", re.I)
_VALUE_FIRST_RE = re.compile(
    r"(?P<value>\d+) (?P<label>[^:]+?)(?: ?:(?: (?P<description>.*))?)?"
)


# TS 32.299 V11.20.0 writes most value lists label first, the value set off
# by tabs: "MONETARY<tabs>0" (clause 7.2.14), "Calling Party<tab>0"
# (7.2.124). Read only where the printed line has that tab
# (`_Line.tabbed_number`).
_VALUE_LAST_RE = re.compile(r"(?P<label>.+?) (?P<value>\d+)(?P<description>)")


# TS 32.299 V11.20.0's other value-first shapes: the value bracketed, "[0]
# called party" (clause 7.2.101), or followed by a full stop, "0.
# SUBMISSION" (7.2.207, 7.2.218); each read behind its own quirk.
_BRACKETED_VALUE_RE = re.compile(r"\[(?P<value>\d+)\] (?P<label>.+?)(?P<description>)")
_DOTTED_VALUE_RE = re.compile(r"(?P<value>\d+)\. (?P<label>.+?)(?P<description>)")
# A list number Word renders before a value, behind `list-numbered-enum-values`:
# "0", or "1." (TS 32.299 V11.20.0 clause 7.2.151).
_LIST_VALUE_RE = re.compile(r"(?P<value>\d+)\.?")


# A label read out of prose is taken only in the shape a value name takes in
# the documents: words of letters, digits, `-`, `_` and parentheses, single
# spaces between (TS 32.299's "VAS4SMS Short Message Virtual Private Network
# (VPN)", 7.2.213). `.dad` can quote any label, but a line of prose that
# happens to follow a value is no label, and this is what turns it away.
_VALUE_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_()-]*(?: [A-Za-z0-9_()-]+)*")


def _loose_enum_value(
    text: str, section: str, quirks: sources.Quirks
) -> ast.EnumValue | None:
    """A value line departing from `NAME (n)` only in ways the document
    declares (`_LOOSE_ENUM_VALUE_RE`), else None, as for any other prose."""
    match = _LOOSE_ENUM_VALUE_RE.fullmatch(text)
    if match is None:
        return None
    needed = []
    if match["dash"]:
        needed.append("dashed-enum-values")
    if match["words"]:
        needed.append("worded-enum-values")
    if match["words"] and "," in match["words"]:
        # TS 29.140 V7.0.0 clause 6.3.5: "MM1 Message Submission, Profile
        # based (0)", a label `.dad` quotes (docs/grammar.md, quoted-name).
        needed.append("comma-enum-labels")
    if match["hex"]:
        needed.append("hex-enum-values")
    name, rest, description = match["name"], match["rest"], None
    if rest in {",", "."}:
        needed.append("punctuated-enum-values")
    elif rest and name:
        needed.append("described-enum-values")
        description = rest
    elif rest:
        # TS 29.109 clause 6.3.1.13 labels "- (0) Private user identity." after
        # the value; the full stop ends the sentence, not the label.
        needed.append("label-after-enum-value")
        name = rest.removesuffix(".")
    if name is None or not all(quirks.enabled(quirk) for quirk in needed):
        return None
    for quirk in needed:
        quirks.fire(quirk)
    value = int(match["value"]) if match["hex"] is None else int(match["hex"], 16)
    if _VALUE_LABEL_RE.fullmatch(name.replace(", ", " ")):
        with contextlib.suppress(pydantic.ValidationError):
            return ast.EnumValue(name=name, value=value, description=description)
    raise ExtractionError(f"{section}: enumerated value line {text!r} is no value name")


def _value_first(match: re.Match, section: str) -> ast.EnumValue:
    if _VALUE_LABEL_RE.fullmatch(match["label"]):
        with contextlib.suppress(pydantic.ValidationError):
            return ast.EnumValue(
                name=match["label"],
                value=int(match["value"]),
                description=match["description"] or None,
            )
    raise ExtractionError(
        f"{section}: enum value label {match['label']!r} is not a value name"
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
# extractor code, not several hundred input patches. A dash states nothing,
# as in the flag cells beside it: TS 32.299 V11.20.0's table 7.1 dashes
# every cell of the fifteen rows it does not use (CC-Sub-Session-Id,
# Vendor-Id), Encrypt included.
_ENCRYPT_CELLS = {"Yes": True, "Y": True, "No": False, "N": False, "": None, "-": None}


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
    # An empty cell, or TS 32.299's dash for one (tables 7.1.0.1, 7.2.0.1):
    # a lone dash names no flag and cannot be read as anything else.
    if text in ("", "-"):
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
    "AVP Name": ast.AvpColumn.NAME,  # TS 32.299 tables 7.1.0.1 and 7.2.0.1
    # oneM2M TS-0004 table A.4-1, "The entity defining the AVP code in the
    # next column" (clause A.4).
    "AVP Vendor Id": ast.AvpColumn.VENDOR,
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


# Columns marking where a row applies (`ast.MarkColumn`), keyed by the label
# they print. A cell lists the document's marks, and what separates them is
# the document's convention rather than a closed vocabulary: TS 29.212
# writes "Both Rel8" and "3GPP-EPS, Non-3GPP-EPS", where TS 29.468 names a
# feature "V2X Localized User Plane" (`worded-marks`). Reading a column at a
# space is right for one document and wrong for the next, so each column is
# read only where its quirk is declared, the declaration naming the legend;
# elsewhere it is dropped with the unmodelled columns' warning.
_MARK_COLUMNS = {
    "Acc. Type": ast.MarkColumn.ACCESS_TYPES,
    "Acc. type": ast.MarkColumn.ACCESS_TYPES,  # TS 29.215
    "Applicability": ast.MarkColumn.APPLICABILITY,
    # TS 29.215 tables A.7.4.1.1 and A.8.4.1.1, the note reference unbracketed.
    "Applicability Note 1": ast.MarkColumn.APPLICABILITY,
    "Applicable Reference Points": ast.MarkColumn.REFERENCE_POINTS,
    # TS 32.299's "Used in" columns, under a spanning header.
    "ACR": ast.MarkColumn.ACR,
    "ACA": ast.MarkColumn.ACA,
    "CCR": ast.MarkColumn.CCR,
    "CCA": ast.MarkColumn.CCA,
}
_MARK_QUIRKS = {
    ast.MarkColumn.ACCESS_TYPES: "access-type-column",
    ast.MarkColumn.APPLICABILITY: "applicability-column",
    ast.MarkColumn.REFERENCE_POINTS: "reference-points-column",
    ast.MarkColumn.ACR: "command-columns",
    ast.MarkColumn.ACA: "command-columns",
    ast.MarkColumn.CCR: "command-columns",
    ast.MarkColumn.CCA: "command-columns",
}


def _with_marks[T: enum.StrEnum](
    known: dict[str, T], kind: type[T], quirks: sources.Quirks
) -> dict[str, T]:
    """`known` plus the mark columns this document's quirks read."""
    return known | {
        label: kind(column.value)
        for label, column in _MARK_COLUMNS.items()
        if quirks.enabled(_MARK_QUIRKS[column])
    }


# A mark as a cell prints it: a word, followed by what the document prints
# beside it in parentheses, a note reference mostly ("All (NOTE 5)", "All
# (see NOTE 3 and NOTE 6)", "EPC-routed (See NOTE 8)"). The parenthetical
# stays with its mark: TS 29.212's note 5 says the AVP "does not apply to
# 3GPP-GPRS access type", which a bare `All` would lose. Behind
# `worded-marks` a mark may be several words, separated from the next by a
# comma only (TS 29.468's "V2X Localized User Plane", "ROHC, FEC").
_MARK_WORD = r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?"
_PARENTHETICAL = r"(?:\s*\([^()]*\))?"
_SPACED_MARK_RE = re.compile(rf"{_MARK_WORD}{_PARENTHETICAL}")
_SPACED_SEPARATOR_RE = re.compile(r"\s*,\s*|\s+")
_WORDED_MARK_RE = re.compile(rf"{_MARK_WORD}(?: {_MARK_WORD})*{_PARENTHETICAL}")
_WORDED_SEPARATOR_RE = re.compile(r"\s*,\s*")


def _split_marks(
    text: str, mark: re.Pattern[str], separator: re.Pattern[str]
) -> list[str] | None:
    """`text` as marks, or None where something between them is neither a
    mark nor a separator."""
    marks: list[str] = []
    position = 0
    while (found := mark.match(text, position)) is not None:
        marks.append(found.group())
        if found.end() == len(text):
            return marks
        gap = separator.match(text, found.end())
        if gap is None:
            return None
        position = gap.end()
    return None


def _mark_cell(
    text: str, column: ast.MarkColumn, name: str, quirks: sources.Quirks
) -> tuple[str, ...] | None:
    """A mark column's cell: None where it is blank, no marks where it
    prints a dash (TS 32.299 clause 7.1.0: "Those Diameter AVPs that are not
    used are marked '-'"), and otherwise its marks, separated by commas or
    spaces, or behind `worded-marks` by commas only. A mark that is not
    words — a hyphen left by a line wrap ("NetLoc- Untrusted-WLAN" in TS
    29.212), a full stop for a comma — fails, for an input patch."""
    quirks.fire(_MARK_QUIRKS[column])
    if not text:
        return None
    if text == "-":
        return ()
    if quirks.enabled("worded-marks"):
        quirks.fire("worded-marks")
        marks = _split_marks(text, _WORDED_MARK_RE, _WORDED_SEPARATOR_RE)
    else:
        marks = _split_marks(text, _SPACED_MARK_RE, _SPACED_SEPARATOR_RE)
    if marks is None:
        raise ExtractionError(
            f"row {name!r}: {column.value} cell {text!r} is no list of marks"
        )
    return tuple(marks)


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


# The label a table prints over its name column. A row starting with one is
# the column-label row.
_NAME_LABELS = frozenset({"Attribute Name", "AVP Name"})


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
    stacked = False
    for index, row in enumerate(table.rows):
        cells = row.cells
        if not cells:
            raise ExtractionError(f"{kind} row with no cells")
        if stacked:
            stacked = False
            continue
        if cells[0] in _NAME_LABELS:
            # A two-row header: the upper row groups ("Used in", "AVP Flag
            # rules"), the lower one labels. TS 32.299 table 7.1.0.1 repeats
            # "AVP Name" in both rows; table 7.2.0.1 prints it only in the
            # upper one, leaving the lower row's first cell blank. The lower
            # row is a label row because it carries known labels, which no
            # data row does.
            following = (
                table.rows[index + 1].cells if index + 1 < len(table.rows) else []
            )
            if (
                following
                and following[0] in ("", cells[0])
                and any(
                    label in known and known[label] != known.get(cells[0])
                    for label in following[1:]
                )
            ):
                cells = [cells[0], *following[1:]]
                stacked = True
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
    table: _Table,
    section_number: str,
    warnings: list[str],
    quirks: sources.Quirks,
    references: dict[str, str] | None = None,
    own_reference: str = "",
) -> tuple[ast.AvpTable, list[ast.ReusedAvpRow]]:
    """Column *order* has been identical in every 3GPP specification examined,
    but the set has not: TS 29.273's table has no Encrypt column, TS 29.212's
    has two the format does not model. Reading the labels rather than assuming
    nine positions is what lets those be extracted at all, and what keeps a
    missing column distinguishable from an empty cell."""
    rows: list[ast.AvpTableRow] = []
    note_refs: list[tuple[str, str]] = []  # (avp name, note number)
    note_rfcs: dict[str, str] = {}  # note number -> RFC number
    referred: list[ast.ReusedAvpRow] = []  # from `refer [n]` type cells

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

    known = _with_marks(_AVP_TABLE_COLUMNS, ast.AvpColumn, quirks)
    if quirks.enabled("reference-cells"):
        known["Reference"] = ast.AvpColumn.SECTION
    columns, positions, data_rows = _walk_table(
        table, known, "AVP table", warnings, skip
    )
    for cells in data_rows:
        name = ""
        marks: dict[ast.MarkColumn, tuple[str, ...]] = {}
        vendor_value: int | None = None
        code_value: int | None = None
        section_value: str | None = None
        type_value: str | None = None
        printed_type: str | None = None
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
                case ast.AvpColumn.VENDOR:
                    if text and not text.isdigit():
                        raise ExtractionError(f"AVP table vendor cell {text!r}")
                    vendor_value = int(text) if text else None
                case ast.AvpColumn.CODE:
                    code, code_note = _strip_note_ref(text)
                    if code == "*" and name == "AVP":
                        # TS 32.299 table 7.1.0.1 tabulates the `* [ AVP ]`
                        # wildcard as a row with code "*": any AVP, so no code.
                        if not quirks.enabled("wildcard-avp-row"):
                            raise ExtractionError(
                                "AVP table row 'AVP' with code '*', which this"
                                " document's source declaration does not read"
                                " (the `wildcard-avp-row` quirk)"
                            )
                        quirks.fire("wildcard-avp-row")
                        code = ""
                    if code and not code.isdigit():
                        raise ExtractionError(f"AVP table code cell {code!r}")
                    code_value = int(code) if code else None
                    note = note or code_note
                case ast.AvpColumn.SECTION if quirks.enabled("reference-cells"):
                    section_value, origin = _reference_cell(name, text, quirks)
                    if origin is not None:
                        referred.append(ast.ReusedAvpRow(name=name, origin=origin))
                case ast.AvpColumn.SECTION:
                    section_value = _clause_cell(text, quirks) or None
                    # Checked here so a typo (TS 29.368 table 6.4.1.1's
                    # "6. 4.2") names its row, not a pydantic pattern.
                    if section_value is not None and not _SECTION_REF_RE.match(
                        section_value
                    ):
                        raise ExtractionError(
                            f"{section_number}: AVP table row {name!r} has"
                            f" clause cell {section_value!r}, which is not a"
                            " clause number"
                        )
                case ast.AvpColumn.TYPE:
                    type_value = text or None
                    if match := _REFER_RE.fullmatch(text):
                        type_value = None
                        origin = _referred_origin(
                            name, match["number"], references, own_reference, quirks
                        )
                        if origin is None:
                            warnings.append(
                                f"AVP table row {name!r} is typed by reference"
                                f" [{match['number']}], which names no document"
                                " a From cell can cite; kept without a type"
                            )
                        else:
                            referred.append(ast.ReusedAvpRow(name=name, origin=origin))
                    elif type_value in _TYPE_SHORT_FORMS:
                        if not quirks.enabled("type-short-forms"):
                            raise ExtractionError(
                                f"AVP table Value Type cell {text!r} is a short"
                                " form, which this document's source declaration"
                                " does not read (the `type-short-forms` quirk)"
                            )
                        quirks.fire("type-short-forms")
                        type_value = _TYPE_SHORT_FORMS[type_value]
                    elif (
                        type_value is not None
                        and type_value not in ast.DataType
                        and quirks.enabled("unknown-type-tokens")
                    ):
                        # TS 29.234 V11.2.0 table 10.1.1 and clause 10.1.27
                        # type code 314 "Integer", which names no width.
                        quirks.fire("unknown-type-tokens")
                        printed_type, type_value = type_value, None
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
                case _:
                    marked = ast.MarkColumn(column.value)
                    found = _mark_cell(text, marked, name, quirks)
                    if found is not None:
                        marks[marked] = found
        if note is not None:
            note_refs.append((name, note))
        rows.append(
            ast.AvpTableRow(
                name=name,
                vendor_id=vendor_value,
                code=code_value,
                section=section_value,
                data_type=_data_type(type_value),
                printed_type=printed_type,
                flag_rules=ast.AvpFlagRules(
                    must=must, may=may, should_not=should_not, must_not=must_not
                ),
                may_encrypt=encrypt,
                marks=marks,
            )
        )
    if table.caption is None:
        raise ExtractionError("AVP table without a caption")
    reused = [
        ast.ReusedAvpRow(name=name, origin=f"RFC{note_rfcs[note]}")
        for name, note in note_refs
        if note in note_rfcs
    ] + referred
    avp_table = ast.AvpTable(
        table=table.caption,
        columns=columns,
        rows=tuple(rows),
        source=ast.SourceRef(section=section_number),
    )
    return avp_table, reused


# oneM2M TS-0004 table A.4-1's Reference cell: a bracketed clause of the
# document itself ("[A.5.1]"), or another document by its clause-2 entry
# ("IETF RFC 6733 [14]", "3GPP TS 32.299 [31]").
_BRACKETED_CLAUSE_RE = re.compile(r"\[(?P<clause>[^\[\]]+)\]")


def _reference_cell(
    name: str, text: str, quirks: sources.Quirks
) -> tuple[str | None, str | None]:
    """A Reference cell as (the row's defining clause, the document it is
    re-used from), the `reference-cells` quirk.

    Clause A.4 of oneM2M TS-0004 calls the column "a reference to where
    this AVP is defined": a bracketed clause number is the document's own,
    which a 3GPP table prints under "Clause defined"; a document's name is
    a re-use, as `refer [n]` is in TS 32.299. Anything else fails."""
    quirks.fire("reference-cells")
    if not text:
        return None, None
    if match := _BRACKETED_CLAUSE_RE.fullmatch(text):
        clause = match["clause"]
        if not _SECTION_REF_RE.match(clause):
            raise ExtractionError(
                f"AVP table row {name!r} has Reference cell {text!r}, whose"
                " bracket holds no clause number"
            )
        return clause, None
    origin = _named_document(text)
    if origin is None:
        raise ExtractionError(
            f"AVP table row {name!r} has Reference cell {text!r}, which names"
            " neither a clause nor a document"
        )
    return None, origin


# "The DCD-Information AVP (AVP code 2115) is of type Grouped.", TS 32.299
# clause 7.2.50: the sentence every AVP clause of the document opens with.
_TYPE_SENTENCE_RE = re.compile(
    r"^The (?P<name>\S+) AVP \(AVP code (?P<code>\d+)\) is of type"
    r" (?P<type>[A-Za-z0-9]+)\b"
)


def _referred_type_sentences(
    table: ast.AvpTable,
    referred: list[ast.ReusedAvpRow],
    sections: list[_Section],
    warnings: list[str],
    quirks: sources.Quirks,
) -> ast.AvpTable:
    """`table` with each row typed `refer [n]` typed from its own clause,
    where the document has one stating the type. The
    `referred-type-sentences` quirk.

    TS 32.299 table 7.2.0.1 types thirteen AVPs "refer [223]",
    OMA-DDS-Charging_Data, and for three of them clauses 7.2.50, 7.2.69
    and 7.2.191 say "The DCD-Information AVP (AVP code 2115) is of type
    Grouped" before "The AVP is defined in OMA-DDS-Charging_Data [223]",
    printing no body: the document's own statement of the type, which the
    row's cell defers. The re-used row stays, since the definition is
    still OMA's. A clause naming another code fails.
    """
    names = {row.name for row in referred}
    titled: dict[str, _Section] = {}
    for section in sections:
        if (match := _AVP_TITLE_RE.match(section.title)) and match["name"] in names:
            titled.setdefault(match["name"], section)
    rows = []
    for row in table.rows:
        section = titled.get(row.name) if row.data_type is None else None
        if section is not None:
            opening = section.paragraphs[0].text if section.paragraphs else ""
            match = _TYPE_SENTENCE_RE.match(opening)
            if match is None or match["name"] != row.name:
                warnings.append(
                    f"{section.number}: {row.name} is typed by reference in"
                    f" table {table.table}, and its clause states no type"
                )
            elif row.code is not None and int(match["code"]) != row.code:
                raise ExtractionError(
                    f"{section.number}: {row.name} has code {match['code']},"
                    f" table {table.table} {row.code}"
                )
            else:
                data_type = _data_type(match["type"])
                row = row.model_copy(update={"data_type": data_type})
                quirks.fire("referred-type-sentences")
        rows.append(row)
    return table.model_copy(update={"rows": tuple(rows)})


_VENDOR_ID_SENTENCE = (
    "The Vendor-ID header of all AVPs defined in this specification shall be"
    " set to 3GPP (10415)."
)


def _vendor_id_sentence(
    table: ast.AvpTable, section: _Section, quirks: sources.Quirks
) -> ast.AvpTable:
    """`table` with V under Must in every row whose flag cells are all
    blank, read from its clause's sentence setting the Vendor-ID header of
    all the document's AVPs. The `vendor-id-sentence` quirk.

    Most documents print the sentence above a table whose V cells say the
    same. TS 29.389 table 6.3.1-1 leaves every flag cell of its three rows
    blank, in every version from V14.0.0 to V19.0.0, and clause 6.3.1's
    sentence is its one statement of the V bit: RFC 6733 section 4.1.1
    puts a Vendor-ID in the header exactly when V is set. The M bit stays
    blank, as printed. A row printing any flag keeps its cells.
    """
    prose = " ".join(paragraph.text for paragraph in section.paragraphs)
    if _VENDOR_ID_SENTENCE not in prose:
        raise ExtractionError(
            f"{section.number}: AVP table {table.table} sits in a clause not"
            f" saying {_VENDOR_ID_SENTENCE!r} (the `vendor-id-sentence` quirk)"
        )
    rows = []
    for row in table.rows:
        if row.flag_rules == ast.AvpFlagRules():
            vendor = ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR}))
            row = row.model_copy(update={"flag_rules": vendor})
            quirks.fire("vendor-id-sentence")
        rows.append(row)
    return table.model_copy(update={"rows": tuple(rows)})


# RFC 6733 §4.5's abbreviations, printed in TS 32.299 table 7.1.0.1 as the
# RFC extractor's `type-short-forms` reads them in RFC 6733's own table.
_TYPE_SHORT_FORMS = {"DiamIdent": "DiameterIdentity", "DiamURI": "DiameterURI"}

# TS 32.299 table 7.2.0.1 types a borrowed AVP by pointing at its definition:
# "refer [207]", once spaced and once not ("refer[223]"). Clause 7.2.0 says
# so: "for AVPs that are just borrowed from other applications only the
# reference ... is provided in the following table".
_REFER_RE = re.compile(r"refer ?\[(?P<number>\d+)\]")
# A clause-2 reference entry: "[207] 3GPP TS 29.061: "Interworking ...""
_REFERENCE_RE = re.compile(r"^\[(?P<number>\d+)\] (?P<text>.+)$")


def _references(sections: list[_Section]) -> dict[str, str]:
    """Clause 2's numbered references, number → entry text."""
    return {
        match["number"]: match["text"]
        for section in sections
        if section.number == "2"
        for paragraph in section.paragraphs
        if (match := _REFERENCE_RE.match(paragraph.text))
    }


def _referred_origin(
    name: str,
    number: str,
    references: dict[str, str] | None,
    own_reference: str,
    quirks: sources.Quirks,
) -> str | None:
    """The document a `refer [n]` type cell cites, or None when the entry
    names none a From cell can cite.

    The row becomes a re-used row citing that document: the type lives
    there, and so does the rest of the definition."""
    if not quirks.enabled("refer-type-cells"):
        raise ExtractionError(
            f"AVP table row {name!r} is typed 'refer [{number}]', which this"
            " document's source declaration does not read (the"
            " `refer-type-cells` quirk)"
        )
    quirks.fire("refer-type-cells")
    entry = (references or {}).get(number)
    if entry is None:
        raise ExtractionError(
            f"AVP table row {name!r} refers to [{number}], which clause 2 does not list"
        )
    return _entry_document(entry)


def _entry_document(entry: str) -> str | None:
    """The document a clause-2 entry names: what precedes its title, so a
    title mentioning another document ("... (3GPP TS 32.299)") names none."""
    return _named_document(entry.partition(":")[0])


def _named_document(text: str) -> str | None:
    """The document a From cell or a clause-2 entry names, as a `SpecRef`,
    or None when it names none a From cell can cite (TS 32.299's [209],
    'OMA "Multimedia Messaging Service; ..."', numbers no document).

    A publisher-led name is tried first, since "ETSI TS 283 034" also reads
    as a TS number. A three-digit series no publisher claims is no answer
    either: `_origin` settles it through clause 2."""
    if match := _ORIGIN_ETSI_RE.search(text):
        return f"ETSI-{match['kind']}{match['series']}.{match['number']}"
    if match := _ORIGIN_3GPP2_RE.search(text):
        return f"3GPP2-{match['number']}"
    if match := _ORIGIN_ONEM2M_RE.search(text):
        return f"oneM2M-TS-{match['number']}"
    if match := _ORIGIN_OMA_RE.search(text):
        return match["name"]
    if match := _ORIGIN_TS_RE.search(text):
        if len(match["series"]) == 3:
            return None
        return f"TS{match['series']}.{match['number']}"
    if match := _ORIGIN_RFC_RE.search(text):
        return f"RFC{match['number']}"
    return None


def _origin(
    reference: str,
    own_reference: str,
    references: dict[str, str] | None = None,
    quirks: sources.Quirks | None = None,
) -> str:
    if (named := _named_document(reference)) is not None:
        return named
    if (ts := _ORIGIN_TS_RE.search(reference)) is not None:
        return _external_by_reference(reference, ts, references, quirks)
    # A bare clause number cites this document itself: 29.336's S6t re-used
    # table lists AVPs its own S6m set defines, with cells like "6.4.2". The
    # faithful origin is the document's own reference, not a parse failure —
    # the linter's origin-resolution rules treat a self-reference like any
    # other, so nothing downstream needs a special case.
    # 29.061 writes one self-reference as "Clause 20.5a.5".
    if _SECTION_REF_RE.match(reference.removeprefix("Clause ")):
        return own_reference
    raise ExtractionError(f"unrecognized origin reference {reference!r}")


def _external_by_reference(
    reference: str,
    ts: re.Match[str],
    references: dict[str, str] | None,
    quirks: sources.Quirks | None,
) -> str:
    """The document a From cell printing a three-digit TS series names,
    read from the clause-2 entry the cell cites, the `origins-by-reference`
    quirk. 3GPP numbers no series so; TS 29.212 prints ETSI TS 283 034 as
    "3GPP TS 283 034 [37]" and TS 29.214 ETSI TS 183 017 as "3GPP TS 183.017
    [15]", and their clause 2 entries name the publisher. The entry must
    name the same number, so a cell citing the wrong entry fails."""
    if quirks is None or not quirks.enabled("origins-by-reference"):
        raise ExtractionError(
            f"origin reference {reference!r} names a TS series 3GPP does not"
            " number, which this document's source declaration does not read"
            " through clause 2 (the `origins-by-reference` quirk)"
        )
    number = _ORIGIN_NUMBER_RE.search(reference)
    entry = (references or {}).get(number["number"]) if number else None
    if entry is None:
        raise ExtractionError(
            f"origin reference {reference!r} cites no reference clause 2 lists"
        )
    named = _entry_document(entry)
    if named is None or not named.endswith(f"{ts['series']}.{ts['number']}"):
        raise ExtractionError(
            f"origin reference {reference!r} cites clause 2's"
            f" [{number['number'] if number else ''}], which names {named or entry!r}"
        )
    quirks.fire("origins-by-reference")
    return named


_REUSED_TABLE_COLUMNS = {
    "Attribute Name": ast.ReusedColumn.NAME,
    "Reference": ast.ReusedColumn.FROM,
    "M-bit": ast.ReusedColumn.M_BIT,
    # TS 29.172 table 7.4.1-2.
    "AVP Code": ast.ReusedColumn.CODE,
    "Value Type": ast.ReusedColumn.TYPE,
}


def _reused_code(text: str, name: str) -> int | None:
    if text and not text.isdigit():
        raise ExtractionError(f"re-used AVPs row {name!r}: code cell {text!r}")
    return int(text) if text else None


def _extract_reused_table(
    table: _Table,
    warnings: list[str],
    own_reference: str,
    quirks: sources.Quirks,
    references: dict[str, str],
) -> tuple[list[ast.ReusedAvpRow], tuple[ast.ReusedColumn, ...]]:
    rows = []
    columns, positions, data_rows = _walk_table(
        table,
        _with_marks(_REUSED_TABLE_COLUMNS, ast.ReusedColumn, quirks),
        "re-used AVPs",
        warnings,
        lambda row: row.cells[0] == "" or row.cells[0].startswith("NOTE"),
    )
    for cells in data_rows:
        name, _ = _strip_note_ref(cells[0])
        if " " in name:
            # As in the AVP table: a line-wrap artifact (TS 29.154 table
            # 5.4.1's "CC-Total- Octets") is input-patched.
            raise ExtractionError(f"re-used AVPs name cell {name!r} contains spaces")
        origin: str | None = None
        m_bit: ast.MBitOverride | None = None
        code: int | None = None
        data_type: ast.DataType | None = None
        marks: dict[ast.MarkColumn, tuple[str, ...]] = {}
        for column, position in zip(columns, positions, strict=True):
            text = cells[position]
            match column:
                case ast.ReusedColumn.NAME:
                    pass  # already read, so that the M-bit check can name it
                case ast.ReusedColumn.CODE:
                    code = _reused_code(text, name)
                case ast.ReusedColumn.TYPE:
                    data_type = _data_type(text or None)
                case (
                    ast.ReusedColumn.ACCESS_TYPES
                    | ast.ReusedColumn.APPLICABILITY
                    | ast.ReusedColumn.REFERENCE_POINTS
                    | ast.ReusedColumn.ACR
                    | ast.ReusedColumn.ACA
                    | ast.ReusedColumn.CCR
                    | ast.ReusedColumn.CCA
                ):
                    marked = ast.MarkColumn(column.value)
                    found = _mark_cell(text, marked, name, quirks)
                    if found is not None:
                        marks[marked] = found
                case ast.ReusedColumn.FROM:
                    origin = _origin(text, own_reference, references, quirks)
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
        rows.append(
            ast.ReusedAvpRow(
                name=name,
                origin=origin,
                m_bit=m_bit,
                code=code,
                data_type=data_type,
                marks=marks,
            )
        )
    return rows, columns


# TS 32.299 clauses 7.3-7.5 tabulate AVPs other vendors define, each row
# pointing at its definition: "the specification including the detailed
# definition and description, is referred to" (7.3), the Reference cell
# holding a clause-2 number ("[215]"). The AVP Code column is the table's
# statement of the code, and the "Used in" columns are read behind
# `command-columns`, as in the AVP tables.
_VENDOR_TABLE_COLUMNS = {
    "AVP Name": ast.ReusedColumn.NAME,
    "AVP Code": ast.ReusedColumn.CODE,
    "Reference": ast.ReusedColumn.FROM,
}
_REFERENCE_CELL_RE = re.compile(r"\[(?P<number>\d+)\]")


def _extract_vendor_table(
    table: _Table,
    section_number: str,
    warnings: list[str],
    quirks: sources.Quirks,
    references: dict[str, str],
) -> _ReusedTable:
    """A table of other vendors' AVPs as a re-used block, the
    `vendor-avp-tables` quirk. A reference naming no document a From cell
    can cite warns and adds no row, as `refer [n]` does."""
    if table.caption is None:
        raise ExtractionError(f"{section_number}: AVP table without a caption")
    columns, positions, data_rows = _walk_table(
        table,
        _with_marks(_VENDOR_TABLE_COLUMNS, ast.ReusedColumn, quirks),
        "re-used AVPs",
        warnings,
        lambda row: row.cells[0] == "",
    )
    rows = []
    for cells in data_rows:
        named = dict(zip(columns, (cells[i] for i in positions), strict=True))
        name = named[ast.ReusedColumn.NAME]
        marks = {
            marked: found
            for column, text in named.items()
            if (marked := ast.mark_column(column)) is not None
            and (found := _mark_cell(text, marked, name, quirks)) is not None
        }
        match = _REFERENCE_CELL_RE.fullmatch(named[ast.ReusedColumn.FROM])
        if match is None:
            raise ExtractionError(
                f"{section_number}: re-used AVPs row {name!r} has Reference"
                f" cell {named[ast.ReusedColumn.FROM]!r}, which is no"
                " reference number"
            )
        entry = references.get(match["number"])
        if entry is None:
            raise ExtractionError(
                f"re-used AVPs row {name!r} refers to [{match['number']}],"
                " which clause 2 does not list"
            )
        quirks.fire("vendor-avp-tables")
        origin = _entry_document(entry)
        if origin is None:
            warnings.append(
                f"re-used AVPs row {name!r} refers to [{match['number']}],"
                " which names no document a From cell can cite; no row added"
            )
            continue
        rows.append(
            ast.ReusedAvpRow(
                name=name,
                origin=origin,
                code=_reused_code(named.get(ast.ReusedColumn.CODE, ""), name),
                marks=marks,
            )
        )
    return _ReusedTable(
        rows=rows, columns=columns, label=table.caption, section=section_number
    )


# TS 29.230's registry tables, by the label of their first column, and the
# labels each prints; read behind `registry-tables`.
_REGISTRY_KINDS = {
    "Application identifier": ast.RegistryKind.APPLICATION_IDS,
    "Command code value": ast.RegistryKind.COMMAND_CODES,
    "AVP Code": ast.RegistryKind.AVP_CODES,
    "Experimental Result Code": ast.RegistryKind.RESULT_CODES,
}
_REGISTRY_COLUMNS = {
    **dict.fromkeys(_REGISTRY_KINDS, ast.RegistryColumn.CODE),
    "Application": ast.RegistryColumn.NAME,
    "Command name": ast.RegistryColumn.NAME,
    "Attribute Name": ast.RegistryColumn.NAME,
    "Result text": ast.RegistryColumn.NAME,
    "Abbreviation": ast.RegistryColumn.ABBREVIATION,
    "Data Type": ast.RegistryColumn.TYPE,
    "3GPP TS": ast.RegistryColumn.DEFINED_IN,
    "Specified in 3GPP TS": ast.RegistryColumn.DEFINED_IN,
    "Specified in the 3GPP TS": ast.RegistryColumn.DEFINED_IN,
    "Specified in the TS": ast.RegistryColumn.DEFINED_IN,
}
# A "Specified in" cell: one or more "29.229 [2]", the document's number and
# its clause-2 reference, separated by commas or "and" (table 4.1's "29.228
# [1] and 29.229 [2]", table 7.1's "29.209 [8], 29.211 [17] , 29.214 [18]").
_REGISTRY_DOCUMENT = r"\d{2}\.\d{3} \[\d+\]"
_REGISTRY_DOCUMENTS_RE = re.compile(
    rf"{_REGISTRY_DOCUMENT}(?:(?:\s*,\s*| and ){_REGISTRY_DOCUMENT})*"
)
_REGISTRY_DOCUMENT_RE = re.compile(r"(?P<number>\d{2}\.\d{3}) \[(?P<reference>\d+)\]")
# A full-width note row reserving a range, behind `reserved-range-notes`:
# "Note: The AVP codes from 320 to 399 are reserved for TS 29.234" (table
# 7.1), "Note: The Experimental Result Codes from 2006 to 2020 are reserved
# for the TS 29.229." (tables 8.1.2-8.1.4). The purpose is the rest of the
# sentence, as printed, less its closing full stop.
_RESERVED_RANGE_NOTE_RE = re.compile(
    r"^Note(?: \d+)?: The (?:AVP codes|Experimental Result Codes) from"
    r" (?P<first>\d+) to (?P<last>\d+) are reserved for (?P<purpose>.+?)\.?$"
)
_NAMED_DOCUMENT_RE = re.compile(r"TS (?P<number>\d{2}\.\d{3})(?!\d)")


def _registry_documents(
    text: str, label: str, references: dict[str, str], warnings: list[str]
) -> tuple[str, ...]:
    """A "Specified in" cell's documents, read by their numbers. A number
    its reference does not name is the cell's to say and warns: TS 29.230
    table 5.1/4 cites TER, which TS 29.215 defines, as "29.215 [30]", and
    clause 2's [30] is TS 29.338."""
    if not text:
        return ()
    if not _REGISTRY_DOCUMENTS_RE.fullmatch(text):
        raise ExtractionError(f"{label}: unrecognized document cell {text!r}")
    documents = []
    for match in _REGISTRY_DOCUMENT_RE.finditer(text):
        document = f"TS{match['number']}"
        entry = references.get(match["reference"])
        cited = None if entry is None else _ORIGIN_TS_RE.search(entry)
        listed = None if cited is None else f"TS {cited['series']}.{cited['number']}"
        if listed != f"TS {match['number']}":
            warnings.append(
                f"{label}: cites {match['number']} as [{match['reference']}],"
                f" which clause 2 lists as {listed or 'no TS'}; reading {document}"
            )
        documents.append(document)
    return tuple(dict.fromkeys(documents))


def _extract_registry(
    table: _Table,
    section: str,
    warnings: list[str],
    quirks: sources.Quirks,
    references: dict[str, str],
) -> ast.Registry:
    """A TS 29.230 registry table: one row per allocation, and behind
    `reserved-range-notes` the full-width notes reserving ranges among them."""
    quirks.fire("registry-tables")
    if table.caption is None:
        raise ExtractionError(f"{section}: registry table without a caption")
    header = table.rows[0].cells
    columns = []
    for label in header:
        if label not in _REGISTRY_COLUMNS:
            raise ExtractionError(
                f"table {table.caption}: unrecognized registry column {label!r}"
            )
        columns.append(_REGISTRY_COLUMNS[label])
    rows: list[ast.RegistryRow | ast.RegistryReservation] = []
    for row in table.rows[1:]:
        cells = row.cells
        if len(cells) == 1:
            if cells[0]:
                rows.extend(
                    _reserved_ranges(
                        row.first_cell_lines, table.caption, warnings, quirks
                    )
                )
            continue
        if len(cells) != len(columns):
            raise ExtractionError(
                f"table {table.caption}: a row of {len(cells)} cells under"
                f" {len(columns)} columns: {cells!r}"
            )
        by_column = dict(zip(columns, cells, strict=True))
        code = by_column[ast.RegistryColumn.CODE]
        if not code:
            # Tables 7.1 and 8.1.2-8.1.4 print a document alone ahead of the
            # range reserved for it, with no code to allocate.
            if any(by_column.values()):
                warnings.append(
                    f"table {table.caption}: a row with no code, printing only"
                    f" {' '.join(cell for cell in cells if cell)!r}; not read"
                )
            continue
        if not code.isdigit():
            raise ExtractionError(f"table {table.caption}: code cell {code!r}")
        label = f"table {table.caption} code {code}"
        defined_in = _registry_documents(
            by_column.get(ast.RegistryColumn.DEFINED_IN, ""),
            label,
            references,
            warnings,
        )
        data_type = by_column.get(ast.RegistryColumn.TYPE, "")
        printed_type = None
        if data_type not in ("", "-", *ast.DataType):
            # TS 29.230 table 7.1 types code 314 "Integer", which could be
            # Integer32, Integer64 or neither; TS 29.234 would say.
            if not quirks.enabled("unknown-type-tokens"):
                raise ExtractionError(
                    f"{label}: Type cell {data_type!r} names no Diameter type,"
                    " and this document's source declaration does not keep"
                    " one (the `unknown-type-tokens` quirk)"
                )
            quirks.fire("unknown-type-tokens")
            printed_type, data_type = data_type, ""
        try:
            rows.append(
                ast.RegistryRow(
                    code=int(code),
                    name=by_column.get(ast.RegistryColumn.NAME) or None,
                    abbreviation=by_column.get(ast.RegistryColumn.ABBREVIATION) or None,
                    # The registry's type is informational: a dash and a
                    # blank cell are the same absence.
                    data_type=None
                    if data_type in ("", "-")
                    else ast.DataType(data_type),
                    printed_type=printed_type,
                    defined_in=defined_in,
                )
            )
        except (ValueError, pydantic.ValidationError) as error:
            raise ExtractionError(f"{label}: {error}") from None
    return ast.Registry(
        registry=_REGISTRY_KINDS[header[0]],
        table=table.caption,
        source=ast.SourceRef(section=section),
        columns=tuple(columns),
        rows=tuple(rows),
    )


def _reserved_ranges(
    lines: list[str], caption: str, warnings: list[str], quirks: sources.Quirks
) -> list[ast.RegistryReservation]:
    """A full-width note row's reservations, one per line; a line reserving
    nothing is prose and warns (table 7.1's "Note 2: The 3GPP-AAA-Server-Name
    definition is moved to TS 29.273 starting from Rel-12.")."""
    if not quirks.enabled("reserved-range-notes"):
        raise ExtractionError(
            f"table {caption}: a full-width note row, which this document's"
            " source declaration does not read (the `reserved-range-notes`"
            f" quirk): {' '.join(lines)!r}"
        )
    reservations = []
    for line in lines:
        match = _RESERVED_RANGE_NOTE_RE.match(line)
        if match is None:
            warnings.append(f"table {caption}: note reserves nothing: {line!r}")
            continue
        quirks.fire("reserved-range-notes")
        purpose = match["purpose"]
        reservations.append(
            ast.RegistryReservation(
                first=int(match["first"]),
                last=int(match["last"]),
                defined_in=tuple(
                    dict.fromkeys(
                        f"TS{named['number']}"
                        for named in _NAMED_DOCUMENT_RE.finditer(purpose)
                    )
                ),
                purpose=purpose,
            )
        )
    return reservations


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


def _pdf_spec_and_version(reader: pypdf.PdfReader) -> tuple[str, str]:
    """An ETSI rendering prints its own title on the cover, with the 3GPP
    original in parentheses: "(3GPP TS 29.272 version 18.6.0 Release 18)".

    Failing the cover, the document information Title ETSI writes with the
    same parenthesis: TS 129 214 V11.16.0 (2015-10) draws its cover title as
    overlapping text runs pypdf reads interleaved, "(3GPP TS 29.21" and
    ".214 version 11.16.0 Release 1", where its Title reads "... (3GPP TS
    29.214 version 11.16.0 Release 11)". Either names the rendering, so a
    neighbouring version is refused all the same."""
    if not reader.pages:
        raise ExtractionError("PDF has no pages")
    cover = _normalize(reader.pages[0].extract_text())
    match = _PDF_COVER_RE.search(cover)
    if match is None and reader.metadata is not None and reader.metadata.title:
        match = _PDF_COVER_RE.search(_normalize(reader.metadata.title))
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
    applications: list[ast.ApplicationScope] = field(default_factory=list)
    grouped: list[ast.GroupedAvp] = field(default_factory=list)
    commented: _Commented = field(default_factory=list)
    # Behind `vendor-avp-tables`: re-used blocks read from tables of other
    # vendors' AVPs, which pair with no AVP table (TS 32.299 7.3.1-7.5.1).
    vendor_reused: list[_ReusedTable] = field(default_factory=list)
    # Sections that read like an enumerated AVP, with the name from the
    # heading. They cannot become definitions until the AVP table is known —
    # that is where their code comes from.
    pending_enums: list[tuple[_Section, str]] = field(default_factory=list)
    # The document's own reference, which a re-used row may cite (TS 29.212's
    # Gxx and S9 tables list Gx's AVPs "from" TS 29.212).
    own_reference: str = ""
    # The publisher's vendor space, for enumerated AVPs nothing else gives
    # one.
    vendor: int = TGPP_VENDOR
    avp_tables: list[_CollectedAvpTable] = field(default_factory=list)
    reused_tables: list[_ReusedTable] = field(default_factory=list)
    # Behind `registry-tables`: TS 29.230's allocation tables.
    registries: list[ast.Registry] = field(default_factory=list)


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
    applications: list[ast.ApplicationScope] = field(default_factory=list)
    registries: list[ast.Registry] = field(default_factory=list)


def _collect(
    sections: list[_Section],
    warnings: list[str],
    own_reference: str,
    quirks: sources.Quirks,
    publisher_vendor: int = TGPP_VENDOR,
) -> _Collected:
    """Walk the document once, classifying sections. Source-shaped work only:
    nothing here needs to know about another section."""
    collected = _Collected(own_reference=own_reference, vendor=publisher_vendor)
    references = (
        _references(sections)
        if quirks.enabled("refer-type-cells")
        or quirks.enabled("vendor-avp-tables")
        or quirks.enabled("registry-tables")
        or quirks.enabled("origins-by-reference")
        else {}
    )
    for section in sections:
        if quirks.enabled("prose-application-ids"):
            collected.applications.extend(_stated_applications(section, quirks))
        if title := _COMMAND_TITLE_RE.match(section.title):
            collected.messages.extend(
                _extract_messages(section, title, warnings, quirks, collected.commented)
            )
            continue
        if (
            quirks.enabled("message-headings")
            and (title := _MESSAGE_TITLE_RE.match(section.title))
            and any("Diameter Header" in line.text for line in section.lines)
        ):
            # Only the clauses printing a rule: 6.4.6-6.4.13 point at RFC 6733.
            collected.messages.extend(
                _extract_messages(
                    section,
                    title,
                    warnings,
                    quirks,
                    collected.commented,
                    message_heading=True,
                )
            )
            continue
        if quirks.enabled("procedure-commands") and any(
            _DIAMETER_HEADER_RE.match(line.text) for line in section.lines
        ):
            collected.messages.extend(
                _extract_messages(section, None, warnings, quirks, collected.commented)
            )
            continue
        for table in section.tables:
            header = table.rows[0].cells
            if quirks.enabled("registry-tables") and header[0] in _REGISTRY_KINDS:
                collected.registries.append(
                    _extract_registry(
                        table, section.number, warnings, quirks, references
                    )
                )
                continue
            # Substring, not membership: 29.214 titles the column group
            # "AVP Flag rules (Note 1)".
            if any("AVP Flag rules" in cell for cell in header):
                # TS 29.330 table 6.3.1-1 is a template with no definitions.
                # Recognise only the full header followed entirely by blank cells.
                labels = next(
                    (
                        i
                        for i, row in enumerate(table.rows)
                        if row.cells[0] in _NAME_LABELS
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
                    table, section.number, warnings, quirks, references, own_reference
                )
                if quirks.enabled("referred-type-sentences"):
                    avp_table = _referred_type_sentences(
                        avp_table, note_reused, sections, warnings, quirks
                    )
                if quirks.enabled("vendor-id-sentence"):
                    avp_table = _vendor_id_sentence(avp_table, section, quirks)
                collected.avp_tables.append(
                    _CollectedAvpTable(
                        table=avp_table,
                        section=section.number,
                        note_reused=note_reused,
                    )
                )
            elif (
                header[0] == "AVP Name"
                and "Reference" in header
                and quirks.enabled("vendor-avp-tables")
            ):
                vendor = _extract_vendor_table(
                    table, section.number, warnings, quirks, references
                )
                if vendor.rows:
                    collected.vendor_reused.append(vendor)
            elif "Attribute Name" in header and "Reference" in header:
                # Keyed on Reference rather than on M-bit: TS 29.128, 29.173
                # and 29.336 print a re-used table with no M-bit column at all.
                if table.caption is None:
                    raise ExtractionError("re-used AVPs table without a caption")
                reused_rows, reused_columns = _extract_reused_table(
                    table, warnings, own_reference, quirks, references
                )
                collected.reused_tables.append(
                    _ReusedTable(
                        rows=reused_rows,
                        columns=reused_columns,
                        label=table.caption,
                        section=section.number,
                    )
                )
        if title := _avp_title(section.title, quirks):
            found = _find_rule_header(section, _AVP_HEADER_RE, quirks)
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
                    _extract_grouped(
                        section,
                        header,
                        body_start,
                        rule_name,
                        quirks,
                        warnings,
                        collected.commented,
                    )
                )
            elif section.paragraphs and "type Enumerated" in section.paragraphs[0].text:
                collected.pending_enums.append((section, title["name"]))
    if quirks.enabled("prose-avp-origins"):
        _prose_avp_origins(collected, sections, quirks)
    return collected


def _avp_title(title: str, quirks: sources.Quirks) -> re.Match | None:
    """The heading of a clause that may define an AVP, with its name."""
    if match := _AVP_TITLE_RE.match(title):
        return match
    if quirks.enabled("access-type-headings") and (
        match := _ACCESS_TYPE_TITLE_RE.match(title)
    ):
        quirks.fire("access-type-headings")
        return match
    return None


def _prose_avp_origins(
    collected: _Collected, sections: list[_Section], quirks: sources.Quirks
) -> None:
    """Keep explicit definition citations alongside the citing AVP table.

    Like NOTE-derived origins, these supplement the table rather than erase
    its local code, type or application flag rules. References to encodings,
    value lists or another AVP do not define this AVP's origin.
    """
    rows = [row for table in collected.avp_tables for row in table.table.rows]
    names = {row.name for row in rows}
    origins: dict[str, str] = {}
    for section in sections:
        # TS 29.140 6.3.6 misspells its heading as 3GGPP-IMSI; the table's
        # clause cell still identifies the AVP unambiguously.
        candidates = {row.name for row in rows if row.section == section.number}
        if (title := _avp_title(section.title, quirks)) and title["name"] in names:
            candidates.add(title["name"])
        for name in candidates:
            subject = rf"(?:The {re.escape(name)} AVP(?: \(AVP code \d+\))?,?|This AVP)"
            for paragraph in section.paragraphs:
                text = paragraph.text
                citations = [
                    match[1]
                    for match in re.finditer(
                        rf"\b{subject} is defined in (?:the )?(.+?)\s*\[\d+\]",
                        text,
                    )
                ]
                # TS 29.329 6.3.11-21: a bare clause citation, or an
                # explicit 'for the definition' qualifier. Coding-only
                # citations (TS 29.272 7.3.185) must not match.
                citations.extend(
                    match[1]
                    for match in re.finditer(
                        r"\bSee (.+?) (?:for (?:the definition|further description)"
                        r" of this AVP\.|"
                        r"clause \d+(?:\.\d+)+ for the definition\b)",
                        text,
                    )
                )
                if match := re.fullmatch(r"See (.+?) clause \d+(?:\.\d+)+\.", text):
                    citations.append(match[1])
                # TS 29.140 6.3.2/6 ('For is' is printed in 6.3.2).
                citations.extend(
                    match[1]
                    for match in re.finditer(
                        r"For (?:is )?the definition of this AVP refer to (.+)", text
                    )
                )
                for citation in citations:
                    origin = _named_document(citation)
                    if origin is None or origin == collected.own_reference:
                        continue
                    if name in origins and origins[name] != origin:
                        raise ExtractionError(
                            f"{section.number}: conflicting prose origins for {name}:"
                            f" {origins[name]} and {origin}"
                        )
                    origins[name] = origin
                    quirks.fire("prose-avp-origins")
    known = {
        (row.name, row.origin)
        for table in [*collected.reused_tables, *collected.vendor_reused]
        for row in table.rows
    }
    for entry in collected.avp_tables:
        for row in entry.table.rows:
            origin = origins.get(row.name)
            if origin is not None and (row.name, origin) not in known:
                inferred = ast.ReusedAvpRow(name=row.name, origin=origin)
                if inferred not in entry.note_reused:
                    entry.note_reused.append(inferred)


def _resolve(
    collected: _Collected,
    quirks: sources.Quirks | None = None,
    warnings: list[str] | None = None,
) -> _Resolved:
    """Cross-section work: pair each AVP table with its re-used table, then
    turn pending enumerated sections into definitions using codes from the
    AVP tables."""
    quirks = quirks if quirks is not None else sources.Quirks([], None)
    warnings = warnings if warnings is not None else []
    if (
        collected.registries
        and not collected.avp_tables
        and not collected.messages
        and not collected.grouped
    ):
        # A registry allocates and defines nothing (TS 29.230): its tables
        # are the whole file.
        return _Resolved(
            messages=[], pairs=[], definitions=[], registries=collected.registries
        )
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
                independent_reused=[
                    *collected.reused_tables,
                    *collected.vendor_reused,
                ],
                applications=collected.applications,
            )
        raise ExtractionError("no AVP table found")
    # A document with several definition sets (29.336's S6m/S6n and S6t,
    # 29.338's S6c and S6d) prints one AVP table and one re-used table per
    # set, in the same document order — that adjacency is the only thing that
    # says which re-used block belongs to which set, so unequal counts leave
    # no defensible pairing and are rejected rather than guessed at. A single
    # AVP table without a re-used table stays legitimate: the re-used block is
    # synthesised for its NOTE-derived rows. So do several AVP tables with
    # no printed re-used table at all (TS 32.299's 7.1.0.1 and 7.2.0.1):
    # each synthesises its own, and there is nothing to mis-pair.
    independent = quirks.enabled("independent-avp-tables")
    if independent:
        quirks.fire("independent-avp-tables")
    if not independent and (
        len(collected.reused_tables) > len(collected.avp_tables)
        or (
            len(collected.avp_tables) > 1
            and collected.reused_tables
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
    #
    # A row citing this document itself is no "elsewhere": TS 29.212's Gxx,
    # S9, Sd and St re-used tables (clauses 5a.4.0, 5b.4.0, 5c.4.1, E.6.4.1)
    # list Gx's AVPs as re-used from TS 29.212, and 29.061's SGmb table (20.5)
    # cites 29.061, while the clauses defining them are in the same document.
    reused_rows = [row for _, reused in pairs for row in reused.rows]
    if independent:
        reused_rows += [row for table in collected.reused_tables for row in table.rows]
    reused_rows += [row for table in collected.vendor_reused for row in table.rows]
    external = {
        row.name for row in reused_rows if row.origin != collected.own_reference
    }
    local_enums = [
        (section, name)
        for section, name in collected.pending_enums
        if name not in external
    ]
    vendor_id = (
        _enum_vendor_id(collected.grouped, collected.vendor) if local_enums else None
    )
    # A table printing each row's vendor states the enumerated AVP's too,
    # 0 being the IETF space a definition spells as no vendor (oneM2M
    # TS-0004's Accounting-Record-Type, table A.4-1).
    row_vendors = {
        row.name: row.vendor_id
        for entry in collected.avp_tables
        for row in entry.table.rows
        if row.vendor_id is not None
    }

    enumerated = []
    for section, name in local_enums:
        code = codes.get(name)
        if code is None:
            raise ExtractionError(
                f"{section.number}: enumerated AVP {name!r}"
                " has no code in the AVP table"
            )
        vendor = row_vendors.get(name, vendor_id)
        enumerated.append(
            _extract_enumerated(section, name, code, vendor or None, quirks, warnings)
        )

    return _Resolved(
        messages=collected.messages,
        pairs=pairs,
        definitions=[*collected.grouped, *enumerated],
        independent_reused=[
            *(collected.reused_tables if independent else []),
            *collected.vendor_reused,
        ],
        applications=collected.applications,
    )


def _enum_vendor_id(grouped: list[ast.GroupedAvp], publisher: int) -> int:
    """The vendor id shared by this spec's locally defined AVPs.

    Enumerated-AVP sections never print it, so it is read off the grouped-AVP
    headers, which normally do — one value per 3GPP spec (10415). TS 29.109
    defines enumerated AVPs but no grouped ones, so no header supplies the
    otherwise implicit value; in that case the publisher's vendor space is the
    only candidate. Several distinct header values remain a resolution error.
    """
    vendors = sorted({avp.vendor_id for avp in grouped if avp.vendor_id is not None})
    if not vendors:
        return publisher
    if len(vendors) != 1:
        found = ", ".join(str(vendor) for vendor in vendors)
        raise ExtractionError(
            "cannot resolve the vendor id of this spec's enumerated AVPs:"
            f" its grouped-AVP headers give {found}"
        )
    return vendors[0]


def _assemble(resolved: _Resolved) -> tuple[ast.Section, ...]:
    """File order: applications, messages and registries, then each
    definition set's AVP table followed by its re-used table, then every
    definition in document order."""
    sections: list[ast.Section] = [
        *resolved.applications,
        *resolved.messages,
        *resolved.registries,
    ]
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
    "prose-avp-origins": (
        "read explicit AVP definition citations in prose as re-used origins,"
        " retaining the citing AVP table's own facts (TS 29.329 6.3.21)"
    ),
    "list-numbered-headings": (
        "number a heading printing no clause number with the number Word's"
        " list numbering renders for it (word/numbering.xml), replayed over"
        " the document (oneM2M TS-0004 annex A)"
    ),
    "message-headings": (
        "read a 'Name message' or 'Name Command' heading over a rule spelled"
        " with the abbreviation ('<ACR> ::=') as the command's long name (TS"
        " 32.299 clauses 6.2.2-6.4.5, oneM2M TS-0004 clauses A.2.1-A.2.2)"
    ),
    "spaced-rule-operator": (
        "read the rule operator spelled ':: =' as '::=' (TS 32.299 clause 7.2,"
        " TS 29.229)"
    ),
    "struck-rules-unused": (
        "comment out struck-through ABNF members, which the document's legend"
        " says are not used (TS 32.299 clauses 6.2.1.2, 6.4.1.2)"
    ),
    "physical-avp-columns": (
        "read physical cells in an AVP table with ragged grid spans, dropping"
        " an empty trailing sliver cell (TS 32.299 table 7.2.0.1)"
    ),
    "vendor-avp-tables": (
        "read tables of other vendors' AVPs, whose Reference cell cites a"
        " clause-2 entry, as re-used blocks (TS 32.299 tables 7.3.1, 7.4.1,"
        " 7.5.1)"
    ),
    "origins-by-reference": (
        "read a re-used row's From cell printing a TS series 3GPP does not"
        " number ('3GPP TS 283 034 [37]') as the document its clause-2"
        " reference names (TS 29.212, 29.214)"
    ),
    "refer-type-cells": (
        "read a 'refer [n]' Value Type cell as no type plus a re-used row"
        " citing clause 2's reference n (TS 32.299 table 7.2.0.1)"
    ),
    "referred-type-sentences": (
        "type a row whose Value Type cell is 'refer [n]' from its own clause's"
        " sentence 'The Name AVP (AVP code n) is of type T', where the"
        " document has such a clause (TS 32.299 clauses 7.2.50, 7.2.69,"
        " 7.2.191)"
    ),
    "type-short-forms": (
        "read RFC 6733's DiamIdent and DiamURI type abbreviations (TS 32.299"
        " table 7.1.0.1)"
    ),
    "wildcard-avp-row": (
        "read the 'AVP' row's code '*' as no code (TS 32.299 table 7.1.0.1)"
    ),
    "value-first-enums": (
        "read 'n Label' enumerated values, the label ending at the first"
        " colon and the rest of the line its description (TS 32.299)"
    ),
    "abnf-comments": (
        "read an ABNF member line's trailing '; comment' (RFC 5234 section"
        " 3.9) as the member, dropping the comment (TS 29.209 V6.8.0 clauses"
        " 6.5.18 and 6.5.20, TS 29.214 V7.12.0 clauses 5.3.16 and 5.3.18)"
    ),
    "comma-enum-labels": (
        "read a worded enumerated label whose words a comma separates,"
        " 'MM1 Message Submission, Profile based (0)', as the quoted name it"
        " is (TS 29.140 V7.0.0 clause 6.3.5)"
    ),
    "bracketed-enum-values": (
        "read '[n] label' enumerated values, the value bracketed before the"
        " label (TS 32.299 V11.20.0 clause 7.2.101)"
    ),
    "dotted-enum-values": (
        "read 'n. Label' enumerated values, the value followed by a full stop"
        " (TS 32.299 V11.20.0 clauses 7.2.207, 7.2.218)"
    ),
    "list-numbered-enum-values": (
        "read an enumerated value's number from the list numbering Word"
        " renders before its label (word/numbering.xml, replayed), '0"
        " Participating PoC Server' and '1. Moderator' in the PDF (TS 32.299"
        " V11.20.0 clauses 7.2.132, 7.2.145, 7.2.147, 7.2.151)"
    ),
    "value-last-enums": (
        "read 'Label<tab>n' enumerated values, the value last and set off by"
        " a tab or a run of spaces (TS 32.299 V11.20.0)"
    ),
    "prose-application-ids": (
        "read 'the Application-ID for the Gx Application ... is n', 'The"
        " Diameter application identifier assigned to the Sy interface"
        " application is n' and the retired documents' wordings into an"
        " application scope applying to the statement's interface clause (TS"
        " 29.212 clause 5.1, TS 29.219 clause 5.1.5)"
    ),
    "external-enum-values": (
        "read where an enumerated clause says its values are defined ('The"
        " possible values are those defined in TS 32.422 [23] ...') into"
        " `; Values:` (TS 29.061 clause 17.7.25, TS 29.212 clause 5.3.120,"
        " TS 29.272, TS 32.299)"
    ),
    "worded-enum-values": (
        "read 'Label In Words (n)' enumerated values, keeping the label's"
        " spaces (TS 29.368 clause 6.4.6)"
    ),
    "access-type-headings": (
        "read 'Name AVP (All access types)' clause headings, the parenthetical"
        " naming the access types the AVP applies to (TS 29.212 clause 5.3)"
    ),
    "dashed-enum-values": (
        "read '- NAME (n)' enumerated values, a list dash printed as text"
        " (TS 29.272 clause 7.3.128)"
    ),
    "hex-enum-values": (
        "read 'NAME (0xFFFFFFFF)' enumerated values (TS 29.214 clause 5.3.19)"
    ),
    "punctuated-enum-values": (
        "read 'NAME (n),' and 'NAME (n).' enumerated values, dropping the"
        " list's punctuation (TS 29.338 clause 5.3.3.5)"
    ),
    "described-enum-values": (
        "read 'NAME (n) Gloss' enumerated values, the rest of the line the"
        " value's description (TS 29.109 clause 6.3.1.8)"
    ),
    "label-after-enum-value": (
        "read '(n) Label.' enumerated values, labelled after the value (TS"
        " 29.109 clause 6.3.1.13)"
    ),
    "run-on-enum-values": (
        "read several 'NAME (n)' run together in one paragraph (TS 29.229"
        " clause 6.3.58)"
    ),
    "body-clause-headings": (
        "read a body paragraph 'n.n.n Name AVP' as a clause heading (TS 32.299"
        " clause 7.2.135C)"
    ),
    "message-only": (
        "retain commands and re-used AVPs without a local AVP table"
        " (TS 29.330 clause 6.3.1)"
    ),
    "procedure-commands": (
        "read command names and abbreviations from intros under procedure"
        " headings (TS 29.273 clauses 8.2.2.1-4)"
    ),
    "spaced-heading-numbers": (
        "read a heading printing a space before the tab after its number (TS"
        " 29.234 clause 4.5.2.2)"
    ),
    "rfc-command-rules": (
        "name a rule no intro names, under a procedure heading, by its command"
        " code as the RFC defining the command does: '<ASR> ::=', and"
        " '<Diameter-EAP-Request> ::=' (TS 29.234 clauses 4.4.2, 5.5, 8.4,"
        " 9.4, 11.4)"
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
    "vendor-id-sentence": (
        "read an AVP table's clause saying 'The Vendor-ID header of all AVPs"
        " defined in this specification shall be set to 3GPP (10415).' as V"
        " under Must for the rows whose flag cells are all blank (TS 29.389"
        " clause 6.3.1)"
    ),
    "access-type-column": (
        "read an 'Acc. Type' column's cells as the access types the row"
        " applies to, separated by commas or spaces (TS 29.212 table 5.3.0.1)"
    ),
    "applicability-column": (
        "read an 'Applicability' column's cells as the supported features"
        " (and in TS 29.212 the CC/PC functions) the row is marked with,"
        " separated by commas or spaces (TS 29.212 table 5.3.0.1 notes 3, 9)"
    ),
    "prose-enum-values": (
        "read 'NAME (value n)' in an enumerated clause's sentences as a value"
        " (oneM2M TS-0004 clause A.5.3)"
    ),
    "reference-cells": (
        "read an AVP table's 'Reference' column: a bracketed clause number"
        " ('[A.5.1]') as the row's defining clause, a document ('IETF RFC 6733"
        " [14]') as a re-used row citing it (oneM2M TS-0004 table A.4-1)"
    ),
    "reference-points-column": (
        "read an 'Applicable Reference Points' column's cells as reference"
        " points, separated by commas (TS 29.061 table 9a)"
    ),
    "worded-marks": (
        "read a mark column's cells as marks separated by commas only, a mark"
        " keeping its spaces (TS 29.468's 'V2X Localized User Plane')"
    ),
    "command-columns": (
        "read 'Used in' columns ACR, ACA, CCR and CCA as per-command use"
        " marks, '-' marking none (TS 32.299 clause 7.1.0)"
    ),
    "registry-tables": (
        "read tables allocating application ids, command codes, AVP codes"
        " and result codes, each row citing the documents defining it, as"
        " registries (TS 29.230 clauses 4.1, 5.1, 7.1, 8.1)"
    ),
    "unknown-type-tokens": (
        "keep a registry or AVP table Type cell naming no Diameter type as"
        " printed, quoted, rather than fail (TS 29.230 table 7.1 and TS 29.234"
        " table 10.1.1 code 314, 'Integer')"
    ),
    "reserved-range-notes": (
        "read full-width 'The AVP codes from a to b are reserved for ...'"
        " notes in a registry table as reserved ranges (TS 29.230 tables"
        " 7.1, 8.1.2-8.1.4)"
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
    extractor uses.

    Members commented out behind `struck-rules-unused` are not in the tree;
    `extract_with_comments` returns them too."""
    return extract_with_comments(docx_path, link, warnings, sources_dir)[0]


def extract_with_comments(
    docx_path: Path | str,
    link: str | None = None,
    warnings: list[str] | None = None,
    sources_dir: Path | None = None,
) -> tuple[ast.Specification, formatter.Comments]:
    """`extract`, plus the `;;` lines the file prints beside the tree, as the
    `formatter.Comments` `format_spec` takes: each member commented out
    behind `struck-rules-unused`, standing before the member that followed
    it, or at its body's end."""
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
            _publisher_vendor(specification),
        )
        patcher.finish()
        sections = _assemble(_resolve(collected, quirks, warnings))
        quirks.finish()
        spec = ast.Specification(
            specification=specification,
            version=version,
            vendor_id=_publisher_vendor(specification),
            bases=(ast.BASE_PROTOCOL,),
            link=None if link is None else pydantic.HttpUrl(link),
            sections=sections,
        )
        return spec, _comments(sections, collected.commented)


def _comments(
    sections: tuple[ast.Section, ...], commented: _Commented
) -> formatter.Comments:
    """The commented-out members, keyed by the path of what follows each:
    the member after it in its body, or the body's end. A body is found by
    identity, since it is the very object the file holds."""
    standing: dict[ast.TreePath, list[str]] = {}
    for body, notes in commented:
        index = next(
            (index for index, section in enumerate(sections) if section is body),
            None,
        )
        if index is None:
            raise ExtractionError(
                f"{body.name}: the body its struck members were commented out"
                " of is not in the file"
            )
        for position, note in notes:
            standing.setdefault(("sections", index, "avps", position), []).append(note)
    return formatter.Comments(standing=standing)


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
