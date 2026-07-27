"""Corrections for 3GPP TS 29.388 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
        target=definition("V2X-PC5-Allowed-PLMN", section="6.3.10"),
        field="name",
        expect="V2X-PC5-Allowed-PLMN",
        replace="PLMN-Allowed-PC5-RATs",
        reason="clause 6.3.10's AVP format re-prints clause 6.3.3's rule name;"
        " the heading, the clause prose and table 6.3.1-1 all call the AVP at"
        " code 4603 'PLMN-Allowed-PC5-RATs', and 6.3.3's own AVP is 4600",
        versions="18.1.0",
    ),
]
