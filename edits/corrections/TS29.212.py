"""Corrections for 3GPP TS 29.212 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, avp_rule, definition, reused_row

# Eight grouped-AVP clauses print `<AVP header: nnn>` with no vendor-id while
# table 5.3.0.1 marks the V flag mandatory for every one of them, exactly the
# TS 29.272 WLAN-offloadability case. The rest of the document's AVP-format
# lines carry the 10415 the table implies.
_VENDORLESS = [
    ("Routing-Rule-Install", "5.3.68"),
    ("Routing-Rule-Remove", "5.3.69"),
    ("Routing-Rule-Definition", "5.3.70"),
    ("Routing-Filter", "5.3.72"),
    ("TDF-Information", "5.3.78"),
    ("Routing-Rule-Report", "5.3.118"),
    ("Conditional-Policy-Information", "5.3.128"),
    ("CS-Service-Resource-Report", "E.6.3.6"),
]

# The document consistently spells two of TS 29.061's AVPs "Ipv6" — in its
# re-used table and in every ABNF that references them — while 29.061, which
# owns them (codes 15 and 16), spells "IPv6" in its table, its ABNF and its
# defining clause 16.4.7. One AVP, one spelling: the origin's.
_IPV6 = [
    ("3GPP-SGSN-Ipv6-Address", "3GPP-SGSN-IPv6-Address"),
    ("3GPP-GGSN-Ipv6-Address", "3GPP-GGSN-IPv6-Address"),
]
_IPV6_RULES = [
    ("CC-Request", "5.6.2", "3GPP-SGSN-Ipv6-Address"),
    ("CC-Request", "5.6.2", "3GPP-GGSN-Ipv6-Address"),
    ("RA-Answer", "5.6.5", "3GPP-SGSN-Ipv6-Address"),
    ("TS-Request", "5b.6.2", "3GPP-SGSN-Ipv6-Address"),
    ("TS-Request", "5b.6.2", "3GPP-GGSN-Ipv6-Address"),
]

CORRECTIONS = [
    Correction(
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; the AVP"
        " table marks the V flag mandatory for it, as for every other AVP"
        " the specification defines",
        versions="18.2.0",
    )
    for name, section in _VENDORLESS
] + [
    Correction(
        target=reused_row(wrong, section=section),
        field="name",
        expect=wrong,
        replace=right,
        reason=f"the clause {section} re-used table spells the AVP 'Ipv6';"
        " TS 29.061, which defines it, spells 'IPv6' throughout",
        versions="18.2.0",
    )
    for wrong, right in _IPV6
    for section in ("5.4.0", "5b.4.0")
] + [
    Correction(
        target=avp_rule(definition(parent, section=section), wrong),
        field="name",
        expect=wrong,
        replace=dict(_IPV6)[wrong],
        reason=f"clause {section}'s ABNF repeats the document's 'Ipv6'"
        " spelling; TS 29.061, which defines the AVP, spells 'IPv6'",
        versions="18.2.0",
    )
    for parent, section, wrong in _IPV6_RULES
]
