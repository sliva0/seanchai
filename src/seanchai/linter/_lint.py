"""Entry points: the single-file and corpus rules in run order, and the
check of the hole record against the corpus.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from .. import corpus, model
from .._versions import VersionRange, spans
from ..dad import ast, corrections, interpretations
from ._constraints import CONSTRAINT_RULES, _constraints
from ._definitions import (
    _applications_agree_with_headers,
    _duplicate_definitions,
    _duplicate_enum_values,
    _duplicate_values,
    _enum_values_out_of_range,
    _one_name_two_commands,
    _values_out_of_range,
    _vendor_specific_overlaps,
    _void_overlaps,
)
from ._elements import ELEMENT_RULES, _elements
from ._findings import Finding, Severity, _ordered, accept
from ._index import _index
from ._origins import (
    _resolve_bases,
    _resolve_origins,
    _unresolved_origins,
    _unresolved_references,
)
from ._referencing import (
    _local_and_reused,
    _members_marked_unused,
    _section_references,
    _self_cited_exists,
    _undefined_avps,
)
from ._registry import _against_registry, _registry_overlaps
from ._reused import (
    _reprint_or_extension,
    _reprints_agree_with_origin,
    _result_codes_agree_with_origin,
    _reused_avp_exists,
    _reused_cells_agree_with_origin,
    _reused_codes_agree_with_origin,
    _reused_row_vendors_agree_with_origin,
    _reused_rows_agree_with_origin,
)
from ._tables import (
    _duplicate_identities,
    _rows_without_codes,
    _table_agrees_with_definitions,
    _tables_agree_with_each_other,
    _vendor_id_agrees_with_header,
    _vendors_agree_with_flags,
)


def lint(spec: ast.Specification) -> list[Finding]:
    """Return every single-file finding, errors before notes."""
    index = _index(spec)
    findings = [
        *_duplicate_definitions(index),
        *_one_name_two_commands(index),
        *_duplicate_enum_values(index),
        *_enum_values_out_of_range(index),
        *_duplicate_values(index),
        *_values_out_of_range(index),
        *_vendor_specific_overlaps(index),
        *_void_overlaps(index),
        *_applications_agree_with_headers(index),
        *_duplicate_identities(index, spec.vendor_id),
        *_rows_without_codes(index),
        *_table_agrees_with_definitions(index),
        *_tables_agree_with_each_other(index),
        *_vendor_id_agrees_with_header(index, spec.vendor_id),
        *_vendors_agree_with_flags(index),
        *_self_cited_exists(index),
        *_local_and_reused(index),
        *_members_marked_unused(spec),
        *_registry_overlaps(spec),
        *_undefined_avps(index),
        *_section_references(spec, index),
        *_elements(spec, index, None),
        *_constraints(spec, index, None),
    ]
    return _ordered(findings)


def lint_with_corpus(
    spec: ast.Specification,
    books: corpus.Corpus,
    acceptances: Sequence[corrections.Accept] = (),
) -> list[Finding]:
    """Return every single-file and cross-file finding for `spec`, with the
    notes `acceptances` acknowledge marked accepted (`accept`).

    Where an origin resolves, `local-and-reused` gives way to
    `reused-reprint` or `reused-body-differs`, and `duplicate-identity` is
    re-run with re-used rows in their origins' vendor spaces. A row whose
    origin is missing from the corpus keeps the single-file finding.
    """
    index = _index(spec)
    origins, crossings = _resolve_origins(spec, index, books)
    bases, missing_bases = _resolve_bases(spec, books)

    def reused_vendor(origin: str) -> int | None:
        resolved = origins.get(origin)
        return None if resolved is None else resolved.spec.vendor_id

    superseded = {
        "local-and-reused",
        "duplicate-identity",
        *ELEMENT_RULES,
        *CONSTRAINT_RULES,
    }
    findings = [
        finding
        for finding in lint(spec)
        if finding.rule not in superseded
        or (finding.rule == "local-and-reused" and finding.origin not in origins)
    ]
    findings += [
        *crossings,
        *_unresolved_origins(spec, index, origins, books),
        *_reused_avp_exists(index, origins),
        *_reprint_or_extension(index, origins),
        *_reprints_agree_with_origin(index, origins),
        *_reused_rows_agree_with_origin(index, origins),
        *_reused_row_vendors_agree_with_origin(index, spec.vendor_id, origins),
        *_reused_cells_agree_with_origin(index, origins),
        *_reused_codes_agree_with_origin(index, origins),
        *_result_codes_agree_with_origin(index, origins),
        *_duplicate_identities(index, spec.vendor_id, reused_vendor),
        *_unresolved_references(index, bases, missing_bases),
        *_against_registry(spec, index, books),
        *_elements(spec, index, lambda reference: _cited(books, spec, reference)),
        *_constraints(spec, index, lambda reference: _cited(books, spec, reference)),
    ]
    return accept(spec, _ordered(findings), acceptances)


def lint_interpretations(
    specification: str,
    declared: Sequence[interpretations.Interpretation],
    books: corpus.Corpus | None,
) -> list[tuple[corpus.Entry, list[Finding]]]:
    """Check an interpretations file's blocks against each corrected copy
    `books` holds of `specification`, the document they interpret, as its
    `; Interprets:` names it: in each copy whose
    version a block's range spans, the `constraint-*` rules, read as the
    copy would read the block merged in place of its own. Each finding's
    message opens with the block's line in the file. A copy no block spans
    is not listed; without `books` nothing is.

    The file's syntax, its rules' shapes, its ids and its clause order are
    checked as it is read (`interpretations.read`)."""
    if books is None or not declared:
        return []
    reference = ast.spec_ref(specification)
    checked = []
    for entry in books:
        if entry.path.name.endswith(".raw.dad"):
            continue
        if ast.spec_ref(entry.spec.specification) != reference:
            continue
        held = [
            item
            for item in declared
            if spans(VersionRange.parse(item.versions), entry.spec.version)
        ]
        if not held:
            continue
        kept = [
            section
            for section in entry.spec.sections
            if not isinstance(section, ast.InterpretedConstraints)
        ]
        merged = entry.spec.model_copy(
            update={"sections": (*kept, *(item.node for item in held))}
        )
        index = _index(merged)

        findings = _constraints(
            merged, index, lambda name, spec=merged: _cited(books, spec, name)
        )
        checked.append(
            (entry, _ordered([_at_line(each, held, len(kept)) for each in findings]))
        )
    return checked


def _at_line(
    finding: Finding,
    held: Sequence[interpretations.Interpretation],
    start: int,
) -> Finding:
    """`finding` naming the line of the block it is about, `held[i]` merged as
    the section at `start + i`."""
    path = finding.paths[0] if finding.paths else ()
    if len(path) < 2 or not isinstance(path[1], int) or path[1] < start:
        return finding
    item = held[path[1] - start]
    return dataclasses.replace(
        finding, message=f"line {item.lines[0]}: {finding.message}"
    )


def _cited(
    books: corpus.Corpus, spec: ast.Specification, reference: str
) -> ast.Specification | None:
    """The copy of `reference` `spec` means, or None where the corpus lacks
    it."""
    entry = books.resolve(reference, like=spec)
    return None if entry is None else entry.spec


def lint_record(books: corpus.Corpus) -> list[Finding]:
    """Check the corpus's hole record as a default `model.Model.build` does,
    at every release the corpus holds whole.

    Reports each hole no entry lists as it is, and each entry naming no hole,
    naming the release where the corpus holds more than one. The findings are
    per corpus, not per file. A corpus with no record gives no findings."""
    if books.record is None:
        return []
    findings = []
    for release in books.releases or (None,):
        built = model.Model.build(books.at(release), holes=model.HolePolicy.ANY)
        known = books.record.at(release)
        at = f"Release {release}: " if len(books.releases) > 1 else ""
        for hole in built.unrecorded_holes():
            entry = known.get((hole.document, hole.name))
            findings.append(
                Finding(
                    Severity.ERROR,
                    "unrecorded-hole",
                    f"{at}{hole}, which the record does not list"
                    if entry is None
                    else f"{at}{hole}, which the record lists missing"
                    f" {', '.join(entry.missing)}",
                    section=hole.section,
                )
            )
        findings += [
            Finding(
                Severity.ERROR,
                "stale-hole-record",
                f"{at}{entry.document} {entry.name} is recorded missing"
                f" {', '.join(entry.missing)}, but the corpus has no such hole:"
                " its entry belongs out of the record",
            )
            for entry in built.stale_record_entries()
        ]
    return findings
