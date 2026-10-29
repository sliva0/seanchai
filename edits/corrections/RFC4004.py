"""Corrections for RFC 4004 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_rule, header, table_row

CORRECTIONS = [
    Correction(
        id="amr-session-id-case",
        target=avp_rule("AA-Mobile-Node-Request", "Session-ID"),
        field="name",
        expect="Session-ID",
        replace="Session-Id",
        reason="the AMR ABNF (clause 5.1) capitalizes the D; the AVP is the"
        " base protocol's Session-Id (code 263), spelled Session-Id in this"
        " document's every other ABNF",
    ),
    *(
        Correction(
            id=f"mip-nonce-case-{parent.lower()}",
            target=avp_rule(parent, "MIP-nonce"),
            field="name",
            expect="MIP-nonce",
            replace="MIP-Nonce",
            reason=f"the {parent} ABNF (clause {clause}) lowercases the"
            " name; clause 9.12 defines MIP-Nonce (code 335) and the AVP"
            " table spells it the same way",
        )
        for parent, clause in (
            ("MIP-MN-to-FA-MSA", "9.5"),
            ("MIP-MN-to-HA-MSA", "9.6"),
        )
    ),
    Correction(
        id="mip-home-agent-host-type",
        target=table_row("MIP-Home-Agent-Host"),
        field="data_type",
        expect=ast.DataType.DIAMETER_IDENTITY,
        replace=ast.DataType.GROUPED,
        reason="table 7 says DiameterIdentity, but clause 7.11 explicitly"
        " defines MIP-Home-Agent-Host as Grouped and prints its grouped ABNF",
    ),
]

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.Application(
            name="Diameter Mobile IPv4",
            source=ast.SourceRef(section="4", page=20),
            application_id=2,
            scope=("5",),
        ),
        after=None,
        reason=(
            "clause 4: 'The value of two (2) MUST be used as the Application-Id "
            "in all AMR/AMA and HAR/HAA commands'; the command headers print "
            "none"
        ),
    ),
]
