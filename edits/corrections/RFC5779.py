"""Corrections for RFC 5779 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, header, reused_avps

CORRECTIONS = [
    Correction(
        id="bases-rfc4004",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4004"),
        reason=(
            "clause 5.1's MIP6-Agent-Info body extends RFC 5447's, whose "
            "MIP-Home-Agent-Address and MIP-Home-Agent-Host RFC 4004 defines"
        ),
    ),
    Insert(
        id="calling-station-id-reused",
        into=reused_avps(None, section="5.2"),
        node=ast.ReusedAvpRow(name="Calling-Station-Id", origin="RFC4005"),
        after=None,
        reason=(
            "clause 5.7 gives Calling-Station-Id's code 31 and type without "
            "citing a document, but clause 9.1 lists only codes 504 to 507 as "
            "new and clause 5 says some AVPs are re-used; clause 4 names NASREQ "
            "[RFC4005] as the kind of application carrying them, and it defines "
            "the AVP"
        ),
        drawn_from="clauses 4 and 5.7",
    ),
]
