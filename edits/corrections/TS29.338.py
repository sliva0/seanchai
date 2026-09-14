"""Corrections for 3GPP TS 29.338 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, definition, reused_avps
from seanchai.versions import VersionRange

CORRECTIONS = [
    Insert(
        id="ip-sm-gw-realm-row-missing",
        into=reused_avps("5.3.3.1/2"),
        node=ast.ReusedAvpRow(name="IP-SM-GW-Realm", origin="TS29.336"),
        after="IP-SM-GW-Number",
        reason="the Serving-Node body (clause 5.3.3.6) uses IP-SM-GW-Realm"
        " but table 5.3.3.1/2 lists only IP-SM-GW-Name and IP-SM-GW-Number;"
        " TS 29.336 clause 6.4.18 defines it beside the two listed ones",
        versions=VersionRange.exact("18.2.0"),
    ),
    Correction(
        id="smsmi-correlation-id-name",
        target=definition("SMS-MI-Correlation-ID", section="6.3.3.13"),
        field="name",
        expect="SMS-MI-Correlation-ID",
        replace="SMSMI-Correlation-ID",
        reason="clause 6.3.3.13's AVP format writes 'SMS-MI-Correlation-ID';"
        " the clause heading, the clause prose, table 6.3.3.1-1 and every"
        " command ABNF in the document spell it 'SMSMI-Correlation-ID'",
        versions=VersionRange.exact("18.2.0"),
    ),
    Correction(
        id="smsmi-correlation-id-code",
        target=definition("SMS-MI-Correlation-ID", section="6.3.3.13"),
        field="code",
        expect=3308,
        replace=3324,
        reason="clause 6.3.3.13's AVP format re-prints SM-RP-MTI's code 3308"
        " (clause 5.3.3.2); table 6.3.3.1-1 gives SMSMI-Correlation-ID the"
        " code 3324",
        versions=VersionRange.exact("18.2.0"),
    ),
]
