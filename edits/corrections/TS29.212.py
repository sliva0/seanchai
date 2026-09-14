"""Corrections for 3GPP TS 29.212 — see docs/corrections.md."""

from seanchai.dad.corrections import (
    Correction,
    avp_rule,
    definition,
    reused_row,
    table_row,
)

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

CORRECTIONS = (
    [
        Correction(
            id=f"vendor-id-{name.lower()}",
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
    ]
    + [
        Correction(
            id=f"ipv6-case-row-{wrong.lower()}-{section.replace('.', '-')}",
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
    ]
    + [
        Correction(
            id=f"ipv6-case-rule-{parent.lower()}-{wrong.lower()}",
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
)

CORRECTIONS += [
    Correction(
        id=f"framed-ipv6-prefix-row-{section.replace('.', '-')}",
        target=reused_row("Framed-Ipv6-Prefix", section=section),
        field="name",
        expect="Framed-Ipv6-Prefix",
        replace="Framed-IPv6-Prefix",
        reason=f"the clause {section} re-used table lower-cases the 'v';"
        " RFC 4005, which defines the AVP, spells 'IPv6'",
        versions="18.2.0",
    )
    for section in ("5.4.0", "5a.4.0", "5b.4.0", "5c.4.1")
]

CORRECTIONS += [
    Correction(
        id=f"framed-ipv6-prefix-rule-{section.replace('.', '-')}",
        target=avp_rule(definition(parent, section=section), "Framed-Ipv6-Prefix"),
        field="name",
        expect="Framed-Ipv6-Prefix",
        replace="Framed-IPv6-Prefix",
        reason=f"clause {section}'s ABNF repeats the document's 'Ipv6'"
        " spelling; RFC 4005, which defines the AVP, spells 'IPv6'",
        versions="18.2.0",
    )
    for parent, section in (
        ("CC-Request", "5.6.2"),
        ("CC-Request", "5a.6.2"),
        ("CC-Answer", "5a.6.3"),
        ("TS-Request", "5b.6.2"),
        ("CC-Request", "5b.6.4"),
        ("CC-Answer", "5b.6.5"),
        ("TS-Request", "5c.6.2"),
    )
] + [
    Correction(
        id="cs-service-qos-request-identifier-case",
        target=table_row("CS-Service-Qos-Request-Identifier"),
        field="name",
        expect="CS-Service-Qos-Request-Identifier",
        replace="CS-Service-QoS-Request-Identifier",
        reason="only the table E.6.3.1 cell lowercases the S; clause"
        " E.6.3.2's heading and prose, and the E.6.6.2/E.6.3.6 ABNFs, all"
        " write CS-Service-QoS-Request-Identifier, matching every sibling"
        " CS-Service-QoS-* AVP in the same table",
        versions="18.2.0",
    ),
]
