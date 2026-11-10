"""Resolving the documents a file cites and builds on, and the cross-file
rules about resolution itself: an origin resolved across releases, one
the corpus lacks, and references no base document resolves.

Everything here and in `_reused` needs a second document. The
single-file rules decline to guess where a name or a vendor space
belongs to another specification; these are what actually go and look.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import corpus
from ..dad import ast
from ._findings import Finding, Severity
from ._index import _clauses, _Index, _index, _references


@dataclass(frozen=True)
class _Origin:
    """One resolved origin document, indexed once.

    Every cross-file rule looks origins up per re-used row, so resolving and
    re-indexing inside the rules would walk each origin document once per
    citation — 29.272 alone cites eighteen origins across a hundred rows.
    """

    spec: ast.Specification
    defined: dict[str, ast.GroupedAvp | ast.EnumeratedAvp]
    tabled: dict[str, ast.AvpTableRow]
    reused: dict[str, str]
    tables: list[ast.AvpTable]
    value_tables: list[ast.ValueTable]

    @classmethod
    def of(cls, spec: ast.Specification) -> _Origin:
        theirs = _index(spec)
        return cls(
            spec=spec,
            defined={definition.name: definition for definition in theirs.definitions},
            tabled={row.name: row for row in theirs.rows},
            reused=theirs.reused,
            tables=theirs.tables,
            value_tables=theirs.value_tables,
        )


def _cited(index: _Index) -> list[str]:
    """Every document the file names as an origin, by a re-used row, a
    re-print or a result code."""
    return sorted(
        {
            *index.reused.values(),
            *(r.origin for r in index.reprints),
            *(row.origin for _, row in index.reused_values if row.origin),
        }
    )


def _resolve_origins(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
) -> tuple[dict[str, _Origin], list[Finding]]:
    """The origins the corpus resolves, and a `cross-release-origin` note
    for each it resolved outside `spec`'s release."""
    origins = {}
    crossings = []
    for origin in _cited(index):
        entry, across = books.resolution(origin, like=spec)
        if entry is None:
            continue
        origins[origin] = _Origin.of(entry.spec)
        if across is not None:
            crossings.append(_cross_release(spec, entry, across, books.rules))
        if (later := books.release_fill(origin, like=spec)) is not None:
            crossings.append(_release_fill(spec, later))
    return origins, crossings


def _release_fill(
    spec: ast.Specification,
    later: tuple[corpus.Entry, corpus.ReleaseFill, corpus.CrossRelease],
) -> Finding:
    """A field a later release's copy states for a citation whose own copy leaves
    it unstated (`corpus.Rules.release_fills`), so a reader can audit it: TS
    29.210 V6.7.0's `3GPP-SGSN-MCC-MNC` is TS 29.061 V6.15.0's, typed by V19.1.0.
    A note, since the citing document's editor meant the older copy."""
    entry, fill, across = later
    citing = spec.specification + (f" V{spec.version}" if spec.version else "")
    return Finding(
        Severity.NOTE,
        "cross-release-origin",
        f"{across.cited} is resolved across releases to {entry.path.name} for"
        f" {', '.join(fill.fields)} of {', '.join(fill.names)}: {citing} is the"
        f" citing file, and it cites the document non-specifically, meaning"
        f" V{across.meant}, which answers for all else and leaves those unstated,"
        f" and V{across.version} states them: {fill.evidence}"
        " (corpus.toml, release_fill)",
    )


def _cross_release(
    spec: ast.Specification,
    entry: corpus.Entry,
    across: corpus.CrossRelease,
    rules: corpus.Rules,
) -> Finding:
    """A re-used origin resolved outside the citing document's release, by
    the drafting rule `corpus.resolution` applied, so a reader can audit it:
    TS 32.299 V19.0.0's TS 29.140 is V7.0.0, the document's final version,
    TS 29.212's 3GPP2 X.S0057-B is revision 0 V2.0, standing in, and TS
    32.299 V11.20.0's TS 29.061 is V19.1.0, standing in for V11.12.0. A
    note: the rule is the corpus's reading of the citing document's
    references, and only its editor knows whether it meant that."""
    citing = spec.specification + (f" V{spec.version}" if spec.version else "")
    if across.rule is corpus.CitationRule.STAND_IN and across.meant is not None:
        release = rules.release_stand_ins[
            across.citing, spec.version or "", across.cited
        ]
        how = "by version, naming" if across.specific else "non-specifically, meaning"
        rule = (
            f"it cites the document {how} V{across.meant},"
            f" which the corpus lacks, and V{across.version} stands in:"
            f" {release.evidence} (corpus.toml, release_stand_in)"
        )
    elif across.rule is corpus.CitationRule.STAND_IN:
        stand_in = rules.stand_ins[across.citing, spec.version or "", across.cited]
        rule = (
            f"its references name revision {across.cited_revision}, which the"
            f" corpus lacks, and revision {across.revision} V{across.version}"
            f" stands in: {stand_in.evidence} (corpus.toml, stand_in)"
        )
    elif across.rule is corpus.CitationRule.SPECIFIC:
        rule = (
            f"its references name V{across.version} (a specific reference;"
            " corpus.toml, cited_version)"
        )
    elif across.rule is corpus.CitationRule.LATEST_EDITION:
        evidence = rules.latest_editions[
            across.citing, spec.version or "", across.cited
        ]
        rule = (
            f"it cites the document non-specifically, which reads as its latest"
            f" edition, V{across.version} of the corpus's copies: {evidence}"
            " (corpus.toml, latest_edition)"
        )
    else:
        rule = (
            f"it cites the document non-specifically, which reads as its"
            f" final version, V{across.version} (corpus.toml, final_version)"
        )
    return Finding(
        Severity.NOTE,
        "cross-release-origin",
        f"{across.cited} is resolved across releases to {entry.path.name}:"
        f" {citing} is the citing file, and {rule}",
    )


