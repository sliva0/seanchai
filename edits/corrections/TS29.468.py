"""Corrections for 3GPP TS 29.468 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    definition,
    table_row,
    value_table,
)

# Every grouped-AVP clause prints `< AVP Header: nnn >` with no vendor-id,
# while clause 6.4.1 sets "the Vendor-Id header of all AVPs defined in the
# present document" to 10415 and table 6.4.1-1 marks the V flag mandatory.
_VENDORLESS = [
    ("MBMS-Bearer-Event-Notification", "6.4.5"),
    ("MBMS-Bearer-Request", "6.4.6"),
    ("MBMS-Bearer-Response", "6.4.7"),
    ("TMGI-Allocation-Request", "6.4.11"),
    ("TMGI-Allocation-Response", "6.4.12"),
    ("TMGI-Deallocation-Request", "6.4.14"),
    ("TMGI-Deallocation-Response", "6.4.15"),
    ("TMGI-Expiry", "6.4.17"),
    ("Local-M1-Information", "6.4.20"),
    ("Local-MB2-U-Information", "6.4.21"),
    ("ROHC-Request", "6.4.28"),
    ("Userplane-Protocol-Result", "6.4.31"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause"
        " 6.4.1 gives every AVP the document defines vendor 10415 and table"
        " 6.4.1-1 marks the V flag mandatory",
        versions="18.0.0..19.0.0",
    )
    for name, section in _VENDORLESS
] + [
    Correction(
        id="rohc-request-code",
        target=definition("ROHC-Request"),
        field="code",
        expect=3525,
        replace=3526,
        reason="the clause 6.4.28 rule header prints FEC-Request's code 3525;"
        " the clause's own sentence and table 6.4.1-1 give ROHC-Request 3526",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="userplane-protocol-result-code",
        target=definition("Userplane-Protocol-Result"),
        field="code",
        expect=3525,
        replace=3529,
        reason="the clause 6.4.31 rule header prints FEC-Request's code 3525;"
        " the clause's own sentence and table 6.4.1-1 give"
        " Userplane-Protocol-Result 3529",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="mbms-bearer-event-diagnostic-info-type",
        target=table_row("MBMS-Bearer-Event-Diagnostic-Info"),
        field="data_type",
        expect=ast.DataType.UNSIGNED32,
        replace=ast.DataType.ENUMERATED,
        reason="clause 6.4.35 defines the AVP as of type Enumerated and lists"
        " its values; table 6.4.1-1 alone says Unsigned32",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="feature-list-avp",
        target=value_table("Supported-Feature-List"),
        field="avp",
        expect="Supported-Feature-List",
        replace="Feature-List",
        reason="clause 6.5.2.2 is headed 'Supported-Feature-List AVP', which no table "
        "lists and no body names; the document's Supported-Features is TS "
        "29.229's, holding Feature-List-ID and Feature-List, and the clause's "
        "table is captioned 'Features of Feature-List-ID 1'",
        versions="18.0.0..19.0.0",
    ),
]
