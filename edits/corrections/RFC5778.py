"""Corrections for RFC 5778 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    Supply,
    avp_rule,
    definition,
    header,
)

CORRECTIONS = [
    Correction(
        id="mia-mip6-agent-info",
        target=avp_rule("MIP6-Answer", "MIP-Agent-Info"),
        field="name",
        expect="MIP-Agent-Info",
        replace="MIP6-Agent-Info",
        reason="the MIA ABNF (clause 5.2.2) writes MIP-Agent-Info, which no"
        " document defines; RFC 5447 defines MIP6-Agent-Info and this"
        " document's other ABNFs and tables use it; verified erratum 3035"
        " corrects the name",
    ),
    Correction(
        id="dea-multi-round-time-out",
        target=avp_rule("Diameter-EAP-Answer", "Multi-Round-Time"),
        field="name",
        expect="Multi-Round-Time",
        replace="Multi-Round-Time-Out",
        reason="the DEA ABNF (clause 5.1.2) drops the -Out; the AVP is"
        " RFC 6733's Multi-Round-Time-Out (code 272), and RFC 4072's DEA,"
        " which this ABNF extends, spells it fully",
    ),
    Correction(
        id="mir-session-id-case",
        target=avp_rule("MIP6-Request", "Session-ID"),
        field="name",
        expect="Session-ID",
        replace="Session-Id",
        reason="the MIR ABNF (clause 5.2.1) capitalizes the D; the AVP is"
        " RFC 6733's Session-Id (code 263), spelled Session-Id in this"
        " document's every other ABNF",
    ),
    Correction(
        id="bases-mip6-dependencies",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4004", "RFC4005", "RFC4072", "RFC5447", "RFC5777"),
        reason=(
            "the MIP6 application's command ABNFs use RFC 4004's MIP- AVPs, NASREQ's "
            "NAS- and Station-Id AVPs, RFC 4072's EAP- AVPs, RFC 5447's MIP6- AVPs "
            "and RFC 5777's QoS-Resources without a re-used table; its mixed "
            "application tables cite those documents by name"
        ),
    ),
]

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id-mip6i",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter Mobile IPv6 IKE (MIP6I)",
            source=ast.SourceRef(section="3", page=6),
            application_id=7,
            applies_to=("5.1.*",),
        ),
        after=None,
        reason=(
            "clause 3 defines MIP6I as 7, used with IKEv2, and clause 5.1.1 "
            "sets the DER's Application-ID to 'the Diameter Mobile IPv6 IKE "
            "Application ID (value of 7)'; the headers print none"
        ),
    ),
    Insert(
        id="application-id-mip6a",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter Mobile IPv6 Auth (MIP6A)",
            source=ast.SourceRef(section="3", page=6),
            application_id=8,
            applies_to=("5.2.*",),
        ),
        after=None,
        reason=(
            "clause 3 defines MIP6A as 8, used with the Mobile IPv6 "
            "Authentication Protocol, whose commands clause 5.2 defines; the "
            "MIR/MIA headers print none"
        ),
    ),
]

# Values the document takes from another.
CORRECTIONS += [
    Supply(
        id="mip-algorithm-type-values",
        target=definition("MIP-Algorithm-Type"),
        expect="[RFC4004] that also fulfill current RFC 4285 requirements",
        values=(ast.EnumValue(name="HMAC-SHA-1", value=2),),
        reason="RFC 4004 section 9.8 defines one value, '2 HMAC-SHA-1"
        " [HMAC]', as the IANA MIP-Algorithm-Type registry"
        " (aaa-parameters-19) still lists; RFC 4285's authentication is"
        " HMAC-SHA-1 too, so its requirement removes nothing",
    ),
]
