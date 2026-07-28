"""Corrections for RFC 4072 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=('RFC6733', 'RFC4005'),
        reason="the DER/DEA ABNFs reference thirty-odd NASREQ AVPs (Callback-Id, the Framed- and NAS- families, Service-Type, Tunneling) without a re-used table; RFC 4072 is the EAP application of NASREQ and its normative references cite RFC 4005 for them",
    ),
]
