"""Corrections for 3GPP TS 29.215 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, avp_rule, definition, header

# The two grouped-AVP clauses print `< AVP Header: nnn >` with no vendor-id,
# while clause 5.3.0 sets "the Vendor-Id header of all AVPs defined in the
# present document" to 10415 and table 5.3.0.1 marks the V flag mandatory.
_VENDORLESS = [
    ("Subsession-Decision-Info", "5.3.1"),
    ("Subsession-Enforcement-Info", "5.3.2"),
]

CORRECTIONS = (
    [
        Correction(
            id="bases-gx",
            target=header(),
            field="bases",
            expect=("RFC6733",),
            replace=("RFC6733", "TS29.212"),
            reason="clause 5.4.0: 'The S9 reference point re-uses all of the Gx"
            " and Gxx AVPs specified in 3GPP TS 29.212', including the AVPs Gx"
            " and Gxx re-use, and prints no re-used table for S9",
            versions="18.0.0",
        ),
    ]
    + [
        Correction(
            id=f"vendor-id-{name.lower()}",
            target=definition(name, section=section),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason=f"clause {section}'s AVP header omits the vendor-id; clause"
            " 5.3.0 gives every AVP the document defines vendor 10415 and table"
            " 5.3.0.1 marks the V flag mandatory",
            versions="18.0.0",
        )
        for name, section in _VENDORLESS
    ]
    + [
        Correction(
            id="subsession-decision-info-framed-ipv6-prefix-case",
            target=avp_rule("Subsession-Decision-Info", "Framed-Ipv6-Prefix"),
            field="name",
            expect="Framed-Ipv6-Prefix",
            replace="Framed-IPv6-Prefix",
            reason="the Subsession-Decision-Info body (clause 5.3.1) lower-cases"
            " the 'v'; Subsession-Enforcement-Info and the CCR and RAA ABNFs spell"
            " Framed-IPv6-Prefix, the AVP TS 29.212 re-uses from RFC 4005",
            versions="18.0.0",
        ),
    ]
)
