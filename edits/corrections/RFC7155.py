"""Corrections for RFC 7155 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    Supply,
    avp_rule,
    definition,
    header,
)

CORRECTIONS = [
    # The redirect family, inherited verbatim from RFC 4005's RAA and ASA
    # ABNFs and corrected the same way there. Verified errata 5993 and 5994
    # confirm the intended RFC 6733 names.
    *(
        Correction(
            id=f"{parent.lower()}-{wrong.lower()}",
            target=avp_rule(parent, wrong),
            field="name",
            expect=wrong,
            replace=right,
            reason=f"the {parent} ABNF writes {wrong}; RFC 6733 defines"
            f" {right} and no Redirected-* AVP exists; verified errata"
            " 5993/5994 correct the spelling",
        )
        for parent, wrong, right in (
            ("Re-Auth-Answer", "Redirected-Host", "Redirect-Host"),
            ("Re-Auth-Answer", "Redirected-Host-Usage", "Redirect-Host-Usage"),
            ("Re-Auth-Answer", "Redirected-Host-Cache-Time", "Redirect-Max-Cache-Time"),
            ("Abort-Session-Answer", "Redirected-Host", "Redirect-Host"),
            ("Abort-Session-Answer", "Redirected-Host-Usage", "Redirect-Host-Usage"),
            (
                "Abort-Session-Answer",
                "Redirected-Max-Cache-Time",
                "Redirect-Max-Cache-Time",
            ),
        )
    ),
    Correction(
        id="acr-connection-info",
        target=avp_rule("Accounting-Request", "Connection-Info"),
        field="name",
        expect="Connection-Info",
        replace="Connect-Info",
        reason="the ACR ABNF (clause 3.9) writes Connection-Info; the AVP is"
        " Connect-Info (code 77), defined in clause 4.2.7 and carried by the"
        " AAR ABNF; verified erratum 5995 corrects the typo",
    ),
    Correction(
        id="bases-nasreq",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4005"),
        reason=(
            "the command ABNFs reference NAS-IP-Address, NAS-Identifier, State and "
            "their siblings, whose rows this document's own tables print with a "
            "'Defined in' pointing at their RADIUS-era origins; RFC 4005 defines and "
            "tabulates them"
        ),
    ),
]

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="NASREQ",
            source=ast.SourceRef(section="1.5", page=8),
            application_id=1,
            applies_to=("3.*",),
        ),
        after=None,
        reason=(
            "clause 1.5: the Auth-Application-Id 'MUST be set to the value one "
            "(1)' in AAR, RAR, STR and ASR, and clause 1.6 recommends one (1) "
            "for ACR/ACA too; the command headers print none"
        ),
    ),
]

# Values the document takes from another.
CORRECTIONS += [
    Supply(
        id="accounting-auth-method-values",
        target=definition("Accounting-Auth-Method"),
        expect="the Microsoft MS-Acct-Auth-Type vendor-specific RADIUS"
        " attribute [RFC2548]",
        values=tuple(
            ast.EnumValue(name=name, value=value)
            for value, name in enumerate(
                ("PAP", "CHAP", "MS-CHAP-1", "MS-CHAP-2", "EAP"), start=1
            )
        ),
        reason="clause 4.6.7 calls the supported values 'identical' to"
        " MS-Acct-Auth-Type's; RFC 2548 section 2.7.4 defines them, 1 PAP to"
        " 5 EAP. IANA's Accounting-Auth-Method registry (aaa-parameters-26)"
        " also lists None 7, from RFC 4005 clause 8.7, which RFC 4005's file"
        " already holds and RFC 2548 does not define",
    ),
]

# The RADIUS-derived AVPs' values, from IANA's "RADIUS Types" registry,
# which [RADIUSAttrVals] names (section 9.2): each AVP takes the values of
# the RADIUS attribute with its code. The registry is open (Service-Type by
# IETF Review, the rest by Expert Review), so this is a snapshot, of the
# file Last Updated 2026-10-09, fetched 2026-10-31. Unassigned codes are
# left out (Login-Service's 7).
_RADIUS_VALUES = {
    "NAS-Port-Type": (
        "Values for RADIUS Attribute 61, NAS-Port-Type",
        "radius-types-13",
        (
            (0, "Async"),
            (1, "Sync"),
            (2, "ISDN Sync"),
            (3, "ISDN Async V.120"),
            (4, "ISDN Async V.110"),
            (5, "Virtual"),
            (6, "PIAFS"),
            (7, "HDLC Clear Channel"),
            (8, "X.25"),
            (9, "X.75"),
            (10, "G.3 Fax"),
            (11, "SDSL - Symmetric DSL"),
            (12, "ADSL-CAP - Asymmetric DSL, Carrierless Amplitude Phase Modulation"),
            (13, "ADSL-DMT - Asymmetric DSL, Discrete Multi-Tone"),
            (14, "IDSL - ISDN Digital Subscriber Line"),
            (15, "Ethernet"),
            (16, "xDSL - Digital Subscriber Line of unknown type"),
            (17, "Cable"),
            (18, "Wireless - Other"),
            (19, "Wireless - IEEE 802.11"),
            (20, "Token-Ring"),
            (21, "FDDI"),
            (22, "Wireless - CDMA2000"),
            (23, "Wireless - UMTS"),
            (24, "Wireless - 1X-EV"),
            (25, "IAPP"),
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
    "Prompt": (
        "Values for RADIUS Attribute 76, Prompt",
        "radius-types-17",
        (
            (0, "No Echo"),
            (1, "Echo"),
        ),
    ),
    "Service-Type": (
        "Values for RADIUS Attribute 6, Service-Type",
        "radius-types-4",
        (
            (1, "Login"),
            (2, "Framed"),
            (3, "Callback Login"),
            (4, "Callback Framed"),
            (5, "Outbound"),
            (6, "Administrative"),
            (7, "NAS Prompt"),
            (8, "Authenticate Only"),
            (9, "Callback NAS Prompt"),
            (10, "Call Check"),
            (11, "Callback Administrative"),
            (12, "Voice"),
            (13, "Fax"),
            (14, "Modem Relay"),
            (15, "IAPP-Register"),
            (16, "IAPP-AP-Check"),
            (17, "Authorize Only"),
            (18, "Framed-Management"),
            (19, "Additional-Authorization"),
        ),
    ),
    "Framed-Protocol": (
        "Values for RADIUS Attribute 7, Framed-Protocol",
        "radius-types-5",
        (
            (1, "PPP"),
            (2, "SLIP"),
            (3, "AppleTalk Remote Access Protocol (ARAP)"),
            (4, "Gandalf proprietary SingleLink/MultiLink protocol"),
            (5, "Xylogics proprietary IPX/SLIP"),
            (6, "X.75 Synchronous"),
            (7, "GPRS PDP Context"),
        ),
    ),
    "Framed-Routing": (
        "Values for RADIUS Attribute 10, Framed-Routing",
        "radius-types-6",
        (
            (0, "None"),
            (1, "Send routing packets"),
            (2, "Listen for routing packets"),
            (3, "Send and Listen"),
        ),
    ),
    "Framed-Compression": (
        "Values for RADIUS Attribute 13, Framed-Compression",
        "radius-types-7",
        (
            (0, "None"),
            (1, "VJ TCP/IP header compression"),
            (2, "IPX header compression"),
            (3, "Stac-LZS compression"),
        ),
    ),
    "ARAP-Zone-Access": (
        "Values for RADIUS Attribute 72, ARAP-Zone-Access",
        "radius-types-16",
        (
            (1, "Only allow access to default zone"),
            (2, "Use zone filter inclusively"),
            (3, "Not used"),
            (4, "Use zone filter exclusively"),
        ),
    ),
    "Login-Service": (
        "Values for RADIUS Attribute 15, Login-Service",
        "radius-types-8",
        (
            (0, "Telnet"),
            (1, "Rlogin"),
            (2, "TCP Clear"),
            (3, "PortMaster (proprietary)"),
            (4, "LAT"),
            (5, "X25-PAD"),
            (6, "X25-T3POS"),
            (8, "TCP Clear Quiet (suppresses any NAS-generated connect string)"),
        ),
    ),
    "Tunnel-Type": (
        "Values for RADIUS Attribute 64, Tunnel-Type",
        "radius-types-14",
        (
            (1, "Point-to-Point Tunneling Protocol (PPTP)"),
            (2, "Layer Two Forwarding (L2F)"),
            (3, "Layer Two Tunneling Protocol (L2TP)"),
            (4, "Ascend Tunnel Management Protocol (ATMP)"),
            (5, "Virtual Tunneling Protocol (VTP)"),
            (6, "IP Authentication Header in the Tunnel-mode (AH)"),
            (7, "IP-in-IP Encapsulation (IP-IP)"),
            (8, "Minimal IP-in-IP Encapsulation (MIN-IP-IP)"),
            (9, "IP Encapsulating Security Payload in the Tunnel-mode (ESP)"),
            (10, "Generic Route Encapsulation (GRE)"),
            (11, "Bay Dial Virtual Services (DVS)"),
            (12, "IP-in-IP Tunneling"),
            (13, "Virtual LANs (VLAN)"),
        ),
    ),
    "Tunnel-Medium-Type": (
        "Values for RADIUS Attribute 65, Tunnel-Medium-Type",
        "radius-types-15",
        (
            (1, "IPv4 (IP version 4)"),
            (2, "IPv6 (IP version 6)"),
            (3, "NSAP"),
            (4, "HDLC (8-bit multidrop)"),
            (5, "BBN 1822"),
            (6, '802 (includes all 802 media plus Ethernet "canonical format")'),
            (7, "E.163 (POTS)"),
            (8, "E.164 (SMDS, Frame Relay, ATM)"),
            (9, "F.69 (Telex)"),
            (10, "X.121 (X.25, Frame Relay)"),
            (11, "IPX"),
            (12, "Appletalk"),
            (13, "Decnet IV"),
            (14, "Banyan Vines"),
            (15, "E.164 with NSAP format subaddress"),
        ),
    ),
    "Acct-Authentic": (
        "Values for RADIUS Attribute 45, Acct-Authentic",
        "radius-types-11",
        (
            (1, "RADIUS"),
            (2, "Local"),
            (3, "Remote"),
            (4, "Diameter"),
        ),
    ),
}

_RADIUS_CITATIONS = {
    "NAS-Port-Type": ("4.2.4", "[RADIUSAttrVals]"),
    "Prompt": ("4.3.3", "[RADIUSAttrVals]"),
    "Service-Type": (
        "4.4.1",
        "[RFC2865] and the relevant IANA registry [RADIUSAttrVals]",
    ),
    "Framed-Protocol": ("4.4.10.1", "[RADIUSAttrVals]"),
    "Framed-Routing": ("4.4.10.2", "[RADIUSAttrVals]"),
    "Framed-Compression": ("4.4.10.4", "[RADIUSAttrVals]"),
    "ARAP-Zone-Access": ("4.4.10.8.2", "[RADIUSAttrVals] and defined in [RFC2869]"),
    "Login-Service": ("4.4.11.3", "RFC 2869"),
    "Tunnel-Type": ("4.5.2", "[RADIUSAttrVals]"),
    "Tunnel-Medium-Type": ("4.5.3", "[RADIUSAttrVals]"),
    "Acct-Authentic": ("4.6.6", "[RADIUSAttrVals]"),
}
# What a clause's citation leaves to explain.
_RADIUS_REMARKS = {
    "Service-Type": "; the clause prints Login (1) to Callback Framed (4),"
    " the values it qualifies further, so the registry's 5 to 19 follow them",
    "Login-Service": "; the clause cites 'RFC 2869', which defines no"
    " Login-Service values: they are RFC 2865 section 5.15's, as the"
    " registry's own reference says",
}
# Service-Type's clause prints its first four values.
_PRINTED = {"Service-Type": 4}

CORRECTIONS += [
    Supply(
        id=f"{avp.lower()}-values",
        target=definition(avp),
        expect=citation,
        values=tuple(
            ast.EnumValue(name=name, value=value)
            for value, name in values[_PRINTED.get(avp, 0) :]
        ),
        extend=avp in _PRINTED,
        reason=f"clause {clause} cites {citation} for the values; IANA's"
        f" RADIUS Types registry, '{title}' ({registry}), as Last Updated"
        f" 2026-10-09{_RADIUS_REMARKS.get(avp, '')}",
    )
    for avp, (clause, citation) in _RADIUS_CITATIONS.items()
    for title, registry, values in (_RADIUS_VALUES[avp],)
]
