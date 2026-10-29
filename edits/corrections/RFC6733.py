"""Corrections for RFC 6733 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Insert, header

# Application ids the command headers omit and the prose states.
CORRECTIONS = [
    Insert(
        id="application-id-common",
        into=header(),
        node=ast.Application(
            name="Diameter common message",
            source=ast.SourceRef(section="2.5", page=25),
            application_id=0,
            scope=("5",),
        ),
        after=None,
        reason=(
            "clause 2.5: 'CER/CEA, DWR/DWA, and DPR/DPA MUST carry an "
            "Application Id of zero (0)', the 'Diameter common message' id of "
            "clause 2.4; the headers print none. The RAR, STR and ASR of clause "
            "8 'MUST carry the Application Id of the application' and get no "
            "block"
        ),
    ),
    Insert(
        id="application-id-accounting",
        into=header(),
        node=ast.Application(
            name="Diameter base accounting",
            source=ast.SourceRef(section="9.3", page=124),
            application_id=3,
            scope=("9",),
        ),
        after=None,
        reason=(
            "clause 9.3: under the split accounting model 'The accounting "
            "message will carry the Application Id of the Diameter base "
            "accounting application', 3 in clause 2.4; the ACR/ACA headers "
            "print none. Under the coupled model the same commands carry the "
            "using application's id"
        ),
    ),
]
