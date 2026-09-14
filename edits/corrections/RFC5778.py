"""Corrections for RFC 5778 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, avp_rule, header

CORRECTIONS = [
    Correction(
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
        target=avp_rule("Diameter-EAP-Answer", "Multi-Round-Time"),
        field="name",
        expect="Multi-Round-Time",
        replace="Multi-Round-Time-Out",
        reason="the DEA ABNF (clause 5.1.2) drops the -Out; the AVP is"
        " RFC 6733's Multi-Round-Time-Out (code 272), and RFC 4072's DEA,"
        " which this ABNF extends, spells it fully",
    ),
    Correction(
        target=avp_rule("MIP6-Request", "Session-ID"),
        field="name",
        expect="Session-ID",
        replace="Session-Id",
        reason="the MIR ABNF (clause 5.2.1) capitalizes the D; the AVP is"
        " RFC 6733's Session-Id (code 263), spelled Session-Id in this"
        " document's every other ABNF",
    ),
    Correction(
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
