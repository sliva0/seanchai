"""Corrections for RFC 7155 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=('RFC6733', 'RFC4005'),
        reason="the command ABNFs reference NAS-IP-Address, NAS-Identifier, State and their siblings, whose rows this document's own tables print with a 'Defined in' pointing at their RADIUS-era origins; RFC 4005 defines and tabulates them",
    ),
]
