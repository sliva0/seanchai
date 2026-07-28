"""Corrections for 3GPP TS 29.283 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Delete, reused_row

CORRECTIONS = [
    Delete(
        target=reused_row("Feature-Id"),
        expect=ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229"),
        reason="table 7.3.1-2 cites Feature-Id from TS 29.229, which neither"
        " defines nor tabulates any such AVP in any version; the Supported-"
        "Features mechanism's real AVPs (Feature-List-ID, Feature-List) are"
        " already listed on the adjacent rows",
        versions="18.0.0",
    ),
    Correction(
        target=reused_row("DRMP"),
        field="origin",
        expect="RFC7844",
        replace="RFC7944",
        reason="RFC 7844 is about DHCP anonymity and defines no DRMP AVP;"
        " RFC 7944 defines DRMP with code 301",
        versions="18.0.0",
    ),
]
