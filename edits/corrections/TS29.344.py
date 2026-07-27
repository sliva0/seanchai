"""Corrections for 3GPP TS 29.344 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition

# Clauses 6.2.11 and 6.2.12 head "ProSe-Initial-Location-Information-Request"
# and "-Answer" and carry command code 8388713 with the abbreviations PSR/PSA,
# but their ABNF re-prints the rule names of clauses 6.2.3/6.2.4, which are
# command 8388664 (PIR/PIA). IANA assigns 8388713 to
# ProSe-Initial-Location-Information-Request/Answer, so the headings and the
# codes agree with each other and only the rule names are wrong.
_PSR_PSA = (
    "clauses 6.2.11/6.2.12 re-print the rule names of 6.2.3/6.2.4; the headings,"
    " the PSR/PSA abbreviations and command code 8388713 all name"
    " ProSe-Initial-Location-Information instead"
)

CORRECTIONS = [
    Correction(
        target=definition(f"ProSe-Subscriber-Information-{kind}", section=section),
        field="name",
        expect=f"ProSe-Subscriber-Information-{kind}",
        replace=f"ProSe-Initial-Location-Information-{kind}",
        reason=_PSR_PSA,
        versions="18.1.0",
    )
    for kind, section in (("Request", "6.2.11"), ("Answer", "6.2.12"))
]
