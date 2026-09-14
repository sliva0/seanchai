"""Corrections for RFC 8581 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC7683"),
        reason=(
            "the OC-OLR extension references RFC 7683's OC- AVP family, which this "
            "document extends rather than re-declares"
        ),
    ),
]
