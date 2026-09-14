"""Corrections for 3GPP TS 29.172 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, avp_rule, definition, table_row

CORRECTIONS = [
    Correction(
        id="periodic-ldr-information-name",
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
    Correction(
        id="plr-supported-gad-shapes",
        target=avp_rule("Provide-Location-Request", "LCS-Supported-GAD-Shapes"),
        field="name",
        expect="LCS-Supported-GAD-Shapes",
        replace="Supported-GAD-Shapes",
        reason="the PLR ABNF (clause 7.3.1) and its information-element table"
        " prefix the name with LCS-; clause 7.4.12's heading and prose, table"
        " 7.4.1-1 and Wireshark's dictionary all define the AVP at code 2510"
        " as Supported-GAD-Shapes",
        versions="18.1.0",
    ),
    Correction(
        id="area-identification-type",
        target=table_row("Area-Identification"),
        field="data_type",
        expect=ast.DataType.GROUPED,
        replace=ast.DataType.OCTET_STRING,
        reason="table 7.4.1-1 says Grouped, but clause 7.4.42 defines the"
        " Area-Identification AVP as of type OctetString and lays out its"
        " octets; no grouped ABNF exists, and Wireshark's dictionary reads"
        " the clause the same way",
        versions="18.1.0",
    ),
]
