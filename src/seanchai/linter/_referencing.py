"""Single-file rules about names and clauses: names both defined and
re-used, self-citations, members marked unused, `Undefined AVP` blocks and
cited clauses.
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
    """A note for an AVP both defined here and listed as re-used.

    It may be a re-print or an extension; telling which needs the origin, so
    the cross-file rules decide.
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
    """A note for a command's ABNF member that its tables mark '-' (unused)
    in that command's column (TS 32.299 clause 7.1.0). A blank cell marks
    nothing; `* [ AVP ]` is skipped.
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
    """Check each `Undefined AVP` block against the file.

    `undefined-avp` (note): a body references the name. `undefined-avp-unused`
    (error): no body references it, or none in the block's clause.
    `undefined-avp-defined` (error): the file defines, tabulates or re-uses
    the name, or declares it twice."""
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
    """Notes for clauses the file cites but does not hold.

    `section-mismatch`: a table row cites a clause for an AVP that a
    definition, re-print or bit table here holds elsewhere (citing a parent
    clause is fine). `section-unknown`: an `; Applies-To:` or `; Values:`
    names a clause no block sits at or under.

    A row whose AVP no block holds is not checked: simple-typed AVPs have no
    block, so the check would mostly report noise.
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
