"""Corrections for RFC 4005 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    Insert,
    Supply,
    avp_rule,
    definition,
    enum_value,
    header,
    table_row,
)

# Clauses 6.13.1-6.13.3 head and define the three AVPs Framed-AppleTalk-*,
# and the Accounting-Request ABNF spells them the same way; the AVP table
# (section 6) and the AA-Answer ABNF lowercase the T. The definitions are
# the canonical spelling — RADIUS's attributes of the same name and
# Wireshark's dictionary both write AppleTalk.
CORRECTIONS = (
    [
        Correction(
            id=f"framed-appletalk-{suffix.lower()}-table-case",
            target=table_row(f"Framed-Appletalk-{suffix}"),
            field="name",
            expect=f"Framed-Appletalk-{suffix}",
            replace=f"Framed-AppleTalk-{suffix}",
            reason=f"clause 6.13.{clause} heads and defines"
            f" Framed-AppleTalk-{suffix}, as do the Accounting-Request ABNF and"
            " Wireshark's dictionary; the AVP table lowercases the T",
        )
        for clause, suffix in enumerate(("Link", "Network", "Zone"), start=1)
    ]
    + [
        Correction(
            id=f"framed-appletalk-{suffix.lower()}-aaa-case",
            target=avp_rule("AA-Answer", f"Framed-Appletalk-{suffix}"),
            field="name",
            expect=f"Framed-Appletalk-{suffix}",
            replace=f"Framed-AppleTalk-{suffix}",
            reason=f"the AA-Answer ABNF lowercases the T of"
            f" Framed-AppleTalk-{suffix} against clause 6.13.{clause}'s"
            " definition and the Accounting-Request ABNF",
        )
        for clause, suffix in enumerate(("Link", "Network", "Zone"), start=1)
    ]
    + [
        # The redirect family: the RAA and ASA ABNFs (clauses 3.4, 3.8) misspell
        # RFC 6733's Redirect-* base AVPs, and the STA ABNF (clause 3.6)
        # misspells Redirect-Host-Usage. RFC 7155, this document's successor,
        # carries the same Redirected-* misspellings and its verified errata
        # 5993/5994 confirm the intended names.
        Correction(
            id=f"{parent.lower()}-{wrong.lower()}",
            target=avp_rule(parent, wrong),
            field="name",
            expect=wrong,
            replace=right,
            reason=f"the {parent} ABNF writes {wrong}; RFC 6733 (and RFC 3588,"
            f" current when this was published) defines {right} and no"
            " Redirected-* AVP exists; the AAR/AAA ABNFs of this same document"
            " spell the family correctly",
        )
        for parent, wrong, right in (
            ("Re-Auth-Answer", "Redirected-Host", "Redirect-Host"),
            ("Re-Auth-Answer", "Redirected-Host-Usage", "Redirect-Host-Usage"),
            ("Re-Auth-Answer", "Redirected-Host-Cache-Time", "Redirect-Max-Cache-Time"),
            (
                "Session-Termination-Answer",
                "Redirect-Host-Usase",
                "Redirect-Host-Usage",
            ),
            ("Abort-Session-Answer", "Redirected-Host", "Redirect-Host"),
            ("Abort-Session-Answer", "Redirected-Host-Usage", "Redirect-Host-Usage"),
            (
                "Abort-Session-Answer",
                "Redirected-Max-Cache-Time",
                "Redirect-Max-Cache-Time",
            ),
        )
    ]
    + [
        Correction(
            id="acr-connection-info",
            target=avp_rule("Accounting-Request", "Connection-Info"),
            field="name",
            expect="Connection-Info",
            replace="Connect-Info",
            reason="the ACR ABNF (clause 3.9) writes Connection-Info; the AVP is"
            " Connect-Info (code 77), defined in clause 4.7 and carried by the"
            " AAR ABNF; RFC 7155's verified erratum 5995 confirms the same typo"
            " in the successor document",
        ),
        Correction(
            id="acr-qos-filter-rule-case",
            target=avp_rule("Accounting-Request", "Qos-Filter-Rule"),
            field="name",
            expect="Qos-Filter-Rule",
            replace="QoS-Filter-Rule",
            reason="the ACR ABNF (clause 3.9) lowercases the S; clause 6.9"
            " defines QoS-Filter-Rule (code 407) and the AVP table spells it the"
            " same way",
        ),
    ]
)

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="NASREQ",
            source=ast.SourceRef(section="11.3", page=78),
            application_id=1,
            applies_to=("3.*",),
        ),
        after=None,
        reason=(
            "clause 11.3: 'This specification uses the value one (1) in the "
            "Application Identifier namespace'; the command headers print none. "
            "Clause 1.3 says the RAR, STR, ASR and ACR 'defined by [BASE]' use "
            "'the Base application id value', which RFC 7155 clause 1.5, this "
            "document's successor, replaces with one (1)"
        ),
    ),
]

# Clause 6.1 lists Service-Type's values, then re-lists four of them as "The
# following values are further qualified", each with its description. Two
# of the four are labelled in words and read a second time; the clause
# assigns nothing new by repeating them.
CORRECTIONS += [
    Delete(
        id=f"service-type-{name.lower().replace(' ', '-')}-requalified",
        target=enum_value("Service-Type", name, value=value, occurrence=2),
        expect=ast.EnumValue(name=name, value=value),
        reason=f"clause 6.1 lists {name} ({value}) among Service-Type's values"
        " and repeats it under 'The following values are further qualified'",
    )
    for name, value in (("Callback Login", 3), ("Callback Framed", 4))
]

# The RADIUS-derived AVPs' values IANA's "RADIUS Types" registry, which
# [RADIUSTypes] names (section 13.1), has added since: the clauses print
# lists "for informational purposes", which match the registry's opening
# values, and ARAP-Zone-Access none. The registry is open, so these are a
# snapshot, of the file Last Updated 2026-10-09, fetched 2026-10-31.
# Prompt, Framed-Routing, Framed-Compression, Login-Service, Tunnel-Type,
# Tunnel-Medium-Type and Acct-Authentic print the registry's whole list.
_RADIUS_ADDED = {
    "NAS-Port-Type": (
        "4.4",
        "[RADIUSTypes]",
        "Values for RADIUS Attribute 61, NAS-Port-Type",
        "radius-types-13",
        (
            (26, "FTTP - Fiber to the Premises"),
            (27, "Wireless - IEEE 802.16"),
            (28, "Wireless - IEEE 802.20"),
            (29, "Wireless - IEEE 802.22"),
            (30, "PPPoA - PPP over ATM"),
            (31, "PPPoEoA - PPP over Ethernet over ATM"),
            (32, "PPPoEoE - PPP over Ethernet over Ethernet"),
            (33, "PPPoEoVLAN - PPP over Ethernet over VLAN"),
            (34, "PPPoEoQinQ - PPP over Ethernet over IEEE 802.1QinQ"),
            (35, "xPON - Passive Optical Network"),
            (36, "Wireless - XGP"),
            (37, "WiMAX Pre-Release 8 IWK Function"),
            (38, "WIMAX-WIFI-IWK: WiMAX WIFI Interworking"),
            (39, "WIMAX-SFF: Signaling Forwarding Function for LTE/3GPP2"),
            (40, "WIMAX-HA-LMA: WiMAX HA and or LMA function"),
            (41, "WIMAX-DHCP: WIMAX DCHP service"),
            (42, "WIMAX-LBS: WiMAX location based service"),
            (43, "WIMAX-WVS: WiMAX voice service"),
        ),
    ),
    "Service-Type": (
        "6.1",
        "[RADIUS] and [RADIUSTypes]",
        "Values for RADIUS Attribute 6, Service-Type",
        "radius-types-4",
        (
            (18, "Framed-Management"),
            (19, "Additional-Authorization"),
        ),
    ),
    "Framed-Protocol": (
        "6.10.1",
        "[RADIUSTypes]",
        "Values for RADIUS Attribute 7, Framed-Protocol",
        "radius-types-5",
        ((7, "GPRS PDP Context"),),
    ),
    "ARAP-Zone-Access": (
        "6.14.2",
        "[RADIUSTypes] and defined in [RADIUSExt]",
        "Values for RADIUS Attribute 72, ARAP-Zone-Access",
        "radius-types-16",
        (
            (1, "Only allow access to default zone"),
            (2, "Use zone filter inclusively"),
            (3, "Not used"),
            (4, "Use zone filter exclusively"),
        ),
    ),
}

CORRECTIONS += [
    Supply(
        id=f"{avp.lower()}-values",
        target=definition(avp),
        expect=citation,
        values=tuple(ast.EnumValue(name=name, value=value) for value, name in values),
        # ARAP-Zone-Access prints none.
        extend=avp != "ARAP-Zone-Access",
        reason=f"clause {clause} cites {citation} for the values; IANA's"
        f" RADIUS Types registry, '{title}' ({registry}), as Last Updated"
        " 2026-10-09, "
        + (
            "gives these, which it attributes to RFC 2869 ([RADIUSExt])"
            if avp == "ARAP-Zone-Access"
            else "adds these to the values the clause prints"
        ),
    )
    for avp, (clause, citation, title, registry, values) in _RADIUS_ADDED.items()
]
