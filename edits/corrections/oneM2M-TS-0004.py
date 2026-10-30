"""Corrections for oneM2M TS-0004 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
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
