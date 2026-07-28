"""Corrections for 3GPP TS 29.128 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition, reused_row

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
    Correction(
        target=reused_row("Bearer-Identity"),
        field="name",
        expect="Bearer-Identity",
        replace="Bearer-Identifier",
        reason="table 6.4.1/2 cites 'Bearer-Identity' from TS 29.212, which"
        " defines no such AVP; 29.212's table 5.3.0.1 and this document's own"
        " command ABNFs (clauses 6.2.3, 6.2.6, 6.2.7) spell it"
        " 'Bearer-Identifier' (code 1020)",
        versions="18.0.0",
    ),
]
