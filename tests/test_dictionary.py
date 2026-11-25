"""What `seanchai dictionary` gives a stack author beyond the bodies: the value
tables a selection reaches, ids that do not depend on the selection, the
conflicts between readings, and what the CLI layers, aliases and refuses
(docs/consumers.md)."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from seanchai import dictionary
from seanchai.cli import main
from seanchai.dad import ast
from seanchai.dictionary import Dictionary, HoleError, build
from seanchai.model import Model, ModelError

_S6A = 16777251
_CX = 16777216
_STA = 16777250


@pytest.fixture(scope="module")
def built() -> Model:
    return Model.installed()


@pytest.fixture(scope="module")
def s6a_and_cx(built) -> Dictionary:
    return build(built, application_ids=(_S6A, _CX))


def _run(*arguments: str):
    return CliRunner().invoke(main, list(arguments))


def _written(tmp_path: Path, *arguments: str) -> dict:
    output = tmp_path / "out.json"
    result = _run("dictionary", "-o", str(output), *arguments)
    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text("utf-8"))
    Dictionary.model_validate(data)
    return data


# --- constraints --------------------------------------------------------------


def test_a_documents_rule_on_a_reused_avp_holds_where_it_reads_it(built):
    """TS 29.272 clause 7.3.43 reads MIP-Home-Agent-Host's members, an AVP
    RFC 4004 defines: its rules hold on S6a, where TS 29.272 reads the AVP,
    and not on RFC 4004's own AA-Mobile-Node-Request."""
    output = build(built, documents=["RFC4004", "TS29.272"])
    rules = [
        each
        for each in output.constraints
        if each.within == "MIP-Home-Agent-Host" and each.reference == "TS29.272"
    ]
    avps = {avp.id: avp for avp in output.avps}

    def reaches(members, ids: set[str], seen: frozenset[str]) -> bool:
        for member in members:
            if member.avp is None or member.avp in seen:
                continue
            if member.avp in ids or reaches(
                getattr(avps.get(member.avp), "members", ()), ids, seen | {member.avp}
            ):
                return True
        return False

    ids = {each for rule in rules for each in rule.avp_ids}
    assert {rule.avp for rule in rules} == {"Destination-Host", "Destination-Realm"}
    assert ids == {"0:348@TS29.272 in RFC4004"}
    reached = {
        (application.application_id, command.name)
        for application in output.applications
        for command in application.commands
        if reaches(command.members, ids, frozenset())
    }
    assert (_S6A, "Update-Location-Request") in reached
    assert not {name for app_id, name in reached if app_id != _S6A}
    amr = next(
        command
        for application in output.applications
        if application.application_id == 2
        for command in application.commands
        if command.name == "AA-Mobile-Node-Request"
    )
    assert reaches(amr.members, {"0:348"}, frozenset())


# --- value tables -------------------------------------------------------------


def test_an_application_holds_the_tables_of_every_reading_it_reaches(s6a_and_cx):
    """S6a reaches RFC 6733's Result-Code and AVPs TS 29.272 re-uses from TS
    29.273, 29.336 and 29.344, whose bit tables come with them."""
    tables = {(t.avp, t.reference) for t in s6a_and_cx.value_tables}

    assert {
        ("Result-Code", "RFC6733"),
        ("Emergency-Services", "TS29.273"),
        ("Reachability-Type", "TS29.336"),
        ("Battery-Indicator", "TS29.336"),
        ("ProSe-Permission", "TS29.344"),
        ("ULR-Flags", "TS29.272"),
    } <= tables


