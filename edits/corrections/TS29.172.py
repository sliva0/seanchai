"""Corrections for 3GPP TS 29.172 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
        target=definition("Periodic-LDR-Info"),
        field="name",
        expect="Periodic-LDR-Info",
        replace="Periodic-LDR-Information",
        reason="clause 7.4.45 heads and names the AVP 'Periodic-LDR-Info', but"
        " table 7.4.1/1 and both message ABNFs spell it"
        " 'Periodic-LDR-Information' at the same code 2540; Wireshark's"
        " dictionary and mensonen/diameter both use the longer name",
        versions="18.1.0",
    ),
]
