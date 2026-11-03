"""Corrections for RFC 6738 — see docs/corrections.md."""

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
            "clause 5.1's IKESKR body lists NAS-Identifier, NAS-IP-Address, "
            "NAS-IPv6-Address and NAS-Port, which no table of this document "
            "holds; the document cites no origin for them and RFC 4005 defines "
            "all four"
        ),
    ),
]

# The application id prose states; both command headers omit it.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter IKE SK",
            source=ast.SourceRef(section="3", page=5),
            application_id=11,
            applies_to=("5.*",),
        ),
        after=None,
        reason=(
            "clause 3 defines 'Diameter IKE SK (IKESK) 11', and clause 5.1 "
            "sets the header's Application-Id to 'the Diameter IKE SK "
            "Application-Id (11)'; clause 5 prints IKESKR and IKESKA with no "
            "id in their headers"
        ),
    ),
]