def test_an_application_holds_the_result_codes_its_document_adds_to(built):
    """TS 29.212 prints Result-Code values of its own (clause 5.5), which its
    reading of the AVP carries in place of RFC 6733's: Gx's dictionary holds
    both, since its answers may carry any, and a Wireshark plugin of Gx alone
    knows DIAMETER_SUCCESS."""
    gx = build(built, application_ids=(16777238,))
    codes = {
        (table.reference, table.section): {row.value for row in table.rows}
        for table in gx.value_tables
        if table.kind is ast.ValueKind.RESULT_CODES and table.vendor_id == 0
    }
    assert 2001 in codes[("RFC6733", "7.1")]
    assert ("TS29.212", "5.5") in codes


def test_a_re_used_bit_table_names_the_reading_and_application_carrying_it(
    s6a_and_cx,
):
    (emergency,) = [t for t in s6a_and_cx.value_tables if t.avp == "Emergency-Services"]
    ids = {avp.id: avp for avp in s6a_and_cx.avps}

    assert emergency.kind is ast.ValueKind.BITS
    assert emergency.applications == ("TS29.272/7/16777251",)
    assert [ids[each].name for each in emergency.avp_ids] == ["Emergency-Services"]
    assert ids[emergency.avp_ids[0]].defined_in == "TS29.273"


def test_each_application_keeps_its_own_feature_lists(s6a_and_cx):
    """Feature-List is TS 29.229's AVP; S6a's lists number other features than
    Cx's, and neither is the other's."""
    features = [
        (t.reference, t.application, t.feature_list_id, t.applications)
        for t in s6a_and_cx.value_tables
        if t.kind is ast.ValueKind.FEATURES
    ]

    assert features == [
        ("TS29.229", "Cx", 1, ("TS29.229/6/16777216",)),
        ("TS29.272", "S6a/S6d", 1, ("TS29.272/7/16777251",)),
        ("TS29.272", "S6a/S6d", 2, ("TS29.272/7/16777251",)),
    ]
    # One Feature-List reading carries both, so the application tells them apart.
    avp_ids = {t.avp_ids for t in s6a_and_cx.value_tables if t.avp == "Feature-List"}
    assert avp_ids == {("10415:630",)}


def test_the_model_reaches_each_identity_once_with_its_tables(built):
    """`Model.reached` is what the dictionary reads: S7a/S7d shares TS 29.272
    with S6a and takes none of its feature lists."""
    (s6a,) = built.applications("TS29.272", application_id=_S6A)
    (s7a,) = built.applications("TS29.272", application_id=16777308)

    reached = {entry.identity: entry for entry in built.reached(s6a)}
    feature_list = reached[10415, 630]
    assert feature_list.definition == built.definition((10415, 630))
    assert {t.application for t in feature_list.value_tables} == {"S6a/S6d"}
    (met,) = feature_list.readings
    assert ("ULR", "7.2.3") in {(p.command, p.section) for p in met.paths}
    assert not [
        table
        for entry in built.reached(s7a)
        for table in entry.value_tables
        if table.kind is ast.ValueKind.FEATURES
    ]
    owners = built.feature_owners(feature_list.value_tables[0])
    assert [owner.application_id for owner in owners] == [_S6A]


# --- readings and ids ---------------------------------------------------------


def test_equal_readings_serialise_alike_and_unequal_ones_apart(built):
    """Equality and `to_dict` cover the same fields: provenance a reading is
    told apart by is in both, and the context's value tables in neither."""
    readings = built.avps()
    texts = {json.dumps(avp.to_dict(), sort_keys=True) for avp in readings}

    assert len(texts) == len(set(readings)) == len(readings)
    for avp in readings:
        assert "value_tables" not in avp.to_dict()


def test_an_id_does_not_depend_on_the_selection(built, s6a_and_cx):
    everything = {avp.id: avp for avp in build(built).avps}

    for avp in s6a_and_cx.avps:
        assert everything[avp.id] == avp, avp.id
    assert dictionary.avp_id(built, built.definition("Session-Id")) == "0:263"


