"""Corrections for RFC 5447 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4004"),
        reason=(
            "clause 4.2.1's MIP6-Agent-Info body references MIP-Home-Agent-Address "
            "and MIP-Home-Agent-Host, which RFC 4004 defines"
        ),
    ),
]
