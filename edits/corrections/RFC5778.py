"""Corrections for RFC 5778 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=('RFC6733', 'RFC4004', 'RFC4005', 'RFC4072', 'RFC5447', 'RFC5777'),
        reason="the MIP6 application's command ABNFs use RFC 4004's MIP- AVPs, NASREQ's NAS- and Station-Id AVPs, RFC 4072's EAP- AVPs, RFC 5447's MIP6- AVPs and RFC 5777's QoS-Resources without a re-used table; its mixed application tables cite those documents by name",
    ),
]
