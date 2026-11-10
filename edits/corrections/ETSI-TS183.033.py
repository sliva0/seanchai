"""Corrections for ETSI TS 183 033 — see docs/corrections.md.

The input is the transcription (`raw/etsi/ts183033-010200.raw.dad`), which
records what the PDF prints. The document endorses TS 29.229 and prints what it
changes, so it uses TS 29.229's AVPs without tabulating them; clause 2.1 [2]
names V6.6.0 (the corpus's `corpus.toml`, `release_stand_in`)."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Delete,
    Insert,
    definition,
    reused_avps,
)

_ADDED = [
    ("ETSI-SIP-Authorization", "Line-Identifier"),
    ("ETSI-SIP-Authenticate", "ETSI-SIP-Authorization"),
    ("ETSI-SIP-Authentication-Info", "ETSI-SIP-Authenticate"),
]

_INHERITED = (
    "SIP-Item-Number",
    "SIP-Authentication-Scheme",
    "SIP-Authenticate",
    "SIP-Authorization",
    "SIP-Authentication-Context",
    "Confidentiality-Key",
    "Integrity-Key",
)

CORRECTIONS = [
    Accept(
        id="sip-auth-data-item-endorsed-change",
        rule="reused-body-differs",
        target=definition("SIP-Auth-Data-Item"),
        expect="SIP-Auth-Data-Item's body, against TS29.229's definition: adds"
        " ETSI-SIP-Authenticate, ETSI-SIP-Authentication-Info,"
        " ETSI-SIP-Authorization, missing Framed-IP-Address, Framed-IPv6-Prefix,"
        " Framed-Interface-Id, SIP-Digest-Authenticate",
        reason="clause 6.3.13 is 'Endorsed with the following change' and clause"
        " ZA.2 says the AVP 'is modified compared to 3GPP TS 29.229 [2] as follows';"
        " the members it lacks are later than V6.6.0, the version clause 2.1 [2]"
        " names, whose body prints none of them",
        versions="1.2.0",
    ),
    Insert(
        id="sip-auth-data-item-reused",
        into=reused_avps("6.3.1"),
        node=ast.ReusedAvpRow(name="SIP-Auth-Data-Item", origin="TS29.229"),
        after=None,
        reason="clause 4: 'The elements of 3GPP TS 29.228 [1] and 3GPP TS 29.229"
        " [2] apply, with the following modifications'; clause 6.3.13 prints the"
        " AVP's body under TS 29.229's vendor and code, 612 10415, which is no"
        " definition of the file's own, and table 6.3.1 prints only the addition",
        versions="1.2.0",
    ),
    Delete(
        id="sip-auth-data-item-annex-body",
        target=definition("SIP-Auth-Data-Item", section="ZA.2"),
        expect=ast.GroupedAvp(
            name="SIP-Auth-Data-Item",
            source=ast.SourceRef(section="ZA.2", page=18),
            code=612,
            vendor_id=10415,
            avps=(
                *(
                    ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL)
                    for name in _INHERITED
                ),
                *(
                    ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL)
                    for name, _ in _ADDED
                ),
                ast.AvpRule(
                    name="AVP",
                    presence=ast.Presence.OPTIONAL,
                    min_occurs=0,
                    max_occurs=None,
                ),
            ),
        ),
        reason="clauses 6.3.13 and ZA.2 each print the AVP as TS 29.229 modified,"
        " the one adding Line-Identifier and the other, for HTTP Digest, three"
        " ETSI-SIP- members; one AVP has one body, and both changes apply, so"
        " clause 6.3.13's carries clause ZA.2's additions",
        versions="1.2.0",
    ),
] + [
    Insert(
        id=f"sip-auth-data-item-{name.lower()}",
        into=definition("SIP-Auth-Data-Item", section="6.3.13"),
        node=ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL),
        after=after,
        reason="clause ZA.2 (HTTP Digest) adds the member to the AVP clause 6.3.13"
        " also modifies, and prints it underlined, the mark clause 4's note gives a"
        " modification",
        versions="1.2.0",
    )
    for name, after in _ADDED
]
