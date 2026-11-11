"""The model over the committed corpus: each rule docs/consumers.md states,
shown on documents a reader can check against the specifications.

`tests/test_export.py` pins the whole resolved corpus by digest; these tests
say which rule a change broke. Rules no committed document shows are in
`test_model_synthetic.py`, the hole and undefined policies in
`test_model_policies.py`.
"""

import dataclasses
import enum
import json

import pytest
from conftest import _ROOT

from seanchai import corpus, model
from seanchai.dad import ast
from seanchai.model import AvpFlag, FlagRules

_M = frozenset({AvpFlag.MANDATORY})
_V = frozenset({AvpFlag.VENDOR})
_P = frozenset({AvpFlag.PROTECTED})


@pytest.fixture(scope="module")
def built() -> model.Model:
    return model.Model.installed()


def _member(avp: model.Avp | None, name: str) -> model.Avp:
    """The AVP `avp`'s body names `name`."""
    assert isinstance(avp, model.Grouped)
    (found,) = [member.avp for member in avp.members if member.name == name]
    assert found is not None, name
    return found


def _message(built: model.Model, reference: str, abbreviation: str) -> model.Message:
    (found, *_) = [
        each for each in built.messages(reference) if each.abbreviation == abbreviation
    ]
    return found


# --- the public contract -----------------------------------------------------


@pytest.mark.parametrize("module", [model, corpus], ids=lambda each: each.__name__)
def test_every_public_name_imports(module):
    assert all(hasattr(module, name) for name in module.__all__)


def test_the_consumers_types_need_no_module_named_ast():
    assert model.DataType is ast.DataType
    assert model.AvpFlag is ast.AvpFlag
    assert model.CommandFlag is ast.CommandFlag
    assert model.RegistryKind is ast.RegistryKind
    assert model.ValueKind is ast.ValueKind


def test_a_model_is_built_only_through_its_builders(built):
    with pytest.raises(TypeError, match=r"Model\.build\(corpus\) or Model\.installed"):
        model.Model()

    rebuilt = model.Model.installed(undefined=model.UndefinedPolicy.DROP)
    assert rebuilt.undefined_policy is model.UndefinedPolicy.DROP
    assert rebuilt.references() == built.references()


def test_a_flag_cannot_be_both_placed_and_application_defined():
    with pytest.raises(ValueError, match="both placed and application-defined"):
        FlagRules(may=_M, application_defined=_M)


def test_every_model_type_has_a_one_line_repr_and_a_json_dict(built):
    undefined = built.undefined()[0]
    found = [
        *built.applications("TS29.229"),
        *built.messages("TS29.229"),
        *built.messages("TS29.229")[0].avps,
        *built.resolve("TS29.234", "Charging-Data").members,
        built.answer_message("TS29.229"),
        *built.avps("TS32.299"),
        *built.holes(),
        *built.undefined(),
        *built.registry(model.RegistryKind.APPLICATION_IDS, 16777216),
        *built.marks("TS29.212", "AN-GW-Address"),
        *built.value_tables("TS29.272"),
        model.Placeholder(undefined),
        model.Alias("TS29.336", "External-Identifier", "source"),
        model.Supplied(1, 2, model.DataType.UTF8_STRING, FlagRules(must=_V), "source"),
        FlagRules(must=_V),
    ]
    public = {
        each
        for each in map(model.__dict__.get, model.__all__)
        if isinstance(each, type)
        and not issubclass(each, (Exception, enum.Enum))
        and each is not model.Model
    }

    assert public <= {type(each) for each in found}
    for each in found:
        assert each is not None
        assert "\n" not in repr(each)
        plain = each.to_dict()
        assert json.loads(json.dumps(plain)) == plain


# --- references --------------------------------------------------------------


@pytest.mark.parametrize(
    ("spelling", "reference"),
    [
        ("TS 29.229", "TS29.229"),
        ("3GPP TS 29.229", "TS29.229"),
        ("rfc 6733", "RFC6733"),
        ("ETSI TS 183 017", "ETSI-TS183.017"),
        ("3gpp2 x.s0057", "3GPP2-X.S0057"),
        ("onem2m ts-0004", "oneM2M-TS-0004"),
    ],
)
def test_a_reference_is_read_however_it_is_spelled(built, spelling, reference):
    assert built.canonical(spelling) == reference
    assert built.applications(spelling) == built.applications(reference)


def test_every_query_takes_the_spelling(built):
    spelling = "ts 29.229"

    assert built.messages(spelling) == built.messages("TS29.229")
    assert built.avps(spelling) == built.avps("TS29.229")
    assert built.resolve(spelling, "Public-Identity") == built.resolve(
        "TS29.229", "Public-Identity"
    )
    assert built.table_rows(spelling, "Public-Identity")
    assert built.across_releases("ts 32.299") == built.across_releases("TS32.299")


def test_a_reference_or_version_the_corpus_lacks_is_refused_naming_what_it_holds(
    built,
):
    with pytest.raises(model.ModelError, match=r"did you mean .*TS29\.229"):
        built.resolve("TS 29.299", "Public-Identity")
    with pytest.raises(model.ModelError, match="no copy of Nonsense"):
        built.messages("Nonsense")
    with pytest.raises(model.ModelError, match=r"V1\.0\.0.*holds.*11\.20\.0"):
        built.messages("TS32.299", version="1.0.0")
    with pytest.raises(model.ModelError, match="name it"):
        built.applications(version="1.0.0")


