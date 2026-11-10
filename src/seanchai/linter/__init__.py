"""Structural rules over one parsed `.dad` file.

The extractor records what a specification says, including where it
contradicts itself; this is the layer that reports those contradictions
instead of resolving them. Every rule here is decided inside a single file,
and nearly every one has a real case in the committed corpus — they are not
hypothetical invariants, they are the inconsistencies three specifications
actually contain. The exceptions are the two application-scope rules, which
report what `model.Model.applications` would otherwise settle without
comment, and two of the registry rules, `registry-command-name` and
`registry-application-document`, which compare the corpus with TS 29.230
and find it agreeing.

Findings carry a severity because not every one of them is a defect:

- `ERROR` — the file asserts two things that cannot both be true, whoever is
  at fault. Two AVPs with one identity; a table row disagreeing with the
  definition it points at.
- `NOTE` — something worth knowing that a single file cannot judge. An AVP
  both defined locally and listed as re-used is the case that forced the
  distinction: a specification may re-print another's AVP for convenience or
  *extend* it with new fields, and deciding which needs the origin document.
- `ACCEPTED` — a note an `Accept` in the specification's corrections module
  acknowledges as a deliberate override its document states (`accept`).

An AVP's identity is `(vendor-id, code)`, and the vendor half comes from the
file's own `; Vendor-ID:` directive, except for a table row printing a
Vendor-ID cell, which states its own, and one whose V flag is Must-not,
which is IETF space (`ast.AvpTableRow.stated_vendor`, the model's reading
too); re-used rows belong to their origins' vendor spaces, which the
single-file rules therefore leave to the cross-file ones — see
`_tables._duplicate_identities`.

Findings are anchored by clause and name rather than by line number. The AST
carries no line information, and a clause reference survives reformatting and
points at the same place in the specification as in the `.dad` file — which is
where the reader has to go anyway.

The package's modules are internal; `__all__` here is its public surface.
`_lint` holds the entry points and the order the rules run in, `_findings`
the finding and acceptances, `_index` the one pass over a file the rules
read; the single-file rules are in `_definitions`, `_tables` and
`_referencing`, the cross-file ones in `_origins` and `_reused`, and the
registry's in `_registry`.
"""

from ._findings import AvpIdentity, Finding, Severity, accept
from ._lint import lint, lint_record, lint_with_corpus

__all__ = [
    "AvpIdentity",
    "Finding",
    "Severity",
    "accept",
    "lint",
    "lint_record",
    "lint_with_corpus",
]
