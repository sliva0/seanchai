"""Corrections for 3GPP TS 29.230 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, registry_reservation

# Table 7.1's note on 1324-1399 follows the run of TS 32.299 rows ending at 1323
# and cites a document clause 2 does not list and no other row names: a
# transposition of TS 32.299, [5] in clause 2, which defines PSCell-Info and
# Nr-Cgi in the range.
CORRECTIONS = [
    Correction(
        id="reserved-1324-document",
        target=registry_reservation(1324, 1399),
        field="defined_in",
        expect=("TS32.229",),
        replace=("TS32.299",),
        reason="table 7.1's note reserves 1324 to 1399 'for TS 32.229', which clause"
        " 2 does not list; [5] is TS 32.299, every row before the range cites it and"
        " it defines PSCell-Info and Nr-Cgi inside the range",
        versions="19.3.0",
    ),
    Correction(
        id="reserved-1324-purpose",
        target=registry_reservation(1324, 1399),
        field="purpose",
        expect="TS 32.229",
        replace="TS 32.299",
        reason="the same note's words: 'reserved for TS 32.229' transposes clause"
        " 2's [5], TS 32.299",
        versions="19.3.0",
    ),
]