# --- commands and applications -----------------------------------------------


def test_applications_split_a_document_by_application_id_and_clause(built):
    """TS 29.272 splits S6a/S6d, S13 and S7a by id within clause 7, its VCSG
    commands joining S7a through clause 7.2.2's block; TS 29.212's headers
    print no ids, so Gx, Gxx, Sd, St and annex E's S15 take theirs from the
    clauses stating them; TS 29.273 shares 16777250 between SWa, STa and SWd;
    TS 32.299 clause 6 holds Rf and Ro; RFC 6733's clause 8 commands carry
    the using application's id, which no block states."""

    def keys(reference):
        return [
            (app.application_id, app.clause, app.name)
            for app in built.applications(reference)
        ]

    assert keys("TS29.272") == [
        (16777251, "7", None),
        (16777308, "7", "S7a/S7d"),
        (16777252, "7", None),
    ]
    assert keys("TS29.212") == [
        (16777238, "5", "Gx"),
        (16777266, "5a", "Gxx"),
        (16777303, "5b", "Sd"),
        (16777349, "5c", "St"),
        (16777318, "E.6", "S15"),
    ]
    assert [key[:2] for key in keys("TS29.273")] == [
        (16777250, "4"),
        (16777250, "5"),
        (16777250, "6"),
        (16777264, "7"),
        (16777265, "8"),
        (16777272, "9"),
    ]
    assert [
        (app.application_id, [m.abbreviation for m in app.messages])
        for app in built.applications("TS32.299")
    ] == [(3, ["ACR", "ACA"]), (4, ["CCR", "CCA", "RAR", "RAA"])]
    assert [key[:2] for key in keys("RFC6733")] == [(0, "5"), (None, "8"), (3, "9")]


def test_the_id_on_the_wire_is_the_headers_or_its_application_scopes(built):
    """TS 29.212 prints CCR with a bare header; TS 29.229 prints Cx's id in
    every header, as 3GPP2 X.S0013-006 does for its Cx."""
    ccr = _message(built, "TS29.212", "CCR")
    uar = _message(built, "TS29.229", "UAR")
    uaa = _message(built, "TS29.229", "UAA")

    assert (ccr.application_id, ccr.header_application_id) == (16777238, None)
    assert uar.application_id == uar.header_application_id == 16777216
    assert ccr.is_request and uar.is_request and not uaa.is_request
    assert {app.reference for app in built.applications(application_id=16777216)} == {
        "TS29.229",
        "3GPP2-X.S0013-006",
    }
    assert built.applications("TS29.229", application_id=1) == ()
    for application in built.applications():
        for message in application.messages:
            assert message.application_id == application.application_id


@pytest.mark.parametrize(
    ("reference", "command", "name", "bounds"),
    [
        ("TS29.229", "UAR", "Session-Id", (1, 1)),  # < Session-Id >
        ("TS29.229", "UAR", "Destination-Host", (0, 1)),  # [ ... ]
        ("RFC5778", "MIR", "MIP-Mobile-Node-Address", (1, 2)),  # 1*2{ ... }
        ("ETSI-ES283.026", "RAR", "Specific-Action", (1, None)),  # *{ ... }
        ("TS29.234", "DEA", "Subscription-Id", (0, None)),  # 1*[ ... ]
    ],
)
def test_occurrence_bounds_read_the_qualifier_as_rfc_6733_section_3_2_does(
    built, reference, command, name, bounds
):
    """`[ X ]` may be absent and `*{ X }` must appear at least once, though
    the rule keeps the qualifier as spelled."""
    (member, *_) = [
        each
        for message in built.messages(reference)
        if message.abbreviation == command
        for each in message.avps
        if each.name == name
    ]

    assert (member.min_occurs, member.max_occurs) == bounds


def test_cx_commands_hold_every_avp_they_name_at_any_depth(built):
    """Every name in a Cx command body resolves; the only bare member is the
    `* [ AVP ]` wildcard. The commands reach 104 AVPs, RFC 6733's
    Destination-Host and Failed-AVP among them, which no table of TS 29.229
    lists: they come through its `; Bases:`."""
    for message in built.messages("TS29.229"):
        for member in message.avps:
            if member.name == "AVP":
                assert (member.avp, member.hole) == (None, None)
            else:
                assert member.avp is not None, (message.name, member.name)
    (cx,) = built.applications("TS29.229", application_id=16777216)

    walked = cx.walk()

    assert len({member.avp.identity for member in walked if member.avp}) == 104
    tabled = {avp.name for avp in built.avps("TS29.229")}
    host = next(m.avp for m in walked if m.name == "Destination-Host")
    assert host is not None and host.defined_in == "RFC6733"
    assert not {"Destination-Host", "Failed-AVP"} & tabled
    # Depth first, each reading once, a grouped AVP right before its members.
    names = [member.name for member in _message(built, "TS29.229", "UAR").walk()]
    assert names[0] == "Session-Id"
    assert len(names) == len(set(names))
    place = names.index("Supported-Features")
    assert names[place + 1 : place + 3] == ["Feature-List-ID", "Feature-List"]


def test_only_the_wildcard_is_a_member_with_neither_an_avp_nor_a_hole(built):
    members = [
        *(member for message in built.messages() for member in message.avps),
        *(
            member
            for avp in built.avps()
            if isinstance(avp, model.Grouped)
            for member in avp.members
        ),
    ]

    bare = {
        member.name for member in members if (member.avp, member.hole) == (None, None)
    }

    assert bare == {"AVP"}


