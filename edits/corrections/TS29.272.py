"""Corrections for 3GPP TS 29.272 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.ast import Codec
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Insert,
    Supply,
    avp_rule,
    definition,
    header,
    information_elements,
    reused_avps,
    reused_row,
    table_row,
    value_row,
    value_table,
)
from seanchai.dad.interpret import (
    Interpret,
    absent_if,
    bit,
    digits,
    element,
    encoding,
    equals,
    exclude,
    octets,
    present_if,
    range_of,
    reading,
    requires,
    text_only,
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
    *(
        Correction(
            id="elements-application-"
            + label.replace("/", "-").replace(".", "-").lower(),
            target=information_elements(label),
            field="application_id",
            expect=None,
            replace=application_id,
            reason=f"clause {label.split('/')[0]} is a procedure of clause"
            f" {interface}, {name}; clauses 7.2.9, 7.2.11 and 7.2.15 print"
            f" {command}-Request/Answer once for S6a/S6d (16777251) and once"
            " for S7a/S7d (16777308)",
            versions="19.6.0",
        )
        for interface, name, application_id in (
            ("5", "the MME and SGSN to HSS interfaces S6a and S6d", 16777251),
            ("5A", "the MME and SGSN to CSS interfaces S7a and S7d", 16777308),
        )
        for clause, command in (
            ("2.2.1.1", "Insert-Subscriber-Data"),
            ("2.2.2.1", "Delete-Subscriber-Data"),
            ("2.4.1.1" if interface == "5" else "2.3.1.1", "Reset"),
        )
        for label in (f"{interface}.{clause}/1", f"{interface}.{clause}/2")
    ),
]

# Interpreted constraints: what TS 29.272's clauses state in prose about an
# AVP's value or presence, read by hand and pinned to the sentences read
# (docs/constraints.md). In clause order: the AVP clauses of 7.3, then the
# conditions of the information-element tables' C rows in clauses 5, 5A and
# 6. A clause pointing at another document for a layout is an `element`; a
# rule depending on an earlier message, a feature, the node or the
# subscriber is `text_only`.
#
# TBCD-encoded E.164 numbers (clauses 7.3.39, 7.3.85, 7.3.91, 7.3.102,
# 7.3.157, 7.3.159) all print the same two sentences.
_NO_INDICATORS = (
    "This AVP shall not include leading indicators for the nature of address"
    " and the numbering plan; it shall contain only the TBCD-encoded digits of"
    " the address."
)
_MNC_FILLER = 'If MNC is 2 digits long, bits 5 to 8 of octet 2 are coded as "1111".'
_TS29002 = "Octets are coded according to TS 29.002 [24]."
_TS29002_DESCRIBED = "Octets are coded as described in TS 29.002 [24]."
_TS32422 = "Octets are coded according to TS 32.422 [23]."

CORRECTIONS += [
    Interpret(
        id="subscription-data-ambr-not-both-zero",
        avp="AMBR",
        within="Subscription-Data",
        section="7.3.2",
        page=98,
        readings=(
            reading(
                "Max-Requested-Bandwidth-UL and Max-Requested-Bandwidth-DL"
                ' within this AVP shall not both be set to "0".',
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="imei-digits",
        avp="IMEI",
        section="7.3.4",
        page=100,
        readings=(
            reading(
                "It should consist of 14 digits, including the 8-digit Type"
                " Allocation Code (TAC) and the 6-digit Serial Number (SNR). It"
                " may also include a 15th digit.",
                encoding(Codec.DIGITS),
                digits(14, 15),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="software-version-digits",
        avp="Software-Version",
        section="7.3.5",
        page=100,
        readings=(
            reading(
                "This AVP shall contain the 2-digit Software Version Number"
                " (SVN) of the International Mobile Equipment Identity, as"
                " specified in TS 23.003 [3].",
                encoding(Codec.DIGITS),
                digits(2),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="3gpp2-meid-element",
        avp="3GPP2-MEID",
        section="7.3.6",
        page=100,
        readings=(
            reading(
                "For further details on the encoding of the AVP data, refer to"
                " the encoding of the Mobile Identity (MEID) octets 3 to 10 in"
                " 3GPP2 A.S0022 [28] Annex A.",
                element("3GPP2-A.S0022", "A", "Mobile Identity (MEID)"),
                octets(8),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="visited-plmn-id-layout",
        avp="Visited-PLMN-Id",
        section="7.3.9",
        page=103,
        readings=(
            reading(
                (
                    "This AVP shall contain the concatenation of MCC and MNC.",
                    "The content of this AVP shall be encoded as an octet string"
                    " according to table 7.3.9-1.",
                    _MNC_FILLER,
                ),
                encoding(Codec.PLMN_ID),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="dsr-flags-exclusive-bits",
        avp="DSR-Flags",
        section="7.3.25",
        table="7.3.25/1",
        page=122,
        readings=(
            reading(
                "Note 4: Bits 3 and 6 are excluding alternatives and shall not"
                " both be set.",
                text_only(),
            ),
            reading(
                "Note 5: When this AVP is transferred over the S7a/S7d"
                " interface, only the bit 9 (CSG Deleted) is meaningful, other"
                " bits shall be cleared.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="access-restriction-data-bits",
        avp="Access-Restriction-Data",
        section="7.3.31",
        table="7.3.31/1",
        page=126,
        readings=(
            reading(
                "NOTE 2: Bits 11 and 12 are only used when bit 4 is not set.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-oi-replacement-labels",
        avp="APN-OI-Replacement",
        section="7.3.32",
        page=127,
        readings=(
            reading(
                "The contents of the APN-OI-Replacement AVP shall be formatted"
                " as a character string composed of one or more labels"
                ' separated by dots (".").',
                encoding(Codec.LABELS),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-profile-default-context",
        avp="Context-Identifier",
        within="APN-Configuration-Profile",
        section="7.3.34",
        page=128,
        readings=(
            reading(
                "The Context-Identifier AVP shall identify the per subscriber's"
                " default APN configuration.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-profile-additional-context",
        avp="Additional-Context-Identifier",
        within="APN-Configuration-Profile",
        section="7.3.34",
        page=128,
        readings=(
            reading(
                "If present, the Additional-Context-Identifier AVP shall"
                " identify another default APN configuration, only for those"
                " subscriptions containing more than one types of APNs",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-profile-third-context",
        avp="Third-Context-Identifier",
        within="APN-Configuration-Profile",
        section="7.3.34",
        page=128,
        readings=(
            reading(
                "If present, the Third-Context-Identifier AVP shall identify"
                " another default APN configuration, only for those"
                " subscriptions containing more than two types of APNs",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-context-identifier",
        avp="Context-Identifier",
        within="APN-Configuration",
        section="7.3.35",
        page=128,
        readings=(
            reading(
                "The Context-Identifier in the APN-Configuration AVP shall"
                " identify that APN configuration, and it shall not have a"
                " value of zero.",
                exclude(0),
            ),
            reading(
                "Furthermore, the Context-Identifier in the APN-Configuration"
                " AVP shall uniquely identify the EPS APN configuration per"
                " subscription.",
                text_only(),
            ),
            reading(
                "NOTE: If interworking with MAP is needed, the"
                " Context-Identifier will be in the range of 1 and 50.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-service-selection",
        avp="Service-Selection",
        within="APN-Configuration",
        section="7.3.35",
        page=128,
        readings=(
            reading(
                "For a particular EPS user having multiple APN configurations,"
                " the Service-Selection AVP values shall be unique across"
                " APN-Configuration AVPs.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-served-party-ip-address",
        avp="Served-Party-IP-Address",
        within="APN-Configuration",
        section="7.3.35",
        page=128,
        readings=(
            reading(
                "These AVPs shall be present if static IP address allocation is"
                " used for the UE",
                text_only(),
            ),
            reading(
                "For the IPv6 prefix, the lower 64 bits of the address shall be"
                " set to zero.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-pdn-gw-allocation-type",
        avp="PDN-GW-Allocation-Type",
        within="APN-Configuration",
        section="7.3.35",
        page=128,
        readings=(
            reading(
                "The PDN-GW-Allocation-Type AVP applies to the MIP6-Agent-Info"
                " AVP. Therefore, it shall not be present if MIP6-Agent-Info is"
                " not present.",
                requires("MIP6-Agent-Info"),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-non-ip-delivery",
        avp="Non-IP-Data-Delivery-Mechanism",
        within="APN-Configuration",
        section="7.3.35",
        page=128,
        readings=(
            reading(
                "The Non-IP-Data-Delivery-Mechanism shall only be present when"
                " Non-IP-PDN-Type-Indicator is set to TRUE (1).",
                requires(equals("Non-IP-PDN-Type-Indicator", "TRUE")),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"apn-configuration-{name.lower()}",
            avp=name,
            within="APN-Configuration",
            section="7.3.35",
            page=128,
            readings=(
                reading(
                    "The SCEF-ID AVP and the SCEF-Realm AVP shall only be present"
                    " when Non-IP-PDN-Type-Indicator is set to TRUE (1), and"
                    " Non-IP-Data-Delivery-Mechanism is set to"
                    " SCEF-BASED-DATA-DELIVERY (1).",
                    requires(equals("Non-IP-PDN-Type-Indicator", "TRUE")),
                    requires(equals("Non-IP-Data-Delivery-Mechanism", 1)),
                ),
            ),
            versions="19.6.0",
        )
        for name in ("SCEF-ID", "SCEF-Realm")
    ),
    Interpret(
        id="service-selection-apn",
        avp="Service-Selection",
        section="7.3.36",
        page=130,
        readings=(
            reading(
                "The contents of the Service-Selection AVP shall be formatted as"
                " a character string composed of one or more labels separated"
                ' by dots ("."), or as the wild card APN, i.e., consisting of'
                ' only one ASCII label, "*".',
                encoding(Codec.APN),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="eps-subscribed-qos-profile-non-gbr",
        avp="QoS-Class-Identifier",
        within="EPS-Subscribed-QoS-Profile",
        section="7.3.37",
        page=130,
        readings=(
            reading(
                "values QCI_1, QCI_2, QCI_3 and QCI_4, which are associated to"
                " GBR bearers, cannot be sent over S6a/S6d.",
                exclude(1, 2, 3, 4),
            ),
            reading(
                "The values allowed for this AVP over the S6a/S6d interface are"
                " only those associated to non-GBR bearers, as indicated in TS"
                " 23.008 [30]",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="stn-sr-e164",
        avp="STN-SR",
        section="7.3.39",
        page=131,
        readings=(
            reading(
                (
                    "This AVP contains an STN-SR, in international number format"
                    " as described in ITU-T Rec E.164 [41], encoded as a"
                    " TBCD-string.",
                    _NO_INDICATORS,
                ),
                encoding(Codec.E164_TBCD),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"allocation-retention-priority-{name.lower()}-default",
            avp=name,
            within="Allocation-Retention-Priority",
            section="7.3.40",
            page=131,
            readings=(
                reading(
                    f"If the {name} AVP is not present in the"
                    " Allocation-Retention-Priority AVP, the default value shall"
                    f" be {default}.",
                    text_only(),
                ),
            ),
            versions="19.6.0",
        )
        for name, default in (
            ("Pre-emption-Capability", "PRE-EMPTION_CAPABILITY_DISABLED (1)"),
            ("Pre-emption-Vulnerability", "PRE-EMPTION_VULNERABILITY_ENABLED (0)"),
        )
    ),
    *(
        Interpret(
            id=f"ambr-extended-max-requested-bw-{direction.lower()}",
            avp=f"Extended-Max-Requested-BW-{direction}",
            within="AMBR",
            section="7.3.41",
            page=131,
            readings=(
                reading(
                    (
                        "When the maximum bandwidth value to be set for UL (or"
                        " DL, respectively) traffic is lower than 4294967296"
                        " bits per second, the Max-Requested-Bandwidth-UL (or"
                        " -DL, respectively) AVP shall be present, and set to"
                        " the requested bandwidth value in bits per second, and"
                        " the Extended-Max-Requested-BW-UL (or -DL,"
                        " respectively) AVP shall be absent.",
                        "When the maximum bandwidth value to be set for UL (or"
                        " DL, respectively) traffic is higher than 4294967295"
                        " bits per second, the Max-Requested-Bandwidth-UL (or"
                        " DL, respectively) AVP shall be present, and set to its"
                        " upper limit 4294967295",
                    ),
                    requires(
                        equals(f"Max-Requested-Bandwidth-{direction}", 4294967295)
                    ),
                ),
            ),
            versions="19.6.0",
        )
        for direction in ("UL", "DL")
    ),
    Interpret(
        id="mip-home-agent-host-destination-host",
        avp="Destination-Host",
        within="MIP-Home-Agent-Host",
        section="7.3.43",
        page=132,
        readings=(
            reading(
                "Destination-Host shall contain the hostname of the PDN-GW,"
                " formatted as described in TS 29.303 [38], clause 4.3.2.",
                element("TS29.303", "4.3.2"),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="mip-home-agent-host-destination-realm",
        avp="Destination-Realm",
        within="MIP-Home-Agent-Host",
        section="7.3.43",
        page=132,
        readings=(
            reading(
                (
                    "Destination-Realm shall be formatted as:",
                    "epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org",
                ),
                encoding(Codec.EPC_PLMN_DOMAIN),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="mip6-agent-info-fqdn-preferred",
        avp="MIP-Home-Agent-Host",
        within="MIP6-Agent-Info",
        section="7.3.45",
        page=132,
        readings=(
            reading("FQDN shall be used if known to the MME/SGSN/HSS.", text_only()),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="mip6-agent-info-home-link-prefix",
        avp="MIP6-Home-Link-Prefix",
        within="MIP6-Agent-Info",
        section="7.3.45",
        page=132,
        readings=(
            reading(
                "The AVP MIP6-Home-Link-Prefix is not used in S6a/S6d, but it"
                " is included here to reflect the complete IETF definition of"
                " the grouped AVP.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="rat-frequency-selection-priority-id-range",
        avp="RAT-Frequency-Selection-Priority-ID",
        section="7.3.46",
        page=133,
        readings=(
            reading("Values shall be in the range of 1 to 256.", range_of(1, 256)),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="user-id-digits",
        avp="User-Id",
        section="7.3.50",
        page=134,
        readings=(
            reading(
                "It shall contain the leading digits of an IMSI (i.e. MCC, MNC,"
                " leading digits of MSIN, see TS 23.003 [3], clause 2.2)"
                " formatted as a character string.",
                encoding(Codec.DIGITS),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="regional-subscription-zone-code-element",
        avp="Regional-Subscription-Zone-Code",
        section="7.3.52",
        page=135,
        readings=(
            reading(
                "It shall contain a Zone Code (ZC) as defined in TS 23.003 [3],"
                " clause 4.4.",
                element("TS23.003", "4.4", "Zone Code"),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower().replace('_', '-')}-element",
            avp=avp,
            section=section,
            page=135,
            readings=(
                reading(
                    f"This AVP shall contain the {name}. See {cited}.",
                    element(document, name=name),
                ),
            ),
            versions="19.6.0",
        )
        for avp, section, name, cited, document in (
            ("RAND", "7.3.53", "RAND", "TS 33.401 [5]", "TS33.401"),
            ("XRES", "7.3.54", "XRES", "TS 33.401 [5]", "TS33.401"),
            ("AUTN", "7.3.55", "AUTN", "TS 33.401 [5]", "TS33.401"),
            ("KASME", "7.3.56", "K_ASME", "TS 33.401 [5]", "TS33.401"),
            ("SRES", "7.3.60", "SRES", "TS 33.102 [18]", "TS33.102"),
        )
    ),
    Interpret(
        id="trace-reference-layout",
        avp="Trace-Reference",
        section="7.3.64",
        page=136,
        readings=(
            reading(
                (
                    "This AVP shall contain the concatenation of MCC, MNC and"
                    " Trace ID, where the Trace ID is a 3 byte Octet String.",
                    "The content of this AVP shall be encoded as octet strings"
                    " according to table 7.3.64/1.",
                    _MNC_FILLER,
                ),
                encoding(Codec.PLMN_ID_PREFIX),
                octets(6),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-element",
            avp=avp,
            section=section,
            page=137,
            readings=(reading(_TS32422, element("TS32.422")),),
            versions="19.6.0",
        )
        for avp, section in (
            ("Trace-NE-Type-List", "7.3.68"),
            ("Trace-Interface-List", "7.3.69"),
            ("Trace-Event-List", "7.3.70"),
        )
    ),
    Interpret(
        id="omc-id-element",
        avp="OMC-Id",
        section="7.3.71",
        page=137,
        readings=(reading(_TS29002, element("TS29.002")),),
        versions="19.6.0",
    ),
    Interpret(
        id="pdp-context-ext-pdp-address",
        avp="Ext-PDP-Address",
        within="PDP-Context",
        section="7.3.74",
        page=138,
        readings=(
            reading(
                "The Ext-PDP-Address AVP may be present only if the PDP-Address"
                " AVP is present.",
                requires("PDP-Address"),
            ),
            reading(
                "If the Ext-PDP-Address AVP is present, then it shall not"
                " contain the same address type (IPv4 or IPv6) as the"
                " PDP-Address AVP.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    # PDP-Type's value is a TS 29.002 PDP-Type, whose octets the clauses do
    # not spell out (7.3.75), so a condition on it stays text.
    Interpret(
        id="pdp-context-ext-pdp-type",
        avp="Ext-PDP-Type",
        within="PDP-Context",
        section="7.3.74",
        page=138,
        readings=(
            reading(
                "When PDP-Type takes the value Non-IP (HEX 02), the"
                " Ext-PDP-Type AVP shall be absent.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="pdp-context-non-ip-delivery",
        avp="Non-IP-Data-Delivery-Mechanism",
        within="PDP-Context",
        section="7.3.74",
        page=138,
        readings=(
            reading(
                "The Non-IP-Data-Delivery-Mechanism shall only be present when"
                " PDP-Type takes the value Non-IP (HEX 02).",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="pdp-context-scef-id",
        avp="SCEF-ID",
        within="PDP-Context",
        section="7.3.74",
        page=138,
        readings=(
            reading(
                "The SCEF-ID shall only be present when"
                " Non-IP-Data-Delivery-Mechanism takes the value"
                " SCEF-BASED-DATA-DELIVERY (1).",
                requires(equals("Non-IP-Data-Delivery-Mechanism", 1)),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="pdp-type-element",
        avp="PDP-Type",
        section="7.3.75",
        page=139,
        readings=(
            reading(_TS29002, element("TS29.002")),
            reading(
                "The allowed values are one of IPv4 encoded as HEX (21) or IPv6"
                " encoded as HEX (57) or Non-IP encoded as HEX (02).",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ext-pdp-type-value",
        avp="Ext-PDP-Type",
        section="7.3.75A",
        page=139,
        readings=(
            reading(
                "Octets are coded according to TS 29.002 [24] and TS 29.060"
                " [39] and shall contain the value of IPv4v6.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="qos-subscribed-element",
        avp="QoS-Subscribed",
        section="7.3.77",
        page=139,
        readings=(
            reading(
                "Octets are coded according to TS 29.002 [24] (octets of"
                " QoS-Subscribed, Ext-QoS-Subscribed, Ext2-QoS-Subscribed,"
                " Ext3-QoS-Subscribed and Ext4-QoS-Subscribed values are"
                " concatenated).",
                element("TS29.002"),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="csg-id-element",
        avp="CSG-Id",
        section="7.3.79",
        page=139,
        readings=(
            reading(
                "Values are coded according to TS 23.003 [3].", element("TS23.003")
            ),
            reading(
                "Unused bits (least significant) shall be padded with zeros.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-specific-apn-info",
        avp="Specific-APN-Info",
        within="APN-Configuration",
        section="7.3.82",
        page=140,
        readings=(
            reading(
                "It shall only be present in the APN configuration when the APN"
                " is a wild card APN.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="gmlc-number-e164",
        avp="GMLC-Number",
        section="7.3.85",
        page=140,
        readings=(
            reading(
                (
                    "This AVP shall contain the ISDN number of the GMLC in"
                    " international number format as described in ITU-T Rec"
                    " E.164 [41] and shall be encoded as a TBCD-string.",
                    _NO_INDICATORS,
                ),
                encoding(Codec.E164_TBCD),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-element",
            avp=avp,
            section=section,
            page=page,
            readings=(reading(_TS29002, element("TS29.002")),),
            versions="19.6.0",
        )
        for avp, section, page in (
            ("SS-Code", "7.3.87", 141),
            ("SS-Status", "7.3.88", 141),
            ("TS-Code", "7.3.100", 143),
        )
    ),
    Interpret(
        id="client-identity-e164",
        avp="Client-Identity",
        section="7.3.91",
        page=141,
        readings=(
            reading(
                (
                    "The Client-Identity AVP is of type OctetString and it shall"
                    " contain the ISDN number of the external client in"
                    " international number format as described in ITU-T Rec"
                    " E.164 [41] and shall be encoded as a TBCD-string.",
                    _NO_INDICATORS,
                ),
                encoding(Codec.E164_TBCD),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="servicetypeidentity-element",
        avp="ServiceTypeIdentity",
        section="7.3.95",
        page=142,
        readings=(
            reading(
                "For details on the values of this AVP, see TS 29.002 [24].",
                element("TS29.002"),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="trace-collection-entity-ip",
        avp="Trace-Collection-Entity",
        section="7.3.98",
        page=143,
        readings=(
            reading(
                "The Trace-Collection-Entity AVP is of type Address and contains"
                " the IPv4 or IPv6 address of the Trace Collection Entity, as"
                " defined in TS 32.422 [23], clause 5.9.",
                encoding(Codec.IP_ADDRESS),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="sgsn-number-e164",
        avp="SGSN-Number",
        section="7.3.102",
        page=143,
        readings=(
            reading(
                (
                    "This AVP contains an SGSN-Number in international number"
                    " format as described in ITU-T Rec E.164 [41] and shall be"
                    " encoded as a TBCD-string.",
                    _NO_INDICATORS,
                ),
                encoding(Codec.E164_TBCD),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="visited-network-identifier-domain",
        avp="Visited-Network-Identifier",
        section="7.3.105",
        page=144,
        readings=(
            reading(
                ("The AVP shall be encoded as:", "mnc<MNC>.mcc<MCC>.3gppnetwork.org"),
                encoding(Codec.PLMN_DOMAIN),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="gmlc-address-ip",
        avp="GMLC-Address",
        section="7.3.109",
        page=145,
        readings=(
            reading(
                "The GMLC-Address AVP is of type Address and shall contain the"
                " IPv4 or IPv6 address of the V-GMLC associated with the serving"
                " node.",
                encoding(Codec.IP_ADDRESS),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="user-state-reserved",
        avp="User-State",
        section="7.3.114",
        page=146,
        readings=(
            reading(
                "This value should not be used by MME or SGSN over S6a/S6d.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-element",
            avp=avp,
            section=section,
            page=page,
            readings=(reading(quote, element("TS29.002")),),
            versions="19.6.0",
        )
        for avp, section, page, quote in (
            ("E-UTRAN-Cell-Global-Identity", "7.3.117", 148, _TS29002_DESCRIBED),
            ("Tracking-Area-Identity", "7.3.118", 148, _TS29002_DESCRIBED),
            ("Cell-Global-Identity", "7.3.119", 148, _TS29002_DESCRIBED),
            ("Routing-Area-Identity", "7.3.120", 148, _TS29002_DESCRIBED),
            ("Location-Area-Identity", "7.3.121", 148, _TS29002_DESCRIBED),
            ("Service-Area-Identity", "7.3.122", 148, _TS29002_DESCRIBED),
            (
                "Geographical-Information",
                "7.3.123",
                148,
                "For details and octet encoding, see TS 29.002 [24].",
            ),
            (
                "Geodetic-Information",
                "7.3.124",
                148,
                "For details and octet encoding, see TS 29.002 [24].",
            ),
            ("NR-Cell-Global-Identity", "7.3.251", 179, _TS29002_DESCRIBED),
        )
    ),
    Interpret(
        id="error-diagnostic-values",
        avp="Error-Diagnostic",
        section="7.3.128",
        page=149,
        readings=(
            reading(
                (
                    "This value shall be used when Experimental-Error is"
                    " DIAMETER_ERROR_UNKNOWN_EPS_SUBSCRIPTION and there is GPRS"
                    " Subscription Data for the user.",
                    "This value shall be used when Experimental-Error is"
                    " DIAMETER_ERROR_ROAMING_NOT_ALLOWED and the Operator"
                    ' Determined Barring indicates "All Packet Oriented'
                    ' Services Barred" (see clause 7.3.30).',
                ),
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-element",
            avp=avp,
            section=section,
            page=152,
            readings=(
                reading(
                    (
                        "The meaning of the bits is defined in TS 32.422 [23].",
                        "The most significant bit is bit 8 of the first octet.",
                    ),
                    element("TS32.422"),
                ),
            ),
            versions="19.6.0",
        )
        for avp, section in (
            ("List-Of-Measurements", "7.3.139"),
            ("Reporting-Trigger", "7.3.140"),
        )
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-element",
            avp=avp,
            section=section,
            page=page,
            readings=(
                reading("See TS 32.422 [23] for allowed values", element("TS32.422")),
            ),
            versions="19.6.0",
        )
        for avp, section, page in (
            ("Event-Threshold-RSRP", "7.3.143", 152),
            ("Event-Threshold-RSRQ", "7.3.144", 152),
            ("Event-Threshold-Event-1F", "7.3.172", 158),
            ("Event-Threshold-Event-1I", "7.3.173", 158),
            ("Event-Threshold-SINR", "7.3.246", 178),
        )
    ),
    Interpret(
        id="relay-node-indicator-default",
        avp="Relay-Node-Indicator",
        section="7.3.147",
        page=153,
        readings=(
            reading(
                "The default value when this AVP is not present is NOT_RELAY_NODE (0).",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="mdt-user-consent-absence",
        avp="MDT-User-Consent",
        section="7.3.148",
        page=153,
        readings=(
            reading(
                (
                    "The default value when this AVP is not present in ULA is"
                    " CONSENT_NOT_GIVEN (0).",
                    "Absence of this AVP in IDR shall be interpreted as the"
                    " MDT-User-Consent has not been modified.",
                ),
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="subscribed-vsrvcc-absence",
        avp="Subscribed-VSRVCC",
        section="7.3.150",
        page=153,
        readings=(
            reading(
                (
                    "Absence of this AVP in IDR shall be interpreted as the"
                    " Subscribed-VSRVCC has not been modified.",
                    "Absence of this AVP in ULA shall be interpreted as the user"
                    " is not subscribed to the vSRVCC.",
                ),
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="a-msisdn-e164",
        avp="A-MSISDN",
        section="7.3.157",
        page=155,
        readings=(
            reading(
                (
                    "This AVP contains an A-MSISDN, in international number"
                    " format as described in ITU-T Rec E.164 [41], encoded as a"
                    " TBCD-string.",
                    _NO_INDICATORS,
                ),
                encoding(Codec.E164_TBCD),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="mme-number-for-mt-sms-e164",
        avp="MME-Number-for-MT-SMS",
        section="7.3.159",
        page=156,
        readings=(
            reading(
                (
                    "This AVP contains an international number with the format"
                    " as described in ITU-T Rec E.164 [41] and shall be encoded"
                    " as a TBCD-string.",
                    _NO_INDICATORS,
                ),
                encoding(Codec.E164_TBCD),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="sms-register-request-skip-subscriber-data",
        avp="SMS-Register-Request",
        section="7.3.162",
        page=156,
        readings=(
            reading(
                "When the MME/SGSN includes the SMS-Register-Request AVP in ULR"
                " in order to modify its registration status for SMS, the"
                ' MME/SGSN shall not set the "Skip Subscriber Data" flag within'
                " the ULR-Flags AVP.",
                text_only(),
            ),
            reading(
                "Absence of this AVP in the Update Location Request message"
                " shall be interpreted as if the MME or SGSN does not request to"
                " HSS any change in its registration status for SMS.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="time-zone-format",
        avp="Time-Zone",
        section="7.3.163",
        page=156,
        readings=(
            reading(
                (
                    "The contents of the Time-Zone AVP shall be formatted as a"
                    " character string with the following format:",
                    'Basic format: ±n, with "n" being the number of units of 15'
                    " minutes from UTC.",
                ),
                encoding(Codec.TIME_ZONE),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-octet",
            avp=avp,
            section=section,
            page=158,
            readings=(
                reading(
                    "It contains one octet carrying a bit map of 8 bits.",
                    octets(1),
                ),
                reading(
                    "The possible values are those defined in TS 32.422 [23] for"
                    f" {name}.",
                    element("TS32.422", name=name),
                ),
            ),
            versions="19.6.0",
        )
        for avp, section, name in (
            ("Positioning-Method", "7.3.170", "Positioning Method"),
            ("Measurement-Quantity", "7.3.171", "Measurement quantity"),
        )
    ),
    Interpret(
        id="restoration-priority-range",
        avp="Restoration-Priority",
        section="7.3.174",
        page=158,
        readings=(
            reading(
                "Values 1 to 16 are defined, with value 1 as the highest level"
                " of priority.",
                range_of(1, 16),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="sgs-mme-identity-element",
        avp="SGs-MME-Identity",
        section="7.3.175",
        page=158,
        readings=(
            reading(
                "This AVP shall contain the MME identity used over the SGs"
                " interface and specified in TS 23.003 [3] clause 19.4.2.4.",
                element("TS23.003", "19.4.2.4", "MME identity"),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="coupled-node-diameter-id-element",
        avp="Coupled-Node-Diameter-ID",
        section="7.3.177",
        page=158,
        readings=(
            reading(
                "This AVP shall contain the S6a or S6d Diameter identity of the"
                " coupled node as specified in TS 23.003 [3] clause 19.4.2.4 and"
                " clause 19.4.2.6.",
                element("TS23.003"),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-layout",
            avp=avp,
            section=section,
            page=page,
            readings=(
                reading(
                    (
                        "This AVP shall contain the concatenation of MCC and MNC.",
                        "The content of this AVP shall be encoded as an octet"
                        f" string according to table {table}.",
                        _MNC_FILLER,
                    ),
                    encoding(Codec.PLMN_ID),
                ),
            ),
            versions="19.6.0",
        )
        for avp, section, page, table in (
            ("MDT-Allowed-PLMN-Id", "7.3.185", 160, "7.3.185/1"),
            ("Group-PLMN-Id", "7.3.191", 161, "7.3.191-1"),
        )
    ),
    Interpret(
        id="dl-buffering-suggested-packet-count-range",
        avp="DL-Buffering-Suggested-Packet-Count",
        section="7.3.188",
        page=161,
        readings=(
            reading(
                (
                    '"Extended DL Data Buffering NOT REQUESTED" 0',
                    '"Extended DL Data Buffering REQUESTED, without a suggested'
                    ' number of packets" -1',
                    '"Extended DL Data Buffering REQUESTED, with a suggested'
                    ' number of packets" > 0',
                ),
                range_of(-1, None),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="group-service-id-operator-range",
        avp="Group-Service-Id",
        section="7.3.190",
        page=161,
        readings=(
            reading(
                "IMSI-Group-IDs with a Group-Service-Id in this range shall not"
                " be sent outside the HPLMN unless roaming agreements allow so.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="aese-communication-pattern-reference-ids",
        avp="AESE-Communication-Pattern",
        section="7.3.193",
        page=162,
        readings=(
            reading(
                "At least one reference ID (either in SCEF-Reference-ID or in"
                " SCEF-Reference-ID-Ext) or a reference ID for deletion (either"
                " in SCEF-Reference-ID-for-Deletion or in"
                " SCEF-Reference-ID-for-Deletion-Ext) shall be present.",
                text_only(),
            ),
            reading(
                'When the "Extended Reference IDs" feature is supported and used'
                " by the HSS and supported by the MME/SGSN, the"
                " SCEF-Reference-ID-Ext and SCEF-Reference-ID-for-Deletion-Ext"
                " AVPs shall be used instead of SCEF-Reference-ID and"
                " SCEF-Reference-ID-for-Deletion respectively.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="monitoring-event-configuration-extended-ids",
        avp="Monitoring-Event-Configuration",
        section="7.3.195",
        page=163,
        readings=(
            reading(
                'When the "Extended Reference IDs" feature is supported and used'
                " by the HSS and supported by the MME/SGSN, the"
                " SCEF-Reference-ID-Ext and SCEF-Reference-ID-for-Deletion-Ext"
                " AVPs shall be used instead of SCEF-Reference-ID and"
                " SCEF-Reference-ID-for-Deletion respectively.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="monitoring-event-configuration-scef-realm",
        avp="SCEF-Realm",
        within="Monitoring-Event-Configuration",
        section="7.3.195",
        page=163,
        readings=(
            reading(
                "When the Monitoring-Event-Configuration AVP is used over the"
                " S6a/S6d interfaces, the SCEF-Realm AVP shall be present",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="monitoring-event-configuration-monitoring-type",
        avp="Monitoring-Type",
        within="Monitoring-Event-Configuration",
        section="7.3.195",
        page=163,
        readings=(
            reading(
                "Monitoring-Type AVP shall be ignored for deletion of an event"
                " (i.e. when SCEF-Reference-ID-for-Deletion/"
                "SCEF-Reference-ID-for-Deletion-Ext AVP is present).",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="monitoring-event-configuration-maximum-number-of-reports",
        avp="Maximum-Number-of-Reports",
        within="Monitoring-Event-Configuration",
        section="7.3.195",
        page=163,
        readings=(
            reading(
                "Maximum-Number-of-Reports shall not be present over S6a/S6d"
                " interfaces if Monitoring-Type is AVAILABILITY_AFTER_DDN_FAILURE"
                " (6).",
                absent_if(equals("Monitoring-Type", 6)),
            ),
            reading(
                "Maximum-Number-of-Reports shall not be greater than one over"
                " S6a/S6d interfaces if Monitoring-Type is LOCATION_REPORTING (2)"
                " and MONTE-Location-Type is LAST_KNOWN_LOCATION (1).",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="monitoring-event-report-reachability-information",
        avp="Reachability-Information",
        within="Monitoring-Event-Report",
        section="7.3.196",
        page=164,
        readings=(
            reading(
                "For S6a/S6d interface, when the Monitoring-Type AVP takes the"
                " value UE_REACHABILITY (1), the Reachability-Information AVP"
                " shall take the value REACHABLE_FOR_DATA (1)",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="monitoring-event-report-pdn-connectivity",
        avp="PDN-Connectivity-Status-Report",
        within="Monitoring-Event-Report",
        section="7.3.196",
        page=164,
        readings=(
            reading(
                "each PDN-Connectivity-Status-Report shall have the"
                ' PDN-Connectivity-Status-Type set to value "CREATED (0)".',
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="monitoring-event-report-scef-reference-id",
        avp="SCEF-Reference-ID",
        within="Monitoring-Event-Report",
        section="7.3.196",
        page=164,
        readings=(
            reading(
                'When the "Extended Reference IDs" feature is supported and used'
                " by the HSS and supported by the MME/SGSN, the"
                " SCEF-Reference-ID-Ext AVP shall be used instead of"
                " SCEF-Reference-ID; in such case, the required AVP"
                ' "SCEF-Reference-ID" shall be included in the grouped AVP by'
                " the sender, but its content shall be discarded by the"
                " receiver.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ue-reachability-configuration-reachability-type",
        avp="Reachability-Type",
        within="UE-Reachability-Configuration",
        section="7.3.197",
        page=165,
        readings=(
            reading(
                "For S6a/S6d interface, the Reachability-Type AVP shall have bit"
                ' 0 ("Reachability for SMS") cleared, and it shall have bit 1'
                ' ("Reachability for Data") set.',
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ue-usage-type-range",
        avp="UE-Usage-Type",
        section="7.3.202",
        page=166,
        readings=(
            reading(
                "The allowed values of UE-Usage-Type shall be in the range of 0"
                " to 255.",
                range_of(0, 255),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-default",
            avp=avp,
            section=section,
            page=page,
            readings=(
                reading(
                    f"The default value when this AVP is not present is {default}.",
                    text_only(),
                ),
            ),
            versions="19.6.0",
        )
        for avp, section, page, default in (
            ("Non-IP-PDN-Type-Indicator", "7.3.204", 167, "FALSE (0)"),
            (
                "Non-IP-Data-Delivery-Mechanism",
                "7.3.205",
                167,
                "SGi-BASED-DATA-DELIVERY (0)",
            ),
            ("RDS-Indicator", "7.3.222", 170, "DISABLED (0)"),
            ("Interworking-5GS-Indicator", "7.3.231", 175, "NOT-SUBSCRIBED (0)"),
            ("Ethernet-PDN-Type-Indicator", "7.3.232", 175, "FALSE (0)"),
        )
    ),
    Interpret(
        id="preferred-data-mode-bits",
        avp="Preferred-Data-Mode",
        section="7.3.209",
        table="7.3.209/1",
        page=168,
        readings=(
            reading(
                "NOTE 2: At least one of the bits 0 and 1 shall be set to 1.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-octet",
            avp=avp,
            section=section,
            page=page,
            readings=(
                reading(
                    f"The contents of {avp} shall consist of 1 octet.",
                    octets(1),
                ),
                reading(
                    "The encoding shall be as defined in TS 24.008 [31], clause"
                    " 10.5.5.32, and it shall only contain the value of the field"
                    f' "{field}"',
                    element("TS24.008", "10.5.5.32", "Extended DRX parameter"),
                ),
                reading(
                    f"the 4 {zeroed} significant bits of the octet in this AVP"
                    " shall be set to 0.",
                    text_only(),
                ),
            ),
            versions="19.6.0",
        )
        for avp, section, page, field, zeroed in (
            ("eDRX-Cycle-Length-Value", "7.3.216", 169, "eDRX value", "most"),
            (
                "Paging-Time-Window-Length",
                "7.3.228",
                175,
                "Paging Time Window length",
                "least",
            ),
        )
    ),
    *(
        Interpret(
            id=f"{avp.lower()}-range",
            avp=avp,
            section=section,
            page=page,
            readings=(reading(quote, range_of(0, high)),),
            versions="19.6.0",
        )
        for avp, section, page, high, quote in (
            (
                "MBSFN-Area-ID",
                "7.3.220",
                170,
                255,
                "it shall contain the MBSFN Area ID value, in the range of"
                " 0..255 (see TS 36.331 [62]).",
            ),
            (
                "Carrier-Frequency",
                "7.3.221",
                170,
                262143,
                "it shall contain the Carrier Frequency value, in the range of"
                " 0..262143 (see TS 36.331 [62]).",
            ),
            (
                "Operation-Mode",
                "7.3.227",
                174,
                255,
                "The allowed values of Operation-Mode shall be in the range of 0"
                " to 255.",
            ),
        )
    ),
    Interpret(
        id="5qi-element",
        avp="5QI",
        section="7.3.238",
        page=177,
        readings=(
            reading(
                "See TS 23.501 [69] for allowed values.",
                element("TS23.501", name="5QI"),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="collection-period-m7-nr-element",
        avp="Collection-Period-M7-NR",
        section="7.3.249",
        page=178,
        readings=(
            reading(
                "The possible values are those defined in TS 32.422 [23] for"
                " Collection period M7 in NR in units of minutes.",
                element("TS32.422", name="Collection period M7 in NR"),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="plmn-rat-usage-control-restricted",
        avp="PLMN-RAT-Usage-Control",
        section="7.3.253",
        table="7.3.253/1",
        page=179,
        readings=(
            reading(
                "RAT restricted by the Access-Restriction-Data AVP shall not be"
                " set as restricted in PLMN-RAT-Usage-Control AVP.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
]

# The conditions of the C rows of the information-element tables, scoped to
# the command each table describes. A row only available on its node's say
# ("if available") states no rule.
_S6A = 16777251


CORRECTIONS += [
    Interpret(
        id="ula-ula-flags",
        avp="ULA-Flags",
        command="Update-Location-Answer",
        section="5.2.1.1.1",
        table="5.2.1.1.1/2",
        page=18,
        readings=(
            reading(
                "It shall be present only when the Result-Code AVP is"
                " DIAMETER_SUCCESS.",
                requires(equals("Result-Code", "DIAMETER_SUCCESS")),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ula-subscription-data",
        avp="Subscription-Data",
        command="Update-Location-Answer",
        section="5.2.1.1.1",
        table="5.2.1.1.1/2",
        page=18,
        readings=(
            reading(
                "It shall be present if success is reported, unless an explicit"
                ' "skip subscriber data" indication was present in the request.',
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ulr-sgsn-number",
        avp="SGSN-Number",
        command="Update-Location-Request",
        section="5.2.1.1.1",
        table="5.2.1.1.1/1",
        page=18,
        readings=(
            reading(
                "It shall be present when the message is sent on the S6d interface"
                " and the SGSN supports LCS (using MAP based Lg interface) or SMS"
                " functionalities or the Gs interface.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ulr-ue-srvcc-capability",
        avp="UE-SRVCC-Capability",
        command="Update-Location-Request",
        section="5.2.1.1.1",
        table="5.2.1.1.1/1",
        page=18,
        readings=(
            reading(
                "shall be present if the MME or the SGSN supports SRVCC and this"
                " information is available to the MME or the SGSN.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ulr-mme-number-for-mt-sms",
        avp="MME-Number-for-MT-SMS",
        command="Update-Location-Request",
        section="5.2.1.1.1",
        table="5.2.1.1.1/1",
        page=18,
        readings=(
            reading(
                "It shall be present when the MME supports SMS in MME and wishes to"
                " provide SMS in MME.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ulr-sms-register-request",
        avp="SMS-Register-Request",
        command="Update-Location-Request",
        section="5.2.1.1.1",
        table="5.2.1.1.1/1",
        page=18,
        readings=(
            reading(
                (
                    "It shall be present when the MME supports SMS in MME and requests"
                    " to be registered for SMS.",
                    'It shall be present when the SGSN supports "SMS in SGSN" as'
                    " defined in clause 5.3.18 in 23.060 [12], and requests to be"
                    " registered for SMS.",
                ),
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="pua-pua-flags",
        avp="PUA-Flags",
        command="Purge-UE-Answer",
        section="5.2.1.3.1",
        table="5.2.1.3.1/2",
        page=33,
        readings=(
            reading(
                "It shall be present only when the Result-Code AVP is"
                " DIAMETER_SUCCESS.",
                requires(equals("Result-Code", "DIAMETER_SUCCESS")),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-ims-voice-over-ps-sessions-supported",
        avp="IMS-Voice-Over-PS-Sessions-Supported",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "If the UE is in detached state, this information element shall not"
                " be included in the response.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-last-ue-activity-time",
        avp="Last-UE-Activity-Time",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "If the UE is in detached state, this information element shall not"
                " be included in the response.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-rat-type",
        avp="RAT-Type",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "If the UE is in detached state, this information element shall not"
                " be included in the response.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-eps-user-state",
        avp="EPS-User-State",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "It shall be present if EPS user state was requested within IDR.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-eps-location-information",
        avp="EPS-Location-Information",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "It shall be present if EPS location information was requested"
                " within IDR.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-local-time-zone",
        avp="Local-Time-Zone",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "It shall be present if the Local Time Zone was requested within IDR.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-monitoring-event-report",
        avp="Monitoring-Event-Report",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "It shall be present if Monitoring event configuration is included"
                " within IDR and any of the requested Monitoring events are"
                " available to be reported.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="ida-monitoring-event-config-status",
        avp="Monitoring-Event-Config-Status",
        command="Insert-Subscriber-Data-Answer",
        application_id=_S6A,
        section="5.2.2.1.1",
        table="5.2.2.1.1/2",
        page=35,
        readings=(
            reading(
                "This Information Element shall be present if Monitoring event"
                " configuration is included in IDR.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="dsr-trace-reference",
        avp="Trace-Reference",
        command="Delete-Subscriber-Data-Request",
        application_id=_S6A,
        section="5.2.2.2.1",
        table="5.2.2.2.1/1",
        page=43,
        readings=(
            reading(
                'This element shall be present only if the "Trace Data Withdrawal"'
                " bit is set in the DSR-Flags.",
                requires(bit("DSR-Flags", "Trace Data Withdrawal")),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="dsr-context-identifier",
        avp="Context-Identifier",
        command="Delete-Subscriber-Data-Request",
        application_id=_S6A,
        section="5.2.2.2.1",
        table="5.2.2.2.1/1",
        page=43,
        readings=(
            reading(
                'This element shall be present only if the "PDN subscription'
                ' contexts Withdrawal" bit or the "PDP context withdrawal" bit is'
                " set in the DSR-Flags.",
                requires(
                    bit("DSR-Flags", "PDN subscription contexts Withdrawal"),
                    bit("DSR-Flags", "PDP contexts Withdrawal"),
                ),
            ),
            reading(
                'In the "PDN subscription contexts Withdrawal" case, the'
                " Context-Identifier shall not be associated with the default APN"
                " configuration.",
                text_only(),
            ),
            reading(
                "For the compatibility with the MAP protocol as defined in the TS"
                " 29.002 [24], this parameter shall not have a value of zero.",
                exclude(0),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="dsr-ts-code",
        avp="TS-Code",
        command="Delete-Subscriber-Data-Request",
        application_id=_S6A,
        section="5.2.2.2.1",
        table="5.2.2.2.1/1",
        page=43,
        readings=(
            reading(
                'This element shall be present only if the "SMS Withdrawal" bit is'
                " set in the DSR-Flags and the SMS related teleservice codes are to"
                " be deleted.",
                requires(bit("DSR-Flags", "SMS Withdrawal")),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="dsr-ss-code",
        avp="SS-Code",
        command="Delete-Subscriber-Data-Request",
        application_id=_S6A,
        section="5.2.2.2.1",
        table="5.2.2.2.1/1",
        page=43,
        readings=(
            reading(
                'This element shall be present only if the "SMS Withdrawal" bit is'
                ' set or the "LCS Withdrawal" bit is set in the DSR-Flags.',
                requires(
                    bit("DSR-Flags", "SMS Withdrawal"),
                    bit("DSR-Flags", "LCS Withdrawal"),
                ),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="dsr-scef-id",
        avp="SCEF-ID",
        command="Delete-Subscriber-Data-Request",
        application_id=_S6A,
        section="5.2.2.2.1",
        table="5.2.2.2.1/1",
        page=43,
        readings=(
            reading(
                'This element shall be present if the "Delete monitoring events"'
                " bit is set in the DSR-Flags.",
                present_if(bit("DSR-Flags", "Delete monitoring events")),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="dsr-edrx-related-rat",
        avp="eDRX-Related-RAT",
        command="Delete-Subscriber-Data-Request",
        application_id=_S6A,
        section="5.2.2.2.1",
        table="5.2.2.2.1/1",
        page=43,
        readings=(
            reading(
                "This element shall be present only if the"
                ' "eDRX-Cycle-Length-Withdrawal" bit is set in the DSR-Flags and'
                " the corresponding eDRX Cycle Lengths are to be deleted.",
                requires(bit("DSR-Flags", "eDRX-Cycle-Length-Withdrawal")),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="aia-ue-usage-type",
        avp="UE-Usage-Type",
        command="Authentication-Information-Answer",
        section="5.2.3.1.1",
        table="5.2.3.1.1/2",
        page=47,
        readings=(
            reading(
                "This IE shall be present if the HSS supports the Dedicated Core"
                ' Networks feature, and the "Send UE Usage Type" flag was set in'
                " the AIR-Flags AVP in the AIR command, and this information is"
                " available in the user subscription.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-terminal-information",
        avp="Terminal-Information",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "Within this Information Element, only the IMEI and the"
                " Software-Version AVPs shall be used on the S6a/S6d interface.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-mip6-agent-info",
        avp="MIP6-Agent-Info",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "It shall be present if a new PDN-GW has been selected and the"
                " subscriber is allowed handover to non 3GPP access or 5GS"
                " interworking without N26 interface enabled.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-visited-network-identifier",
        avp="Visited-Network-Identifier",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "It shall be present when the PDN GW Identity is present and does"
                " not contain an FQDN.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-service-selection",
        avp="Service-Selection",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "For establishment of non-emergency PDN connections, it shall be"
                " present if the selected PDN-GW is present and is particular for"
                " one specific APN and not common to all the APNs.",
                text_only(),
            ),
            reading(
                "For establishment of emergency PDN connections (i.e., the"
                " Emergency-Services AVP is present, with the Emergency-Indication"
                " flag set), this AVP shall be left absent.",
                absent_if(bit("Emergency-Services", "Emergency-Indication")),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-alert-reason",
        avp="Alert-Reason",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "It shall be present when notifying the HSS about the presence of"
                " the UE or the UE has memory capacity available to receive one or"
                " more short messages.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-ue-srvcc-capability",
        avp="UE-SRVCC-Capability",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "If the MME/SGSN supports SRVCC and the UE SRVCC Capability has"
                " changed, the MME or SGSN shall include the new UE SRVCC"
                " Capability in the request.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-nor-flags",
        avp="NOR-Flags",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "Absence of this information element shall be interpreted as all"
                " bits set to 0.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-homogeneous-support",
        avp="Homogeneous-Support-of-IMS-Voice-Over-PS-Sessions",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "This Information Element shall be present if Homogeneous Support"
                " of IMS Voice Over PS Sessions is modified to one of the values"
                ' "SUPPORTED" or "NOT_SUPPORTED".',
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-monitoring-event-config-status",
        avp="Monitoring-Event-Config-Status",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "This information element shall be present if the MME/SGSN sends"
                " the Notify Request after receiving the"
                " Configuration-Information-Answer from the IWK-SCEF.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="nor-emergency-services",
        avp="Emergency-Services",
        command="Notify-Request",
        section="5.2.5.1.1",
        table="5.2.5.1.1/1",
        page=54,
        readings=(
            reading(
                "The MME shall include this information element, and set the"
                " Emergency-Indication flag, to notify the HSS that a new PDN-GW"
                " has been selected for the establishment of an emergency PDN"
                " connection",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="uvr-sgsn-number",
        avp="SGSN-Number",
        command="Update-VCSG-Location-Request",
        section="5A.2.1.1.1",
        table="5A.2.1.1.1/1",
        page=61,
        readings=(
            reading(
                "It shall be present when the message is sent on the S7d interface.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="uva-vplmn-csg-subscription-data",
        avp="VPLMN-CSG-Subscription-Data",
        command="Update-VCSG-Location-Answer",
        section="5A.2.1.1.1",
        table="5A.2.1.1.1/2",
        page=61,
        readings=(
            reading(
                "It shall be present if success is reported, unless an explicit"
                ' "skip subscriber data" indication was present in the request or'
                " the Temporary Empty VPLMN CSG Subscription Data flag is set.",
                text_only(),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="eca-equipment-status",
        avp="Equipment-Status",
        command="ME-Identity-Check-Answer",
        section="6.2.1.1",
        table="6.2.1.1/2",
        page=69,
        readings=(
            reading(
                "It shall be present if the result of the ME Identity Check is"
                " DIAMETER_SUCCESS.",
                present_if(equals("Result-Code", "DIAMETER_SUCCESS")),
            ),
        ),
        versions="19.6.0",
    ),
]
