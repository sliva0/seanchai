"""Corrections for RFC 8582 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        id="bases-rfc7683-rfc8581",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC7683", "RFC8581"),
        reason=(
            "the OC-OLR extension references RFC 7683's OC- AVP family and RFC 8581's"
            " SourceID, which this document extends rather than re-declares"
        ),
    ),
]