def test_an_answer_with_the_e_bit_takes_its_documents_answer_message(built):
    """TS 29.229 prints its own in clause 7.3.1; TS 29.272 prints none and
    takes RFC 6733 section 7.2's through its bases, read through TS 29.272."""
    own = built.answer_message("TS29.229")
    taken = built.answer_message("TS29.272")

    assert own is not None and taken is not None
    assert (own.defined_in, own.section, own.read_through) == (
        "TS29.229",
        "7.3.1",
        "TS29.229",
    )
    assert (taken.defined_in, taken.section, taken.read_through) == (
        "RFC6733",
        "7.2",
        "TS29.272",
    )
    assert "Supported-Applications" in {member.name for member in own.avps}
    origin_host = next(m.avp for m in taken.walk() if m.name == "Origin-Host")
    assert origin_host is not None and origin_host.identity == (0, 264)


# --- how a name resolves -----------------------------------------------------


def test_a_documents_own_definition_comes_before_the_origin_it_cites(built):
    """TS 32.299 re-uses RFC 4006's Multiple-Services-Credit-Control and
    defines it again with its own members: its reading is its own, M from its
    table 7.2.0.1 and P, which that row leaves, from RFC 4006's. TS 29.272
    re-prints TS 29.212's Allocation-Retention-Priority in clause 7.3.40 and
    tabulates it nowhere, so its flags are TS 29.212's."""
    mscc = built.resolve("TS32.299", "Multiple-Services-Credit-Control")
    arp = built.resolve("TS29.272", "Allocation-Retention-Priority")

    assert isinstance(mscc, model.Grouped) and isinstance(arp, model.Grouped)
    assert (mscc.defined_in, mscc.identity) == ("TS32.299", (0, 456))
    assert mscc.flag_rules == FlagRules(must=_M, may=_P, must_not=_V)
    assert dict(mscc.completed_by) == {"flag_rules": "RFC4006"}
    assert arp.defined_in == "TS29.272"
    assert built.table_rows("TS29.272", "Allocation-Retention-Priority") == ()
    assert dict(arp.completed_by) == {"flag_rules": "TS29.212"}
    (row, *_) = built.table_rows("TS29.212", "Allocation-Retention-Priority")
    assert arp.flag_rules == FlagRules.printed(row.flag_rules)


def test_a_reused_name_follows_its_origin_to_the_real_definition(built):
    """TS 29.229 tabulates the Digest AVPs it re-uses from RFC 4590, yet RFC
    4590 defines them; TS 29.172 cites Service-Selection from TS 29.272,
    which re-uses it from RFC 5778; TS 29.229's DRMP is RFC 7944's. TS 29.109
    prints RFC 6733's Auth-Application-Id rule and defines nothing by it."""
    digest = built.resolve("TS29.229", "Digest-Qop")
    selection = built.resolve("TS29.172", "Service-Selection")
    drmp = built.resolve("TS29.229", "DRMP")

    assert digest is not None and (digest.defined_in, digest.identity) == (
        "RFC4590",
        (0, 110),
    )
    assert selection is not None and selection.defined_in == "RFC5778"
    assert isinstance(drmp, model.Enumerated) and drmp.defined_in == "RFC7944"
    definition = built.definition((0, 260))
    assert definition is not None and definition.defined_in == "RFC6733"
    assert 260 not in {avp.code for avp in built.avps("TS29.109")}


def test_the_first_table_row_wins_and_every_row_stays_reachable(built):
    """TS 29.061 tabulates 3GPP-IMSI in table 9a (Gi/SGi, M in Must not) and
    table 10 (Gmb, M in Must); resolution reads table 9a's."""
    imsi = built.resolve("TS29.061", "3GPP-IMSI")

    first, second = built.table_rows("TS29.061", "3GPP-IMSI")

    assert imsi is not None and AvpFlag.MANDATORY in imsi.flag_rules.must_not
    assert FlagRules.printed(first.flag_rules) == imsi.flag_rules
    assert AvpFlag.MANDATORY in second.flag_rules.must
    assert built.table_rows("TS29.061", "No-Such-AVP") == ()


def test_a_citing_tables_flags_outrank_the_origins(built):
    """TS 29.229 table 6.3.0.1 puts M in Must for four Digest AVPs that RFC
    4590's corrected rows put in May; RFC 4590's P in May fills the bit the
    table leaves. RFC 4590's own reading keeps its rules, so `readings`
    returns both."""
    for name in ("Digest-Realm", "Digest-Algorithm", "Digest-Qop", "Digest-HA1"):
        ours = built.resolve("TS29.229", name)
        theirs = built.resolve("RFC4590", name)
        assert ours is not None and theirs is not None
        assert ours.identity == theirs.identity
        assert ours.flag_rules == FlagRules(must=_M, may=_P, must_not=_V), name
        assert theirs.flag_rules == FlagRules(may=_M | _P, must_not=_V), name
        assert set(built.readings(ours.identity)) == {ours, theirs}


