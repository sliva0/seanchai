"""Entry points: the single-file and corpus rules in run order, and the
check of the hole record against the corpus.
"""

from __future__ import annotations

from collections.abc import Sequence

from .. import corpus, model
from ..dad import ast, corrections
from ._definitions import (
    _applications_agree_with_headers,
    _duplicate_definitions,
    _duplicate_enum_values,
    _duplicate_values,
    _one_name_two_commands,
    _values_out_of_range,
    _vendor_specific_overlaps,
    _void_overlaps,
)
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

    superseded = {"local-and-reused", "duplicate-identity"}
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
    ]
    return accept(spec, _ordered(findings), acceptances)


def lint_record(books: corpus.Corpus) -> list[Finding]:
    """Check the corpus's hole record as a default `model.Model.build` does.

    Reports each hole no entry lists as it is, and each entry naming no hole.
    The findings are per corpus, not per file. A corpus with no record gives
    no findings."""
    if books.record is None:
        return []
    built = model.Model.build(books, holes=model.HolePolicy.ANY)
    known = {(entry.document, entry.name): entry for entry in books.record.holes}
    findings = []
    for hole in built.unrecorded_holes():
        entry = known.get((hole.document, hole.name))
        findings.append(
            Finding(
                Severity.ERROR,
                "unrecorded-hole",
                f"{hole}, which the record does not list"
                if entry is None
                else f"{hole}, which the record lists missing"
                f" {', '.join(entry.missing)}",
                section=hole.section,
            )
        )
    findings += [
        Finding(
            Severity.ERROR,
            "stale-hole-record",
            f"{entry.document} {entry.name} is recorded missing"
            f" {', '.join(entry.missing)}, but the corpus has no such hole: its"
            " entry belongs out of the record",
        )
        for entry in built.stale_record_entries()
    ]
    return findings
