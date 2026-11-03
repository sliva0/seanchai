"""Corrections for 3GPP TS 29.272 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Insert,
    Supply,
    avp_rule,
    definition,
    header,
    reused_avps,
    reused_row,
    table_row,
    value_row,
    value_table,
)

# The VCSG command headers print "< Diameter Header: 8388638, REQ, PXY, >" with
# the application id left empty. Clause 7.2.2 assigns these command codes to
# table 7.2.2/3 and states that "the Application-ID field shall be set to
# 16777308 (application identifier of the S7a/S7d interface application)", so
# the value is not in doubt; the headers stay as printed.
CORRECTIONS = [
    Insert(
        id="application-id-vcsg",
        into=header(),
        node=ast.ApplicationScope(
            name="S7a/S7d",
            source=ast.SourceRef(section="7.2.2", page=73),
            application_id=16777308,
            applies_to=("7.2.21.*", "7.2.22.*", "7.2.23.*", "7.2.24.*"),
        ),
        after=None,
        reason=(
            "clause 7.2.2: for the VCSG commands of table 7.2.2/3 'the"
            " Application-ID field shall be set to 16777308 (application"
            " identifier of the S7a/S7d interface application, allocated by"
            " IANA)'; their headers in clauses 7.2.21-7.2.24 print no id"
        ),
        versions="18.7.0..19.6.0",
    ),
]

CORRECTIONS += [
    Correction(
        id="area-scope-code",
        target=definition("Area-Scope"),
        field="code",
        expect=1623,
        replace=1624,
        reason="clause 7.3.138's AVP header prints Job-Type's code; table"
        " 7.3.1/1 and the TS 29.230 registry both assign Area-Scope 1624",
        versions="18.6.0..19.6.0",
    ),
    Correction(
        id="wlan-offloadability-vendor-id",
        target=definition("WLAN-offloadability"),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason="clause 7.3.181's AVP header omits the vendor-id; table 7.3.1/1"
        " marks the V flag mandatory for it, as for every other AVP the"
        " specification defines",
        versions="18.6.0..19.6.0",
    ),
    # Two AVPs the ABNF appears to reference without the document introducing
    # them turned out to be spelling mismatches against table 7.3.1/1 — the
    # references resolve once one side is spelled the way the defining clause
    # heading spells it.
    Correction(
        id="additional-context-identifier-name",
        target=table_row("Additional-Context-ID"),
        field="name",
        expect="Additional-Context-ID",
        replace="Additional-Context-Identifier",
        reason="clause 7.3.206's heading and body, and the ABNF reference in"
        " clause 7.3.34, all spell it Additional-Context-Identifier; only the"
        " table row abbreviates it",
        versions="18.6.0..19.6.0",
    ),
    Correction(
        id="re-synchronization-info-case",
        target=avp_rule(
            "Requested-EUTRAN-Authentication-Info", "Re-synchronization-Info"
        ),
        field="name",
        expect="Re-synchronization-Info",
        replace="Re-Synchronization-Info",
        reason="clause 7.3.15's heading and table 7.3.1/1 both spell it"
        " Re-Synchronization-Info; clause 7.3.11's ABNF lower-cases the S",
        versions="18.6.0..19.6.0",
    ),
    Correction(
        id="re-synchronization-info-utran-geran-case",
        target=avp_rule(
            "Requested-UTRAN-GERAN-Authentication-Info", "Re-synchronization-Info"
        ),
        field="name",
        expect="Re-synchronization-Info",
        replace="Re-Synchronization-Info",
        reason="clause 7.3.15's heading and table 7.3.1/1 both spell it"
        " Re-Synchronization-Info; clause 7.3.12's ABNF lower-cases the S",
        versions="18.7.0..19.6.0",
    ),
    # Three re-printed grouped bodies use member AVPs that table 7.3.1/2
    # omits while listing the grouped AVPs themselves and, for
    # Communication-Pattern-Set, three of its eight members
    # (Reference-ID-Validity-Time, Traffic-Profile, Battery-Indicator).
    *(
        Insert(
            id=f"missing-row-{name.lower()}",
            into=reused_avps("7.3.1/2"),
            node=ast.ReusedAvpRow(name=name, origin=origin),
            after=after,
            reason=f"the {parent} body (clause {clause}) uses {name} but"
            f" table 7.3.1/2 omits the row; {origin} defines the AVP",
            versions="18.6.0..19.6.0",
        )
        for name, origin, after, parent, clause in (
            (
                "MIP6-Home-Link-Prefix",
                "RFC5447",
                "MIP6-Agent-Info",
                "MIP6-Agent-Info",
                "7.3.45",
            ),
            (
                "ProSe-Permission",
                "TS29.344",
                "ProSe-Subscription-Data",
                "ProSe-Subscription-Data",
                "7.3.180",
            ),
            (
                "Periodic-Communication-Indicator",
                "TS29.336",
                "Communication-Pattern-Set",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Communication-Duration-Time",
                "TS29.336",
                "Periodic-Communication-Indicator",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Periodic-Time",
                "TS29.336",
                "Communication-Duration-Time",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Scheduled-Communication-Time",
                "TS29.336",
                "Periodic-Time",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Stationary-Indication",
                "TS29.336",
                "Scheduled-Communication-Time",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
        )
    ),
]

# TS 29.217, which defines both AVPs, spells them eNodeB-Id and
# Extended-eNodeB-Id in its table 5.3.1.1, the defining clauses and its
# Congestion-Location-Id body; this document's re-used table and the
# MME-Location-Information body (clause 7.3.115) capitalise the D.
CORRECTIONS += [
    correction
    for printed, name, clause in (
        ("eNodeB-ID", "eNodeB-Id", "5.3.10"),
        ("Extended-eNodeB-ID", "Extended-eNodeB-Id", "5.3.15"),
    )
    for correction in (
        Correction(
            id=f"{name.lower()}-row-spelling",
            target=reused_row(printed),
            field="name",
            expect=printed,
            replace=name,
            reason=f"the re-used row cites TS 29.217, which defines {name}"
            f" (clause {clause})",
            versions="18.7.0..19.6.0",
        ),
        Correction(
            id=f"{name.lower()}-in-mme-location-information",
            target=avp_rule("MME-Location-Information", printed),
            field="name",
            expect=printed,
            replace=name,
            reason="the MME-Location-Information body (clause 7.3.115) uses the"
            f" re-used row's spelling; TS 29.217 defines {name}",
            versions="18.7.0..19.6.0",
        ),
    )
]

# Findings the linter reports that the document makes on purpose; they
# change no data (docs/corrections.md).
CORRECTIONS += [
    Accept(
        id="monitoring-event-configuration-s6a-body",
        rule="reused-body-differs",
        target=definition("Monitoring-Event-Configuration"),
        expect="Monitoring-Event-Configuration's body, against TS29.336's definition: "
        "adds External-Identifier, SCEF-Realm, missing Association-Type, "
        "DL-Buffering-Suggested-Packet-Count, Exclude-Identifiers, "
        "Include-Identifiers, Maximum-Detection-Time, PLMN-ID-Requested",
        reason="clause 7.3.195: 'It is originally defined in TS 29.336 [54]. For "
        "S6a/S6d interface, the Monitoring-Event-Configuration AVP format is specified "
        "as following'",
        versions="18.7.0..19.6.0",
    ),
    Accept(
        id="monitoring-event-report-s6a-body",
        rule="reused-body-differs",
        target=definition("Monitoring-Event-Report"),
        expect="Monitoring-Event-Report's body, against TS29.336's definition: missing "
        "Event-Handling, IMEI-Change, Roaming-Information, "
        "SCEF-Reference-ID-for-Deletion, SCEF-Reference-ID-for-Deletion-Ext, "
        "Service-Report, Terminal-Information, Visited-PLMN-Id",
        reason="clause 7.3.196: 'It is originally defined in TS 29.336 [54]. For "
        "S6a/S6d interface, the Monitoring-Event-Report AVP format is specified as "
        "following'",
        versions="18.7.0..19.6.0",
    ),
    Accept(
        id="ue-reachability-configuration-s6a-body",
        rule="reused-body-differs",
        target=definition("UE-Reachability-Configuration"),
        expect="UE-Reachability-Configuration's body, against TS29.336's definition: "
        "missing DL-Buffering-Suggested-Packet-Count, Maximum-Latency",
        reason="clause 7.3.197: 'It is originally defined in TS 29.336 [54]. For "
        "S6a/S6d interface, the UE-Reachability-Configuration AVP format is specified "
        "as following'",
        versions="18.7.0..19.6.0",
    ),
]

# Trace and MDT parameters whose values the clauses take from TS 32.422
# ("those defined in TS 32.422 [23] for ..."), which numbers each value in
# parentheses; a None is a code the list skips. Reference [23] is
# non-specific, so Release 19's latest version answers, V19.7.0 (2026-06);
# the version matters, because Release
# 16 renumbered codes incompatibly: Report Interval LTE went from 15-27 to
# 0-12, Measurement Period UMTS from 0-14 (250 to 64000 ms) to 0-12 (1000 to
# 64000 ms). Report-Interval (clause 7.3.141) stays a citation: clause
# 5.10.5 numbers UMTS, LTE and NR intervals from 0 each, so one flat list
# would give 0 to 11 three meanings.
_TS32422 = "TS 32.422 V19.7.0 (2026-06), Release 19's latest,"
_TRACE_PARAMETERS = (
    (
        "Trace-Depth",
        "7.3.67",
        "Trace Depth",
        "5.3",
        (
            "Minimum",
            "Medium",
            "Maximum",
            "MinimumWithoutVendorSpecificExtension",
            "MediumWithoutVendorSpecificExtension",
            "MaximumWithoutVendorSpecificExtension",
            "MinimumOnlyVendorSpecificTraceRecord",
            "MediumOnlyVendorSpecificTraceRecord",
            "MaximumOnlyVendorSpecificTraceRecord",
        ),
        ", Release 19 adding the last three",
    ),
    (
        "Job-Type",
        "7.3.137",
        "Job-Type",
        "5.9a",
        (
            "IMMEDIATE_MDT_ONLY",
            "LOGGED_MDT_ONLY",
            "TRACE_ONLY",
            "IMMEDIATE_MDT_AND_TRACE",
            "RLF_REPORT_ONLY",
            "RCEF_REPORT_ONLY",
            "LOGGED_MBSFN_MDT",
            "5GC_UE_LEVEL_MEASUREMENTS_ONLY",
            "TRACE_AND_5GC_UE_LEVEL_MEASUREMENTS",
            "IMMEDIATE_MDT_AND_5GC_UE_LEVEL_MEASUREMENTS",
            "TRACE_AND_IMMEDIATE_MDT_AND_5GC_UE_LEVEL_MEASUREMENTS",
            "RRC_REPORT",
            "IMMEDIATE_MDT_AND_LOGGED_MDT",
        ),
        ", Release 19 adding the last two; its NOTEs 1 to 5 restrict where some"
        " apply, not the list, and it spaces the last name after AND_, which its"
        " other names do not",
    ),
    (
        "Report-Amount",
        "7.3.142",
        "Report Amount",
        "5.10.6.2",
        ("1", "2", "4", "8", "16", "32", "64", "infinity"),
        "; clauses 5.10.6.3 to 5.10.6.12 repeat the list per RAT and"
        " measurement, NR's spelling INFINITY",
    ),
    (
        "Logging-Interval",
        "7.3.145",
        "Logging Interval",
        "5.10.8",
        (
            "1280 ms",
            "2560 ms",
            "5120 ms",
            "10240 ms",
            "20480 ms",
            "30720 ms",
            "40960 ms",
            "61440 ms",
            "320 ms",
            "640 ms",
            "Infinity",
        ),
        "; UMTS and LTE take 0 to 7, NR the same plus 8 to 10, so the list is NR's",
    ),
    (
        "Logging-Duration",
        "7.3.146",
        "Logging Duration",
        "5.10.9",
        ("600 sec", "1200 sec", "2400 sec", "3600 sec", "5400 sec", "7200 sec"),
        "",
    ),
    (
        "Measurement-Period-LTE",
        "7.3.166",
        "Measurement period LTE",
        "5.10.23",
        ("1024 ms", None, "2048 ms", None, "5120 ms", "10240 ms", "1 min"),
        "; 1 and 3 are unassigned, Release 16 having dropped 1280 ms and 2560 ms",
    ),
    (
        "Measurement-Period-UMTS",
        "7.3.167",
        "Measurement period UMTS",
        "5.10.22",
        (
            "1000 ms",
            "2000 ms",
            "3000 ms",
            "4000 ms",
            "6000 ms",
            "8000 ms",
            "12000 ms",
            "16000 ms",
            "20000 ms",
            "24000 ms",
            "28000 ms",
            "32000 ms",
            "64000 ms",
        ),
        "",
    ),
    (
        "Collection-Period-RRM-LTE",
        "7.3.168",
        "Collection period for RRM measurements LTE",
        "5.10.20",
        (
            "100 ms",
            "1000 ms",
            "1024 ms",
            "1280 ms",
            "2048 ms",
            "2560 ms",
            "5120 ms",
            "10000 ms",
            "10240 ms",
            "1 min",
        ),
        "",
    ),
    (
        "Collection-Period-RRM-UMTS",
        "7.3.169",
        "Collection period for RRM measurements UMTS",
        "5.10.21",
        (
            "100ms",
            "250 ms",
            "500 ms",
            "1000 ms",
            "2000 ms",
            "3000 ms",
            "4000 ms",
            "6000 ms",
        ),
        "; '100ms' is spelled as printed",
    ),
    (
        "Collection-Period-RRM-NR",
        "7.3.247",
        "Collection period for RRM measurements NR",
        "5.10.30",
        ("1024 ms", "2048 ms", "5120 ms", "10240 ms", "60000 ms"),
        "",
    ),
    (
        "Collection-Period-M6-NR",
        "7.3.248",
        "Collection period M6 in NR",
        "5.10.34",
        (
            "120 ms",
            "240 ms",
            "480 ms",
            "640 ms",
            "1024 ms",
            "2048 ms",
            "5120 ms",
            "10240 ms",
            "20480 ms",
            "40960 ms",
            "1 min",
            "6 min",
            "12 min",
            "30 min",
        ),
        "",
    ),
)

CORRECTIONS += [
    Supply(
        id=f"{avp.lower()}-values",
        target=definition(avp),
        expect=f"TS 32.422 [23] for {parameter}",
        values=tuple(
            ast.EnumValue(name=name, value=value)
            for value, name in enumerate(names)
            if name is not None
        ),
        reason=f"clause {clause} takes the values 'defined in TS 32.422 [23]"
        f" for {parameter}'; {_TS32422} clause {cited} lists them with their"
        f" codes{remark}. The version matters: Release 16 renumbered Report"
        " Interval LTE's and Measurement Period UMTS's codes",
        versions="19.6.0",
    )
    for avp, clause, parameter, cited, names, remark in _TRACE_PARAMETERS
]

CORRECTIONS += [
    Correction(
        id="odb-all-international-og-feature-spelling",
        target=value_row(
            value_table("Feature-List", feature_list_id=1), "ODB-all- InternationalOG"
        ),
        field="name",
        expect="ODB-all- InternationalOG",
        replace="ODB-all-InternationalOG",
        reason="the cell prints a space after the hyphen, where the column wraps the "
        "name; the feature's name has no space (clause 7.3.10.1, table 7.3.10/1, "
        "feature bit 4)",
        versions="18.7.0..19.6.0",
    ),
    Correction(
        id="lcs-basic-self-location-feature-spelling",
        target=value_row(
            value_table("Feature-List", feature_list_id=1), "LCS- BasicSelfLocation"
        ),
        field="name",
        expect="LCS- BasicSelfLocation",
        replace="LCS-BasicSelfLocation",
        reason="the cell prints a space after the hyphen, where the column wraps the "
        "name; the feature's name has no space (clause 7.3.10.1, table 7.3.10/1, "
        "feature bit 18)",
        versions="18.7.0..19.6.0",
    ),
    Correction(
        id="lcs-autonomous-self-location-feature-spelling",
        target=value_row(
            value_table("Feature-List", feature_list_id=1),
            "LCS- AutonomousSelfLocation",
        ),
        field="name",
        expect="LCS- AutonomousSelfLocation",
        replace="LCS-AutonomousSelfLocation",
        reason="the cell prints a space after the hyphen, where the column wraps the "
        "name; the feature's name has no space (clause 7.3.10.1, table 7.3.10/1, "
        "feature bit 19)",
        versions="18.7.0..19.6.0",
    ),
    Correction(
        id="lcs-transfer-to-third-party-feature-spelling",
        target=value_row(
            value_table("Feature-List", feature_list_id=1), "LCS- TransferToThirdParty"
        ),
        field="name",
        expect="LCS- TransferToThirdParty",
        replace="LCS-TransferToThirdParty",
        reason="the cell prints a space after the hyphen, where the column wraps the "
        "name; the feature's name has no space (clause 7.3.10.1, table 7.3.10/1, "
        "feature bit 20)",
        versions="18.7.0..19.6.0",
    ),
    Correction(
        id="dia-lcs-basic-self-location-feature-spelling",
        target=value_row(
            value_table("Feature-List", feature_list_id=2), "Dia-LCS- BasicSelfLocation"
        ),
        field="name",
        expect="Dia-LCS- BasicSelfLocation",
        replace="Dia-LCS-BasicSelfLocation",
        reason="the cell prints a space after the hyphen, where the column wraps the "
        "name; the feature's name has no space (clause 7.3.10.1, table 7.3.10/2, "
        "feature bit 9)",
        versions="18.7.0..19.6.0",
    ),
    Correction(
        id="dia-lcs-autonomous-self-location-feature-spelling",
        target=value_row(
            value_table("Feature-List", feature_list_id=2),
            "Dia-LCS- AutonomousSelfLocation",
        ),
        field="name",
        expect="Dia-LCS- AutonomousSelfLocation",
        replace="Dia-LCS-AutonomousSelfLocation",
        reason="the cell prints a space after the hyphen, where the column wraps the "
        "name; the feature's name has no space (clause 7.3.10.1, table 7.3.10/2, "
        "feature bit 10)",
        versions="18.7.0..19.6.0",
    ),
    Correction(
        id="dia-lcs-transfer-to-third-party-feature-spelling",
        target=value_row(
            value_table("Feature-List", feature_list_id=2),
            "Dia-LCS- TransferToThirdParty",
        ),
        field="name",
        expect="Dia-LCS- TransferToThirdParty",
        replace="Dia-LCS-TransferToThirdParty",
        reason="the cell prints a space after the hyphen, where the column wraps the "
        "name; the feature's name has no space (clause 7.3.10.1, table 7.3.10/2, "
        "feature bit 11)",
        versions="18.7.0..19.6.0",
    ),
    Correction(
        id="edrx-cycle-length-withdrawal-spelling",
        target=value_row("DSR-Flags", "eDRX-Cycle-Length -Withdrawal"),
        field="name",
        expect="eDRX-Cycle-Length -Withdrawal",
        replace="eDRX-Cycle-Length-Withdrawal",
        reason="table 7.3.25/1 bit 30 prints a space before the hyphen, where the "
        "column wraps the name, unlike the bit's every other Withdrawal",
        versions="18.7.0..19.6.0",
    ),
]
