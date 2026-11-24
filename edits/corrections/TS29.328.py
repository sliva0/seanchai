"""Corrections for 3GPP TS 29.328 — see docs/corrections.md."""

from seanchai.dad.corrections import Accept, information_elements

CORRECTIONS = [
    Accept(
        id="user-identity-content-unattached",
        rule="elements-unattached",
        target=information_elements("7.1.1"),
        expect="table 7.1.1 names no command; a correction names the one it describes",
        reason="table 7.1.1, 'User Identity content', tabulates the User Identity"
        " information element, 'IMS Public User Identity, Public Service Identity,"
        " MSISDN or External Identifier according to the conditions described in"
        " table 7.1.1' (clause 7.1), which tables 6.1.1.1, 6.1.2.1, 6.1.3.1 and"
        " 6.1.4.1 map to User-Identity in Sh-Pull, Sh-Update, Sh-Subs-Notif and"
        " Sh-Notif: four commands, where a table names one",
        versions="18.2.0..19.2.0",
    )
]