def test_conflicting_readings_are_listed_with_where_each_is_met(built):
    """TS 29.273's STa reads MIP6-Agent-Info both through its own table and,
    inside a grouped AVP of TS 29.272's, through TS 29.272's: so do the
    application's clauses 5 and 6, and not its clause 4."""
    (sta,) = built.applications("TS29.273", application_id=_STA)[1:2]
    (entry,) = [each for each in built.reached(sta) if each.identity == (0, 486)]

    assert entry.conflicts == ("flag_rules",)
    assert {met.avp.read_through for met in entry.readings} == {
        "TS29.273",
        "TS29.272",
    }

    written = build(built, application_ids=(_STA,))
    (conflict,) = [c for c in written.conflicts if (c.vendor_id, c.code) == (0, 486)]
    assert conflict.fields == ("flag_rules",)
    assert len(conflict.readings) == 2
    assert all(reading.paths for reading in conflict.readings)
    assert {path.application for r in conflict.readings for path in r.paths} <= {
        application.id for application in written.applications
    }
    assert not build(built, application_ids=(_S6A,)).conflicts


def test_a_conflict_only_an_obsoleted_document_dissents_from_is_marked(built):
    """RFC 7155 obsoletes RFC 4005, whose NAS-Port flags differ: the conflict
    is listed, marked obsolete, its RFC 4005 reading obsoleted by RFC 7155."""
    assert built.obsoleted_by("RFC4005") == ("RFC7155",)
    assert built.obsoletes("RFC6733") == ("RFC3588", "RFC5719")
    assert built.obsoleted_by("RFC3588") == ("RFC6733",)

    written = build(built, documents=("RFC4005", "RFC7155"))
    (nas_port,) = [c for c in written.conflicts if (c.vendor_id, c.code) == (0, 5)]
    by_document = {
        avp.read_through: reading.obsoleted_by
        for reading in nas_port.readings
        for avp in written.avps
        if avp.id == reading.avp
    }
    assert nas_port.obsolete
    assert by_document == {"RFC4005": ("RFC7155",), "RFC7155": ()}
    sta = build(built, application_ids=(_STA,))
    assert sta.conflicts and not any(conflict.obsolete for conflict in sta.conflicts)


def test_a_command_carries_its_information_elements(s6a_and_cx):
    """Each member indexes the command's rows mapping it; Cx's come from TS
    29.228, which the output lists as read."""
    s6a = next(a for a in s6a_and_cx.applications if a.application_id == _S6A)
    ulr = next(c for c in s6a.commands if c.abbreviation == "ULR")
    (user_name,) = [m for m in ulr.members if m.name == "User-Name"]
    (index,) = user_name.elements
    assert (ulr.elements[index].name, ulr.elements[index].category) == ("IMSI", "M")
    assert all(not m.elements for avp in s6a_and_cx.avps for m in avp.members)
    copies = {(each.reference, each.version) for each in s6a_and_cx.resolved}
    assert ("TS29.228", "19.2.0") in copies


def test_an_avp_carries_what_a_codec_needs(s6a_and_cx):
    by_name = {avp.name: avp for avp in s6a_and_cx.avps if avp.defining}

    assert by_name["Origin-Host"].basic_type is ast.DataType.OCTET_STRING
    assert by_name["Result-Code"].basic_type is ast.DataType.UNSIGNED32
    assert by_name["Cancellation-Type"].basic_type is ast.DataType.INTEGER32
    assert by_name["Visited-PLMN-Id"].may_encrypt is False
    # Cx reaches ETSI's Line-Identifier.
    assert {(v.vendor_id, v.name) for v in s6a_and_cx.vendors} == {
        (0, "IETF"),
        (10415, "3GPP"),
        (13019, "ETSI"),
    }
    (ulr,) = [
        p for a in s6a_and_cx.applications for p in a.pairs if p.command_code == 316
    ]
    assert (len(ulr.requests), len(ulr.answers)) == (1, 1)


