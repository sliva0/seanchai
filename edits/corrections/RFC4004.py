"""Corrections for RFC 4004 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, avp_rule, table_row

CORRECTIONS = [
    Correction(
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
        target=table_row("MIP-Home-Agent-Host"),
        field="data_type",
        expect=ast.DataType.DIAMETER_IDENTITY,
        replace=ast.DataType.GROUPED,
        reason="table 7 says DiameterIdentity, but clause 7.11 explicitly"
        " defines MIP-Home-Agent-Host as Grouped and prints its grouped ABNF",
    ),
]
