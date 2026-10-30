"""Corrections for 3GPP TS 32.299 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Delete,
    Insert,
    Supply,
    avp_rule,
    definition,
    flag_rules,
    header,
    reused_avps,
    reused_row,
    table_row,
)

# Table 7.1.0.1 ("Use Of IETF Diameter AVPs") tabulates the IETF AVPs the
# charging applications use with codes, types and flags, but names no origin
# per row; clause 7.1.0 says they "can be found from RFC 6733 [401], RFC 4006
# [402] and RFC 4005 [407]". Each name is assigned to the one of those RFCs
# whose own AVP table defines it. The OC-* rows belong to none of the three:
# clause 2 cites RFC 7683 [411], Diameter Overload Indication Conveyance,
# which defines them.
_IETF_ORIGINS = {
    "RFC6733": (
        "Accounting-Realtime-Required",
        "Accounting-Record-Number",
        "Accounting-Record-Type",
        "Accounting-Sub-Session-Id",
        "Acct-Application-Id",
        "Acct-Interim-Interval",
        "Acct-Multi-Session-Id",
        "Acct-Session-Id",
        "Auth-Application-Id",
        "Destination-Host",
        "Destination-Realm",
        "Error-Message",
        "Error-Reporting-Host",
        "Event-Timestamp",
        "Experimental-Result",
        "Experimental-Result-Code",
        "Failed-AVP",
        "Origin-Host",
        "Origin-Realm",
        "Origin-State-Id",
        "Proxy-Info",
        "Proxy-Host",
        "Proxy-State",
        "Redirect-Host",
        "Redirect-Host-Usage",
        "Redirect-Max-Cache-Time",
        "Result-Code",
        "Route-Record",
        "Session-Id",
        "Termination-Cause",
        "User-Name",
        "Vendor-Id",
        "Vendor-Specific-Application-Id",
    ),
    "RFC4006": (
        "CC-Correlation-Id",
        "CC-Input-Octets",
        "CC-Money",
        "CC-Output-Octets",
        "CC-Request-Number",
        "CC-Request-Type",
        "CC-Service-Specific-Units",
        "CC-Session-Failover",
        "CC-Sub-Session-Id",
        "CC-Time",
        "CC-Total-Octets",
        "CC-Unit-Type",
        "Check-Balance-Result",
        "Cost-Information",
        "Cost-Unit",
        "Credit-Control",
        "Credit-Control-Failure-Handling",
        "Currency-Code",
        "Direct-Debiting-Failure-Handling",
        "Exponent",
        "Final-Unit-Action",
        "Final-Unit-Indication",
        "Granted-Service-Unit",
        "G-S-U-Pool-Identifier",
        "G-S-U-Pool-Reference",
        "Multiple-Services-Credit-Control",
        "Multiple-Services-Indicator",
        "Rating-Group",
        "Redirect-Address-Type",
        "Redirect-Server",
        "Redirect-Server-Address",
        "Requested-Action",
        "Requested-Service-Unit",
        "Restriction-Filter-Rule",
        "Service-Context-Id",
        "Service-Identifier",
        "Service-Parameter-Info",
        "Service-Parameter-Type",
        "Service-Parameter-Value",
        "Subscription-Id",
        "Subscription-Id-Data",
        "Subscription-Id-Type",
        "Tariff-Change-Usage",
        "Tariff-Time-Change",
        "Unit-Value",
        "Used-Service-Unit",
        "User-Equipment-Info",
        "User-Equipment-Info-Type",
        "User-Equipment-Info-Value",
        "Value-Digits",
        "Validity-Time",
    ),
    # Also tabulated by RFC 7155, which obsoletes RFC 4005; the document
    # cites RFC 4005 [407].
    "RFC4005": (
        "Accounting-Input-Octets",
        "Accounting-Output-Octets",
        "Called-Station-Id",
        "Filter-Id",
    ),
    "RFC7683": (
        "OC-Feature-Vector",
        "OC-OLR",
        "OC-Reduction-Percentage",
        "OC-Report-Type",
        "OC-Sequence-Number",
        "OC-Supported-Features",
        "OC-Validity-Duration",
    ),
}
_IETF_REASONS = {
    "RFC6733": "table 7.1.0.1 lists IETF AVPs without per-row origins; clause"
    " 7.1.0 points at RFC 6733 [401], whose AVP table defines this one",
    "RFC4006": "table 7.1.0.1 lists IETF AVPs without per-row origins; clause"
    " 7.1.0 points at RFC 4006 [402], whose AVP table defines this one",
    "RFC4005": "table 7.1.0.1 lists IETF AVPs without per-row origins; clause"
    " 7.1.0 points at RFC 4005 [407], whose AVP table defines this one",
    "RFC7683": "table 7.1.0.1 lists IETF AVPs without per-row origins; clause 2"
    " cites RFC 7683 [411], which defines the OC-* AVPs",
}

# Clause 7.2.0: "The 3GPP Charging Application uses the value 10415 (3GPP) as
# Vendor-Id." Every grouped header in clause 7.2 and annex B prints only the
# code ("< AVP Header: 4401 >"), while table 7.2.0.1 sets the V flag.
_VENDORLESS_3GPP_GROUPED = (
    "Access-Network-Info-Change",
    "Access-Transfer-Information",
    "Accumulated-Cost",
    "Additional-Content-Information",
    "Address-Domain",
    "AF-Correlation-Information",
    "Announcement-Information",
    "AoC-Cost-Information",
    "AoC-Information",
    "AoC-Service",
    "AoC-Subscription-Information",
    "APN-Rate-Control",
    "APN-Rate-Control-Downlink",
    "APN-Rate-Control-Uplink",
    "Application-Server-Information",
    "Basic-Service-Code",
    "Called-Identity-Change",
    "Coverage-Info",
    "CPDT-Information",
    "Current-Tariff",
    "Destination-Interface",
    "Early-Media-Description",
    "Enhanced-Diagnostics",
    "Envelope",
    "Event-Type",
    "Exposure-Function-API-Information",
    "Incremental-Cost",
    "IMS-Information",
    "Inter-Operator-Identifier",
    "ISUP-Cause",
    "LCS-Client-ID",
    "LCS-Client-Name",
    "LCS-Information",
    "LCS-Requestor-ID",
    "Location-Info",
    "Location-Type",
    "MBMS-Information",
    "Message-Body",
    "Message-Class",
    "MM-Content-Type",
    "MMS-Information",
    "MMTel-Information",
    "Monitoring-Event-Information",
    "Monitoring-Event-Report-Data",
    "Next-Tariff",
    "NNI-Information",
    "NIDD-Submission",
    "Offline-Charging",
    "Originator-Address",
    "Originator-Interface",
    "Originator-Received-Address",
    "Participant-Group",
    "PoC-Information",
    "PoC-User-Role",
    "ProSe-Direct-Communication-Reception-Data-Container",
    "ProSe-Direct-Communication-Transmission-Data-Container",
    "ProSe-Information",
    "PS-Furnish-Charging-Information",
    "PS-Information",
    "Radio-Parameter-Set-Info",
    "RAN-Secondary-RAT-Usage-Report",
    "Rate-Element",
    "Real-Time-Tariff-Information",
    "Recipient-Address",
    "Recipient-Info",
    "Recipient-Received-Address",
    "Related-Change-Condition-Information",
    "Related-Trigger",
    "Remaining-Balance",
    "Scale-Factor",
    "SCS-AS-Address",
    "SDP-Media-Component",
    "SDP-TimeStamps",
    "Service-Data-Container",
    "Service-Information",
    "Service-Specific-Info",
    "SM-Device-Trigger-Information",
    "SMS-Information",
    "Supplementary-Service",
    "Talk-Burst-Exchange",
    "Tariff-Information",
    "Time-Quota-Mechanism",
    "Time-Stamps",
    "Traffic-Data-Volumes",
    "Transmitter-Info",
    "Trigger",
    "Trunk-Group-ID",
    "TWAN-User-Location-Info",
    "Unit-Cost",
    "User-CSG-Information",
    "VCS-Information",
    "VoLTE-Information",
    "Variable-Part",
    "UWAN-User-Location-Info",
    "WLAN-Operator-Id",
    "PSCell-Info",
    "3GPP-OC-Specific-Reduction",
)

# Body members spelled differently from the clause that defines them in this
# document (or, for Redirect-Max-Cache-Time, in RFC 6733 and table 7.1.0.1).
_MEMBER_SPELLINGS = (
    ("Traffic-Data-Volumes", "Change-condition", "Change-Condition", "7.2.37"),
    (
        "ProSe-Direct-Communication-Transmission-Data-Container",
        "Coverage-status",
        "Coverage-Status",
        "7.2.46aA",
    ),
    ("CPDT-Information", "NIDD-submission", "NIDD-Submission", "7.2.112aA"),
    ("PoC-User-Role", "PoC-User-Role-Ids", "PoC-User-Role-IDs", "7.2.150"),
    (
        "ProSe-Information",
        "Prose-Function-PLMN-Identifier",
        "ProSe-Function-PLMN-Identifier",
        "7.2.154F",
    ),
    ("PS-Information", "ePDG-Address", "EPDG-Address", "7.2.62A"),
    ("IMS-Information", "Service-Id", "Service-ID", "7.2.190"),
)

# Table 7.2.0.1 rows spelled differently from the clause defining the AVP.
_ROW_SPELLINGS = (
    ("RAN-End-Time", "RAN-End-Timestamp", "7.2.160Da"),
    ("RAN-Start-Time", "RAN-Start-Timestamp", "7.2.160Dc"),
    ("Service-Id", "Service-ID", "7.2.190"),
)

CORRECTIONS = [
    Correction(
        id="bases-dcca-nasreq",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4006", "RFC4005"),
        reason="clause 7.1.0 names RFC 6733 [401], RFC 4006 [402] and RFC 4005"
        " [407] as where the IETF AVPs it uses are defined",
        versions="18.0.0",
    ),
    Delete(
        id="wildcard-row",
        target=table_row("AVP", table="7.1.0.1"),
        expect=ast.AvpTableRow(
            name="AVP",
            code=None,
            data_type=ast.DataType.GROUPED,
            flag_rules=ast.AvpFlagRules(),
            # "-" under all four commands, which clause 7.1.0 reads as unused.
            marks={ast.MarkColumn(each): () for each in ("ACR", "ACA", "CCR", "CCA")},
        ),
        reason="table 7.1.0.1 tabulates the '* [ AVP ]' wildcard with code '*';"
        " it is ABNF grammar, not an AVP",
        versions="18.0.0",
    ),
    *(
        Insert(
            id=f"ietf-origin-{name.lower()}",
            into=reused_avps("7.1.0.1"),
            node=ast.ReusedAvpRow(name=name, origin=origin),
            after=None,
            reason=_IETF_REASONS[origin],
            versions="18.0.0",
        )
        for origin, names in _IETF_ORIGINS.items()
        for name in names
    ),
    *(
        Correction(
            id=f"vendor-{name.lower()}",
            target=definition(name),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason="clause 7.2.0 gives the 3GPP charging AVPs vendor 10415; the"
            " grouped header prints only the code",
            versions="18.0.0",
        )
        for name in _VENDORLESS_3GPP_GROUPED
    ),
    *(
        Correction(
            id=f"member-{wrong.lower()}",
            target=avp_rule(parent, wrong),
            field="name",
            expect=wrong,
            replace=right,
            reason=f"clause {clause} defines {right}; the body of {parent}"
            f" spells it {wrong}",
            versions="18.0.0",
        )
        for parent, wrong, right, clause in _MEMBER_SPELLINGS
    ),
    Correction(
        id="raa-redirect-max-cache-time",
        target=avp_rule("Re-Auth-Answer", "Redirect-Host-Cache-Time"),
        field="name",
        expect="Redirect-Host-Cache-Time",
        replace="Redirect-Max-Cache-Time",
        reason="RFC 6733 and table 7.1.0.1 name the AVP Redirect-Max-Cache-Time;"
        " no document defines Redirect-Host-Cache-Time",
        versions="18.0.0",
    ),
    *(
        Correction(
            id=f"row-{wrong.lower()}",
            target=table_row(wrong, table="7.2.0.1"),
            field="name",
            expect=wrong,
            replace=right,
            reason=f"clause {clause} defines {right}; table 7.2.0.1 spells it {wrong}",
            versions="18.0.0",
        )
        for wrong, right, clause in _ROW_SPELLINGS
    ),
    Correction(
        id="row-application-port-identifier",
        target=table_row("Application-Port-Identifer", table="7.2.0.1"),
        field="name",
        expect="Application-Port-Identifer",
        replace="Application-Port-Identifier",
        reason="table 7.2.0.1 drops an 'i' from the TS 29.337 AVP it refers to;"
        " clauses 7.2.205B and 7.2.211 spell it Application-Port-Identifier",
        versions="18.0.0",
    ),
    Correction(
        id="reused-application-port-identifier",
        target=reused_row("Application-Port-Identifer"),
        field="name",
        expect="Application-Port-Identifer",
        replace="Application-Port-Identifier",
        reason="the re-used row comes from the same misspelt table 7.2.0.1 row",
        versions="18.0.0",
    ),
    Correction(
        id="application-port-identifier-origin",
        target=reused_row("Application-Port-Identifer"),
        field="origin",
        expect="TS29.337",
        replace="TS29.368",
        reason="table 7.2.0.1 refers to [231], TS 29.337, which does not define"
        " Application-Port-Identifier; TS 29.368 does, and TS 29.336 re-uses it"
        " from there",
        versions="18.0.0",
    ),
    *(
        Correction(
            id=f"type-{name.lower()}",
            target=table_row(name, table="7.2.0.1"),
            field="data_type",
            expect=ast.DataType.INTEGER32,
            replace=ast.DataType.ENUMERATED,
            reason=f"clause {clause} defines {name} as Enumerated with a value"
            " list; table 7.2.0.1 types it Integer32, the same encoding",
            versions="18.0.0",
        )
        for name, clause in (
            ("Monitoring-Event-Configuration-Activity", "7.2.111AaA"),
            ("Monitoring-Event-Functionality", "7.2.111AaB"),
        )
    ),
]

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id-rf",
        into=header(),
        node=ast.ApplicationScope(
            name="Rf",
            source=ast.SourceRef(section="7.1.5", page=97),
            application_id=3,
            applies_to=("6.2.*",),
        ),
        after=None,
        reason=(
            "clause 7.1.5: 'The Acct-Application-Id AVP (AVP code 259) shall "
            "contain the value of 3 as defined in RFC 6733'; the offline "
            "charging ACR/ACA of clause 6.2 use the Diameter Base Protocol "
            "Accounting application (6.2.1.1), and their headers print no id"
        ),
        versions="18.0.0",
    ),
    Insert(
        id="application-id-ro",
        into=header(),
        node=ast.ApplicationScope(
            name="Ro",
            source=ast.SourceRef(section="7.1.6", page=97),
            application_id=4,
            applies_to=("6.4.*",),
        ),
        after=None,
        reason=(
            "clause 7.1.6: 'The Auth-Application-Id AVP (AVP code 258) shall "
            "contain the value of 4 as defined in RFC 4006'; the online "
            "charging commands of clause 6.4 use the Diameter Credit-Control "
            "Application (6.3.2.1), and their headers print no id"
        ),
        versions="18.0.0",
    ),
]

# Table 7.1.0.1 rows contradicting the RFC that defines them, as the table's
# own notes say it does (NOTE 2: "Experimental-Result AVP is defined in
# Diameter Base Protocol in RFC 6733 [401]").
CORRECTIONS += [
    Correction(
        id="acct-multi-session-id-type",
        target=table_row("Acct-Multi-Session-Id", table="7.1.0.1"),
        field="data_type",
        expect=ast.DataType.UNSIGNED32,
        replace=ast.DataType.UTF8_STRING,
        reason=(
            "table 7.1.0.1 types Acct-Multi-Session-Id Unsigned32; RFC 6733,"
            " which clause 7.1.0 names for these AVPs, defines it as"
            " UTF8String (clause 9.8.5 and the table in 4.5)"
        ),
        versions="18.0.0",
    ),
]
CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-m-flag-{field.replace('_', '-')}",
        target=flag_rules(table_row(name, table="7.1.0.1")),
        field=field,
        expect=expect,
        replace=replace,
        reason=(
            f"table 7.1.0.1 puts M in Must not for {name}, which its NOTE 2"
            " says RFC 6733 defines; RFC 6733's table in clause 4.5 sets M in"
            " Must, and gives M,V in Must not to Error-Reporting-Host, the row"
            " above Experimental-Result there"
        ),
        versions="18.0.0",
    )
    for name in ("Experimental-Result", "Experimental-Result-Code")
    # Out of Must not first: each field is validated as it is replaced.
    for field, expect, replace in (
        (
            "must_not",
            frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}),
            frozenset({ast.AvpFlag.VENDOR}),
        ),
        ("must", frozenset(), frozenset({ast.AvpFlag.MANDATORY})),
    )
]

# Findings the linter reports that the document makes on purpose; they
# change no data (docs/corrections.md).
CORRECTIONS += [
    Accept(
        id="multiple-services-credit-control-charging-body",
        rule="reused-body-differs",
        target=definition("Multiple-Services-Credit-Control"),
        expect="Multiple-Services-Credit-Control's body, against RFC4006's definition: "
        "adds 3GPP-RAT-Type, AF-Correlation-Information, Announcement-Information, "
        "Envelope, Envelope-Reporting, PS-Furnish-Charging-Information, "
        "QoS-Information, Quota-Consumption-Time, Quota-Holding-Time, "
        "Refund-Information, Related-Trigger, Reporting-Reason, Service-Specific-Info, "
        "Time-Quota-Mechanism, Time-Quota-Threshold, Trigger, Unit-Quota-Threshold, "
        "Volume-Quota-Threshold, missing AVP, Tariff-Change-Usage",
        reason="clause 7.1.9: 'of type grouped as specified in RFC 4006 [402]. It "
        "contains additional 3GPP specific charging parameters.'; the members it "
        "leaves out, Tariff-Change-Usage and the * [ AVP ] wildcard, are struck, which "
        "clauses 6.2.1.2 and 6.4.1.2 read as not used by 3GPP",
        versions="18.0.0",
    ),
    Accept(
        id="used-service-unit-charging-body",
        rule="reused-body-differs",
        target=definition("Used-Service-Unit"),
        expect="Used-Service-Unit's body, against RFC4006's definition: adds "
        "Event-Charging-TimeStamp, Reporting-Reason, missing AVP, CC-Money",
        reason="clause 7.1.14: 'of type grouped as specified in RFC 4006 [402]. It "
        "contains additional 3GPP specific charging parameters.'; the members it "
        "leaves out, CC-Money and the * [ AVP ] wildcard, are struck, which clauses "
        "6.2.1.2 and 6.4.1.2 read as not used by 3GPP",
        versions="18.0.0",
    ),
    Accept(
        id="oc-olr-extension",
        rule="reused-extension",
        target=definition("OC-OLR"),
        expect="OC-OLR's body, against RFC7683's definition: extended, adding "
        "3GPP-OC-Specific-Reduction",
        reason="clause B.2.4: 'It has been extended compared to the IETF RFC 7683 "
        "[403].'",
        versions="18.0.0",
    ),
    Accept(
        id="supported-features-charging-m",
        rule="reused-row-mismatch",
        target=table_row("Supported-Features", table="7.2.0.1"),
        expect="Supported-Features is tabulated with flag rule M in Must in table "
        "7.2.0.1, but TS29.229, which it is re-used from, reads M in May in table "
        "6.3.0.1",
        reason="clause 6.5.10.3 answers a request whose Supported-Features the server "
        "does not support 'as per 'M' bit set rule', with DIAMETER_AVP_UNSUPPORTED, so "
        "the charging applications set M where TS 29.229 table 6.3.0.1 leaves it May; "
        "clause 7.2.0 gives table 7.2.0.1 'along with the AVP flag rules'",
        versions="18.0.0",
    ),
]

# Table 7.2.0.1 types thirteen AVPs only "refer [223]", OMA-DDS-Charging_Data
# (clause 7.2.0: "for AVPs that are just borrowed from other applications only
# the reference ... is provided"), and leaves their flag cells blank. OMA's
# approved V1.0 (OMA-DDS-Charging_Data-V1_0-20110201-A) states both in table
# 11 of its clause 8.4, the code 10415 vendor's, as this table's codes are:
# Must V,M and May P for each. Its names differ in case from table 7.2.0.1's
# (`Application-Server-Id`, `Content-provider-ID`), its codes do not.
_OMA_TYPES = {
    "Application-Server-ID": (ast.DataType.UTF8_STRING, 2101),
    "Application-Service-Type": (ast.DataType.ENUMERATED, 2102),
    "Application-Session-ID": (ast.DataType.UNSIGNED32, 2103),
    "Content-ID": (ast.DataType.UTF8_STRING, 2116),
    "Content-Provider-ID": (ast.DataType.UTF8_STRING, 2117),
    "DCD-Information": (ast.DataType.GROUPED, 2115),
    "Delivery-Status": (ast.DataType.UTF8_STRING, 2104),
    "IM-Information": (ast.DataType.GROUPED, 2110),
    "Number-Of-Messages-Successfully-Exploded": (ast.DataType.UNSIGNED32, 2111),
    "Number-Of-Messages-Successfully-Sent": (ast.DataType.UNSIGNED32, 2112),
    "Service-Generic-Information": (ast.DataType.GROUPED, 1256),
    "Total-Number-Of-Messages-Exploded": (ast.DataType.UNSIGNED32, 2113),
    "Total-Number-Of-Messages-Sent": (ast.DataType.UNSIGNED32, 2114),
}
# OMA's clauses defining the grouped three say so again with their bodies.
_OMA_GROUPED_CLAUSES = {
    "DCD-Information": "8.5.5",
    "IM-Information": "8.5.6",
    "Service-Generic-Information": "8.5.10",
}
CORRECTIONS += [
    Supply(
        id=f"oma-{name.lower()}",
        target=table_row(name, table="7.2.0.1"),
        expect=ast.AvpTableRow(
            name=name,
            code=code,
            marks={
                ast.MarkColumn.ACR: ("X",),
                ast.MarkColumn.ACA: (),
                ast.MarkColumn.CCR: ("X",),
                ast.MarkColumn.CCA: (),
            },
        ),
        data_type=data_type,
        flag_rules=ast.AvpFlagRules(
            must=frozenset({ast.AvpFlag.VENDOR, ast.AvpFlag.MANDATORY}),
            may=frozenset({ast.AvpFlag.PROTECTED}),
        ),
        reason=(
            f"table 7.2.0.1 types {name} 'refer [223]', OMA-DDS-Charging_Data;"
            f" its V1.0 table 11 (clause 8.4) gives code {code} type {data_type},"
            " flags Must V,M and May P"
            + (
                f", and clause {_OMA_GROUPED_CLAUSES[name]} prints its body"
                if name in _OMA_GROUPED_CLAUSES
                else ""
            )
        ),
        versions="18.0.0",
    )
    for name, (data_type, code) in _OMA_TYPES.items()
]
