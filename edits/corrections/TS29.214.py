"""Corrections for 3GPP TS 29.214 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    avp_rule,
    definition,
    enum_value,
    reused_row,
)

# Eleven grouped-AVP clauses print `<AVP header: nnn>` with no vendor-id while
# table 5.3.0.1 marks the V flag mandatory for every one of them, exactly the
# TS 29.272 WLAN-offloadability case.
_VENDORLESS = [
    ("Access-Network-Charging-Identifier", "5.3.3"),
    ("Flows", "5.3.10"),
    ("Media-Component-Description", "5.3.16"),
    ("Media-Sub-Component", "5.3.18"),
    ("Acceptable-Service-Info", "5.3.24"),
    ("Sponsored-Connectivity-Data", "5.3.27"),
    ("Callee-Information", "5.3.62"),
    ("MA-Information", "5.3.66"),
    ("5GS-RAN-NAS-Release-Cause", "5.3.69"),
    ("NGAP-Cause", "5.3.72"),
    ("Wireline-User-Location-Info", "5.3.75"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; table"
        " 5.3.0.1 marks the V flag mandatory for it, as for every other AVP"
        " the specification defines",
        versions="18.4.0",
    )
    for name, section in _VENDORLESS
] + [
    Delete(
        id=f"specific-action-void-{value}",
        target=enum_value("Specific-Action", "Void", value=value),
        expect=ast.EnumValue(name="Void", value=value),
        reason="clause 5.3.13 prints 'Void' as the label of values 0 and 5 —"
        " a 3GPP editorial placeholder for removed values, not an enumerated"
        " value a dictionary can carry, and one name cannot label two values",
        versions="18.4.0",
    )
    for value in (0, 5)
]

CORRECTIONS += [
    Correction(
        id="framed-ipv6-prefix-row-case",
        target=reused_row("Framed-Ipv6-Prefix", section="5.4.0"),
        field="name",
        expect="Framed-Ipv6-Prefix",
        replace="Framed-IPv6-Prefix",
        reason="table 5.4.0.1 lower-cases the 'v'; RFC 4005, which defines"
        " the AVP, spells 'IPv6'",
        versions="18.4.0",
    )
]

CORRECTIONS += [
    Correction(
        id="aar-framed-ipv6-prefix-case",
        target=avp_rule("AA-Request", "Framed-Ipv6-Prefix"),
        field="name",
        expect="Framed-Ipv6-Prefix",
        replace="Framed-IPv6-Prefix",
        reason="the AAR ABNF (clause 5.6.1) lower-cases the 'v' as table"
        " 5.4.0.1 does; RFC 4005, which defines the AVP, spells 'IPv6'",
        versions="18.4.0",
    ),
    Correction(
        id="sta-netloc-access-support-case",
        target=avp_rule("ST-Answer", "Netloc-Access-Support"),
        field="name",
        expect="Netloc-Access-Support",
        replace="NetLoc-Access-Support",
        reason="the STA ABNF (clause 5.6.6) lower-cases the 'L'; table 5.4.0.1"
        " re-uses NetLoc-Access-Support from TS 29.212 and the AAA and RAR"
        " ABNFs spell it the same way",
        versions="18.4.0",
    ),
]

# Release 7, V7.12.0, the copy ETSI TS 183 017 [19] cites as "3GPP TS 29.214
# Release 7"; the Release 18 declarations above do not reach it
# (src/seanchai/versions.py). Five grouped-AVP clauses print no vendor-id
# where clause 5.3 says "The Vendor-Id header of all AVPs defined in the
# present document shall be set to 3GPP (10415)" and table 5.3.1 marks V
# mandatory.
_VENDORLESS_REL7 = [
    ("Access-Network-Charging-Identifier", "5.3.3"),
    ("Flows", "5.3.10"),
    ("Media-Component-Description", "5.3.16"),
    ("Media-Sub-Component", "5.3.18"),
    ("Acceptable-Service-Info", "5.3.24"),
]

CORRECTIONS += [
    Correction(
        id=f"rel7-vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause 5.3"
        " sets the Vendor-Id header of every AVP the document defines to 3GPP"
        " (10415), and table 5.3.1 marks the V flag mandatory",
        versions="7.12.0",
    )
    for name, section in _VENDORLESS_REL7
]

# The Release 7 ASA (clause 5.6.8) prints "Redirected-Host" and its two
# siblings, as TS 29.209 V6.8.0's did; the AAA and STA (5.6.2, 5.6.6) and
# RFC 6733's ASA (8.5.2) carry the RFC 6733 names.
CORRECTIONS += [
    Correction(
        id=f"rel7-asa-{right.lower()}",
        target=avp_rule("AS-Answer", wrong),
        field="name",
        expect=wrong,
        replace=right,
        reason=f"the ASA (clause 5.6.8) prints {wrong}, which nothing"
        f" defines; the AAA and STA (5.6.2, 5.6.6) and RFC 6733's ASA (8.5.2)"
        f" carry {right}",
        versions="7.12.0",
    )
    for wrong, right in (
        ("Redirected-Host", "Redirect-Host"),
        ("Redirected-Host-Usage", "Redirect-Host-Usage"),
        ("Redirected-Max-Cache-Time", "Redirect-Max-Cache-Time"),
    )
]