def test_a_reused_rows_m_bit_outranks_the_origins_m_rule(built):
    """TS 29.272 table 7.3.1/2 marks TS 29.212's RAT-Type MUST where TS
    29.212 puts M in Must not, at top level and inside TS 29.272's
    eDRX-Cycle-Length, and marks TS 29.229's Visited-Network-Identifier
    MUST-NOT where TS 29.229 puts M in Must. TS 29.336 prints `-` for DRMP in
    table 6.4.1/2 and MUST-NOT in 8.4.1-2: the first row stating M counts."""
    rat = built.resolve("TS29.272", "RAT-Type")
    visited = built.resolve("TS29.272", "Visited-Network-Identifier")
    drmp = built.resolve("TS29.336", "DRMP")

    assert rat is not None and rat.defined_in == "TS29.212"
    assert rat.flag_rules == FlagRules(must=_M | _V, may=_P)
    assert built.resolve("TS29.212", "RAT-Type").flag_rules == FlagRules(
        must=_V, may=_P, must_not=_M
    )
    assert _member(built.resolve("TS29.272", "eDRX-Cycle-Length"), "RAT-Type") == rat
    assert visited is not None and visited.flag_rules == FlagRules(must=_V, must_not=_M)
    assert (
        AvpFlag.MANDATORY
        in built.resolve("TS29.229", "Visited-Network-Identifier").flag_rules.must
    )
    assert drmp is not None and drmp.flag_rules == FlagRules(must_not=_M | _V)


def test_an_ietf_reading_stating_no_m_leaves_it_to_the_application(built):
    """RFC 6733 section 4.1 leaves M to the application and section 4.1.1
    forbids V in vendor 0. RFC 5777 prints no flag columns, and TS 29.273's
    table puts M in Must for its QoS-Capability; RFC 6734 prints none, and
    TS 29.273's re-used row marks its Key MUST-NOT; RFC 7683's table places
    V alone. A vendor reading placing V alone, TS 29.229's Line-Identifier,
    gets no rule for M."""
    qos = built.resolve("RFC5777", "QoS-Capability")
    key = built.resolve("TS29.273", "Key")
    olr = built.resolve("RFC7683", "OC-OLR")
    line = built.resolve("TS29.229", "Line-Identifier")

    assert qos is not None and qos.flag_rules == FlagRules(
        must_not=_V, application_defined=_M
    )
    assert built.resolve("TS29.273", "QoS-Capability").flag_rules.must == _M
    assert key is not None and key.flag_rules == FlagRules(must_not=_M | _V)
    assert built.resolve("RFC6734", "Key").flag_rules.application_defined == _M
    assert olr is not None and olr.flag_rules.application_defined == _M
    assert line is not None and line.flag_rules == FlagRules(must=_V)


def test_a_grouped_avp_keeps_its_body_and_reads_what_the_citing_document_says(
    built,
):
    """TS 32.299 table 7.2.0.1 sets M on Supported-Features and on its
    Feature-List-ID and Feature-List members, all TS 29.229's, whose table
    6.3.0.1 forbids M on the two members: through TS 32.299 the body is TS
    29.229's and the members TS 32.299's. Vendor-Id, which TS 32.299
    tabulates with dashes only, stays RFC 6733's."""
    ours = built.resolve("TS32.299", "Supported-Features")
    theirs = built.resolve("TS29.229", "Supported-Features")

    assert isinstance(ours, model.Grouped) and isinstance(theirs, model.Grouped)
    assert (ours.defined_in, ours.read_through) == ("TS29.229", "TS32.299")
    assert [m.rule for m in ours.members] == [m.rule for m in theirs.members]
    for name in ("Feature-List-ID", "Feature-List"):
        mine = _member(ours, name)
        assert mine.flag_rules == FlagRules(must=_M | _V)
        assert _member(theirs, name).flag_rules == FlagRules(must=_V, must_not=_M)
        assert mine == built.resolve("TS32.299", name)
    assert _member(ours, "Vendor-Id") == _member(theirs, "Vendor-Id")
    assert _member(ours, "Vendor-Id").read_through == "RFC6733"


def test_a_name_is_no_identity_inside_a_grouped_avp(built):
    """TS 32.299 defines its own Originator, (10415, 864) Enumerated; the
    M2M-Information it re-uses from oneM2M TS-0004 holds oneM2M's, (45687,
    1008) UTF8String, which a name read through TS 32.299 must not replace.
    Asked by name alone, `definition` refuses."""
    ours = built.resolve("TS32.299", "M2M-Information")
    own = built.resolve("TS32.299", "Originator")

    inner = _member(ours, "Originator")

    assert inner is _member(
        built.resolve("oneM2M-TS-0004", "M2M-Information"), "Originator"
    )
    assert (inner.identity, inner.data_type) == (
        (45687, 1008),
        model.DataType.UTF8_STRING,
    )
    assert own is not None
    assert (own.identity, own.data_type) == ((10415, 864), model.DataType.ENUMERATED)
    with pytest.raises(model.ModelError, match=r"\(10415, 864\), \(45687, 1008\)"):
        built.definition("Originator")
    assert built.definition((45687, 1008)) == inner


def test_a_rows_vendor_is_its_vendor_id_cell_or_else_its_v_flag(built):
    """oneM2M TS-0004 table A.4-1 mixes vendors in a Vendor-ID column;
    TS 29.229's Digest rows print V under Must not in vendor 10415's file,
    which places them in vendor 0; TS 29.229's own 621 and RFC 7683's are
    two AVPs."""
    m2m = built.resolve("TS32.299", "M2M-Information")
    assert isinstance(m2m, model.Grouped)

    vendors = {m.avp.vendor_id for m in m2m.members if m.avp is not None}

    assert vendors == {0, 10415, 45687}
    assert _member(m2m, "Rating-Group").identity == (0, 432)
    assert _member(m2m, "Node-Id").identity == (10415, 2064)
    assert {a.name for a in built.readings((10415, 621))} == {
        "Primary-Charging-Collection-Function-Name"
    }
    assert {a.name for a in built.readings((0, 621))} == {"OC-Supported-Features"}


