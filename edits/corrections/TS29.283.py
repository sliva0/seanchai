"""Corrections for 3GPP TS 29.283 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    reused_row,
    value_row,
)

CORRECTIONS = [
    Delete(
        id="feature-id-row-not-in-origin",
        target=reused_row("Feature-Id"),
        expect=ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229"),
        reason="table 7.3.1-2 cites Feature-Id from TS 29.229, which neither"
        " defines nor tabulates any such AVP in any version; the Supported-"
        "Features mechanism's real AVPs (Feature-List-ID, Feature-List) are"
        " already listed on the adjacent rows",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="drmp-origin-rfc",
        target=reused_row("DRMP"),
        field="origin",
        expect="RFC7844",
        replace="RFC7944",
        reason="RFC 7844 is about DHCP anonymity and defines no DRMP AVP;"
        " RFC 7944 defines DRMP with code 301",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="unknown-data-result-spelling",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_ UNKNOWN _DATA"),
        field="name",
        expect="DIAMETER_ERROR_ UNKNOWN _DATA",
        replace="DIAMETER_ERROR_UNKNOWN_DATA",
        reason="clause 7.4.3.12's heading prints two spaces inside the name; TS "
        "29.230 table 8.1.4 allocates 5670 to it, whose own misprint is "
        "corrected",
        versions="18.0.0..19.0.0",
    ),
]
