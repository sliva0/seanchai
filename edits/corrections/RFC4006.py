"""Corrections for RFC 4006 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=('RFC6733', 'RFC4005'),
        reason="the CCR/CCA ABNFs reference Filter-Id, which NASREQ (RFC 4005) defines; the document's normative references cite NASREQ for it",
    ),
]