def test_an_application_carries_its_tables_marks(built):
    """TS 29.212's Gx table 5.3.0.1 marks each AVP's access types and
    features."""
    written = build(built, application_ids=(16777238,))
    (gx,) = written.applications

    marked = {each.name: each for each in gx.marks}
    assert "Acc-Type" in marked["AN-GW-Address"].marks
    assert all(ast.interface_clause(each.section) == "5" for each in gx.marks)


def test_the_output_records_every_document_copy_it_read(built, s6a_and_cx):
    resolved = {(each.reference, each.version) for each in s6a_and_cx.resolved}

    assert ("TS29.272", built.version("TS29.272")) in resolved
    assert ("RFC6733", None) in resolved
    assert ("TS29.273", built.version("TS29.273")) in resolved


def test_an_older_copy_can_be_selected(built):
    older = build(built, documents=("TS29.061",), version="6.15.0")

    assert older.version == "6.15.0"
    assert {a.version for a in older.applications} == {"6.15.0"}
    assert ("TS29.061", "6.15.0") in {(d.reference, d.version) for d in older.resolved}
    with pytest.raises(ModelError, match="one document"):
        build(built, version="6.15.0")


def test_strict_refuses_a_reachable_hole(built):
    """TS 29.154's Nta names External-Group-Identifier, which no document
    defines."""
    with pytest.raises(HoleError, match="External-Group-Identifier") as raised:
        build(built, application_ids=(16777358,), strict=True)

    assert [hole.name for hole in raised.value.holes] == ["External-Group-Identifier"]
    assert build(built, application_ids=(_S6A,), strict=True).strict


def test_the_schema_validates_what_the_commands_write(tmp_path):
    schema_file = tmp_path / "schema.json"
    data = _written(tmp_path, "--application", str(_CX), "--schema", str(schema_file))
    schema = json.loads(schema_file.read_text("utf-8"))

    assert schema == dictionary.json_schema()
    definitions = schema["$defs"]
    for root, written in (
        ("Dictionary", data),
        ("Lookup", json.loads(_run("show", "Session-Id", "--json").stdout)),
        ("Listing", json.loads(_run("commands", "TS29.229", "--json").stdout)),
    ):
        assert {"$ref": f"#/$defs/{root}"} in schema["oneOf"]
        described = definitions[root]
        # Every field is always written, so every property is required.
        assert (
            set(described["required"]) == set(described["properties"]) == set(written)
        )
        version = described["properties"]["format_version"]
        assert version["minimum"] == version["maximum"] == dictionary.FORMAT_VERSION


# --- the command line ---------------------------------------------------------

# A private document: a stack's own AVPs and commands, in its own vendor's
# space, over the corpus. It re-uses TS 29.272's ULR-Flags, and a second one
# re-uses its token.
_ACME = """\
; Specification: Private ACME-HSS
; Version: 4.2
; Vendor-ID: 99999
; Bases: RFC6733

; Type: Message
; Name: ACME-Probe-Request, APR
; Section: 1
<ACME-Probe-Request> ::= < Diameter Header: 9999, REQ, 4242 >
        < Session-Id >
        { ACME-Token }
        [ ULR-Flags ]

; Type: AVP Table
; Section: 2
; Columns: Name Code Type Must May S.not M.not
ACME-Token 1 OctetString V,M - - -

; Type: Reused AVPs
; Section: 2
; Columns: Name From
ULR-Flags TS29.272
"""

_ACME_EDGE = """\
; Specification: Private ACME-Edge
; Vendor-ID: 99999
; Bases: RFC6733

; Type: Message
; Name: ACME-Edge-Request, AER
; Section: 1
<ACME-Edge-Request> ::= < Diameter Header: 9998, REQ, 4243 >
        < Session-Id >
        { ACME-Token }

; Type: Reused AVPs
; Section: 1
; Columns: Name From
ACME-Token Private-ACME-HSS
"""


