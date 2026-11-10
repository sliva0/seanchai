"""Corrections for 3GPP TS 29.212 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Supply,
    avp_rule,
    definition,
    reused_row,
)

# Thirty-nine grouped-AVP clauses print `<AVP header: nnn>` with no
# vendor-id while the AVP tables mark the V flag mandatory for every one of
# them, exactly the TS 29.272 WLAN-offloadability case. The rest of the
# document's AVP-format lines carry the 10415 the tables imply.
_VENDORLESS = [
    ("Charging-Rule-Install", "5.3.2"),
    ("Charging-Rule-Remove", "5.3.3"),
    ("Charging-Rule-Definition", "5.3.4"),
    ("TFT-Packet-Filter-Information", "5.3.14"),
    ("QoS-Information", "5.3.16"),
    ("Charging-Rule-Report", "5.3.18"),
    ("Access-Network-Charging-Identifier-Gx", "5.3.22"),
    ("Event-Report-Indication", "5.3.30"),
    ("Allocation-Retention-Priority", "5.3.32"),
    ("Tunnel-Information", "5.3.36"),
    ("CoA-Information", "5.3.37"),
    ("Default-EPS-Bearer-QoS", "5.3.48"),
    ("Flow-Information", "5.3.53"),
    ("Packet-Filter-Information", "5.3.56"),
    ("Usage-Monitoring-Information", "5.3.60"),
    ("Routing-Rule-Install", "5.3.68"),
    ("Routing-Rule-Remove", "5.3.69"),
    ("Routing-Rule-Definition", "5.3.70"),
    ("Routing-Filter", "5.3.72"),
    ("TDF-Information", "5.3.78"),
    ("Redirect-Information", "5.3.82"),
    ("Application-Detection-Information", "5.3.91"),
    ("Default-QoS-Information", "5.3.103"),
    ("Conditional-APN-Aggregate-Max-Bitrate", "5.3.105"),
    ("Presence-Reporting-Area-Information", "5.3.109"),
    ("Fixed-User-Location-Info", "5.3.112"),
    ("Routing-Rule-Report", "5.3.118"),
    ("Conditional-Policy-Information", "5.3.128"),
    ("PRA-Install", "5.3.130"),
    ("PRA-Remove", "5.3.131"),
    ("QoS-Rule-Install", "5a.3.1"),
    ("QoS-Rule-Remove", "5a.3.2"),
    ("QoS-Rule-Definition", "5a.3.3"),
    ("QoS-Rule-Report", "5a.3.5"),
    ("ADC-Rule-Install", "5b.3.1"),
    ("ADC-Rule-Remove", "5b.3.2"),
    ("ADC-Rule-Definition", "5b.3.3"),
    ("ADC-Rule-Report", "5b.3.6"),
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
    ("Event-Report-Indication", "5.3.30", "3GPP-SGSN-Ipv6-Address"),
    ("QoS-Rule-Install", "5a.3.1", "3GPP-GGSN-Ipv6-Address"),
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
            versions="18.2.0..19.1.0",
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
            versions="18.2.0..19.1.0",
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
            versions="18.2.0..19.1.0",
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
        versions="18.2.0..19.1.0",
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
        versions="18.2.0..19.1.0",
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
]

# Release 11, V11.19.0, which TS 32.299 V11.20.0 [215] cites
# non-specifically within Release 11; Release 19's declarations above do
# not reach it (src/seanchai/_versions.py). Its thirty-one vendorless
# grouped-AVP headers, and the same 'Ipv6' spellings, are Release 19's
# defects as printed then.
_VENDORLESS_REL11 = [
    ("Charging-Rule-Install", "5.3.2"),
    ("Charging-Rule-Remove", "5.3.3"),
    ("Charging-Rule-Definition", "5.3.4"),
    ("TFT-Packet-Filter-Information", "5.3.14"),
    ("QoS-Information", "5.3.16"),
    ("Charging-Rule-Report", "5.3.18"),
    ("Access-Network-Charging-Identifier-Gx", "5.3.22"),
    ("Event-Report-Indication", "5.3.30"),
    ("Allocation-Retention-Priority", "5.3.32"),
    ("Tunnel-Information", "5.3.36"),
    ("CoA-Information", "5.3.37"),
    ("Default-EPS-Bearer-QoS", "5.3.48"),
    ("Flow-Information", "5.3.53"),
    ("Packet-Filter-Information", "5.3.56"),
    ("Usage-Monitoring-Information", "5.3.60"),
    ("Routing-Rule-Install", "5.3.68"),
    ("Routing-Rule-Remove", "5.3.69"),
    ("Routing-Rule-Definition", "5.3.70"),
    ("Routing-Filter", "5.3.72"),
    ("TDF-Information", "5.3.78"),
    ("Redirect-Information", "5.3.82"),
    ("Application-Detection-Information", "5.3.91"),
    ("QoS-Rule-Install", "5a.3.1"),
    ("QoS-Rule-Remove", "5a.3.2"),
    ("QoS-Rule-Definition", "5a.3.3"),
    ("QoS-Rule-Report", "5a.3.5"),
    ("ADC-Rule-Install", "5b.3.1"),
    ("ADC-Rule-Remove", "5b.3.2"),
    ("ADC-Rule-Definition", "5b.3.3"),
    ("ADC-Rule-Report", "5b.3.6"),
    ("CS-Service-Resource-Report", "E.6.3.6"),
]
_IPV6_ROWS_REL11 = [
    ("3GPP-GGSN-Ipv6-Address", "5.4"),
    ("3GPP-SGSN-Ipv6-Address", "5.4"),
    ("3GPP-SGSN-Ipv6-Address", "5b.4"),
]
_IPV6_RULES_REL11 = [
    ("CC-Request", "5.6.2", "3GPP-SGSN-Ipv6-Address"),
    ("CC-Request", "5.6.2", "3GPP-GGSN-Ipv6-Address"),
    ("RA-Answer", "5.6.5", "3GPP-SGSN-Ipv6-Address"),
    ("TS-Request", "5b.6.2", "3GPP-SGSN-Ipv6-Address"),
    ("Event-Report-Indication", "5.3.30", "3GPP-SGSN-Ipv6-Address"),
    ("QoS-Rule-Install", "5a.3.1", "3GPP-GGSN-Ipv6-Address"),
]

CORRECTIONS += [
    Correction(
        id=f"rel11-vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; the AVP"
        " table marks the V flag mandatory for it, as for every other AVP"
        " the specification defines",
        versions="11.19.0",
    )
    for name, section in _VENDORLESS_REL11
]

CORRECTIONS += [
    Correction(
        id=f"rel11-ipv6-case-row-{wrong.lower()}-{section.replace('.', '-')}",
        target=reused_row(wrong, section=section),
        field="name",
        expect=wrong,
        replace=dict(_IPV6)[wrong],
        reason=f"the clause {section} re-used table spells the AVP 'Ipv6';"
        " TS 29.061, which defines it, spells 'IPv6' throughout",
        versions="11.19.0",
    )
    for wrong, section in _IPV6_ROWS_REL11
] + [
    Correction(
        id=f"rel11-ipv6-case-rule-{parent.lower()}-{wrong.lower()}",
        target=avp_rule(definition(parent, section=section), wrong),
        field="name",
        expect=wrong,
        replace=dict(_IPV6)[wrong],
        reason=f"clause {section}'s ABNF repeats the document's 'Ipv6'"
        " spelling; TS 29.061, which defines the AVP, spells 'IPv6'",
        versions="11.19.0",
    )
    for parent, section, wrong in _IPV6_RULES_REL11
]

CORRECTIONS += [
    Correction(
        id=f"rel11-framed-ipv6-prefix-row-{section.replace('.', '-')}",
        target=reused_row("Framed-Ipv6-Prefix", section=section),
        field="name",
        expect="Framed-Ipv6-Prefix",
        replace="Framed-IPv6-Prefix",
        reason=f"the clause {section} re-used table lower-cases the 'v';"
        " RFC 4005, which defines the AVP, spells 'IPv6'",
        versions="11.19.0",
    )
    for section in ("5.4", "5a.4", "5b.4")
] + [
    Correction(
        id=f"rel11-framed-ipv6-prefix-rule-{section.replace('.', '-')}",
        target=avp_rule(definition(parent, section=section), "Framed-Ipv6-Prefix"),
        field="name",
        expect="Framed-Ipv6-Prefix",
        replace="Framed-IPv6-Prefix",
        reason=f"clause {section}'s ABNF repeats the document's 'Ipv6'"
        " spelling; RFC 4005, which defines the AVP, spells 'IPv6'",
        versions="11.19.0",
    )
    for parent, section in (
        ("CC-Request", "5.6.2"),
        ("CC-Request", "5a.6.2"),
        ("CC-Answer", "5a.6.3"),
        ("TS-Request", "5b.6.2"),
        ("CC-Request", "5b.6.4"),
        ("CC-Answer", "5b.6.5"),
    )
]

# Values the document defines by pointing at another of its AVPs.
CORRECTIONS += [
    Supply(
        id="default-access-values",
        target=definition("Default-Access"),
        expect="IP-CAN-Type AVP",
        values=tuple(
            ast.EnumValue(name=name, value=value)
            for value, name in enumerate(
                (
                    "3GPP-GPRS",
                    "DOCSIS",
                    "xDSL",
                    "WiMAX",
                    "3GPP2",
                    "3GPP-EPS",
                    "Non-3GPP-EPS",
                    "FBA",
                    "3GPP-5GS",
                    "Non-3GPP-5GS",
                )
            )
        ),
        reason="clause 5.3.120: 'The values defined in the Default-Access AVP"
        " are the same as the ones defined in IP-CAN-Type AVP'; clause 5.3.27"
        " of V19.1.0 defines IP-CAN-Type's 0 to 9, copied here. The clause's"
        " NOTE makes only 3GPP-EPS and Non-3GPP-EPS applicable in this"
        " release, which limits their use, not the list",
        versions="18.2.0..19.1.0",
    ),
]

# Clause 2 [37] prints "ETSI TS 283 034 v2.2.0" and the Gx and Sd tables cite it
# so. ETSI publishes that document as an ETSI Standard, ES 283 034 V2.2.0, whose
# title is the title [37] gives, and has no TS 283 034.
CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-etsi-standard-{section.replace('.', '-')}",
        target=reused_row(name, section=section),
        field="origin",
        expect="ETSI-TS283.034",
        replace="ETSI-ES283.034",
        reason=f"the clause {section} table cites [37], 'ETSI TS 283 034 v2.2.0'; ETSI"
        " publishes that title and version as ES 283 034, and has no TS 283 034",
        versions="19.1.0",
    )
    for section in ("5.4.0", "5b.4.0")
    for name in ("Logical-Access-ID", "Physical-Access-ID")
]

CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-etsi-standard-{section.replace('.', '-')}",
        target=reused_row(name, section=section),
        field="origin",
        expect="ETSI-TS283.034",
        replace="ETSI-ES283.034",
        reason=f"the clause {section} table cites [37], 'ETSI TS 283 034 v2.2.0'; ETSI"
        " publishes that title and version as ES 283 034, and has no TS 283 034",
        versions="11.19.0",
    )
    for section in ("5.4", "5b.4")
    for name in ("Logical-Access-ID", "Physical-Access-ID")
]

# Table 5c.4.1.1 cites "IETF RFC 7863 [49]" for the two overload AVPs, and clause
# 2's [49] is IETF RFC 7683, as the same rows of the document's other re-used
# tables read it. RFC 7863 concerns NFS and defines no AVP.
CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-origin-5c-4-1",
        target=reused_row(name, section="5c.4.1"),
        field="origin",
        expect="RFC7863",
        replace="RFC7683",
        reason=f"table 5c.4.1.1 cites 'IETF RFC 7863 [49]' for {name}; clause 2's"
        " [49] is IETF RFC 7683, 'Diameter Overload Indication Conveyance', which"
        " defines it and the other tables cite, and RFC 7863 concerns NFS",
        versions="19.1.0",
    )
    for name in ("OC-OLR", "OC-Supported-Features")
]
