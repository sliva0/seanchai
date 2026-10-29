"""Corrections for RFC 8506 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, header

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

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.Application(
            name="Diameter Credit Control",
            source=ast.SourceRef(section="12.1", page=97),
            application_id=4,
            scope=("3",),
        ),
        after=None,
        reason=(
            "clause 12.1: 'This specification assigns the value 4, \"Diameter "
            'Credit Control", to the "Application IDs" namespace\'; the CCR/CCA '
            "headers print none"
        ),
    ),
]
