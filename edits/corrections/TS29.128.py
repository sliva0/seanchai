"""Corrections for 3GPP TS 29.128 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
        target=definition("Number-of-UE-Per-Location-Configuration"),
        field="name",
        expect="Number-of-UE-Per-Location-Configuration",
        replace="Number-Of-UE-Per-Location-Configuration",
        reason="table 6.4.1/1, the clause heading, and the ABNF reference in"
        " clause 6.2.4 all capitalize 'Of'; only the rule name uses 'of'",
        versions="18.0.0",
    ),
    Correction(
        target=definition("Number-of-UE-Per-Location-Report"),
        field="name",
        expect="Number-of-UE-Per-Location-Report",
        replace="Number-Of-UE-Per-Location-Report",
        reason="table 6.4.1/1, the clause heading, and the ABNF reference in"
        " clause 6.2.5 all capitalize 'Of'; only the rule name uses 'of'",
        versions="18.0.0",
    ),
]
