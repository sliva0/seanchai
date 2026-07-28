"""Corrections for 3GPP TS 29.345 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, definition, table_row

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
]
