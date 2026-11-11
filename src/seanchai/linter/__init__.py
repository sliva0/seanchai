"""Rules that report where the corpus contradicts itself, without resolving it.

See docs/linter.md for the rules and severities. A finding is anchored by
clause and name, not line: the AST has no line numbers. An AVP's identity is
`(vendor-id, code)`, with the vendor read as `ast.AvpTableRow.stated_vendor`
reads it; re-used rows belong to their origins' vendor spaces, so the
cross-file rules check them.

Severities: `ERROR` means two statements that cannot both be true; `NOTE`
means something one file cannot judge; `ACCEPTED` is a note an `Accept` in
the corrections module acknowledges. An error is never accepted.

The modules are internal and `__all__` is the public surface. `_lint` holds
the entry points and rule order, `_findings` the finding and acceptances,
`_index` the per-file index the rules read. Single-file rules are in
`_definitions`, `_tables` and `_referencing`; cross-file rules in `_origins`
and `_reused`; registry rules in `_registry`.
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
