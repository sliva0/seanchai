"""Which document a citation names: clause 2's references, a From cell
or a clause-2 entry as a `SpecRef`, a `refer [n]` cell, and, behind
`prose-avp-origins`, the definition citations in a clause's prose."""

from __future__ import annotations

import re
from collections.abc import Iterator

from ...dad import ast
from .. import sources
from ..errors import ExtractionError
from ._base import _avp_title, _Collected, _ReusedTable, _Section

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


# The document a citation names, up to the end of its sentence, so that an
# encoding reference in one sentence is not read as the next one's origin.
_CITED = r"((?:(?!\. )[^,;])+?)"
_CLAUSE = r"clause \d+(?:\.\d+)+"
# Definition language whose subject is the clause's AVP, unnamed.
_THIS_AVP_DEFINED = (
    rf"\bThis AVP is defined in (?:the )?{_CITED}\s*\[\d+\]",
    rf"\bSee {_CITED}(?: {_CLAUSE})? for the definition of this AVP\b",
    # TS 29.140 6.3.2/6 ('For is' is printed in 6.3.2).
    r"\bFor (?:is )?the definition of this AVP refer to (.+)",
)
# TS 29.329 6.3.9 and 6.3.11-21: pointers that say no "definition".
_THIS_AVP_DESCRIBED = rf"\bSee {_CITED} for further description of this AVP\."
_BARE_CITATION = rf"See {_CITED} {_CLAUSE}\."


def _named_citations(name: str, text: str) -> Iterator[str]:
    """What `text` cites as defining the AVP it calls `name`."""
    named = re.escape(name)
    for pattern in (
        rf"\bThe {named} AVP(?: \(AVP code \d+\))?,? is defined in"
        rf" (?:the )?{_CITED}\s*\[\d+\]",
        # TS 29.329 6.3.19 prints "theWildcarded-Public-Identity".
        rf"\bSee {_CITED} {_CLAUSE} for the definition of the ?{named} AVP\b",
    ):
        for match in re.finditer(pattern, text):
            yield match[1]


def _unnamed_citations(
    section: _Section, headed: bool, text: str, quirks: sources.Quirks
) -> Iterator[tuple[re.Match, str]]:
    """What `text` cites for an AVP only its clause identifies, each with the
    quirk reading it. A bare citation is read only as the whole of a clause
    headed by the AVP: with anything beside it, it is as likely an encoding
    reference (TS 29.272 7.3.185's "See TS 23.003 [3].")."""
    for pattern in _THIS_AVP_DEFINED:
        for match in re.finditer(pattern, text):
            yield match, "prose-avp-origins"
    if not quirks.enabled("bare-avp-citations"):
        return
    for match in re.finditer(_THIS_AVP_DESCRIBED, text):
        yield match, "bare-avp-citations"
    if (
        headed
        and len(section.paragraphs) == 1
        and (match := re.fullmatch(_BARE_CITATION, text))
    ):
        yield match, "bare-avp-citations"


def _prose_avp_origins(
    collected: _Collected, sections: list[_Section], quirks: sources.Quirks
) -> None:
    """Keep explicit definition citations, each in a block at the clause
    stating it.

    Like NOTE-derived origins, these supplement the table and keep its local
    code, type and flag rules; they stand at their sentence's clause, not
    under a table's caption. A name two clauses cite is in both. References
    to encodings, value lists or another AVP are not origins. A citation that
    could be any of a clause's several AVPs fails.
    """
    rows = [row for table in collected.avp_tables for row in table.table.rows]
    names = {row.name for row in rows}
    origins: dict[str, str] = {}
    # The clauses stating each name's origin, in document order.
    stated: dict[str, dict[str, None]] = {}

    def cited(citation: str) -> str | None:
        origin = _named_document(citation)
        return None if origin == collected.own_reference else origin

    def record(section: _Section, name: str, origin: str, quirk: str) -> None:
        if origins.setdefault(name, origin) != origin:
            raise ExtractionError(
                f"{section.number}: conflicting prose origins for {name}:"
                f" {origins[name]} and {origin}"
            )
        stated.setdefault(name, {})[section.number] = None
        quirks.fire(quirk)

    for section in sections:
        # TS 29.140 6.3.6 misspells its heading as 3GGPP-IMSI; the table's
        # clause cell still identifies the AVP unambiguously.
        candidates = {row.name for row in rows if row.section == section.number}
        title = _avp_title(section.title, quirks)
        headed = title is not None and title["name"] in names
        if title is not None and headed:
            candidates.add(title["name"])
        if not candidates:
            continue
        for paragraph in section.paragraphs:
            text = paragraph.text
            for name in sorted(candidates):
                for citation in _named_citations(name, text):
                    if origin := cited(citation):
                        record(section, name, origin, "prose-avp-origins")
            for match, quirk in _unnamed_citations(section, headed, text, quirks):
                origin = cited(match[1])
                if origin is None:
                    continue
                if len(candidates) > 1:
                    raise ExtractionError(
                        f"{section.number}: {origin} is cited for an unnamed AVP,"
                        f" which could be {' or '.join(sorted(candidates))}"
                    )
                # "The Other AVP is ... This AVP is defined in ..." is Other's.
                before = text[: match.start()]
                mentioned = re.findall(r"\bThe ([\w-]+) AVP\b", before)
                (name,) = candidates
                if not mentioned or mentioned[-1] == name:
                    record(section, name, origin, quirk)
    known = {
        (row.name, row.origin)
        for table in [*collected.reused_tables, *collected.vendor_reused]
        for row in table.rows
    }
    for entry in collected.avp_tables:
        known |= {(row.name, row.origin) for row in entry.note_reused}
    by_clause: dict[str, list[ast.ReusedAvpRow]] = {}
    for name in dict.fromkeys(row.name for row in rows):
        origin = origins.get(name)
        if origin is None or (name, origin) in known:
            continue
        for clause in stated[name]:
            by_clause.setdefault(clause, []).append(
                ast.ReusedAvpRow(name=name, origin=origin)
            )
    collected.prose_reused = [
        # A sentence states a name and a document, and no M-bit.
        _ReusedTable(
            rows=found,
            columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
            label=None,
            section=clause,
        )
        for clause, found in sorted(
            by_clause.items(), key=lambda item: ast.section_sort_key(item[0])
        )
    ]
