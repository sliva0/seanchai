"""Corrections for RFC 4004 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, table_row

CORRECTIONS = [
    Correction(
        target=table_row("MIP-Home-Agent-Host"),
        field="data_type",
        expect=ast.DataType.DIAMETER_IDENTITY,
        replace=ast.DataType.GROUPED,
        reason="table 7 says DiameterIdentity, but clause 7.11 explicitly"
        " defines MIP-Home-Agent-Host as Grouped and prints its grouped ABNF",
    ),
]
