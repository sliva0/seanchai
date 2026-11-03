"""Corrections for 3GPP TS 29.219 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition, reused_row

# The two grouped-AVP clauses print `< AVP Header: nnn >` with no vendor-id,
# while clause 5.3.0 sets "the Vendor-Id header of all AVPs defined in the
# present document" to 10415 and table 5.3.0.1 marks the V flag mandatory.
_VENDORLESS = [
    ("Policy-Counter-Status-Report", "5.3.3"),
    ("Pending-Policy-Counter-Information", "5.3.5"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause"
        " 5.3.0 gives every AVP the document defines vendor 10415 and table"
        " 5.3.0.1 marks the V flag mandatory",
        versions="18.0.0..19.0.0",
    )
    for name, section in _VENDORLESS
]

# Clause 2 [17] prints "ETSI TS 283 034 v2.2.0"; ETSI publishes it as ES 283 034.
CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-etsi-standard",
        target=reused_row(name),
        field="origin",
        expect="ETSI-TS283.034",
        replace="ETSI-ES283.034",
        reason="table 5.4 cites [17], 'ETSI TS 283 034 v2.2.0'; ETSI publishes that"
        " title and version as ES 283 034, and has no TS 283 034",
        versions="19.0.0",
    )
    for name in ("Logical-Access-ID", "Physical-Access-ID")
]
