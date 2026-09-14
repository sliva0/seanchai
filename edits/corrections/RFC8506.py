"""Corrections for RFC 8506 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, header

CORRECTIONS = [
    Correction(
        id="bases-nasreq-rfc5777",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4005", "RFC5777"),
        reason=(
            "the credit-control ABNFs reference NASREQ's Filter-Id and RFC 5777's "
            "Filter-Rule without a re-used table"
        ),
    ),
]
