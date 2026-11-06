"""Corrections for 3GPP TS 29.329 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Delete, table_row

CORRECTIONS = [
    Delete(
        id="load-row-not-local",
        target=table_row("Load"),
        expect=ast.AvpTableRow(
            name="Load",
            code=None,
            section="6.3.35",
            data_type=ast.DataType.GROUPED,
            flag_rules=ast.AvpFlagRules(
                must_not=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR})
            ),
            may_encrypt=False,
        ),
        reason="table 6.3.1 prints Load with no AVP code because it is not"
        " this document's AVP: clause 6.3.35 says it is defined in RFC 8583,"
        " and table 6.3/2 already lists it as re-used from there — the"
        " code-less table row is the same fact printed in the wrong table",
        versions="18.0.0..19.1.0",
    ),
]
