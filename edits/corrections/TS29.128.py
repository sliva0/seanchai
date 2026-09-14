"""Corrections for 3GPP TS 29.128 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    definition,
    reused_avps,
    reused_row,
)

CORRECTIONS = [
    Correction(
        id="number-of-ue-per-location-configuration-case",
        target=definition("Number-of-UE-Per-Location-Configuration"),
        field="name",
        expect="Number-of-UE-Per-Location-Configuration",
        replace="Number-Of-UE-Per-Location-Configuration",
        reason="table 6.4.1/1, the clause heading, and the ABNF reference in"
        " clause 6.2.4 all capitalize 'Of'; only the rule name uses 'of'",
        versions="18.0.0",
    ),
    Correction(
        id="number-of-ue-per-location-report-case",
        target=definition("Number-of-UE-Per-Location-Report"),
        field="name",
        expect="Number-of-UE-Per-Location-Report",
        replace="Number-Of-UE-Per-Location-Report",
        reason="table 6.4.1/1, the clause heading, and the ABNF reference in"
        " clause 6.2.5 all capitalize 'Of'; only the rule name uses 'of'",
        versions="18.0.0",
    ),
    Correction(
        id="bearer-identifier-spelling",
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
    # The Terminal-Information body (clause 6.4.30) re-prints TS 29.272's
    # grouped AVP; its members IMEI and Software-Version are TS 29.272's too
    # (codes 1402, 1403), but table 6.4.1-2 omits their rows.
    *(
        Insert(
            id=f"missing-row-{name.lower()}",
            into=reused_avps("6.4.1-2"),
            node=ast.ReusedAvpRow(name=name, origin="TS29.272"),
            after=after,
            reason=f"the Terminal-Information body (clause 6.4.30) uses"
            f" {name} but table 6.4.1-2 omits the row; TS 29.272 defines"
            " the AVP",
            versions="18.0.0",
        )
        for name, after in (
            ("IMEI", "Terminal-Information"),
            ("Software-Version", "IMEI"),
        )
    ),
]
