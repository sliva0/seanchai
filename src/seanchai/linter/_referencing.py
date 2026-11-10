"""Single-file rules over what a file says about names and clauses: a
name both defined and re-used or cited from the file itself, a member
its tables mark unused, `Undefined AVP` blocks, and cited clauses.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..dad import ast
from ._findings import Finding, Severity
from ._index import _clauses, _Index, _references, _table_labels


def _self_cited_exists(index: _Index) -> list[Finding]:
    """A re-used row citing this file for an AVP the file neither defines nor
    tabulates: `reused-avp-not-in-origin`, with the file as the origin."""
    local = {definition.name for definition in index.definitions} | {
        row.name for row in index.rows
    }
    return [
        Finding(
            Severity.ERROR,
            "reused-avp-not-in-origin",
            f"{name} is listed as re-used from this document, which neither"
            " defines nor tabulates it",
        )
        for name in sorted(set(index.self_cited) - local)
    ]


def _local_and_reused(index: _Index) -> list[Finding]:
    """An AVP both defined here and listed as re-used from elsewhere.

    A note, not an error. TS 29.272 does this nine times, and it is not
    necessarily a mistake: a specification may re-print another's AVP so a
    reader need not fetch the other document, or *extend* it with fields of its
    own. Which of those it is cannot be decided from this file — it needs the
    origin's definition to compare against, so the comparison belongs to the
    cross-document rules.
    """
    findings = []
    for definition in sorted(index.definitions, key=lambda d: d.name):
        origin = index.reused.get(definition.name)
        if origin is None:
            continue
        findings.append(
            Finding(
                Severity.NOTE,
                "local-and-reused",
                f"{definition.name} is defined here and also listed as re-used"
                f" from {origin}; whether this re-prints or extends it needs"
                f" {origin}",
                definition.source.section,
                origin=origin,
            )
        )
    return findings


def _members_marked_unused(spec: ast.Specification) -> list[Finding]:
    """A command's ABNF member its tables mark unused in that command.

    TS 32.299 tabulates per command whether an AVP is used in it, a column
    each for ACR, ACA, CCR and CCA, and clause 7.1.0 reads the dash: "Those
    Diameter AVPs that are not used are marked '-'". Table 7.1.0.1 marks
    `Error-Message` and `Failed-AVP` so under ACA, whose clause 6.2.3 ABNF
    lists both. A note: the ABNF is the wire format, and only the document's
    editor knows which statement is meant. A blank cell marks nothing, and
    the `* [ AVP ]` wildcard is grammar, not a member.
    """
    unused: dict[tuple[str, ast.MarkColumn], list[str]] = defaultdict(list)
    for section in spec.sections:
        if not isinstance(section, ast.AvpTable | ast.ReusedAvps):
            continue
        label = section.table or f"(clause {section.source.section})"
        for row in section.rows:
            for column, marks in row.marks.items():
                if marks == ():
                    unused[row.name, column].append(label)
    findings = []
    for position, section in enumerate(spec.sections):
        if (
            not isinstance(section, ast.Message)
            or section.abbreviation not in ast.MarkColumn
        ):
            continue
        command = ast.MarkColumn(section.abbreviation)
        for number, rule in enumerate(section.avps):
            if rule.name == "AVP":
                continue
            findings += [
                Finding(
                    Severity.NOTE,
                    "member-marked-unused",
                    f"{rule.name} is a member of {section.abbreviation}, but"
                    f" table {label} marks it '-', unused in"
                    f" {section.abbreviation}",
                    section.source.section,
                    paths=(("sections", position, "avps", number),),
                )
                for label in unused.get((rule.name, command), [])
            ]
    return findings


def _undefined_avps(index: _Index) -> list[Finding]:
    """What each `Undefined AVP` block declares, checked against the file.

    `undefined-avp`, a note per block a body references: the name is a
    corpus finding a consumer has to decide about (docs/consumers.md).
    `undefined-avp-unused`, an error: a block whose name no body
    references, or whose clause holds no body naming it. And
    `undefined-avp-defined`, an error: a block for a name the file defines,
    tabulates, lists as re-used or declares twice, a stale claim the model
    would quietly read past."""
    referenced = _references(index)
    known = (
        {definition.name for definition in index.definitions}
        | {row.name for row in index.rows}
        | set(index.reused)
        | set(index.self_cited)
    )
    declared: dict[str, int] = defaultdict(int)
    for block in index.undefined:
        declared[block.name] += 1
    findings = []
    for block in index.undefined:
        name, clause = block.name, block.source.section
        paths = (index.path(block),)
        where = referenced.get(name)
        if name in known:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-defined",
                    f"{name} is declared undefined, but the file defines,"
                    " tabulates or re-uses it",
                    clause,
                    paths=paths,
                )
            )
        if declared[name] > 1:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-defined",
                    f"{name} is declared undefined {declared[name]} times",
                    clause,
                    paths=paths,
                )
            )
        if where is None:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-unused",
                    f"{name} is declared undefined, but no body references it",
                    clause,
                    paths=paths,
                )
            )
        elif clause not in where:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-unused",
                    f"{name} is declared undefined citing a clause whose"
                    f" bodies do not reference it; it is referenced in"
                    f" {_clauses(where)}",
                    clause,
                    paths=paths,
                )
            )
        else:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "undefined-avp",
                    f"{name} is referenced in {_clauses(where)} and declared undefined",
                    clause,
                    paths=paths,
                )
            )
    return findings


def _with_parents(clause: str) -> set[str]:
    """`clause` and every clause above it: 5.3.81, 5.3 and 5."""
    parts = clause.split(".")
    return {".".join(parts[:count]) for count in range(1, len(parts) + 1)}


# A `; Values:` naming a clause and no document, so a clause of this one:
# oneM2M TS-0004 clause A.5.25's "clause 6.6.3".
_OWN_CLAUSE = re.compile(r"^(?:clause|section) (\S+)$", re.IGNORECASE)


def _section_references(spec: ast.Specification, index: _Index) -> list[Finding]:
    """A clause the file cites against the clauses the file holds.

    `section-mismatch`: a row citing a clause for an AVP a block here holds
    elsewhere. TS 29.214 V19.3.0's table 5.3.0.1 cites 5.3.142 for
    `PC-Session-Recovery-Status`, which clause 5.3.81 defines and no 5.3.142
    exists. A definition, a re-print and a bit table are what hold an AVP, and
    a row may cite any of them or a clause above one, as a table may. A result
    code or feature table is not: TS 29.229 tabulates `Feature-List` at its
    clause 6.3.31 and lists the features in clause 7.1.1, both as they should.

    `section-unknown`: an `; Applies-To:` or a `; Values:` naming a clause no
    block sits at or under, each a sentence about a clause in particular.

    A row whose AVP no block holds is not checked. A simple-typed AVP has no
    block, so its clause is absent from any file: against the documents' own
    headings, the 1249 of 2257 citations such a check reports held one wrong,
    `PC-Session-Recovery-Status`, which the first rule finds anyway. A re-used
    row, a registry row and `; From:` cite documents and no clause.

    Notes: a file holds what its document prints, so a misprint stays, and a
    clause may exist that the file has no block for.
    """
    known: set[str] = set()
    holding: dict[str, list[str]] = defaultdict(list)
    for section in spec.sections:
        known |= _with_parents(section.source.section)
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp | ast.ReprintedAvp):
            holding[section.name].append(section.source.section)
        elif isinstance(section, ast.ValueTable):
            known.update(
                clause
                for row in section.rows
                if row.section is not None
                for clause in _with_parents(row.section)
            )
            if section.kind is ast.ValueKind.BITS:
                holding[section.avp].append(section.source.section)
    findings = []
    for table in index.tables:
        for row in table.rows:
            cited, held = row.section, holding.get(row.name)
            if (
                cited is None
                or held is None
                or any(cited in _with_parents(clause) for clause in held)
            ):
                continue
            absent = "" if cited in known else f", and nothing at clause {cited}"
            findings.append(
                Finding(
                    Severity.NOTE,
                    "section-mismatch",
                    f"{row.name} is cited at clause {cited} in"
                    f" {_table_labels([table])}, but the file holds it at"
                    f" {_clauses(list(dict.fromkeys(held)))}{absent}",
                    table.source.section,
                    paths=(index.path(row),),
                )
            )
    for block in index.applications:
        for entry in block.applies_to:
            clause = entry.removesuffix(".*")
            if clause not in known:
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "section-unknown",
                        f"{block.name} applies to clause {entry}, under which the"
                        " file holds no block",
                        block.source.section,
                        paths=(index.path(block),),
                    )
                )
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        cited = _OWN_CLAUSE.match(definition.values_source or "")
        if cited is not None and cited[1] not in known:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "section-unknown",
                    f"{definition.name}'s values are cited from clause {cited[1]},"
                    " where the file holds no block",
                    definition.source.section,
                    paths=(index.path(definition),),
                )
            )
    return findings
