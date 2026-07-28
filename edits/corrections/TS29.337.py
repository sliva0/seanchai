"""Corrections for 3GPP TS 29.337 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Insert, reused_avps

# The T4-specific Serving-Node and Additional-Serving-Node bodies (clauses
# 6.3.3, 6.3.4) use six member AVPs that table 6.3.1/2 does not list, though
# it lists every other member those bodies use (the IP-SM-GW-* family from
# TS 29.336, the SMSF-* family from TS 29.338, MME-Number-for-MT-SMS from
# TS 29.272). The origins follow the same table: TS 29.173 defines five and
# itself re-uses SGSN-Number from TS 29.272, which is where this document's
# own MME-Number-for-MT-SMS row already points.
_MISSING = (
    ("MME-Name", "TS29.173"),
    ("MME-Realm", "TS29.173"),
    ("MSC-Number", "TS29.173"),
    ("SGSN-Name", "TS29.173"),
    ("SGSN-Realm", "TS29.173"),
    ("SGSN-Number", "TS29.272"),
)

CORRECTIONS = [
    Insert(
        into=reused_avps("6.3.1/2"),
        node=ast.ReusedAvpRow(name=name, origin=origin),
        after=after,
        reason=f"the Serving-Node and Additional-Serving-Node bodies (clauses"
        f" 6.3.3, 6.3.4) use {name} but table 6.3.1/2 omits the row while"
        " listing every other member those bodies use;"
        f" {origin} defines the AVP",
        versions="18.0.0",
    )
    for (name, origin), after in zip(
        _MISSING,
        ("Additional-Serving-Node", "MME-Name", "MME-Realm", "MSC-Number",
         "SGSN-Name", "SGSN-Realm"),
    )
]
