"""Corrections for 3GPP TS 29.272 — see docs/proposal-corrections.md."""

from seanchai.dad.corrections import Correction, definition

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