def test_a_field_the_first_reading_leaves_comes_from_the_next(built):
    """TS 29.229 states no code or flag rule for Wildcarded-IMPU; through TS
    29.329 its reading takes them from TS 29.329 table 6.3.1, and
    `completed_by` says so. TS 29.229's own stays a hole."""
    impu = built.resolve("TS29.329", "Wildcarded-IMPU")

    assert impu is not None
    assert (impu.defined_in, impu.identity) == ("TS29.229", (10415, 636))
    assert dict(impu.completed_by) == dict.fromkeys(
        ("code", "vendor_id", "flag_rules"), "TS29.329"
    )
    assert built.resolve("TS29.229", "Wildcarded-IMPU") is None


def test_every_etsi_tispan_citation_resolves_to_its_transcription(built):
    """3GPP cites ES 283 034 as "ETSI TS 283 034" (`cited_as`) and TS 183 017
    under its own number; each row resolves to the transcribed AVP, in ETSI's
    vendor space. A transcription re-printing what it imports reads its own
    copy first."""
    cited = [
        (entry.reference, row.name, row.origin)
        for entry in corpus.Corpus.installed()
        for section in entry.spec.sections
        if isinstance(section, ast.ReusedAvps)
        for row in section.rows
        if row.origin in {"ETSI-ES283.034", "ETSI-TS183.017"}
    ]

    assert {origin for *_, origin in cited} == {"ETSI-ES283.034", "ETSI-TS183.017"}
    for reference, name, origin in cited:
        avp = built.resolve(reference, name)
        assert avp is not None, (reference, name)
        assert avp.vendor_id == 13019, (reference, name)
        assert avp.defined_in in {reference, origin}


# --- readings ----------------------------------------------------------------


def test_readings_name_the_document_whose_table_made_each(built):
    """OMA-DDS-Charging_Data's table 11 adds P under May to RFC 6733's
    Session-Id; TS 29.229's table agrees with RFC 6733 and makes no reading.
    Two copies of TS 29.061 read 3GPP-RAT-Type apart, so the older copy's
    reading names its version."""
    plain, protected = sorted(
        built.readings("Session-Id"),
        key=lambda avp: AvpFlag.PROTECTED in avp.flag_rules.may,
    )

    assert plain.read_through == "RFC6733"
    assert protected.read_through == "OMA-DDS-Charging_Data"
    assert built.resolve("TS29.229", "Session-Id") == plain
    assert built.readings((0, 263)) == built.readings("Session-Id")
    assert {avp.read_through for avp in built.readings("3GPP-RAT-Type")} == {
        "TS29.061",
        "TS29.061 V6.15.0",
    }
    assert built.readings("No-Such-AVP") == built.readings((0, 999999)) == ()


def test_every_reading_of_an_identity_says_where_it_came_from(built):
    identities = {avp.identity for avp in built.avps()}

    for identity in identities:
        readings = built.readings(identity)
        told = {
            (avp.defined_in, avp.read_through, avp.across_releases) for avp in readings
        }
        assert len(told) == len(readings), identity


@pytest.mark.parametrize(
    ("name", "document"),
    [
        ("Session-Id", "RFC6733"),
        # Extended from TS 29.212 by a local copy TS 29.272 also re-uses.
        ("Allocation-Retention-Priority", "TS29.212"),
        # TS 29.214 succeeds TS 29.209, and ETSI's copies cite both.
        ("Flows", "TS29.214"),
        # RFC 8506 obsoletes RFC 4006.
        ("CC-Request-Type", "RFC8506"),
        # 3GPP2 X.S0013-014 has one of that name in its own space.
        ((10415, 1001), "TS29.212"),
    ],
)
def test_definition_is_the_defining_documents_reading(built, name, document):
    avp = built.definition(name)

    assert avp is not None
    assert avp.defined_in == avp.read_through == document


def test_definition_of_what_no_document_completes_is_none(built):
    assert built.definition("No-Such-AVP") is None
    assert built.definition((1, 1)) is None
    # A hole has no reading to give; `hole` says why.
    assert built.definition("Charging-Characteristics") is None
    assert built.hole("TS29.234", "Charging-Characteristics") is not None


# --- marks, values and registries --------------------------------------------


def test_marks_give_every_tables_row_in_file_order(built):
    """TS 29.212 marks AN-GW-Address in Gx's AVP table and again in Gxx's
    re-used table, a note reference kept with its mark; TS 32.299 marks
    Error-Message per command, `()` for each printed dash, and leaves
    Termination-Cause blank, None, under ACR."""
    gx, gxx = built.marks("TS29.212", "AN-GW-Address")

    assert (gx.table, gx.section) == ("5.3.0.1", "5.3.0")
    assert gx.marks == {
        ast.MarkColumn.ACCESS_TYPES: ("All",),
        ast.MarkColumn.APPLICABILITY: ("Both", "Rel8", "EPC-routed"),
    }
    assert gxx.table == "5a.4.0.1"
    assert gxx.marks[ast.MarkColumn.APPLICABILITY] == ("EPC-routed (See NOTE 8)",)
    commands = [ast.MarkColumn(each) for each in ("ACR", "ACA", "CCR", "CCA")]
    (charging,) = built.marks("TS32.299", "Error-Message")
    assert charging.marks == dict.fromkeys(commands, ())
    (termination,) = built.marks("TS32.299", "Termination-Cause")
    assert list(termination.marks.values()) == [None, (), ("OC",), ()]
    assert built.marks("TS29.229", "User-Data") == ()


