"""Corrections for 3GPP TS 29.211 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, avp_rule

# The ASA (clause 7.3.8) prints its redirect members "Redirected-Host",
# "Redirected-Host-Usage" and "Redirected-Max-Cache-Time", names nothing
# defines, as TS 29.209 V6.8.0's clause 6.3.8 does; the STA (7.3.6) prints the
# same three as RFC 6733 defines them, and RFC 6733's own ASA (clause 8.5.2)
# carries those.
CORRECTIONS = [
    Correction(
        id=f"asa-{right.lower()}",
        target=avp_rule("AS-Answer", wrong),
        field="name",
        expect=wrong,
        replace=right,
        reason=f"the ASA (clause 7.3.8) prints {wrong}, which nothing"
        f" defines; the STA (7.3.6) and RFC 6733's ASA (8.5.2) carry {right}",
        versions="6.4.0",
    )
    for wrong, right in (
        ("Redirected-Host", "Redirect-Host"),
        ("Redirected-Host-Usage", "Redirect-Host-Usage"),
        ("Redirected-Max-Cache-Time", "Redirect-Max-Cache-Time"),
    )
]
