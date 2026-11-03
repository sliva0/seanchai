"""Corrections for RFC 6737 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Insert, header

# The application id prose states; both command headers omit it.
CORRECTIONS = [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter Capabilities Update",
            source=ast.SourceRef(section="3", page=3),
            application_id=10,
            applies_to=("4.*",),
        ),
        after=None,
        reason=(
            "clause 3 'specifies Diameter Application-Id 10' and clause 6.1 "
            "records IANA's allocation; clause 4.1 prints CUR and CUA with no "
            "id in their headers"
        ),
    ),
]
