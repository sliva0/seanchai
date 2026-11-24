"""What looks like a definition and no reading claimed.

A declared edit catches a known defect disappearing upstream; nothing in the
readings catches a new shape, since a table no pass recognises is passed over
in silence. So each extraction also lists the tables (and, in an RFC, the
clauses holding a ruled table) that look like candidates, by a caption or
header resembling an AVP table, a value table, an information-element table,
an enumeration or a command list, and that no pass read.

`seanchai corpus regenerate` reports them and holds them to a committed
baseline (`Baseline`, `edits/unclaimed.json`): a candidate the baseline does
not list fails its document until a maintainer acknowledges it
(`--acknowledge-unclaimed`), so a version upgrade bringing a new table shape
shows in review. The test is a resemblance and no reading: a candidate may
well be prose in a grid, and the baseline says only that someone looked.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

__all__ = ["Baseline", "Candidate", "classify", "with_pages"]


@dataclass(frozen=True, order=True)
class Candidate:
    """A table, or an RFC clause, no reading claimed that resembles one."""

    section: str
    # What it resembles: "avp-table", "values", "information-elements",
    # "enumeration", "commands" or "application-ids".
    kind: str
    # The table's caption as printed, "Table 7.3.1/1: S6a/S6d specific Diameter
    # AVPs", None for an uncaptioned table or an RFC clause.
    caption: str | None
    # The header row's cells, or an RFC table's header line.
    header: tuple[str, ...]
    # Where the clause starts in the PDF or the RFC; not part of its identity.
    page: int | None = None
    # Why the baseline leaves it unread, a maintainer's line; not part of its
    # identity, and kept as the candidate is acknowledged again.
    reason: str | None = field(default=None, compare=False)

    @property
    def key(self) -> tuple[str, str, str | None, tuple[str, ...]]:
        """What the baseline matches: everything but the page, which moves."""
        return (self.section, self.kind, self.caption, self.header)

    def describe(self) -> str:
        page = f", page {self.page}" if self.page is not None else ""
        caption = self.caption or "uncaptioned"
        return (
            f"{self.section}{page}: {self.kind}: {caption} [{' | '.join(self.header)}]"
        )


# Header cells, folded to lower case, saying what a table lists. Each kind
# needs one cell naming the thing listed and one naming something a
# definition states of it, so that "Name | Description" alone, a glossary,
# is nothing. Read in order; the first kind matched is the candidate's.
_HEADER_KINDS: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "information-elements",
        # TS 32.299's message tables, "AVP | Category | Description", say per
        # member what an information-element table does.
        re.compile(r"\binformation elements?\b|\bie name\b|^ie$|^avp$"),
        re.compile(r"\bmapping\b|^cat\.?$|^category$|\bpresence\b"),
    ),
    (
        "values",
        # "Result-Code AVP value | Condition": the codes an answer may carry.
        re.compile(
            r"^(?:value|values|bit|bits|result[- ]codes?(?: avp)?(?: values?)?"
            r"|enumerated value|feature(?: bit)?)$"
        ),
        re.compile(
            r"\bname\b|\bdescription\b|\bmeaning\b|\bfeature\b|\bvalue\b"
            r"|\bcondition\b"
        ),
    ),
    (
        "avp-table",
        re.compile(r"\b(?:avp|attribute)(?: name)?\b|^name$"),
        re.compile(
            r"\bcode\b|\bflag|\bdata ?type\b|\bvalue type\b|^must|^reference$"
            r"|^attr ?#$|^#$"
        ),
    ),
    (
        "commands",
        re.compile(r"\bcommand(?:[- ]name)?\b|^message$"),
        re.compile(r"\bcode\b|\babbreviation\b|^abbr"),
    ),
    (
        "application-ids",
        re.compile(r"\bapplication\b"),
        re.compile(r"\bid(?:entifier)?s?\b"),
    ),
)
# A caption saying the table numbers an AVP's values, though its header names
# neither ("Table 7.3.80/1: Values of Ext-PDP-Type").
_CAPTION_VALUES_RE = re.compile(
    r"\b(?:values?|bits?|result codes?|enumerat\w*|features?)\b", re.IGNORECASE
)
# A row that is an enumeration's line, "NAME (n)", in any cell.
_ENUM_CELL_RE = re.compile(r"^[A-Z][A-Z0-9_-]+ ?\((?:0x[0-9A-Fa-f]+|\d+)\)$")
# A cell that is a number, as a value column holds one.
_NUMBER_RE = re.compile(r"^(?:0x[0-9A-Fa-f]+|\d+)$")


def classify(
    header: Sequence[str], caption: str | None, rows: Iterable[Sequence[str]] = ()
) -> str | None:
    """What a table of `header` (its first row's cells), `caption` and data
    `rows` resembles, or None for nothing a reading could want."""
    cells = [re.sub(r"\s+", " ", cell).strip().casefold() for cell in header]
    for kind, listed, stated in _HEADER_KINDS:
        named = [index for index, cell in enumerate(cells) if listed.search(cell)]
        # One cell may say both, "Application identifier", where its words
        # past the thing listed state something of it.
        if named and any(
            stated.search(listed.sub(" ", cell) if index in named else cell)
            for index, cell in enumerate(cells)
        ):
            return kind
    data = [list(row) for row in rows]
    if any(_ENUM_CELL_RE.match(cell.strip()) for row in data for cell in row):
        return "enumeration"
    numbered = sum(
        1 for row in data if row and _NUMBER_RE.match(row[0].strip()) is not None
    )
    if (
        caption is not None
        and _CAPTION_VALUES_RE.search(caption)
        and data
        and numbered >= max(2, len(data) // 2)
    ):
        return "values"
    return None


@dataclass(frozen=True)
class Baseline:
    """The candidates acknowledged, by document reference."""

    documents: Mapping[str, tuple[Candidate, ...]]

    @classmethod
    def load(cls, path: Path) -> Baseline:
        """Read `path`; a missing file acknowledges nothing."""
        if not path.is_file():
            return cls({})
        data = json.loads(path.read_text(encoding="utf-8"))["documents"]
        return cls(
            {
                reference: tuple(
                    Candidate(
                        section=entry["section"],
                        kind=entry["kind"],
                        caption=entry.get("caption"),
                        header=tuple(entry["header"]),
                        page=entry.get("page"),
                        reason=entry.get("reason"),
                    )
                    for entry in entries
                )
                for reference, entries in data.items()
            }
        )

    def compare(
        self, reference: str, found: Iterable[Candidate]
    ) -> tuple[list[Candidate], list[Candidate]]:
        """The candidates in `found` the baseline does not list for
        `reference`, and those it lists that `found` lacks."""
        listed = {candidate.key for candidate in self.documents.get(reference, ())}
        found = sorted(set(found))
        seen = {candidate.key for candidate in found}
        return (
            [candidate for candidate in found if candidate.key not in listed],
            [
                candidate
                for candidate in self.documents.get(reference, ())
                if candidate.key not in seen
            ],
        )

    def updated(self, documents: Mapping[str, Iterable[Candidate]]) -> Baseline:
        """This baseline with `documents`' lists in place of its own, each
        table once however many copies of the document print it: at the
        page the baseline gives it where a copy still starts its clause
        there, else at the first page found, with the reason the baseline
        gives it, none for a table it did not list."""
        merged = dict(self.documents)
        for reference, found in documents.items():
            listed = set(self.documents.get(reference, ()))
            reasons = {
                candidate.key: candidate.reason
                for candidate in self.documents.get(reference, ())
            }
            chosen: dict[tuple, Candidate] = {}
            for candidate in sorted(set(found)):
                if candidate.key not in chosen or candidate in listed:
                    chosen[candidate.key] = replace(
                        candidate, reason=reasons.get(candidate.key)
                    )
            candidates = tuple(sorted(chosen.values()))
            if candidates:
                merged[reference] = candidates
            else:
                merged.pop(reference, None)
        return Baseline(merged)

    def render(self) -> str:
        """The file's text: each document's candidates in clause order, one
        field a line, as `corrections.json` is written."""
        documents = {
            reference: [
                {
                    "section": candidate.section,
                    "kind": candidate.kind,
                    "caption": candidate.caption,
                    "header": list(candidate.header),
                    "page": candidate.page,
                    "reason": candidate.reason,
                }
                for candidate in sorted(candidates, key=_clause_key)
            ]
            for reference, candidates in self.documents.items()
        }
        return (
            json.dumps(
                {"note": _NOTE, "documents": documents},
                ensure_ascii=False,
                sort_keys=True,
                indent=1,
            )
            + "\n"
        )


_NOTE = (
    "Written by `seanchai corpus regenerate --acknowledge-unclaimed`: the"
    " tables each document prints that resemble a definition and that no"
    " reading claims, as looked over, each with the reason it stays unread,"
    " which a maintainer writes and acknowledging keeps. See"
    " docs/extractor.md."
)


def with_pages(
    candidates: Iterable[Candidate], pages: Mapping[str, int]
) -> list[Candidate]:
    """`candidates`, each with the page its clause starts on."""
    return [
        replace(candidate, page=pages.get(candidate.section, candidate.page))
        for candidate in candidates
    ]


def _clause_key(candidate: Candidate) -> tuple:
    parts = re.split(r"[.]", candidate.section)
    return (
        [(0, int(part)) if part.isdigit() else (1, part) for part in parts],
        candidate.key,
    )
