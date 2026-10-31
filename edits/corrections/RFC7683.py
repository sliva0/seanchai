"""Corrections for RFC 7683 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Insert, definition

CORRECTIONS = [
    Insert(
        id="peer-report-rfc8581",
        into=definition("OC-Report-Type"),
        node=ast.EnumValue(name="PEER_REPORT", value=2),
        after="REALM_REPORT",
        reason=(
            "RFC 8581 clause 7.2.1: 'The following new report type is defined"
            " for the OC-Report-Type AVP. PEER_REPORT 2'; the value extends the"
            " list RFC 7683 clause 7.6 defines, and RFC 8581's own file has no"
            " definition of the AVP to hold it"
        ),
    ),
]
