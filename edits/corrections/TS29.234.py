"""Corrections for 3GPP TS 29.234 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    Insert,
    avp_rule,
    definition,
    header,
    reused_avps,
    value_row,
)

# Clauses 4.2, 5.2, 8.2 and 9.2 build Wa, Wd, Wm and Wg on these, whose AVPs
# the commands of clauses 4, 5, 8, 9 and 11 use without listing them: the
# document prints no re-used table at all.
CORRECTIONS = [
    Correction(
        id="bases-wlan",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4005", "RFC4072", "RFC5580"),
        reason="clause 4.2 builds Wa's Diameter on 'IETF RFC 4072 [8]', 'IETF RFC"
        " 4005 [12]' and 'IETF RFC 5580 [16]'; 5.2, 8.2 and 9.2 name the same for"
        " Wd, Wm and Wg (RFC 3588 standing where the corpus holds RFC 6733), and"
        " the commands print their AVPs with no re-used table to cite them",
        versions="11.2.0",
    )
]

# Four grouped-AVP clauses print `<AVP header: nnn>` with no vendor-id where
# clause 10.1 says "The Vendor-Id header of all AVPs defined in this
# specification shall be set to 3GPP (10415)" and table 10.1.1 marks V.
CORRECTIONS += [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause 10.1"
        " sets the Vendor-Id header of every AVP the document defines to 3GPP"
        " (10415), and table 10.1.1 marks the V flag mandatory",
        versions="11.2.0",
    )
    for name, section in (
        ("WLAN-User-Data", "10.1.8"),
        ("Charging-Data", "10.1.10"),
        ("APN-Authorized", "10.1.14"),
        ("Charging-Nodes", "10.1.28"),
    )
]
CORRECTIONS += [
    Correction(
        id="vendor-id-sip-auth-data-item",
        target=definition("SIP-Auth-Data-Item", section="10.1.4"),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason="clause 10.1.4's AVP header omits the vendor-id of the AVP it says"
        " 'is defined in 3GPP TS 29.229 [6]', whose clause 6.3.13 prints '< AVP"
        " Header : 612 10415 >'; read without one it is IETF space, another AVP",
        versions="11.2.0",
    )
]

# Table 10.1.1 lists "only those AVPs initially defined by the reference
# points mentioned within this specification" and no re-used table exists, so
# each clause saying where an AVP is defined gives it a row.
_REUSED = (
    (
        "Visited-Network-Identifier",
        "TS29.229",
        "clause 10.1.3: 'defined in 3GPP TS 29.229 [6]'",
    ),
    (
        "SIP-Auth-Data-Item",
        "TS29.229",
        "clause 10.1.4: 'defined in 3GPP TS 29.229 [6]'",
    ),
    *(
        (
            name,
            "TS29.229",
            "clause 10.1.4 extends TS 29.229 [6]'s SIP-Auth-Data-Item, whose"
            " members these are",
        )
        for name in (
            "SIP-Item-Number",
            "SIP-Authentication-Scheme",
            "SIP-Authenticate",
            "SIP-Authorization",
            "SIP-Authentication-Context",
            "Confidentiality-Key",
            "Integrity-Key",
        )
    ),
    (
        "SIP-Number-Auth-Items",
        "TS29.229",
        "the MAR and MAA (6.4.1) carry it beside SIP-Auth-Data-Item and tables"
        " 6.3.1.1 and 6.3.1.4 map to it; no clause here defines it, and TS"
        " 29.229 [6], which clause 10.1.4 cites for SIP-Auth-Data-Item, does",
    ),
    (
        "Server-Assignment-Type",
        "TS29.229",
        "clause 10.1.18: 'defined in 3GPP TS 29.229 [6]'",
    ),
    (
        "Secondary-Charging-Collection-Function-Name",
        "TS29.229",
        "clause 10.1.31: 'defined in 3GPP TS 29.229 [6]'",
    ),
    (
        "Primary-Charging-Collection-Function-Name",
        "TS29.229",
        "clause 10.1.36: 'defined in 3GPP TS 29.229 [6]'",
    ),
    (
        "Subscription-Id",
        "RFC4006",
        "clause 10.1.25: 'defined in the IETF RFC 4006 [19]'",
    ),
    ("QoS-Resources", "RFC5777", "clause 10.1.42: 'defined in IETF RFC 5777 [35]'"),
    ("QoS-Capability", "RFC5777", "clause 10.1.43: 'defined in IETF RFC 5777 [35]'"),
    (
        "Deregistration-Reason",
        "TS29.229",
        "clause 10.1.19: 'defined in 3GPP TS 29.229 [6]'; table 6.3.2.3 maps to it",
    ),
    (
        "WLAN-Session-Id",
        "TS32.299",
        "clause 10.1.39: 'specified in 3GPP TS 32.299 [32]'; tables 8.3.1.2 and"
        " 8.3.2.2 map to it. The clause's 'of type Unsigned32' is prose a row has"
        " no cell for, and TS 32.299 V11.20.0 table 7.2 types the AVP UTF8String",
    ),
    (
        "PDG-Charging-Id",
        "TS32.299",
        "clause 10.1.40: 'specified in 3GPP TS 32.299 [32]'; tables 8.3.1.1 and"
        " 8.3.2.1 map to it",
    ),
)

CORRECTIONS += [
    Insert(
        id=f"reused-{name.lower()}",
        into=reused_avps("10.1.1"),
        node=ast.ReusedAvpRow(name=name, origin=origin),
        after=_REUSED[index - 1][0] if index else None,
        reason=f"the document prints no re-used table; {why}",
        versions="11.2.0",
    )
    for index, (name, origin, why) in enumerate(_REUSED)
]

# Members the formats print under a name nothing defines, where the document
# says which AVP it means.
_MEMBERS = (
    (
        "accounting-interim-interval",
        "Diameter-EAP-Answer",
        "4.4.2.1",
        "Accounting-Interim-Interval",
        "Acct-Interim-Interval",
        "the Wa DEA prints the long form of RFC 6733's Acct-Interim-Interval,"
        " as the ACA (4.5.2.2) and Wm's DEA (8.4.1) print it",
    ),
    (
        "redirect-host-cache-time",
        "Re-Auth-Answer",
        "4.4.2.4",
        "Redirect-Host-Cache-Time",
        "Redirect-Max-Cache-Time",
        "the RAA follows Redirect-Host and Redirect-Host-Usage with a name RFC"
        " 6733 prints Redirect-Max-Cache-Time, as this document's DEA (8.4.1)"
        " and STA (8.4.3) do",
    ),
    (
        "acc-terminate-cause",
        "AC-Request",
        "4.5.2.2",
        "Acc-Terminate-Cause",
        "Termination-Cause",
        "the ACR prints the RADIUS attribute's name (table 4.5.1);"
        " the Diameter table 4.5.2.1 maps the information to Termination-Cause,"
        " and RFC 4005 section 9.3.5 maps Acct-Terminate-Cause onto it",
    ),
    (
        "accounting-session-time",
        "AC-Request",
        "4.5.2.2",
        "Accounting-Session-Time",
        "Acct-Session-Time",
        "the ACR and table 4.5.2.1 print the long form of RFC 4005's"
        " Acct-Session-Time (clause 8.5), 'the length of the current session in"
        " seconds'",
    ),
    *(
        (
            f"max-requested-bandwidth-{section.replace('.', '-')}",
            command,
            section,
            "Max-Subscribed-Bandwidth",
            "Max-Requested-Bandwidth",
            f"table {table} maps the information element Max-Subscribed-Bandwidth"
            " to the Max-Requested-Bandwidth AVP (table 10.1.1, clause 10.1.26)",
        )
        for command, section, table in (
            ("Diameter-EAP-Answer", "8.4.1", "8.3.1.2"),
            ("AA-Answer", "8.4.2", "8.3.2.2"),
        )
    ),
    *(
        (
            f"subscription-id-{section.replace('.', '-')}",
            command,
            section,
            printed,
            "Subscription-Id",
            f"clause {section}'s format misprints RFC 4006's Subscription-Id, the"
            " AVP clause 10.1.25 says it means",
        )
        for command, section, printed in (
            ("Diameter-EAP-Answer", "5.5.1", "Subscription-ID"),
            ("Diameter-EAP-Answer", "8.4.1", "Subscription-ID-AVP"),
            ("AA-Answer", "8.4.2", "Subscription-ID-AVP"),
            ("AA-Request", "9.4.1", "Subscription-ID"),
            ("WLAN-User-Data", "10.1.8", "Subscription-ID"),
            ("AA-Answer", "11.4.2.1", "Subscription-ID-AVP"),
        )
    ),
)

CORRECTIONS += [
    Correction(
        id=member_id,
        target=avp_rule(definition(command, section=section), printed),
        field="name",
        expect=printed,
        replace=right,
        reason=why,
        versions="11.2.0",
    )
    for member_id, command, section, printed, right, why in _MEMBERS
]

CORRECTIONS += [
    Delete(
        id="framed-ip-prefix",
        target=avp_rule(definition("AA-Answer", section="8.4.2"), "Framed-IP-Prefix"),
        expect=ast.AvpRule(name="Framed-IP-Prefix", presence=ast.Presence.OPTIONAL),
        reason="table 8.3.2.2's Framed-IP-Prefix 'contains the remote IPv6 prefix"
        " of the WLAN UE', which clause 10.1.33 says of RFC 4005's"
        " Framed-IPv6-Prefix; nothing defines the printed name, and the same"
        " AAA prints '* [ Framed-IPv6-Prefix ]' further down",
        versions="11.2.0",
    )
]

# The ASA of clauses 4.4.2.2, 8.4.4, 9.4.2 and 11.4.2.2 prints these three
# names, which nothing defines, as TS 29.209 V6.8.0's clause 6.3.8 does.
CORRECTIONS += [
    Correction(
        id=f"asa-{right.lower()}-{section.replace('.', '-')}",
        target=avp_rule(definition("Abort-Session-Answer", section=section), wrong),
        field="name",
        expect=wrong,
        replace=right,
        reason=f"the ASA (clause {section}) prints {wrong}, which nothing defines;"
        f" this document's STA (8.4.3) and RFC 6733's ASA (8.5.2) carry {right}",
        versions="11.2.0",
    )
    for section in ("4.4.2.2", "8.4.4", "9.4.2", "11.4.2.2")
    for wrong, right in (
        ("Redirected-Host", "Redirect-Host"),
        ("Redirected-Host-Usage", "Redirect-Host-Usage"),
        ("Redirected-Max-Cache-Time", "Redirect-Max-Cache-Time"),
    )
]

CORRECTIONS += [
    Insert(
        id="undefined-error-cause",
        into=header(),
        node=ast.UndefinedAvp(
            name="Error-Cause",
            source=ast.SourceRef(section="4.4.2.1"),
            note="table 4.4.1: 'The 3GPP AAA server shall include this"
            ' attribute with a value of "Location-Info-Required" if it did not'
            " receive the requested location information as specified in IETF"
            " RFC 5580 [16]'",
        ),
        after=None,
        reason="an optional member of Wa's and Wd's DEA (4.4.2.1, 5.5.1) that no"
        " clause defines and that V11.2.0, the document's last version, leaves"
        " so; RFC 5580 table 'Error-Cause (*)' lists a RADIUS attribute 'defined"
        " in [RFC5176]', and RFC 4072 mentions it only for RADIUS translation,"
        " no Diameter document in the corpus defining the name; the TS 29.230"
        " registry allocates no such name. Wireshark's dictionary.xml has"
        " Error-Cause at (0, 101), Enumerated, carrying RADIUS's number under no"
        " citation, which stays evidence",
        versions="11.2.0",
    )
]

CORRECTIONS += [
    Correction(
        id="no-wlan-subscription-result-spelling",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_NO_WLAN_SUBSCRIPTON"
        ),
        field="name",
        expect="DIAMETER_ERROR_USER_NO_WLAN_SUBSCRIPTON",
        replace="DIAMETER_ERROR_USER_NO_WLAN_SUBSCRIPTION",
        reason="clause 10.3.1.1's heading drops a letter; TS 29.230 table 8.1.4 "
        "allocates 5041 under the full word",
        versions="11.2.0",
    ),
]