def test_an_enumeration_tells_its_values_from_reserved_void_and_vendor_ranges(built):
    """TS 29.214 clause 5.3.13 prints `Void (0)` and `Void (5)`; TS 32.299
    clause 7.2.213 names 0-10, reserves 11-99 and leaves 100-199 to vendors."""
    action = built.resolve("TS29.214", "Specific-Action")
    sm = built.resolve("TS32.299", "SM-Service-Type")

    assert isinstance(action, model.Enumerated) and isinstance(sm, model.Enumerated)
    assert [v for v in action.values if isinstance(v, ast.VoidValues)] == [
        ast.VoidValues(first=0, last=0),
        ast.VoidValues(first=5, last=5),
    ]
    assert not any(
        isinstance(v, ast.EnumValue) and v.name.lower() == "void" for v in action.values
    )
    assert sm.vendor_specific == (
        ast.VendorSpecificValues(
            first=100, last=199, description="Vendor specific SM services"
        ),
    )
    assert {value["kind"] for value in sm.to_dict()["values"]} == {
        "value",
        "reserved",
        "vendor-specific",
    }
    assert {value["kind"] for value in action.to_dict()["values"]} >= {"void"}


def test_values_defined_elsewhere_keep_their_citation(built):
    """TS 29.272 clause 7.3.141 points Report-Interval at TS 32.422, which no
    flat list holds: an AVP with no values and their source, not a hole.
    Clause 7.3.67's Trace-Depth points there too; a correction supplied its
    values, and the citation stays."""
    interval = built.resolve("TS29.272", "Report-Interval")
    depth = built.resolve("TS29.272", "Trace-Depth")
    alert = built.resolve("TS29.272", "Alert-Reason")

    assert isinstance(interval, model.Enumerated)
    assert (interval.values, interval.values_source) == (
        (),
        "TS 32.422 [23] for Report Interval",
    )
    assert isinstance(depth, model.Enumerated)
    assert depth.values[0] == ast.EnumValue(name="Minimum", value=0)
    assert depth.values_source == "TS 32.422 [23] for Trace Depth"
    assert isinstance(alert, model.Enumerated) and alert.values_source is None


def test_a_bit_mask_avp_carries_its_bits(built):
    """TS 29.272 table 7.3.7/1 numbers ULR-Flags' bits; Session-Id has none."""
    avp = built.definition("ULR-Flags")

    assert type(avp) is model.Avp
    assert avp.data_type is model.DataType.UNSIGNED32
    table = avp.value_table
    assert table is not None
    assert (table.kind, table.reference, table.section, table.table) == (
        model.ValueKind.BITS,
        "TS29.272",
        "7.3.7",
        "7.3.7/1",
    )
    assert table.vendor_id == 10415
    assert (table.rows[0].name, table.rows[0].value) == (
        "Single-Registration-Indication",
        0,
    )
    assert built.definition("Session-Id").value_tables == ()


def test_a_value_table_is_the_reading_documents_or_else_its_origins(built):
    """RFC 6733's Experimental-Result-Code read through TS 29.229 carries TS
    29.229's codes, with no second reading; OMA's reading of Result-Code,
    printing none, carries RFC 6733's."""
    cx = built.resolve("TS29.229", "Experimental-Result-Code")
    oma = built.resolve("OMA-DDS-Charging_Data", "Result-Code")

    assert cx is not None and cx.defined_in == "RFC6733"
    assert (cx.value_table.reference, cx.value_table.vendor_id) == ("TS29.229", 10415)
    assert {row.value: row.name for row in cx.value_table.rows}[5001] == (
        "DIAMETER_ERROR_USER_UNKNOWN"
    )
    assert cx == built.definition("Experimental-Result-Code")
    assert oma is not None and oma.read_through == "OMA-DDS-Charging_Data"
    assert (oma.value_table.reference, oma.value_table.vendor_id) == ("RFC6733", 0)


def test_value_tables_filter_by_document_avp_and_kind(built):
    assert {table.kind for table in built.value_tables()} == set(model.ValueKind)
    assert {t.reference for t in built.value_tables("ts 29.272")} == {"TS29.272"}
    (flags,) = built.value_tables("TS29.272", avp="ULR-Flags")
    assert flags.kind is model.ValueKind.BITS
    features = built.value_tables("TS29.272", kind=model.ValueKind.FEATURES)
    assert [(t.application, t.feature_list_id) for t in features] == [
        ("S6a/S6d", 1),
        ("S6a/S6d", 2),
    ]
    assert built.value_tables(avp="No-Such-AVP") == ()
    older = built.value_tables("TS29.212", version="11.19.0", avp="Feature-List")
    assert {table.version for table in older} == {"11.19.0"}


def test_feature_lists_are_keyed_by_application_and_list_id(built):
    lists = built.feature_lists()

    assert (lists["S6a/S6d", 1].rows[0].name, lists["S6a/S6d", 1].rows[0].mark) == (
        "ODB-all-APN",
        "O",
    )
    assert lists["S6t", None].reference == "TS29.336"
    assert set(built.feature_lists("TS29.273")) == {("SWx", 1), ("S6b", 1)}
    # A feature table's AVP is corrected where its clause misnames it.
    assert lists["T4", 1].avp == "Feature-List"


