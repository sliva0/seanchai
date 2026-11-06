"""Corrections for 3GPP TS 29.229 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    Insert,
    avp_rule,
    avp_table,
    reused_avps,
    reused_row,
    table_row,
)

CORRECTIONS = [
    Insert(
        id="wildcarded-impu-row-missing",
        into=avp_table("6.3.0.1"),
        node=ast.AvpTableRow(
            name="Wildcarded-IMPU",
            section="6.3.43",
            data_type=ast.DataType.UTF8_STRING,
        ),
        after="Wildcarded-Public-Identity",
        reason="clause 6.3.43 defines Wildcarded-IMPU as UTF8String, but table"
        " 6.3.0.1 omits it; the clause states no code, flag rule or encryption,"
        " so the row leaves those cells blank",
        versions="18.1.0..19.1.0",
        drawn_from="clause 6.3.43",
    ),
    Delete(
        id="load-row-not-local",
        target=table_row("Load"),
        expect=ast.AvpTableRow(
            name="Load",
            code=None,
            section="6.3.68",
            data_type=ast.DataType.GROUPED,
            flag_rules=ast.AvpFlagRules(
                must_not=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR})
            ),
            may_encrypt=False,
        ),
        reason="table 6.3.0.1 prints Load with no AVP code because it is not"
        " this document's AVP: clause 6.3.68 says it is defined in RFC 8583,"
        " so the row belongs in the re-used table, where the next edit puts it",
        versions="18.1.0..19.1.0",
    ),
    Insert(
        id="load-row-reused",
        into=reused_avps("6.3.0.1"),
        node=ast.ReusedAvpRow(name="Load", origin="RFC8583"),
        after="DRMP",
        reason="clause 6.3.68 defines Load only by reference to RFC 8583, the"
        " same wording DRMP's clause uses for RFC 7944, but table 6.3.0.1"
        " lists DRMP as re-used and prints Load as a code-less local row",
        versions="18.1.0..19.1.0",
        drawn_from="clause 6.3.68",
    ),
    Correction(
        id="digest-qop-case",
        target=reused_row("Digest-QoP"),
        field="name",
        expect="Digest-QoP",
        replace="Digest-Qop",
        reason="table 6.3.0.1 cites RFC 4590, whose registered attribute name"
        " is Digest-Qop; the table uniquely capitalizes its final letter",
        versions="18.1.0..19.1.0",
    ),
    # The same name on the row stating Cx's flag rules for it, V in Must not
    # (code 110, RFC 4590's IETF space), and in the body using it.
    Correction(
        id="digest-qop-row-case",
        target=table_row("Digest-QoP", table="6.3.0.1"),
        field="name",
        expect="Digest-QoP",
        replace="Digest-Qop",
        reason="the row tabulates code 110 with V in Must not, RFC 4590's"
        " attribute, which section 3.8 names Digest-Qop; NOTE 3 says these"
        " attributes are defined in RFC 4590",
        versions="18.1.0..19.1.0",
    ),
    Correction(
        id="digest-qop-member-case",
        target=avp_rule("SIP-Digest-Authenticate", "Digest-QoP"),
        field="name",
        expect="Digest-QoP",
        replace="Digest-Qop",
        reason="clause 6.3.36's member is RFC 4590's attribute, which section"
        " 3.8 names Digest-Qop; clause 6.3.40 says the AVP is defined"
        " elsewhere (RFC 4740, which imports it from RFC 4590)",
        versions="18.1.0..19.1.0",
    ),
    Insert(
        id="framed-ip-address-reused",
        into=reused_avps("6.3.0.1"),
        node=ast.ReusedAvpRow(name="Framed-IP-Address", origin="RFC4005"),
        after=None,
        reason="clause 6.3.53 says the Framed-IP-Address AVP 'is defined in"
        " IETF RFC 4005 [19]'; SIP-Auth-Data-Item (6.3.13) uses it, and table"
        " 6.3.0.1 omits it",
        versions="18.1.0..19.1.0",
        drawn_from="clause 6.3.53",
    ),
    Insert(
        id="framed-ipv6-prefix-reused",
        into=reused_avps("6.3.0.1"),
        node=ast.ReusedAvpRow(name="Framed-IPv6-Prefix", origin="RFC4005"),
        after=None,
        reason="clause 6.3.54 says the Framed-IPv6-Prefix AVP 'is defined in"
        " IETF RFC 4005 [19]'; SIP-Auth-Data-Item (6.3.13) uses it, and table"
        " 6.3.0.1 omits it",
        versions="18.1.0..19.1.0",
        drawn_from="clause 6.3.54",
    ),
    Insert(
        id="framed-interface-id-reused",
        into=reused_avps("6.3.0.1"),
        node=ast.ReusedAvpRow(name="Framed-Interface-Id", origin="RFC4005"),
        after=None,
        reason="clause 6.3.55 says the Framed-Interface-Id AVP 'is defined in"
        " IETF RFC 4005 [19]'; SIP-Auth-Data-Item (6.3.13) uses it, and table"
        " 6.3.0.1 omits it",
        versions="18.1.0..19.1.0",
        drawn_from="clause 6.3.55",
    ),
    # Clause 6.3.42 defines Line-Identifier in ETSI's vendor space, and the
    # table, whose rows are all the file's vendor or IETF's by their V flag,
    # prints no row for it. A Vendor-ID column, blank in every printed row,
    # is where the row states the vendor the clause gives it.
    Correction(
        id="vendor-id-column",
        target=avp_table("6.3.0.1"),
        field="columns",
        expect=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
            ast.AvpColumn.MUST,
            ast.AvpColumn.MAY,
            ast.AvpColumn.SHOULD_NOT,
            ast.AvpColumn.MUST_NOT,
            ast.AvpColumn.ENCRYPT,
        ),
        replace=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.VENDOR,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
            ast.AvpColumn.MUST,
            ast.AvpColumn.MAY,
            ast.AvpColumn.SHOULD_NOT,
            ast.AvpColumn.MUST_NOT,
            ast.AvpColumn.ENCRYPT,
        ),
        reason="clause 6.3.42: Line-Identifier 'has Vendor Id ETSI (13019)',"
        " which no cell of table 6.3.0.1 can state; the printed rows' cells"
        " stay blank, their vendor the file's or IETF's by their V flag",
        versions="18.1.0..19.1.0",
    ),
    Insert(
        id="line-identifier-row-missing",
        into=avp_table("6.3.0.1"),
        node=ast.AvpTableRow(
            name="Line-Identifier",
            vendor_id=13019,
            code=500,
            section="6.3.42",
            data_type=ast.DataType.OCTET_STRING,
            flag_rules=ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR})),
        ),
        after="Digest-HA1",
        reason="clause 6.3.42: 'The Line-Identifier AVP is of type OctetString."
        " This AVP has Vendor Id ETSI (13019) and AVP code 500.' SIP-Auth-Data-Item"
        " (6.3.13) uses it and table 6.3.0.1 omits the row; V is in Must, as RFC"
        " 6733 section 4.1.1 sets it for a header carrying a Vendor-ID, and the"
        " clause states neither M nor encryption",
        versions="18.1.0..19.1.0",
    ),
    Delete(
        id="rta-session-id-repeated",
        target=avp_rule("Registration-Termination-Answer", "Session-Id", occurrence=2),
        expect=ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),
        reason="clause 6.1.10 prints RTA's '< Session-Id >' on two consecutive"
        " lines; RFC 6733 section 8.8 says a message MUST include only one"
        " Session-Id, and every other Cx command prints it once",
        versions="18.1.0..19.1.0",
    ),
    # V19.1.0 clause 6.3.61 prints OC-OLR with OC-Reg-Timer-Ext added.
    *(
        Insert(
            id=f"{name.lower()}-reused",
            into=reused_avps("6.3.0.1"),
            node=ast.ReusedAvpRow(name=name, origin="RFC7683"),
            after=None,
            reason="clause 6.3.61 prints OC-OLR 'extended from the format defined"
            f" in IETF RFC 7683 [23]', whose member {name} is; table 6.3.0.1 lists"
            " OC-OLR's origin and none of its members'",
            versions="19.1.0",
        )
        for name in (
            "OC-Sequence-Number",
            "OC-Report-Type",
            "OC-Reduction-Percentage",
            "OC-Validity-Duration",
        )
    ),
]
