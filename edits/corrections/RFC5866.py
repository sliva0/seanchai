"""Corrections for RFC 5866 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_rule, header

CORRECTIONS = [
    Correction(
        id="bases-rfc5777",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC5777"),
        reason=(
            "clause 7.2 says 'This document reuses the AVPs defined in Section "
            "4 of [RFC5777]', and every command body lists its QoS-Resources"
        ),
    ),
    Correction(
        id="qaa-acct-multi-session-id",
        target=avp_rule("QoS-Authorization-Answer", "Acct-Multisession-Id"),
        field="name",
        expect="Acct-Multisession-Id",
        replace="Acct-Multi-Session-Id",
        reason="the QAA ABNF (clause 5.2) drops a hyphen of the base protocol's"
        " Acct-Multi-Session-Id (RFC 6733 clause 9.8.5, code 50); no document"
        " defines the printed spelling",
    ),
    *(
        Correction(
            id=f"{suffix}-authorization-lifetime",
            target=avp_rule(parent, "Authorization-Session-Lifetime"),
            field="name",
            expect="Authorization-Session-Lifetime",
            replace="Authorization-Lifetime",
            reason=f"the {suffix.upper()} ABNF (clause {clause}) writes"
            " Authorization-Session-Lifetime, which no document defines; clause"
            " 7.1's table of the base AVPs this application uses lists"
            " Authorization-Lifetime (code 291)",
        )
        for suffix, parent, clause in (
            ("qaa", "QoS-Authorization-Answer", "5.2"),
            ("qir", "QoS-Install-Request", "5.3"),
            ("rar", "Re-Auth-Request", "5.5"),
        )
    ),
    *(
        Correction(
            id=f"{suffix}-auth-grace-period",
            target=avp_rule(parent, "Authorization-Grace-Period"),
            field="name",
            expect="Authorization-Grace-Period",
            replace="Auth-Grace-Period",
            reason=f"the {suffix.upper()} ABNF (clause {clause}) writes"
            " Authorization-Grace-Period, which no document defines; clause"
            " 7.1's table of the base AVPs this application uses lists"
            " Auth-Grace-Period (code 276)",
        )
        for suffix, parent, clause in (
            ("qaa", "QoS-Authorization-Answer", "5.2"),
            ("qir", "QoS-Install-Request", "5.3"),
            ("rar", "Re-Auth-Request", "5.5"),
        )
    ),
    Correction(
        id="raa-redirect-max-cache-time",
        target=avp_rule("Re-Auth-Answer", "Redirect-Host-Max-Cache-Time"),
        field="name",
        expect="Redirect-Host-Max-Cache-Time",
        replace="Redirect-Max-Cache-Time",
        reason="the RAA ABNF (clause 5.6) writes Redirect-Host-Max-Cache-Time,"
        " which no document defines; the base protocol's RAA carries"
        " Redirect-Max-Cache-Time (RFC 6733 clause 6.14, code 262) after the"
        " Redirect-Host and Redirect-Host-Usage this body also lists",
    ),
    Insert(
        id="undefined-authorization-session-volume",
        into=header(),
        node=ast.UndefinedAvp(
            name="Authorization-Session-Volume",
            source=ast.SourceRef(section="5.3", page=32),
        ),
        after=None,
        reason=(
            "the QIR (clause 5.3) and RAR (clause 5.5) bodies list it and no "
            "clause or table defines it; clause 7.1's table of base AVPs omits "
            "it, RFC 5866 has no errata, IANA's AVP Codes registry assigns it "
            "nothing and Wireshark's dictionary has no such AVP"
        ),
    ),
]

# The application ids prose states; the command headers omit them.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter QoS application",
            source=ast.SourceRef(section="5", page=29),
            application_id=9,
            applies_to=("5.1.*", "5.2.*", "5.3.*", "5.4.*"),
        ),
        after=None,
        reason=(
            "clause 5 says 'The value of 9 MUST be used as the Application-Id "
            "in all QAR/QAA and QIR/QIA commands', and clause 10.2 records "
            "IANA's allocation"
        ),
    ),
    Insert(
        id="application-id-common",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter common message",
            source=ast.SourceRef(section="5", page=29),
            application_id=0,
            applies_to=("5.5.*", "5.6.*"),
        ),
        after=None,
        reason=(
            "clause 5 says 'The value of zero (0) SHOULD be used as the "
            "Application-Id in all STR/STA, ASR/ASA, and RAR/RAA commands', and "
            "clauses 5.5 and 5.6 print RAR and RAA"
        ),
    ),
]
