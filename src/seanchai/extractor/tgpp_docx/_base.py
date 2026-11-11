"""The section model every reading works on, and what the readings share:
the paragraphs, lines and tables of a numbered clause, as `_docx` builds
them; the publishers' vendor spaces; the clause titles that may define an
AVP; and what one pass over the document collects (`_Collected`), which
`_collect` fills and `_origins` adds the prose origins to."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...dad import ast
from .. import sources

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


# Every AVP a 3GPP specification defines is in 3GPP's vendor space, a fact
# about the publisher, so it is stated rather than read, as the RFC extractor
# states the IETF's 0.
TGPP_VENDOR = 10415
# oneM2M TS-0004 clause A.4: "AVPs defined for oneM2M specific usage are
# assigned Vendor-Id of 45687."
ONEM2M_VENDOR = 45687


def _publisher_vendor(specification: str) -> int:
    """The vendor space a publisher defines its AVPs in."""
    return ONEM2M_VENDOR if specification.startswith("oneM2M ") else TGPP_VENDOR


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
    # Whether the first cell opens on a tab, which normalizing removes: TS 32.299
    # table 6.4.4 sets a grouped AVP's members off under it so.
    indented: bool = False


@dataclass
class _Table:
    caption: str | None
    rows: list[_Row]
    # The caption's whole text: a feature table's says which list it is.
    caption_text: str | None = None


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


# The lines commented out of a body behind `struck-rules-unused` and
# `elided-members`, by the message or grouped AVP they stood in: each the note
# standing for it, with the number of members before it.
type _Commented = list[tuple[ast.Message | ast.GroupedAvp, list[tuple[int, str]]]]
# What a re-printed rule glosses (`reprinted-avps`), by the block and the member.
type _Glosses = list[tuple[ast.ReprintedAvp, int, str]]


type _ValueNotes = list[tuple[ast.ValueTable | ast.AvpTable, list[tuple[int, str]]]]


@dataclass(frozen=True)
class _ReusedTable:
    """A re-used AVPs table with the provenance the output block needs: its own
    caption and its own clause, which is not necessarily the AVP table's. No
    caption for the origins a clause's prose states."""

    rows: list[ast.ReusedAvpRow]
    columns: tuple[ast.ReusedColumn, ...]
    label: str | None
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

    Tables are kept as lists: 29.336 (S6m/S6n and S6t) and 29.338 (S6c and
    S6d) each carry a definition set per interface.
    """

    messages: list[ast.Message] = field(default_factory=list)
    # RFC 6733 section 7.2's `<answer-message>`, as the document prints its own.
    answers: list[ast.AnswerMessage] = field(default_factory=list)
    applications: list[ast.ApplicationScope] = field(default_factory=list)
    grouped: list[ast.GroupedAvp] = field(default_factory=list)
    commented: _Commented = field(default_factory=list)
    # The notes standing among an AVP table's rows: the `* [ AVP ]` wildcard
    # TS 32.299 tabulates (`wildcard-avp-row`).
    table_notes: _ValueNotes = field(default_factory=list)
    # Behind `reprinted-avps`: another document's rule, as printed here.
    reprints: list[ast.ReprintedAvp] = field(default_factory=list)
    glosses: _Glosses = field(default_factory=list)
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
    # Behind `prose-avp-origins`: the origins each clause's prose states, a
    # block per clause, in document order.
    prose_reused: list[_ReusedTable] = field(default_factory=list)
    # Behind `registry-tables`: TS 29.230's allocation tables.
    registries: list[ast.Registry] = field(default_factory=list)


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