def test_the_registry_answers_by_code_beside_the_model(built):
    """TS 29.230 table 4.1 allocates Cx's id; table 7.1 prints AVP code 318
    in TS 29.234's block and again in TS 29.273's, and reserves 1-255."""
    (cx,) = built.registry(model.RegistryKind.APPLICATION_IDS, 16777216)
    twice = built.registry(model.RegistryKind.AVP_CODES, 318)
    (radius,) = built.registry(model.RegistryKind.AVP_CODES, 1)

    assert (cx.reference, cx.table, cx.section) == ("TS29.230", "4.1", "4.1")
    assert cx.entry == ast.RegistryRow(
        code=16777216, name="3GPP Cx/Px", defined_in=("TS29.228", "TS29.229")
    )
    assert [allocation.entry.defined_in for allocation in twice] == [("TS29.234",), ()]
    assert isinstance(radius.entry, ast.RegistryReservation)
    assert (radius.entry.first, radius.entry.last) == (1, 255)
    assert cx in built.registry(model.RegistryKind.APPLICATION_IDS)


# --- resolution across releases ----------------------------------------------


def test_a_specific_reference_means_the_version_it_names(built):
    """TS 183 017's "TS 29.214 Release 7" [19] is V7.12.0, Release 7's last;
    oneM2M TS-0004's "TS 32.299 (Release 11)" [31] is V11.20.0."""
    codec = built.resolve("ETSI-TS183.017", "Codec-Data")
    node = built.resolve("oneM2M-TS-0004", "Node-Id")

    assert codec is not None and node is not None
    assert codec.across_releases == corpus.CrossRelease(
        "ETSI-TS183.017", "TS29.214", "7.12.0", corpus.CitationRule.SPECIFIC
    )
    assert node.across_releases == corpus.CrossRelease(
        "oneM2M-TS-0004", "TS32.299", "11.20.0", corpus.CitationRule.SPECIFIC
    )
    current = built.resolve("TS32.299", "Node-Id")
    assert current is not None and current.across_releases is None


def test_a_non_specific_reference_means_the_newest_copy_of_the_citing_release(built):
    """TS 29.210 V6.7.0's TS 29.061 is V6.15.0, whose table 10 puts M in Must
    for 3GPP-RAT-Type where Release 19's table 9a puts it in Must not: within
    the release, nothing crosses. TS 32.299's TS 29.140 [213] ended at
    V7.0.0, its `final_version`. ES 283 035's clause 2.1 says the latest
    edition applies, so its TS 29.329 is the newest held."""
    rat = built.resolve("TS29.210", "3GPP-RAT-Type")
    vas = built.resolve("TS32.299", "VAS-ID")
    latest = [
        avp.across_releases
        for avp in built.across_releases("ETSI-ES283.035")
        if avp.across_releases is not None and avp.across_releases.cited == "TS29.329"
    ]

    assert rat is not None
    assert (rat.identity, rat.across_releases) == ((10415, 21), None)
    assert AvpFlag.MANDATORY in rat.flag_rules.must
    assert (
        AvpFlag.MANDATORY
        in built.resolve("TS29.061", "3GPP-RAT-Type").flag_rules.must_not
    )
    assert vas is not None and vas.defined_in == "TS29.140"
    assert vas.across_releases == corpus.CrossRelease(
        "TS32.299", "TS29.140", "7.0.0", corpus.CitationRule.NON_SPECIFIC
    )
    assert latest
    assert {each.rule for each in latest} == {corpus.CitationRule.LATEST_EDITION}


def test_a_stand_in_answers_for_a_copy_the_corpus_lacks(built):
    """TS 29.212 [24] names 3GPP2 X.S0057 revision B, which the corpus lacks;
    revision 0 stands in, and TS 32.299 reaches the same AVP through TS
    29.212. TS 29.210 V6.7.0 means TS 29.229 V6.11.0, and V19.1.0, which
    defines Charging-Information alike, stands in."""
    for reference in ("TS29.212", "TS32.299"):
        bsid = built.resolve(reference, "3GPP2-BSID")
        assert bsid is not None, reference
        assert (bsid.defined_in, bsid.identity) == ("3GPP2-X.S0057", (5535, 9010))
        assert bsid.flag_rules == FlagRules(must=_M | _V, may=_P)
        assert bsid.across_releases == corpus.CrossRelease(
            "TS29.212",
            "3GPP2-X.S0057",
            "2.0",
            corpus.CitationRule.STAND_IN,
            cited_revision="B",
            revision="0",
        )
    charging = built.resolve("TS29.210", "Charging-Information")
    assert charging is not None
    assert charging.across_releases == corpus.CrossRelease(
        "TS29.210", "TS29.229", "19.1.0", corpus.CitationRule.STAND_IN, meant="6.11.0"
    )


