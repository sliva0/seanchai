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
        id="mn-to-ha-msa-spi-name",
        target=avp_rule("MIP-MN-to-HA-MSA", "MIP-MN-HA-SPI"),
        field="name",
        expect="MIP-MN-HA-SPI",
        replace="MIP-MN-to-HA-SPI",
        reason="the MIP-MN-to-HA-MSA ABNF (clause 9.6) writes MIP-MN-HA-SPI,"
        " where its prose says 'The HA allocates the MIP-MN-to-HA-SPI' and"
        " the command AVP table of clause 11.1 lists MIP-MN-to-HA-SPI;"
        " verified erratum 1462 corrects the name. No clause defines either"
        " spelling, and the printed one is RFC 5778's later MIPv6 AVP (code"
        " 491)",
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
        node=ast.ApplicationScope(
            name="Diameter Mobile IPv4",
            source=ast.SourceRef(section="4", page=20),
            application_id=2,
            applies_to=("5.*",),
        ),
        after=None,
        reason=(
            "clause 4: 'The value of two (2) MUST be used as the Application-Id "
            "in all AMR/AMA and HAR/HAA commands'; the command headers print "
            "none"
        ),
    ),
]
