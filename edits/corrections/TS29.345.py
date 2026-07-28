"""Corrections for 3GPP TS 29.345 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, avp_rule, definition, table_row

CORRECTIONS = [
    Correction(
        target=table_row("Assistance-info"),
        field="name",
        expect="Assistance-info",
        replace="Assistance-Info",
        reason="the AVP rule and its references capitalize Info; table 6.3.1/1"
        " alone spells the name Assistance-info",
        versions="18.0.0",
    ),
    Correction(
        target=table_row("WLAN-Link-Layer-Id"),
        field="data_type",
        expect=ast.DataType.OCTET_STRING,
        replace=ast.DataType.GROUPED,
        reason="clause 6.3.32 explicitly defines this AVP as Grouped and gives"
        " its grouped rule; table 6.3.1/1 incorrectly says OctetString",
        versions="18.0.0",
    ),
    Correction(
        target=table_row("ProSe-Restricted-Code-Suffix-Range"),
        field="data_type",
        expect=ast.DataType.OCTET_STRING,
        replace=ast.DataType.GROUPED,
        reason="clause 6.3.68 explicitly defines this AVP as Grouped and gives"
        " its grouped rule; table 6.3.1/1 incorrectly says OctetString",
        versions="18.0.0",
    ),
    Correction(
        target=definition("Code-Receiving-Security-Material"),
        field="code",
        expect=3847,
        replace=3860,
        reason="table 6.3.1/1 assigns this AVP code 3860; clause 6.3.75's rule"
        " repeats code 3847 from ProSe-Restricted-Code-Suffix-Range",
        versions="18.0.0",
    ),
    Correction(
        target=definition("Code-Sending-Security-Material"),
        field="code",
        expect=3847,
        replace=3861,
        reason="table 6.3.1/1 assigns this AVP code 3861; clause 6.3.76's rule"
        " repeats code 3847 from ProSe-Restricted-Code-Suffix-Range",
        versions="18.0.0",
    ),
    Correction(
        target=definition("ProSe-App-Code-Suffix-Range"),
        field="code",
        expect=3847,
        replace=3867,
        reason="table 6.3.1/1 assigns this AVP code 3867; clause 6.3.82's rule"
        " repeats code 3847 from ProSe-Restricted-Code-Suffix-Range",
        versions="18.0.0",
    ),
    Correction(
        target=table_row("ProSe-App-Code-Suffix-Range"),
        field="data_type",
        expect=ast.DataType.OCTET_STRING,
        replace=ast.DataType.GROUPED,
        reason="clause 6.3.82 explicitly defines this AVP as Grouped and gives"
        " its grouped rule; table 6.3.1/1 incorrectly says OctetString",
        versions="18.0.0",
    ),
    Correction(
        target=table_row("MIC-Check-indicator"),
        field="name",
        expect="MIC-Check-indicator",
        replace="MIC-Check-Indicator",
        reason="only the table 6.3.1-1 cell lowercases the I; clause 6.3.80's"
        " heading and prose and the Match-Report ABNF (clause 6.3.75) all"
        " write MIC-Check-Indicator",
        versions="18.0.0",
    ),
    Correction(
        target=avp_rule("WLAN-Assistance-Info", "WiFi-P2P-Assistance-Iinfo"),
        field="name",
        expect="WiFi-P2P-Assistance-Iinfo",
        replace="WiFi-P2P-Assistance-Info",
        reason="the WLAN-Assistance-Info body (clause 6.3.31) doubles the i;"
        " clause 6.3.30 defines WiFi-P2P-Assistance-Info and table 6.3.1-1"
        " spells it the same way",
        versions="18.0.0",
    ),
    # The Discovery-Auth-Request/Match-Report-Info bodies (clauses 6.3.53,
    # 6.3.56) capitalize the D of ProSe-App-Id, which clause 6.3.17 defines
    # and table 6.3.1-1 lists; the same two bodies and the PAR command
    # (clause 6.2.3) write User-Identity for User-Identifier, the TS 29.336
    # AVP their information-element tables name and which table 6.3.1-2
    # lists as re-used — no AVP named User-Identity exists in this document
    # or its citations, and the listed User-Identifier row is otherwise
    # referenced by nothing.
    *(
        Correction(
            target=avp_rule(parent, wrong),
            field="name",
            expect=wrong,
            replace=right,
            reason=f"the {parent} body writes {wrong}; the AVP is {right} —"
            " see the block comment above",
            versions="18.0.0",
        )
        for parent, wrong, right in (
            ("Discovery-Auth-Request", "ProSe-App-ID", "ProSe-App-Id"),
            ("Match-Report-Info", "ProSe-App-ID", "ProSe-App-Id"),
            ("ProSe-Authorization-Request", "User-Identity", "User-Identifier"),
            ("Discovery-Auth-Request", "User-Identity", "User-Identifier"),
            ("Match-Report-Info", "User-Identity", "User-Identifier"),
        )
    ),
]
