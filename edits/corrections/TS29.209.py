"""Corrections for 3GPP TS 29.209 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, avp_rule, definition

# Five grouped-AVP clauses print `<AVP Header: nnn>` with no vendor-id
# where clause 6.5 says "The Vendor-Id header of all AVPs defined in the
# present document shall be set to 3GPP (10415)" and table 6.5.1 marks V
# mandatory.
_VENDORLESS = [
    ("Access-Network-Charging-Identifier", "6.5.3"),
    ("Flow-Grouping", "6.5.9"),
    ("Flows", "6.5.11"),
    ("Media-Component-Description", "6.5.18"),
    ("Media-Sub-Component", "6.5.20"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause 6.5"
        " sets the Vendor-Id header of every AVP the document defines to 3GPP"
        " (10415), and table 6.5.1 marks the V flag mandatory",
        versions="6.8.0",
    )
    for name, section in _VENDORLESS
]

# The ASA (clause 6.3.8) prints its redirect members "Redirected-Host",
# "Redirected-Host-Usage" and "Redirected-Max-Cache-Time", names nothing
# defines; the STA (6.3.6) prints the same three as RFC 6733 defines them,
# and RFC 6733's own ASA (clause 8.5.2) carries those.
CORRECTIONS += [
    Correction(
        id=f"asa-{right.lower()}",
        target=avp_rule("AS-Answer", wrong),
        field="name",
        expect=wrong,
        replace=right,
        reason=f"the ASA (clause 6.3.8) prints {wrong}, which nothing"
        f" defines; the STA (6.3.6) and RFC 6733's ASA (8.5.2) carry {right}",
        versions="6.8.0",
    )
    for wrong, right in (
        ("Redirected-Host", "Redirect-Host"),
        ("Redirected-Host-Usage", "Redirect-Host-Usage"),
        ("Redirected-Max-Cache-Time", "Redirect-Max-Cache-Time"),
    )
]
