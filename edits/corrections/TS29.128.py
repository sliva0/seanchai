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
    value_row,
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
    Correction(
        id="configuration-event-storage-result-spelling",
        target=value_row(
            "Experimental-Result-Code",
            "DIAMETER_ERROR_CONFIGURATION_EVENT_STORAGE_NOT_ SUCCESSFUL",
        ),
        field="name",
        expect="DIAMETER_ERROR_CONFIGURATION_EVENT_STORAGE_NOT_ SUCCESSFUL",
        replace="DIAMETER_ERROR_CONFIGURATION_EVENT_STORAGE_NOT_SUCCESSFUL",
        reason="clause 6.3.3.3's heading prints a space inside the name; clause "
        "6.3.3.3 says the code is TS 29.336's and TS 29.230 table 8.1.4 allocates "
        "5513 under the name without it",
        versions="18.0.0",
    ),
    Correction(
        id="scef-reference-id-result-spelling",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_ SCEF_REFERENCE_ID_UNKNOWN"
        ),
        field="name",
        expect="DIAMETER_ERROR_ SCEF_REFERENCE_ID_UNKNOWN",
        replace="DIAMETER_ERROR_SCEF_REFERENCE_ID_UNKNOWN",
        reason="clause 6.3.3.10's heading prints a space inside the name; TS 29.230 "
        "table 8.1.4 allocates 5515 under the name without it",
        versions="18.0.0",
    ),
]

# The codes clauses say are defined elsewhere, as the registry allocates them.
CORRECTIONS += [
    Accept(
        id="unauthorized-requesting-entity-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_UNAUTHORIZED_REQUESTING_ENTITY"
        ),
        expect="DIAMETER_ERROR_UNAUTHORIZED_REQUESTING_ENTITY (code 5510) is listed "
        "here, but TS29.230 table 8.1.4 allocates the code to TS29.336",
        reason="clause 6.3.3.1 says 'This error code is defined in 3GPP TS 29.336 "
        "[5].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="unauthorized-service-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_UNAUTHORIZED_SERVICE"
        ),
        expect="DIAMETER_ERROR_UNAUTHORIZED_SERVICE (code 5511) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.336",
        reason="clause 6.3.3.2 says 'This error code is defined in 3GPP TS 29.336 "
        "[5].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="configuration-event-storage-not-successful-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code",
            "DIAMETER_ERROR_CONFIGURATION_EVENT_STORAGE_NOT_SUCCESSFUL",
        ),
        expect="DIAMETER_ERROR_CONFIGURATION_EVENT_STORAGE_NOT_SUCCESSFUL (code 5513) "
        "is listed here, but TS29.230 table 8.1.4 allocates the code to TS29.336",
        reason="clause 6.3.3.3 says 'This error code is defined in 3GPP TS 29.336 "
        "[5].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="configuration-event-non-existant-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code",
            "DIAMETER_ERROR_CONFIGURATION_EVENT_NON_EXISTANT",
        ),
        expect="DIAMETER_ERROR_CONFIGURATION_EVENT_NON_EXISTANT (code 5514) is listed "
        "here, but TS29.230 table 8.1.4 allocates the code to TS29.336",
        reason="clause 6.3.3.4 says 'This error code is defined in 3GPP TS 29.336 "
        "[5].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="user-unknown-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_USER_UNKNOWN"),
        expect="DIAMETER_ERROR_USER_UNKNOWN (code 5001) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.3.3.6 says 'This error code is defined in 3GPP TS 29.229 "
        "[4].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="operation-not-allowed-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_OPERATION_NOT_ALLOWED"
        ),
        expect="DIAMETER_ERROR_OPERATION_NOT_ALLOWED (code 5101) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 6.3.3.7 says 'This error code is defined in 3GPP TS 29.329 "
        "[17].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="unreachable-user-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_UNREACHABLE_USER"),
        expect="DIAMETER_ERROR_UNREACHABLE_USER (code 4221) is listed here, but "
        "TS29.230 table 8.1.3 allocates the code to TS29.172",
        reason="clause 6.3.3.12 says 'This error code is defined in 3GPP TS 29.172 "
        "[26].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
]
