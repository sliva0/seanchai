"""Corrections for 3GPP TS 29.283 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Delete, reused_row

CORRECTIONS = [
    Delete(
        id="sequence-number-origin-is-another-avp",
        target=reused_row("Sequence-Number"),
        expect=ast.ReusedAvpRow(name="Sequence-Number", origin="TS29.329"),
        reason="clause 7.3.21 cites TS 29.329, but table 7.3.1-1 gives"
        " this MC service profile's Sequence-Number code 4512; TS 29.230"
        " allocates 4512 to TS 29.283 and separately allocates 716 to"
        " TS 29.329's Sh Sequence-Number, so the citation does not identify"
        " this AVP's origin and following it would change its wire identity",
        versions="18.0.0",
    ),
    Delete(
        id="feature-id-row-not-in-origin",
        target=reused_row("Feature-Id"),
        expect=ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229"),
        reason="table 7.3.1-2 cites Feature-Id from TS 29.229, which neither"
        " defines nor tabulates any such AVP in any version; the Supported-"
        "Features mechanism's real AVPs (Feature-List-ID, Feature-List) are"
        " already listed on the adjacent rows",
        versions="18.0.0",
    ),
    Correction(
        id="drmp-origin-rfc",
        target=reused_row("DRMP"),
        field="origin",
        expect="RFC7844",
        replace="RFC7944",
        reason="RFC 7844 is about DHCP anonymity and defines no DRMP AVP;"
        " RFC 7944 defines DRMP with code 301",
        versions="18.0.0",
    ),
]
