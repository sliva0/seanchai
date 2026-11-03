"""Corrections for 3GPP TS 29.368 — see docs/corrections.md."""

from seanchai.dad.corrections import (
    Correction,
    avp_rule,
    definition,
    reused_row,
    value_table,
)

# The three grouped-AVP clauses print `< AVP Header: nnn >` with no vendor-id,
# while clause 6.4.1 sets "the Vendor-Id header of all AVPs defined in the
# present document" to 10415 and table 6.4.1.1 marks the V flag mandatory.
_VENDORLESS = [
    ("Device-Action", "6.4.2"),
    ("Device-Notification", "6.4.3"),
    ("Trigger-Data", "6.4.4"),
]

CORRECTIONS = (
    [
        Correction(
            id=f"vendor-id-{name.lower()}",
            target=definition(name, section=section),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason=f"clause {section}'s AVP header omits the vendor-id; clause"
            " 6.4.1 gives every AVP the document defines vendor 10415 and table"
            " 6.4.1.1 marks the V flag mandatory",
            versions="18.0.0..19.0.0",
        )
        for name, section in _VENDORLESS
    ]
    + [
        Correction(
            id="external-identifier-row-name",
            target=reused_row("External-Id"),
            field="name",
            expect="External-Id",
            replace="External-Identifier",
            reason="table 6.5.1.1 cites TS 29.336 for External-Id; TS 29.336"
            " defines the AVP as External-Identifier (clause 6.4.11, code 3111)",
            versions="18.0.0..19.0.0",
        ),
    ]
    + [
        Correction(
            id=f"external-identifier-in-{parent.lower()}",
            target=avp_rule(parent, "External-Id"),
            field="name",
            expect="External-Id",
            replace="External-Identifier",
            reason=f"the {parent} body (clause {section}) uses table 6.5.1.1's"
            " External-Id; TS 29.336 clause 6.4.11 defines the AVP as"
            " External-Identifier",
            versions="18.0.0..19.0.0",
        )
        for parent, section in (
            ("Device-Action", "6.4.2"),
            ("Device-Notification", "6.4.3"),
        )
    ]
)

CORRECTIONS += [
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
