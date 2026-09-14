"""Corrections for 3GPP TS 29.229 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    Insert,
    reused_avps,
    reused_row,
    table_row,
)
from seanchai.versions import VersionRange

CORRECTIONS = [
    Delete(
        id="load-row-not-local",
        target=table_row("Load"),
        expect=ast.AvpTableRow(
            name="Load",
            code=None,
            section="6.3.68",
            data_type=ast.DataType.GROUPED,
            flag_rules=ast.AvpFlagRules(
                must_not=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR})
            ),
            may_encrypt=False,
        ),
        reason="table 6.3.0.1 prints Load with no AVP code because it is not"
        " this document's AVP: clause 6.3.68 says it is defined in RFC 8583,"
        " so the row belongs in the re-used table, where the next edit puts it",
        versions=VersionRange.exact("18.1.0"),
    ),
    Insert(
        id="load-row-reused",
        into=reused_avps("6.3.0.1"),
        node=ast.ReusedAvpRow(name="Load", origin="RFC8583"),
        after="DRMP",
        reason="clause 6.3.68 defines Load only by reference to RFC 8583, the"
        " same wording DRMP's clause uses for RFC 7944, but table 6.3.0.1"
        " lists DRMP as re-used and prints Load as a code-less local row",
        versions=VersionRange.exact("18.1.0"),
    ),
    Correction(
        id="digest-qop-case",
        target=reused_row("Digest-QoP"),
        field="name",
        expect="Digest-QoP",
        replace="Digest-Qop",
        reason="table 6.3.0.1 cites RFC 4590, whose registered attribute name"
        " is Digest-Qop; the table uniquely capitalizes its final letter",
        versions=VersionRange.exact("18.1.0"),
    ),
]
