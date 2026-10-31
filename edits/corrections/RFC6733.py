"""Corrections for RFC 6733 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Insert, Supply, definition, header

# Application ids the command headers omit and the prose states.
CORRECTIONS = [
    Insert(
        id="application-id-common",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter common message",
            source=ast.SourceRef(section="2.5", page=25),
            application_id=0,
            applies_to=("5.*",),
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
        node=ast.ApplicationScope(
            name="Diameter base accounting",
            source=ast.SourceRef(section="9.3", page=124),
            application_id=3,
            applies_to=("9.*",),
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

# Termination-Cause's values, from the IANA registry clause 8.15 cites. The
# registry also holds 11 to 32, RADIUS-derived, which it attributes to RFC
# 2866, RFC 3580 and RFC 7155 and which RFC 4005's file already defines, so
# only the values it attributes to RFC 3588 and this document are supplied,
# with its reservation of 0: RFC 6733 is not made a second definer of
# NASREQ's values.
CORRECTIONS += [
    Supply(
        id="termination-cause-values",
        target=definition("Termination-Cause"),
        expect="the IANA registry for Termination-Cause AVP Values [IANATCV]",
        values=(
            ast.ReservedValues(first=0, last=0),
            *(
                ast.EnumValue(name=name, value=value)
                for value, name in enumerate(
                    (
                        "DIAMETER_LOGOUT",
                        "DIAMETER_SERVICE_NOT_PROVIDED",
                        "DIAMETER_BAD_ANSWER",
                        "DIAMETER_ADMINISTRATIVE",
                        "DIAMETER_LINK_BROKEN",
                        "DIAMETER_AUTH_EXPIRED",
                        "DIAMETER_USER_MOVED",
                        "DIAMETER_SESSION_TIMEOUT",
                    ),
                    start=1,
                )
            ),
        ),
        reason="clause 8.15 finds the values 'in the IANA registry for"
        " Termination-Cause AVP Values [IANATCV]', aaa-parameters-16 of the"
        " AAA Parameters file Last Updated 2026-01-27: 0 Reserved, and 1 to 8"
        " referencing RFC 3588 and RFC 6733; its 11 to 32, RADIUS-derived,"
        " are RFC 4005's",
    ),
]