def test_your_own_documents_sit_beside_the_corpus(tmp_path):
    acme = tmp_path / "acme.dad"
    acme.write_text(_ACME, encoding="utf-8")
    edge = tmp_path / "edge.dad"
    edge.write_text(_ACME_EDGE, encoding="utf-8")

    data = _written(
        tmp_path, "--with", str(acme), "--with", str(edge), "--application", "4242"
    )

    (application,) = data["applications"]
    assert application["reference"] == "Private-ACME-HSS"
    ids = {avp["id"]: avp for avp in data["avps"]}
    assert ids["99999:1"]["name"] == "ACME-Token"
    assert ids["0:263"]["defined_in"] == "RFC6733"
    # A private document means the newest copy it holds of what it cites.
    assert ids["10415:1405"]["defined_in"] == "TS29.272"
    shown = _run("show", "ACME-Token", "--with", str(acme))
    assert shown.exit_code == 0, shown.output
    listed = _run("commands", "--application", "4242", "--with", str(acme))
    assert "ACME-Probe-Request" in listed.stdout
    edged = _written(
        tmp_path, "--with", str(acme), "--with", str(edge), "--application", "4243"
    )
    (token,) = [avp for avp in edged["avps"] if avp["name"] == "ACME-Token"]
    assert (token["id"], token["defined_in"]) == ("99999:1", "Private-ACME-HSS")


def test_commands_read_another_corpus(tmp_path):
    acme = tmp_path / "acme.dad"
    acme.write_text(_ACME, encoding="utf-8")

    result = _run("commands", "--corpus", str(acme))

    assert result.exit_code == 0, result.output
    assert len(result.stdout.splitlines()) == 2
    assert _run("show", "Session-Id", "--corpus", str(acme)).exit_code == 1


def test_an_alias_answers_for_an_undefined_name(tmp_path):
    with pytest.raises(AssertionError):
        _written(tmp_path, "--application", "16777358", "--strict")

    data = _written(
        tmp_path,
        "--application",
        "16777358",
        "--strict",
        "--policy",
        "supply",
        "--alias",
        "External-Group-Identifier",
        "TS29.336",
        "External-Identifier",
    )

    aliased = [
        member
        for application in data["applications"]
        for command in application["commands"]
        for member in command["members"]
        if member["name"] == "External-Group-Identifier"
    ]
    assert aliased
    assert {m["alias"]["name"] for m in aliased} == {"External-Identifier"}
    assert not data["holes"]


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        ((), "give -o/--output, --schema or both"),
        (("-o", "x.json", "--version", "1.0.0"), "exactly one --document"),
        (
            ("-o", "x.json", "--alias", "A", "TS29.336", "B"),
            "--policy supply goes with",
        ),
    ],
)
def test_dictionary_refuses_a_usage_it_cannot_read(tmp_path, arguments, says):
    result = CliRunner().invoke(main, ["dictionary", *arguments])

    assert result.exit_code == 2, result.output
    assert says in result.stderr


def test_wireshark_names_come_with_a_wireshark_dictionary(tmp_path):
    """The Wireshark dictionary is downloaded, not committed, so this one is
    written here."""
    wireshark = tmp_path / "wireshark"
    wireshark.mkdir()
    (wireshark / "dictionary.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<dictionary><base>'
        '<avp name="Cx-User-Data" code="606" vendor-id="TGPP">'
        '<type type-name="OctetString"/></avp></base>'
        '<vendor vendor-id="TGPP" code="10415" name="3GPP"/></dictionary>\n',
        encoding="utf-8",
    )

    named = _written(tmp_path, "--application", str(_CX), "--wireshark", str(wireshark))
    plain = _written(tmp_path, "--application", str(_CX))

    by_id = {avp["id"]: avp["wireshark_name"] for avp in named["avps"]}
    assert by_id["10415:606"] == "Cx-User-Data"
    assert not {avp["wireshark_name"] for avp in plain["avps"]} - {None}
