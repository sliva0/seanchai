"""Corrections for RFC 6942 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Insert, header

# The application id prose states. The RFC prints no command of its own: it runs
# RFC 4072's DER and DEA under this id, so the block covers no `Message` here.
CORRECTIONS = [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter ERP",
            source=ast.SourceRef(section="7", page=12),
            application_id=13,
            applies_to=("5.2.*", "6.*"),
        ),
        after=None,
        reason=(
            "clause 7 defines 'Diameter ERP, with an Application Id value of "
            "13' and clause 10.1 records IANA's allocation; clauses 5.2 and 6 "
            "send the ERP/DER and ERP/DEA that clause 2 says carry it"
        ),
    ),
]
