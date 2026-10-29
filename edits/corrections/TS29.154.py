"""Corrections for 3GPP TS 29.154 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition

# Every grouped-AVP clause prints `< AVP Header: nnn >` with no vendor-id,
# while clauses 5.3.1 and A.6.3.1 set "the Vendor-Id header of all AVPs
# defined in the present document" to 10415 and tables 5.3.1.1 and
# A.6.3.1-1 mark the V flag mandatory.
_VENDORLESS = [
    ("Time-window", "5.3.5"),
    ("Transfer-Policy", "5.3.8"),
    ("Access-Network-Reports", "A.6.3.2"),
    ("Event-Configuration", "A.6.3.3"),
    ("Event-Configuration-Status", "A.6.3.5"),
    ("Event-Reports", "A.6.3.7"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; the"
        " document gives every AVP it defines vendor 10415 and its AVP"
        " table marks the V flag mandatory",
        versions="18.0.0",
    )
    for name, section in _VENDORLESS
] + [
    Correction(
        id="time-window-rule-case",
        target=definition("Time-window", section="5.3.5"),
        field="name",
        expect="Time-window",
        replace="Time-Window",
        reason="the clause 5.3.5 rule lower-cases the 'w'; its heading, table"
        " 5.3.1.1 and the Transfer-Policy and BTR bodies spell Time-Window",
        versions="18.0.0",
    ),
]
