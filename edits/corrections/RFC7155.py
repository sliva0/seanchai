"""Corrections for RFC 7155 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_rule, header

CORRECTIONS = [
    # The redirect family, inherited verbatim from RFC 4005's RAA and ASA
    # ABNFs and corrected the same way there. Verified errata 5993 and 5994
    # confirm the intended RFC 6733 names.
    *(
        Correction(
            id=f"{parent.lower()}-{wrong.lower()}",
            target=avp_rule(parent, wrong),
            field="name",
            expect=wrong,
            replace=right,
            reason=f"the {parent} ABNF writes {wrong}; RFC 6733 defines"
            f" {right} and no Redirected-* AVP exists; verified errata"
            " 5993/5994 correct the spelling",
        )
        for parent, wrong, right in (
            ("Re-Auth-Answer", "Redirected-Host", "Redirect-Host"),
            ("Re-Auth-Answer", "Redirected-Host-Usage", "Redirect-Host-Usage"),
            ("Re-Auth-Answer", "Redirected-Host-Cache-Time", "Redirect-Max-Cache-Time"),
            ("Abort-Session-Answer", "Redirected-Host", "Redirect-Host"),
            ("Abort-Session-Answer", "Redirected-Host-Usage", "Redirect-Host-Usage"),
            (
                "Abort-Session-Answer",
                "Redirected-Max-Cache-Time",
                "Redirect-Max-Cache-Time",
            ),
        )
    ),
    Correction(
        id="acr-connection-info",
        target=avp_rule("Accounting-Request", "Connection-Info"),
        field="name",
        expect="Connection-Info",
        replace="Connect-Info",
        reason="the ACR ABNF (clause 3.9) writes Connection-Info; the AVP is"
        " Connect-Info (code 77), defined in clause 4.2.7 and carried by the"
        " AAR ABNF; verified erratum 5995 corrects the typo",
    ),
    Correction(
        id="bases-nasreq",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4005"),
        reason=(
            "the command ABNFs reference NAS-IP-Address, NAS-Identifier, State and "
            "their siblings, whose rows this document's own tables print with a "
            "'Defined in' pointing at their RADIUS-era origins; RFC 4005 defines and "
            "tabulates them"
        ),
    ),
]

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="NASREQ",
            source=ast.SourceRef(section="1.5", page=8),
            application_id=1,
            applies_to=("3.*",),
        ),
        after=None,
        reason=(
            "clause 1.5: the Auth-Application-Id 'MUST be set to the value one "
            "(1)' in AAR, RAR, STR and ASR, and clause 1.6 recommends one (1) "
            "for ACR/ACA too; the command headers print none"
        ),
    ),
]
