"""Corrections for 3GPP TS 29.153 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition

# The grouped-AVP clause prints `< AVP header: 4101 >` with no vendor-id,
# while clause 5.3.1 sets "the Vendor-Id header of all AVPs defined in the
# present document" to 10415 and table 5.3.1.1 marks the V flag mandatory.
CORRECTIONS = [
    Correction(
        id="vendor-id-network-congestion-area-report",
        target=definition("Network-Congestion-Area-Report", section="5.3.2"),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason="clause 5.3.2's AVP header omits the vendor-id; clause 5.3.1"
        " gives every AVP the document defines vendor 10415 and table 5.3.1.1"
        " marks the V flag mandatory",
        versions="18.0.0",
    )
]
