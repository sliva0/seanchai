"""Corrections for oneM2M TS-0004 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    Supply,
    definition,
    flag_rules,
    header,
    table_row,
)

_VENDOR = frozenset({ast.AvpFlag.VENDOR})
_MANDATORY = frozenset({ast.AvpFlag.MANDATORY})

# Table A.4-1 gives oneM2M's own AVPs Vendor Id 45687 and puts V under Must
# not in every one of their rows, the cell its IETF rows print. Clause A.4
# assigns the vendor ("AVPs defined for oneM2M specific usage are assigned
# Vendor-Id of 45687"), and RFC 6733 section 4.1.1 sets V exactly when the
# header carries a Vendor-ID, so the bit belongs under Must.
_ONEM2M_ROWS = (
    "Access-Network-Identifier",
    "Application-Entity-ID",
    "Control-Memory-Size",
    "Current-Number-Members",
    "Data-Memory-Size",
    "External-ID",
    "Group-Name",
    "Hosting-CSE-ID",
    "Originator",
    "Maximum-Number-Members",
    "M2M-Event-Record-Timestamp",
    "M2M-Information",
    "Occupancy",
    "Protocol-Type",
    "Receiver",
    "Request-Body-Size",
    "Request-Headers-Size",
    "Request-Operation",
    "Response-Body-Size",
    "Response-Headers-Size",
    "Response-Status-Code",
    "Subgroup-Name",
    "Target-ID",
)
_V_UNDER_MUST = {
    name: (
        "table A.4-1 gives the row Vendor Id 45687 and V under Must not; clause"
        " A.4: 'AVPs defined for oneM2M specific usage are assigned Vendor-Id"
        " of 45687', and RFC 6733 section 4.1.1 sets V exactly when the header"
        " carries a Vendor-ID"
    )
    for name in _ONEM2M_ROWS
} | {
    "Service-Information": (
        "table A.4-1 gives the row Vendor Id 10415, cites 3GPP TS 32.299 [31]"
        " for it and puts V under Must not; RFC 6733 section 4.1.1 sets V"
        " exactly when the header carries a Vendor-ID, and TS 32.299 table"
        " 7.2.0.1 sets V under Must for code 873"
    ),
}

CORRECTIONS = [
    Correction(
        id=f"{name.lower()}-v-flag-{field.replace('_', '-')}",
        target=flag_rules(table_row(name, table="A.4-1")),
        field=field,
        expect=expect,
        replace=replace,
        reason=reason,
        versions="2.35.0",
    )
    for name, reason in _V_UNDER_MUST.items()
    # Out of Must not before into Must, so V is never in both.
    for field, expect, replace in (
        ("must_not", _VENDOR, frozenset()),
        ("must", _MANDATORY, _MANDATORY | _VENDOR),
    )
]

CORRECTIONS += [
    Correction(
        id="m2m-information-vendor",
        target=definition("M2M-Information"),
        field="vendor_id",
        expect=None,
        replace=45687,
        reason=(
            "clause A.5.14 prints '< AVP Header: 1011>' with no vendor-id;"
            " table A.4-1 gives M2M-Information Vendor Id 45687, which clause"
            " A.4 assigns to 'AVPs defined for oneM2M specific usage'"
        ),
        versions="2.35.0",
    ),
    Correction(
        id="service-context-id-type",
        target=table_row("Service-Context-Id", table="A.4-1"),
        field="data_type",
        expect=ast.DataType.GROUPED,
        replace=ast.DataType.UTF8_STRING,
        reason=(
            "table A.4-1 types Service-Context-Id Grouped and cites [A.5.26],"
            " whose clause says 'This AVP is of type UTF8String', as RFC 4006"
            " clause 8.42 defines code 461"
        ),
        versions="2.35.0",
    ),
]

# Table A.4-1's Reference cells pointing at another clause than the one
# heading the AVP; clause A.5 defines each in the clause its heading names.
CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-clause",
        target=table_row(name, table="A.4-1"),
        field="section",
        expect=printed,
        replace=heading,
        reason=(
            f"table A.4-1 cites [{printed}] for {name}; clause {printed} is"
            f" '{title}', and clause {heading} is headed '{name} AVP'"
        ),
        versions="2.35.0",
    )
    for name, printed, title, heading in (
        ("Acct-Application-Id", "5.5.1", "Introduction", "A.5.2"),
        ("Accounting-Record-Type", "5.4.2", "Primitives modelling", "A.5.3"),
        ("Application-Entity-ID", "A.5.2", "Acct-Application-Id AVP", "A.5.4"),
    )
]

# The ACR and ACA headers (clauses A.2.1, A.2.2) print no application id.
CORRECTIONS += [
    Insert(
        id="application-id-mch",
        into=header(),
        node=ast.ApplicationScope(
            name="Mch",
            source=ast.SourceRef(section="A.5.2"),
            application_id=3,
            applies_to=("A.2.*",),
        ),
        after=None,
        reason=(
            "clause A.5.2: 'Since the protocol used on Mch is Diameter"
            " Accounting, this AVP shall contain the value of 3 as defined in"
            " IETF RFC 6733 [14]'; the ACR and ACA of clause A.2, 'Diameter"
            " Commands on Mch', print no id in their headers"
        ),
        versions="2.35.0",
    ),
]

# Values clause A.5 points at in the document's own data-type clauses,
# which the extractor reads no AVPs from.
_RESPONSE_STATUS_CODES = (
    (1000, "ACCEPTED"),
    (1001, "ACCEPTED for nonBlockingRequestSynch"),
    (1002, "ACCEPTED for nonBlockingRequestAsynch"),
    (2000, "OK"),
    (2001, "CREATED"),
    (2002, "DELETED"),
    (2004, "UPDATED"),
    (4000, "BAD_REQUEST"),
    (4001, "RELEASE_VERSION_NOT_SUPPORTED"),
    (4004, "NOT_FOUND"),
    (4005, "OPERATION_NOT_ALLOWED"),
    (4008, "REQUEST_TIMEOUT"),
    (4015, "UNSUPPORTED_MEDIA_TYPE"),
    (4101, "SUBSCRIPTION_CREATOR_HAS_NO_PRIVILEGE"),
    (4103, "ORIGINATOR_HAS_NO_PRIVILEGE"),
    (4104, "GROUP_REQUEST_IDENTIFIER_EXISTS"),
    (4105, "CONFLICT"),
    (4106, "ORIGINATOR_NOT_AUTHENTICATED"),
    (4107, "SECURITY_ASSOCIATION_REQUIRED"),
    (4108, "INVALID_CHILD_RESOURCE_TYPE"),
    (4109, "NO_MEMBERS"),
    (4110, "GROUP_MEMBER_TYPE_INCONSISTENT"),
    (4111, "ESPRIM_UNSUPPORTED_OPTION"),
    (4112, "ESPRIM_UNKNOWN_KEY_ID"),
    (4113, "ESPRIM_UNKNOWN_ORIG_RAND_ID"),
    (4114, "ESPRIM_UNKNOWN_RECV_RAND_ID"),
    (4115, "ESPRIM_BAD_MAC"),
    (4116, "ESPRIM_IMPERSONATION_ERROR"),
    (4117, "ORIGINATOR_HAS_ALREADY_REGISTERED"),
    (4125, "SPECIALIZATION_SCHEMA_NOT_FOUND"),
    (4126, "APP_RULE_VALIDATION_FAILED"),
    (4128, "SERVICE_SUBSCRIPTION_NOT_ESTABLISHED"),
    (4143, "INVALID_SPARQL_QUERY"),
    (5000, "INTERNAL_SERVER_ERROR"),
    (5001, "NOT_IMPLEMENTED"),
    (5103, "TARGET_NOT_REACHABLE"),
    (5105, "RECEIVER_HAS_NO_PRIVILEGE"),
    (5106, "ALREADY_EXISTS"),
    (5203, "TARGET_NOT_SUBSCRIBABLE"),
    (5204, "SUBSCRIPTION_VERIFICATION_INITIATION_FAILED"),
    (5205, "SUBSCRIPTION_HOST_HAS_NO_PRIVILEGE"),
    (5206, "NON_BLOCKING_SYNCH_REQUEST_NOT_SUPPORTED"),
    (5207, "NOT_ACCEPTABLE"),
    (5208, "DISCOVERY_DENIED_BY_IPE"),
    (5209, "GROUP_MEMBERS_NOT_RESPONDED"),
    (5210, "ESPRIM_DECRYPTION_ERROR"),
    (5211, "ESPRIM_ENCRYPTION_ERROR"),
    (5212, "SPARQL_UPDATE_ERROR"),
    (5220, "UNABLE_TO_RECALL_REQUEST"),
    (6003, "EXTERNAL_OBJECT_NOT_REACHABLE"),
    (6005, "EXTERNAL_OBJECT_NOT_FOUND"),
    (6010, "MAX_NUMBER_OF_MEMBER_EXCEEDED"),
    (6020, "MGMT_SESSION_CANNOT_BE_ESTABLISHED"),
    (6021, "MGMT_SESSION_ESTABLISHMENT_TIMEOUT"),
    (6022, "INVALID_CMDTYPE"),
    (6023, "INVALID_ARGUMENTS"),
    (6024, "INSUFFICIENT_ARGUMENTS"),
    (6025, "MGMT_CONVERSION_ERROR"),
    (6026, "MGMT_CANCELLATION_FAILED"),
    (6028, "ALREADY_COMPLETE"),
    (6029, "MGMT_COMMAND_NOT_CANCELLABLE"),
)

CORRECTIONS += [
    Supply(
        id="request-operation-values",
        target=definition("Request-Operation"),
        expect="Table 6.3.4.2.5-6",
        values=tuple(
            ast.EnumValue(name=name, value=value)
            for value, name in enumerate(
                ("Create", "Retrieve", "Update", "Delete", "Notify"), start=1
            )
        ),
        reason="clause 6.3.4.2.5's table 'Interpretation of m2m:operation'"
        " (its caption numbers it -6, the list of tables 6.3.4.2.5-1) gives"
        " 1 Create, 2 Retrieve, 3 Update, 4 Delete and 5 Notify",
        versions="2.35.0",
    ),
    Supply(
        id="response-status-code-values",
        target=definition("Response-Status-Code"),
        expect="clause 6.6.3",
        values=tuple(
            ast.EnumValue(name=name, value=value)
            for value, name in _RESPONSE_STATUS_CODES
        ),
        reason="clauses 6.6.3.2 to 6.6.3.7 tabulate the response status codes"
        " by class: informational 1000-1002, successful 2000-2004, none for"
        " redirection (6.6.3.4: 'no values in this response class are"
        " defined'), originator error 4000-4143, receiver error 5000-5220"
        " and network system error 6003-6029; the names are the tables'"
        " descriptions, as printed",
        versions="2.35.0",
    ),
]
