"""Corrections for 3GPP TS 29.230 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, registry_reservation, registry_row

# Table 7.1's note on 1324-1399 follows the run of TS 32.299 rows ending at 1323
# and cites a document clause 2 does not list and no other row names: a
# transposition of TS 32.299, [5] in clause 2, which defines PSCell-Info and
# Nr-Cgi in the range.
CORRECTIONS = [
    Correction(
        id="reserved-1324-document",
        target=registry_reservation(1324, 1399),
        field="defined_in",
        expect=("TS32.229",),
        replace=("TS32.299",),
        reason="table 7.1's note reserves 1324 to 1399 'for TS 32.229', which clause"
        " 2 does not list; [5] is TS 32.299, every row before the range cites it and"
        " it defines PSCell-Info and Nr-Cgi inside the range",
        versions="19.3.0",
    ),
    Correction(
        id="reserved-1324-purpose",
        target=registry_reservation(1324, 1399),
        field="purpose",
        expect="TS 32.229",
        replace="TS 32.299",
        reason="the same note's words: 'reserved for TS 32.229' transposes clause"
        " 2's [5], TS 32.299",
        versions="19.3.0",
    ),
]

# Table 7.1 names these codes otherwise than the clause defining each, and table
# 8.1.4 one so. Each prints a name the reading takes as one, so the registry's
# misprint is the raw file's, and the defining clause's spelling the corrected
# file's: what a dictionary keys on.
CORRECTIONS += [
    Correction(
        id=f"{name.lower().replace('_', '-')}-registry-name",
        target=registry_row(registry, code),
        field="name",
        expect=printed,
        replace=name,
        reason=reason,
        versions="18.6.0..19.3.0",
    )
    for registry, code, printed, name, reason in (
        (
            ast.RegistryKind.AVP_CODES,
            912,
            "MBMS-Session-Identity-Repetition-Number",
            "MBMS-Session-Repetition-Number",
            "table 7.1 names code 912 'MBMS-Session-Identity-Repetition-Number'; the "
            "defining document names it MBMS-Session-Repetition-Number: TS 29.061 "
            "clause 17.7.15 ('The MBMS-Session-Repetition-Number AVP (AVP code 912)') "
            "and table 10",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            402,
            "NAF-Hostname",
            "NAF-Id",
            "table 7.1 names code 402 'NAF-Hostname'; the defining document names it "
            "NAF-Id: TS 29.109 clause 6.3.1.3 ('The NAF-Id AVP (AVP code 402)'), table "
            "6.1 and the Bootstrapping-Info-Request ABNF of clause 5.2; the document "
            "never prints NAF-Hostname",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            519,
            "Media-Sub-Component AVP",
            "Media-Sub-Component",
            "table 7.1 names code 519 'Media-Sub-Component AVP'; the defining document "
            "names it Media-Sub-Component: TS 29.214 clause 5.3.18 and table 5.3.0.1; "
            "the cell carries the word AVP from the clause heading",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1629,
            "Event-ThresholdRSRP",
            "Event-Threshold-RSRP",
            "table 7.1 names code 1629 'Event-ThresholdRSRP'; the defining document "
            "names it Event-Threshold-RSRP: TS 29.272 clause 7.3.143 and table 7.3.1/1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1630,
            "Event-ThresholdRSRQ",
            "Event-Threshold-RSRQ",
            "table 7.1 names code 1630 'Event-ThresholdRSRQ'; the defining document "
            "names it Event-Threshold-RSRQ: TS 29.272 clause 7.3.144 and table 7.3.1/1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1719,
            "Third-Context-ID",
            "Third-Context-Identifier",
            "table 7.1 names code 1719 'Third-Context-ID'; the defining document names "
            "it Third-Context-Identifier: TS 29.272 clause 7.3.244 and table 7.3.1/1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1407,
            "Visited PLMN Id",
            "Visited-PLMN-Id",
            "table 7.1 names code 1407 'Visited PLMN Id'; the defining document names "
            "it Visited-PLMN-Id: TS 29.272 clause 7.3.9 and table 7.3.1/1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3144,
            "Supported-Monitoring-Event",
            "Supported-Monitoring-Events",
            "table 7.1 names code 3144 'Supported-Monitoring-Event'; the defining "
            "document names it Supported-Monitoring-Events: TS 29.336 clause 8.4.41 "
            "and table 8.4.1-1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3143,
            "Supported-Service",
            "Supported-Services",
            "table 7.1 names code 3143 'Supported-Service'; the defining document "
            "names it Supported-Services: TS 29.336 clause 8.4.40 and table 8.4.1-1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3313,
            "MME-Absent-User-Subscriber-Diagnostic-SM",
            "MME-Absent-User-Diagnostic-SM",
            "table 7.1 names code 3313 'MME-Absent-User-Subscriber-Diagnostic-SM'; the "
            "defining document names it MME-Absent-User-Diagnostic-SM: TS 29.338 "
            "clause 5.3.3.9 and table 5.3.3.1/1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3314,
            "MSC-Absent-User-Subscriber-Diagnostic-SM",
            "MSC-Absent-User-Diagnostic-SM",
            "table 7.1 names code 3314 'MSC-Absent-User-Subscriber-Diagnostic-SM'; the "
            "defining document names it MSC-Absent-User-Diagnostic-SM: TS 29.338 "
            "clause 5.3.3.10 and table 5.3.3.1/1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            849,
            "Authorized-QoS",
            "Authorised-QoS",
            "table 7.1 names code 849 'Authorized-QoS'; the defining document names it "
            "Authorised-QoS: TS 32.299 clause 7.2.27 and table 7.2.0.1; CR 0325 "
            "(V9.6.0) replaced 'the Authorized-QoS AVP name with Authorised-QoS'",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            2066,
            "Charging-Characteristic-Selection-Mode",
            "Charging-Characteristics-Selection-Mode",
            "table 7.1 names code 2066 'Charging-Characteristic-Selection-Mode'; the "
            "defining document names it Charging-Characteristics-Selection-Mode: TS "
            "32.299 clause 7.2.39A and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1230,
            "Deferred-Location-Even-Type",
            "Deferred-Location-Event-Type",
            "table 7.1 names code 1230 'Deferred-Location-Even-Type'; the defining "
            "document names it Deferred-Location-Event-Type: TS 32.299 clause 7.2.51's "
            "heading, table 7.2.0.1 and LCS-Information's rule; the clause's first "
            "sentence drops the 't'",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            2603,
            "IP-Realm-Default-Indicator",
            "IP-Realm-Default-Indication",
            "table 7.1 names code 2603 'IP-Realm-Default-Indicator'; the defining "
            "document names it IP-Realm-Default-Indication: TS 32.299 clause 7.2.80A "
            "and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3416,
            "ISUP-Release-Cause",
            "ISUP-Cause",
            "table 7.1 names code 3416 'ISUP-Release-Cause'; the defining document "
            "names it ISUP-Cause: TS 32.299 clause 7.2.80B and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            2604,
            "Local-GW-Inserted-Indicator",
            "Local-GW-Inserted-Indication",
            "table 7.1 names code 2604 'Local-GW-Inserted-Indicator'; the defining "
            "document names it Local-GW-Inserted-Indication: TS 32.299 clause 7.2.92A "
            "and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            2307,
            "MBMS GW-Address",
            "MBMS-GW-Address",
            "table 7.1 names code 2307 'MBMS GW-Address'; the defining document names "
            "it MBMS-GW-Address: TS 32.299 clause 7.2.98 and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            2008,
            "Originating-SCCP-Address",
            "Originator-SCCP-Address",
            "table 7.1 names code 2008 'Originating-SCCP-Address'; the defining "
            "document names it Originator-SCCP-Address: TS 32.299 clause 7.2.128 and "
            "table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3434,
            "ProSe-PC3-Control-Protocol-Cause",
            "PC3-Control-Protocol-Cause",
            "table 7.1 names code 3434 'ProSe-PC3-Control-Protocol-Cause'; the "
            "defining document names it PC3-Control-Protocol-Cause: TS 32.299 clause "
            "7.2.135A and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3435,
            "ProSe-PC3-EPC-Control-Protocol-Cause",
            "PC3-EPC-Control-Protocol-Cause",
            "table 7.1 names code 3435 'ProSe-PC3-EPC-Control-Protocol-Cause'; the "
            "defining document names it PC3-EPC-Control-Protocol-Cause: TS 32.299 "
            "clause 7.2.135B and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1261,
            "PoC-Change-Conditions",
            "PoC-Change-Condition",
            "table 7.1 names code 1261 'PoC-Change-Conditions'; the defining document "
            "names it PoC-Change-Condition: TS 32.299 clause 7.2.139 and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            3446,
            "ProSe-Group-IP-Multicast-Addresses",
            "ProSe-Group-IP-Multicast-Address",
            "table 7.1 names code 3446 'ProSe-Group-IP-Multicast-Addresses'; the "
            "defining document names it ProSe-Group-IP-Multicast-Address: TS 32.299 "
            "clause 7.2.154H and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1301,
            "RAN-End-Time",
            "RAN-End-Timestamp",
            "table 7.1 names code 1301 'RAN-End-Time'; the defining document names it "
            "RAN-End-Timestamp: TS 32.299 clause 7.2.160Da; table 7.2.0.1's "
            "RAN-End-Time row, which table 7.1 copied, is corrected to the clause",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            1303,
            "RAN-Start-Time",
            "RAN-Start-Timestamp",
            "table 7.1 names code 1303 'RAN-Start-Time'; the defining document names "
            "it RAN-Start-Timestamp: TS 32.299 clause 7.2.160Dc; table 7.2.0.1's "
            "RAN-Start-Time row, which table 7.1 copied, is corrected to the clause",
        ),
        (
            ast.RegistryKind.AVP_CODES,
            2605,
            "Transcoder-Inserted-Indicator",
            "Transcoder-Inserted-Indication",
            "table 7.1 names code 2605 'Transcoder-Inserted-Indicator'; the defining "
            "document names it Transcoder-Inserted-Indication: TS 32.299 clause "
            "7.2.233A and table 7.2.0.1",
        ),
        (
            ast.RegistryKind.RESULT_CODES,
            5670,
            "DIAMETER_ERROR_UNKNKOWN_DATA",
            "DIAMETER_ERROR_UNKNOWN_DATA",
            "table 8.1.4 misspells 5670, whose defining clause, TS 29.283's 7.4.3.12, "
            "spells the word",
        ),
    )
]