def test_a_later_release_states_only_the_field_its_entry_names(built):
    """TS 29.061 V6.15.0 numbers 3GPP-SGSN-MCC-MNC among its RADIUS
    sub-attributes and types it nowhere. Through TS 29.210 the identity and
    clause stay V6.15.0's, the flags are TS 29.210 clause 5.3's, and only the
    type is V19.1.0 table 9a's, whose M in Must not is no part of the reading.
    V6.15.0's own reading stays a hole the corpus does not list."""
    avp = built.resolve("TS29.210", "3GPP-SGSN-MCC-MNC")

    assert avp is not None
    assert (avp.identity, avp.data_type) == ((10415, 18), model.DataType.UTF8_STRING)
    assert avp.flag_rules == FlagRules(must=_M | _V, may=_P)
    assert (avp.defined_in, avp.section, avp.read_through) == (
        "TS29.061",
        "16.4.7",
        "TS29.210",
    )
    assert dict(avp.completed_by) == {
        "data_type": "TS29.061 V19.1.0",
        "flag_rules": "TS29.210",
    }
    assert avp.across_releases == corpus.CrossRelease(
        "TS29.210",
        "TS29.061",
        "19.1.0",
        corpus.CitationRule.LATER_RELEASE,
        meant="6.15.0",
    )
    older = built.hole("TS29.061", "3GPP-SGSN-MCC-MNC", version="6.15.0")
    assert older is not None and older.missing == ("data_type", "flag_rules")
    assert older not in built.holes()


@pytest.mark.parametrize(
    ("table", "key", "reference", "name", "missing"),
    [
        (
            "stand_ins",
            ("TS29.212", "19.1.0", "3GPP2-X.S0057"),
            "TS29.212",
            "3GPP2-BSID",
            ("definition",),
        ),
        (
            "release_fills",
            ("TS29.210", "6.7.0", "TS29.061"),
            "TS29.210",
            "3GPP-SGSN-MCC-MNC",
            ("data_type",),
        ),
    ],
)
def test_without_its_corpus_toml_entry_a_citation_crosses_nothing(
    table, key, reference, name, missing
):
    books = corpus.Corpus.installed()
    rules = getattr(books.rules, table)
    assert key in rules
    books.rules = dataclasses.replace(
        books.rules, **{table: {k: v for k, v in rules.items() if k != key}}
    )

    built = model.Model.build(books, holes=model.HolePolicy.ANY)

    assert built.resolve(reference, name) is None
    hole = built.hole(reference, name)
    assert hole is not None and hole.missing == missing


def test_across_releases_lists_every_crossing_and_older_copies_answer_only_so(built):
    """oneM2M TS-0004's Service-Information is TS 32.299 V11.20.0's, whose
    non-specific references mean Release 11's last versions: its
    QoS-Information is TS 29.212 V11.19.0's, nine members and the wildcard
    where Release 19's has sixteen. Reference-level queries read the newest
    copy, but corpus-wide ones find what only V11.20.0 holds:
    WLAN-Information."""
    everything = built.across_releases()
    order = [
        (found.across_releases.citing, found.name)
        for found in everything
        if found.across_releases is not None
    ]
    service = built.resolve("oneM2M-TS-0004", "Service-Information")
    qos = _member(_member(service, "PS-Information"), "QoS-Information")
    current = built.resolve("TS29.212", "QoS-Information")
    wlan = built.definition((10415, 875))

    assert len(order) == len(everything) and order == sorted(order)
    assert set(built.across_releases("oneM2M-TS-0004")) <= set(everything)
    assert isinstance(qos, model.Grouped) and isinstance(current, model.Grouped)
    assert qos.identity == current.identity
    assert (len(qos.members), len(current.members)) == (10, 17)
    assert wlan is not None
    assert (wlan.name, wlan.read_through) == ("WLAN-Information", "TS32.299 V11.20.0")
    assert "WLAN-Information" not in {avp.name for avp in built.avps("TS32.299")}


# --- Wireshark names ---------------------------------------------------------


def test_a_dictionary_adds_wireshark_names_beside_the_documents(tmp_path):
    """The Wireshark dictionary is downloaded, not committed, so this one is
    written here."""
    (tmp_path / "dictionary.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<dictionary>
  <base>
    <avp name="Cx-User-Data" code="606" vendor-id="TGPP">
      <type type-name="OctetString"/>
    </avp>
  </base>
  <vendor vendor-id="TGPP" code="10415" name="3GPP"/>
</dictionary>
""",
        encoding="utf-8",
    )
    named = model.Model.installed(wireshark=tmp_path)

    data = named.resolve("TS29.229", "User-Data")
    other = named.resolve("TS29.229", "Public-Identity")

    assert data is not None and (data.name, data.wireshark_name) == (
        "User-Data",
        "Cx-User-Data",
    )
    assert other is not None and other.wireshark_name is None


def test_a_wireshark_dictionary_that_does_not_read_is_refused(tmp_path):
    (tmp_path / "dictionary.xml").write_text("<dictionary><base>", "utf-8")

    with pytest.raises(model.ModelError, match="cannot read the Wireshark dictionary"):
        model.Model.installed(wireshark=tmp_path)


@pytest.mark.sources
def test_the_pinned_dictionary_names_the_avps_it_spells_differently():
    """Wireshark's deliberate disambiguations and its own defects both
    arrive as `wireshark_name`, beside the specifications' spelling."""
    named = model.Model.installed(wireshark=_ROOT / "specifications" / "wireshark")
    for reference, name, wireshark_name in [
        ("TS29.229", "User-Data", "Cx-User-Data"),
        ("TS29.329", "User-Data", "Sh-User-Data"),
        ("TS29.272", "Call-Barring-Info", "Call-Barring-Infor-List"),
        ("RFC6733", "Session-Id", "Session-Id"),
    ]:
        avp = named.resolve(reference, name)
        assert avp is not None
        assert (avp.name, avp.wireshark_name) == (name, wireshark_name)
    hole = named.hole("TS29.061", "3GPP-Session-Stop-Indicator")
    assert hole is not None
    assert hole.wireshark_name == "3GPP-Session-Stop-Indicator"