def _unresolved_origins(
    spec: ast.Specification,
    index: _Index,
    origins: dict[str, _Origin],
    books: corpus.Corpus,
) -> list[Finding]:
    """A re-used row citing a document the corpus does not hold.

    A note, not an error: the document is fine, the corpus is incomplete. It is
    still worth saying, because every other cross-file rule silently does
    nothing for such a row, and a rule that is quiet because it had nothing to
    read looks exactly like a rule that found nothing wrong.

    One note per file rather than per origin. A Rel-19 corpus without an RFC
    extractor cannot resolve a single RFC, and 29.272 alone cites eighteen
    origins — reported individually they would bury every real finding, and
    they all say the same thing.

    An origin outside 3GPP and IETF (ETSI, 3GPP2, OMA, oneM2M) gets a note of
    its own, `external-origin-not-in-corpus`: no 3GPP or IETF download
    closes the gap, only a hand-written file or a catalogued document an
    extractor reads (oneM2M TS-0004).
    """
    cited = _cited(index)
    missing: list[str] = []
    external: list[str] = []
    for origin in cited:
        if origin in origins:
            continue
        if ast.is_external(origin):
            external.append(origin)
            continue
        held = books.versions(origin)
        missing.append(f"{origin} (corpus has {', '.join(held)})" if held else origin)
    findings = []
    if missing:
        findings.append(
            Finding(
                Severity.NOTE,
                "origin-not-in-corpus",
                f"{len(missing)} of {len(cited)} cited origins"
                f" could not be resolved for a {spec.version or 'version-less'}"
                f" document, and the rules"
                f" needing them were skipped: {', '.join(missing)}",
            )
        )
    if external:
        findings.append(
            Finding(
                Severity.NOTE,
                "external-origin-not-in-corpus",
                f"{len(external)} of {len(cited)} cited origins are documents"
                " outside 3GPP and IETF that the corpus holds no copy of, and"
                f" the rules needing them were skipped: {', '.join(external)}",
            )
        )
    return findings


def _resolve_bases(
    spec: ast.Specification, books: corpus.Corpus
) -> tuple[dict[str, _Origin], list[str]]:
    """Resolve `; Bases:` the way re-used origins resolve, keeping the misses.

    Bases are the documents a file builds on without citing them anywhere —
    RFC 6733 for every Diameter application — so they share the origin
    machinery but not the origin rules: a base supplies names for reference
    resolution rather than rows to compare against.
    """
    resolved, missing = {}, []
    for base in spec.bases:
        entry = books.resolve(base, like=spec)
        if entry is None:
            missing.append(base)
            continue
        resolved[base] = _Origin.of(entry.spec)
    return resolved, missing


def _unresolved_references(
    index: _Index, bases: dict[str, _Origin], missing_bases: list[str]
) -> list[Finding]:
    """Every AVP referenced in a message or grouped body resolves somewhere:
    a local definition, an AVP-table row, a re-used entry, or a base document.

    This is phase two's rule, enforceable now that `; Bases:` names the
    document that supplies `Session-Id`, `Origin-Host` and the rest. The
    trailing `* [ AVP ]` is RFC 6733's any-AVP wildcard — grammar, not a
    reference — and is skipped rather than resolved to the name `AVP`.

    A base missing from the corpus turns the rule off with a note instead of
    reporting every base-protocol AVP as unresolved: the document is fine, the
    corpus is incomplete, and a hundred spurious errors would bury the real
    findings.

    A name an `Undefined AVP` block declares is no unresolved reference:
    `undefined-avp` reports it, and here `undefined-avp-defined` reports a
    block whose name a base document resolves after all, the stale claim's
    cross-file form.

    An error: the corrected corpus resolves every reference or declares it
    undefined, so one that does neither is a defect wanting a correction (a
    block, a renamed member, a row or a `; Bases:` entry).
    """
    if missing_bases:
        return [
            Finding(
                Severity.NOTE,
                "base-not-in-corpus",
                f"the corpus holds no copy of base"
                f" document{'s' if len(missing_bases) > 1 else ''}"
                f" {', '.join(missing_bases)}, so reference resolution was"
                " skipped",
            )
        ]
    known = (
        {definition.name for definition in index.definitions}
        | {row.name for row in index.rows}
        | set(index.reused)
    )
    local = set(known)
    for base in bases.values():
        known |= base.defined.keys() | base.tabled.keys() | base.reused.keys()
    declared = {block.name: block for block in index.undefined}
    stale = [
        Finding(
            Severity.ERROR,
            "undefined-avp-defined",
            f"{name} is declared undefined, but a base document resolves it",
            block.source.section,
            paths=(index.path(block),),
        )
        for name, block in sorted(declared.items())
        if name in known and name not in local
    ]
    return stale + [
        Finding(
            Severity.ERROR,
            "unresolved-reference",
            f"{name} is referenced in {_clauses(where)} but resolves to no"
            " local definition, table row, re-used entry or base document,"
            " and no Undefined AVP block declares it",
        )
        for name, where in sorted(_references(index).items())
        if name not in known and name not in declared
    ]
