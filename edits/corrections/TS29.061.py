"""Corrections for 3GPP TS 29.061 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    Supply,
    avp_rule,
    avp_table,
    definition,
    header,
    table_row,
)

CORRECTIONS = [
    Correction(
        id="mbms-flags-name",
        target=table_row("MBMS-Flag"),
        field="name",
        expect="MBMS-Flag",
        replace="MBMS-Flags",
        reason="only the table cell drops the s; clause 20.5a.9's heading,"
        " prose and value table all write MBMS-Flags, and Wireshark's"
        " dictionary reads it the same way",
        versions="18.1.0..19.1.0",
    ),
    Insert(
        id="session-stop-indicator-row",
        into=avp_table("9a"),
        node=ast.AvpTableRow(
            name="3GPP-Session-Stop-Indicator",
            code=11,
            section="16.4.7",
            flag_rules=ast.AvpFlagRules(),
        ),
        after="3GPP-NSAPI",
        reason="clause 16.4.7.2 codes sub-attribute 11, 3GPP-Session-Stop-Indicator,"
        " among the others table 9a lists, but the table skips it; TS 32.299"
        " table 7.2.0.1 re-uses it from here. Only the name, code and clause"
        " are stated: the clause gives no Diameter type or flags",
        versions="18.1.0..19.1.0",
        drawn_from="clause 16.4.7.2",
    ),
]

# TS 29.210 V6.7.0 table 5.3 re-uses these two from here, meaning Release 6's
# last version (its clause 2 [11] is non-specific). V6.15.0 tabulates neither:
# table 10, its only AVP table, is Gmb's, and clause 16.4.7 lists them as RADIUS
# sub-attributes, by number and with no Diameter type or flag rule. So through TS
# 29.210 the flags are its own clause 5.3's (TS29.210.py) and the type table 9a's
# of a later release (corpus.toml, release_fill); this copy's own reading stays
# short.
CORRECTIONS += [
    Insert(
        id=f"{name.lower()}-row",
        into=avp_table("10"),
        node=ast.AvpTableRow(
            name=name,
            code=code,
            section="16.4.7",
            flag_rules=ast.AvpFlagRules(),
        ),
        after="MBMS-Counting-Information",
        reason=f"clause 16.4.7 codes sub-attribute {code}, {name}, and TS 29.210"
        " V6.7.0 table 5.3 re-uses it from here, but table 10 skips it. Only the"
        " name, code and clause are stated: the clause gives no Diameter type or"
        " flags",
        versions="6.15.0",
        drawn_from="clause 16.4.7",
    )
    for name, code in (
        ("3GPP-GPRS-Negotiated-QoS-Profile", 5),
        ("3GPP-SGSN-MCC-MNC", 18),
    )
]

# The commands' bodies list NASREQ's AVPs, and no re-used table does.
CORRECTIONS += [
    Correction(
        id="bases-nasreq",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC7155", "RFC4005"),
        reason="clauses 16a.4, 17.6 and 20.4 say the bodies' other AVPs are"
        " 'Diameter NASREQ (IETF RFC 7155 [120]) AVPs' and print no re-used table"
        " for them; the ACR and ACA of 16a.4.3 and 16a.4.4 also list"
        " NAS-IP-Address, NAS-IPv6-Address and NAS-Identifier, which RFC 7155"
        " takes from RFC 4005 (RFC7155.py#bases-nasreq)",
        versions="18.1.0..19.1.0",
    ),
    Correction(
        id="rel6-bases-nasreq",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4005"),
        reason="clause 17.6 says the bodies' other AVPs are 'Diameter NASREQ (IETF"
        " RFC 4005 [67]) AVPs' and prints no re-used table for them; the corpus"
        " reads the base protocol as RFC 6733, which obsoletes RFC 3588 [66]",
        versions="6.15.0",
    ),
    Insert(
        id="application-id-nasreq",
        into=header(),
        node=ast.ApplicationScope(
            name="NASREQ",
            source=ast.SourceRef(section="16a.1", page=112),
            application_id=1,
            applies_to=("16a.*",),
        ),
        after=None,
        reason="clause 16a.1: 'shall advertise the support of the Diameter NASREQ"
        " Application', used 'according to RFC 7155 [120]', and 16a.2 uses its"
        " accounting the same way; RFC 7155 clauses 1.5 and 1.6 give one (1) for"
        " every command clause 16a.4 prints. The command headers print none",
        versions="18.1.0..19.1.0",
    ),
]

# RFC 6733 sections 6.12 to 6.14 name the redirect AVPs Redirect-Host,
# Redirect-Host-Usage and Redirect-Max-Cache-Time, as RFC 3588 did; these bodies
# spell them otherwise in every Gi, Gmb and SGmb answer printing them.
_REDIRECTS = {
    "Redirected-Host": "Redirect-Host",
    "Redirected-Host-Usage": "Redirect-Host-Usage",
    "Redirected-Host-Cache-Time": "Redirect-Max-Cache-Time",
}
_SHORT = ("Redirected-Host", "Redirected-Host-Usage")
_LONG = (*_SHORT, "Redirected-Host-Cache-Time")


def _redirect_reason(section, printed):
    return (
        f"clause {section}'s body prints {printed}; RFC 6733 section 6 and the"
        f" bodies of the other answers name the AVP {_REDIRECTS[printed]}, and no"
        " document defines the printed name"
    )


CORRECTIONS += [
    Correction(
        id=f"{printed.lower()}-{section.replace('.', '-')}",
        target=avp_rule(definition(command, section=section), printed),
        field="name",
        expect=printed,
        replace=_REDIRECTS[printed],
        reason=_redirect_reason(section, printed),
        versions="18.1.0..19.1.0",
    )
    for command, section, printed_names in (
        ("Abort-Session-Answer", "16a.4.8", _SHORT),
        ("Re-Auth-Answer", "17.6.6", _LONG),
        ("Abort-Session-Answer", "17.6.8", _SHORT),
        ("Re-Auth-Answer", "20.4.2", _LONG),
        ("Abort-Session-Answer", "20.4.6", _SHORT),
    )
    for printed in printed_names
]
CORRECTIONS += [
    Correction(
        id=f"rel6-{printed.lower()}-{section.replace('.', '-')}",
        target=avp_rule(definition(command, section=section), printed),
        field="name",
        expect=printed,
        replace=_REDIRECTS[printed],
        reason=_redirect_reason(section, printed),
        versions="6.15.0",
    )
    for command, section, printed_names in (
        ("Re-Auth-Answer", "17.6.6", _LONG),
        ("Abort-Session-Answer", "17.6.8", _SHORT),
    )
    for printed in printed_names
]
CORRECTIONS += [
    Correction(
        id="acr-ms-timezone-spelling",
        target=avp_rule("AC-Request", "3GPP-MS-Time-Zone"),
        field="name",
        expect="3GPP-MS-Time-Zone",
        replace="3GPP-MS-TimeZone",
        reason="clause 16a.4.3's body alone hyphenates the name; tables 9a and 10"
        " and clause 16.4.7's sub-attribute name print 3GPP-MS-TimeZone",
        versions="18.1.0..19.1.0",
    ),
    Correction(
        id="acr-connect-info-spelling",
        target=avp_rule("AC-Request", "Connection-Info"),
        field="name",
        expect="Connection-Info",
        replace="Connect-Info",
        reason="clause 16a.4.3's ACR body copies the typo of RFC 4005's and RFC"
        " 7155's ACR (RFC 7155's verified erratum 5995); the AVP is Connect-Info,"
        " code 77, and the AAR body of clause 16a.4.1 spells it so",
        versions="18.1.0..19.1.0",
    ),
    Insert(
        id="undefined-delegated-ipv6-prefix",
        into=header(),
        node=ast.UndefinedAvp(
            name="Delegated-IPv6-Prefix",
            source=ast.SourceRef(section="16a.4.1", page=123),
            note='"clause 2: [97] IETF RFC 4818 (2007): RADIUS'
            ' Delegated-IPv6-Prefix Attribute"',
        ),
        after=None,
        reason="a member of the AAR, AAA and ACR bodies (clauses 16a.4.1 to"
        " 16a.4.3) in no table of this document; clause 2 cites RFC 4818 [97],"
        " which defines the RADIUS attribute with no Diameter type or flags and"
        " which the corpus does not hold. Wireshark's dictionary has code 123,"
        " OctetString, with may-M",
        versions="18.1.0..19.1.0",
    ),
]

# Values the document takes from another.
CORRECTIONS += [
    Supply(
        id="mbms-hc-indicator-values",
        target=definition("MBMS-HC-Indicator"),
        expect="3GPP TS 25.413 [92]",
        values=(
            ast.EnumValue(name="uncompressed-header", value=0),
            ast.EnumValue(name="compressed-header", value=1),
        ),
        reason="TS 25.413 V19.0.0 (2025-09), the only Release 19 version,"
        " clause 9.2.1.84 types MBMS HC Indicator 'ENUMERATED (uncompressed"
        " header, compressed header, ...)', and its ASN.1 MBMSHCIndicator"
        " lists uncompressed-header, then compressed-header, then the"
        " extension marker. The ASN.1 numbers nothing: 0 and 1 are"
        " the declaration order, X.680's ordinal numbering, a judgement"
        " Wireshark's dictionary shares; the names are the ASN.1 identifiers",
        versions="18.1.0..19.1.0",
    ),
]
