"""Corrections for RFC 6736 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Insert, header

# The application id prose states; both command headers omit it.
CORRECTIONS = [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter NAT Control Application",
            source=ast.SourceRef(section="8.1", page=29),
            application_id=12,
            applies_to=("6.*",),
        ),
        after=None,
        reason=(
            "clause 8.1 says 'The value of the Auth-Application-Id for the "
            "Diameter NAT Control Application is 12' and clause 11.1 records "
            "IANA's allocation; clause 6 prints NCR and NCA with no id in their "
            "headers"
        ),
    ),
]
