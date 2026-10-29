"""Corrections for RFC 4006 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, header

CORRECTIONS = [
    Correction(
        id="bases-nasreq",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4005"),
        reason=(
            "the CCR/CCA ABNFs reference Filter-Id, which NASREQ (RFC 4005) defines; "
            "the document's normative references cite NASREQ for it"
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
            source=ast.SourceRef(section="12.1", page=86),
            application_id=4,
            scope=("3",),
        ),
        after=None,
        reason=(
            "clause 12.1: 'This specification assigns the value 4, 'Diameter "
            "Credit Control', to the Application Identifier namespace'; the "
            "CCR/CCA headers print none"
        ),
    ),
]
