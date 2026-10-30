"""Corrections for 3GPP TS 29.337 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Insert,
    avp_rule,
    definition,
    reused_avps,
    reused_row,
)

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
        id=f"missing-row-{name.lower()}",
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
        (
            "Additional-Serving-Node",
            "MME-Name",
            "MME-Realm",
            "MSC-Number",
            "SGSN-Name",
            "SGSN-Realm",
        ),
        strict=True,
    )
]

CORRECTIONS += [
    Correction(
        id="application-port-identifier-row-name",
        target=reused_row("SMS-Application-Port-ID"),
        field="name",
        expect="SMS-Application-Port-ID",
        replace="Application-Port-Identifier",
        reason="table 6.3.1/2 cites TS 29.368 for SMS-Application-Port-ID;"
        " TS 29.368 defines the AVP as Application-Port-Identifier (clause"
        " 6.4.11, code 3010)",
        versions="18.0.0",
    ),
    Correction(
        id="dtr-application-port-identifier",
        target=avp_rule("Device-Trigger-Request", "SMS-Application-Port-ID"),
        field="name",
        expect="SMS-Application-Port-ID",
        replace="Application-Port-Identifier",
        reason="the DTR ABNF (clause 6.2.3) uses table 6.3.1/2's"
        " SMS-Application-Port-ID; TS 29.368 clause 6.4.11 defines the AVP as"
        " Application-Port-Identifier",
        versions="18.0.0",
    ),
]

# Findings the linter reports that the document makes on purpose; they
# change no data (docs/corrections.md).
CORRECTIONS += [
    Accept(
        id="serving-node-t4-body",
        rule="reused-body-differs",
        target=definition("Serving-Node"),
        expect="Serving-Node's body, against TS29.173's definition: adds "
        "IP-SM-GW-Name, IP-SM-GW-Number, IP-SM-GW-Realm, MME-Number-for-MT-SMS, "
        "SMSF-3GPP-Name, SMSF-3GPP-Number, SMSF-3GPP-Realm, SMSF-Non-3GPP-Name, "
        "SMSF-Non-3GPP-Number, SMSF-Non-3GPP-Realm, missing 3GPP-AAA-Server-Name, "
        "GMLC-Address, LCS-Capabilities-Sets",
        reason="clause 6.3.3 says the AVP 'is originally defined in 3GPP TS 29.173 "
        "[8]' and lists the member combinations 'allowed' for T4-triggering, which "
        "name every member its body adds and none it leaves out",
        versions="18.0.0",
    ),
    Accept(
        id="additional-serving-node-t4-body",
        rule="reused-body-differs",
        target=definition("Additional-Serving-Node"),
        expect="Additional-Serving-Node's body, against TS29.173's definition: adds "
        "MME-Number-for-MT-SMS, SMSF-3GPP-Name, SMSF-3GPP-Number, SMSF-3GPP-Realm, "
        "SMSF-Non-3GPP-Name, SMSF-Non-3GPP-Number, SMSF-Non-3GPP-Realm, missing "
        "3GPP-AAA-Server-Name, GMLC-Address, LCS-Capabilities-Sets",
        reason="clause 6.3.4 says the AVP 'is originally defined in 3GPP TS 29.173 "
        "[8]' and lists the member combinations 'allowed' for T4-triggering, which "
        "name every member its body adds and none it leaves out",
        versions="18.0.0",
    ),
]
