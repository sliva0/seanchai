"""Corrections for 3GPP TS 29.128 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Insert,
    avp_rule,
    definition,
    reused_avps,
    reused_row,
)

CORRECTIONS = [
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
    Correction(
        id="pdn-connection-charging-id-reused-case",
        target=reused_row("PDN-Connection-Charging-Id"),
        field="name",
        expect="PDN-Connection-Charging-Id",
        replace="PDN-Connection-Charging-ID",
        reason="the row cites TS 32.299, whose clause 7.2.136 and table 7.2.0.1"
        " spell the AVP PDN-Connection-Charging-ID",
        versions="18.0.0",
    ),
    Correction(
        id="pdn-connection-charging-id-member-case",
        target=avp_rule("Connection-Management-Answer", "PDN-Connection-Charging-Id"),
        field="name",
        expect="PDN-Connection-Charging-Id",
        replace="PDN-Connection-Charging-ID",
        reason="TS 32.299 clause 7.2.136 defines PDN-Connection-Charging-ID;"
        " the CMA rule spells it as the re-used table does",
        versions="18.0.0",
    ),
]

# Findings the linter reports that the document makes on purpose; they
# change no data (docs/corrections.md).
CORRECTIONS += [
    Accept(
        id="monitoring-event-configuration-t6a-body",
        rule="reused-body-differs",
        target=definition("Monitoring-Event-Configuration"),
        expect="Monitoring-Event-Configuration's body, against TS29.336's definition: "
        "adds Number-Of-UE-Per-Location-Configuration, missing Association-Type, "
        "DL-Buffering-Suggested-Packet-Count, Exclude-Identifiers, "
        "Include-Identifiers, MTC-Provider-Info, Maximum-Detection-Time, "
        "PDN-Connectivity-Status-Configuration, PLMN-ID-Requested",
        reason="clause 6.4.2: 'It is originally defined in 3GPP TS 29.336 [5]. For the "
        "T6a/T6b interface, the Monitoring-Event-Configuration AVP format is specified "
        "as following'",
        versions="18.0.0",
    ),
    Accept(
        id="monitoring-event-report-t6a-body",
        rule="reused-body-differs",
        target=definition("Monitoring-Event-Report"),
        expect="Monitoring-Event-Report's body, against TS29.336's definition: adds "
        "Communication-Failure-Information, Number-Of-UE-Per-Location-Report, "
        "Reporting-Time-Stamp, missing Event-Handling, IMEI-Change, "
        "Roaming-Information, SCEF-Reference-ID-for-Deletion, "
        "SCEF-Reference-ID-for-Deletion-Ext, Service-Report, Terminal-Information",
        reason="clause 6.4.3: 'It is originally defined in 3GPP TS 29.336 [5]. For the "
        "T6a/T6b interface, the Monitoring-Event-Report AVP format is specified as "
        "following'",
        versions="18.0.0",
    ),
]
