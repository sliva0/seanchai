"""Corrections for 3GPP TS 29.272 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, avp_rule, definition, table_row

# The VCSG command headers print "< Diameter Header: 8388638, REQ, PXY, >" with
# the application id left empty. Clause 7.2.2 assigns these command codes to
# table 7.2.2/3 and states that "the Application-ID field shall be set to
# 16777308 (application identifier of the S7a/S7d interface application)", so
# the value is not in doubt — only the header is.
_S7A_S7D = 16777308

CORRECTIONS = [
    Correction(
        target=definition(name),
        field="application_id",
        expect=None,
        replace=_S7A_S7D,
        reason="clause 7.2.2 assigns the VCSG commands to S7a/S7d (16777308);"
        " the command header omits the id",
        versions="18.6.0",
    )
    for name in (
        "Update-VCSG-Location-Request",
        "Update-VCSG-Location-Answer",
        "Cancel-VCSG-Location-Request",
        "Cancel-VCSG-Location-Answer",
    )
]

CORRECTIONS += [
    Correction(
        target=definition("Area-Scope"),
        field="code",
        expect=1623,
        replace=1624,
        reason="clause 7.3.138's AVP header prints Job-Type's code; table"
        " 7.3.1/1 and the TS 29.230 registry both assign Area-Scope 1624",
        versions="18.6.0",
    ),
    Correction(
        target=definition("WLAN-offloadability"),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason="clause 7.3.181's AVP header omits the vendor-id; table 7.3.1/1"
        " marks the V flag mandatory for it, as for every other AVP the"
        " specification defines",
        versions="18.6.0",
    ),
    # Two AVPs the ABNF appears to reference without the document introducing
    # them turned out to be spelling mismatches against table 7.3.1/1 — the
    # references resolve once one side is spelled the way the defining clause
    # heading spells it.
    Correction(
        target=table_row("Additional-Context-ID"),
        field="name",
        expect="Additional-Context-ID",
        replace="Additional-Context-Identifier",
        reason="clause 7.3.206's heading and body, and the ABNF reference in"
        " clause 7.3.34, all spell it Additional-Context-Identifier; only the"
        " table row abbreviates it",
        versions="18.6.0",
    ),
    Correction(
        target=avp_rule(
            "Requested-EUTRAN-Authentication-Info", "Re-synchronization-Info"
        ),
        field="name",
        expect="Re-synchronization-Info",
        replace="Re-Synchronization-Info",
        reason="clause 7.3.15's heading and table 7.3.1/1 both spell it"
        " Re-Synchronization-Info; clause 7.3.11's ABNF lower-cases the S",
        versions="18.6.0",
    ),
]
