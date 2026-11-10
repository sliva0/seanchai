"""`seanchai show`, `commands` and `dictionary`, over the committed corpus."""

import json
import os
import subprocess
import sys

import pytest
from click.testing import CliRunner

import seanchai
from seanchai.cli import main
from seanchai.corpus import Corpus
from seanchai.dad import ast
from seanchai.dictionary import FORMAT_VERSION, Dictionary, Listing, Lookup, build
from seanchai.model import Model, UndefinedPolicy


def _run(*arguments: str):
    return CliRunner().invoke(main, list(arguments))


def test_show_prints_the_defining_reading_and_how_the_others_differ():
    result = _run("show", "Session-Id")

    assert result.exit_code == 0, result.output
    assert "Session-Id 0:263" in result.stdout
    assert "type: UTF8String" in result.stdout
    assert "flags: must M; must not V" in result.stdout
    assert "defined in: RFC6733, clause 8.8" in result.stdout
    assert "other readings:" in result.stdout
    assert "OMA-DDS-Charging_Data: flags must M; may P; must not V" in result.stdout


def test_show_says_nothing_of_other_readings_where_there_are_none():
    result = _run("show", "Data-Reference")

    assert result.exit_code == 0, result.output
    assert "other readings" not in result.stdout


def test_show_lists_a_grouped_avps_members_with_their_identities():
    result = _run("show", "Server-Capabilities")

    assert result.exit_code == 0, result.output
    assert "members:" in result.stdout
    assert "* [ Mandatory-Capability ]  10415:604" in result.stdout
    assert "* [ AVP ]" in result.stdout


def test_show_lists_an_enumerated_avps_values():
    result = _run("show", "CC-Request-Type")

    assert result.exit_code == 0, result.output
    assert "values:" in result.stdout
    assert "INITIAL_REQUEST = 1" in result.stdout


def test_show_takes_an_identity_and_gives_what_the_name_gives():
    assert _run("show", "0:263").stdout == _run("show", "Session-Id").stdout


def _shown(*arguments: str) -> dict:
    result = _run("show", *arguments, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    Lookup.model_validate(data)
    return data


def _asked(data: dict) -> dict:
    (asked,) = (avp for avp in data["avps"] if avp["id"] == data["avp"])
    return asked


def test_show_as_json_is_the_dictionarys_reading_and_the_other_readings(tmp_path):
    data = _shown("Session-Id")

    assert data["format_version"] == FORMAT_VERSION
    assert data["seanchai_version"] == seanchai.__version__
    assert data["corpus_version"] == Corpus.installed().version
    assert data["undefined_policy"] == "hole"
    assert data["avp"] == "0:263"
    first, *others = data["avps"]
    assert first["id"] == data["avp"]
    assert first["defining"]
    assert [(each["id"], each["read_through"]) for each in others] == [
        ("0:263#2", "OMA-DDS-Charging_Data")
    ]
    # The defining reading as the whole dictionary writes it.
    dictionary = {avp["id"]: avp for avp in _dictionary(tmp_path)["avps"]}
    assert dictionary["0:263"] == first


def test_show_as_json_holds_everything_a_body_names():
    data = _shown("Server-Capabilities")

    assert _asked(data)["kind"] == "grouped"
    assert data["avps"][0]["id"] == data["avp"]
    names = {avp["name"] for avp in data["avps"]}
    assert {"Mandatory-Capability", "Optional-Capability", "Server-Name"} <= names
    _assert_resolves(data)

    held = _shown("SIP-Auth-Data-Item", "--document", "TS29.229")
    _assert_resolves(held)

    tables = _shown("ULR-Flags")["value_tables"]
    assert [(table["kind"], table["table"]) for table in tables] == [
        ("bits", "7.3.7/1")
    ]
    assert tables[0]["avp_id"] == "10415:1405"


def test_show_reads_it_as_a_document_does_and_at_an_older_copy():
    defining = _asked(_shown("Digest-Qop"))
    cited_data = _shown("Digest-Qop", "--document", "TS 29.229")
    cited = _asked(cited_data)
    assert defining["flag_rules"]["must"] == []
    assert defining["defining"]
    assert cited["flag_rules"]["must"] == ["M"]
    assert not cited["defining"]
    assert cited_data["avps"][0] == cited
    assert [avp["read_through"] for avp in cited_data["avps"]] == [
        "TS29.229",
        "RFC4590",
    ]

    assert _shown("0:110", "--document", "TS29.229") == cited_data

    older = _run("show", "VAS-ID", "--document", "TS32.299", "--version", "11.20.0")
    assert older.exit_code == 0, older.output
    assert "VAS-ID" in older.stdout


@pytest.mark.parametrize(
    ("arguments", "status", "says"),
    [
        (("Originator",), 1, "names 2 AVPs"),
        (("External-Group-Identifier",), 1, "undefined"),
        (("Sessoin-Id",), 1, "did you mean Session-Id"),
        (("Session-Id", "--document", "TS99.999"), 1, "no copy of TS99.999"),
        (("Session-Id", "--version", "1.0.0"), 2, "--version needs --document"),
        (("1:x",), 2, "VENDOR:CODE"),
        ((), 2, "NAME_OR_IDENTITY"),
    ],
)
def test_show_refuses(arguments, status, says):
    result = _run("show", *arguments)

    assert result.exit_code == status, result.output
    assert says in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_commands_lists_one_document():
    result = _run("commands", "TS 29.229")

    assert result.exit_code == 0, result.output
    header, *rows = result.stdout.splitlines()
    assert header.split() == [
        "CODE",
        "KIND",
        "APPLICATION",
        "NAME",
        "DOCUMENT",
        "SECTION",
    ]
    assert rows[0].split() == [
        "300",
        "request",
        "16777216",
        "User-Authorization-Request",
        "(UAR)",
        "TS29.229",
        "6.1.1",
    ]
    assert rows[1].split()[:2] == ["300", "answer"]


def _listed(*arguments: str) -> list[dict]:
    """The commands `seanchai commands --json` lists, each with its
    application's `reference`."""
    result = _run("commands", *arguments, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    Listing.model_validate(data)
    assert data["format_version"] == FORMAT_VERSION
    return [
        {**command, "reference": application["reference"]}
        for application in data["applications"]
        for command in application["commands"]
    ]


def test_commands_shows_the_effective_application_id():
    """TS 29.212 prints its CCR with a bare header: the id on the wire comes
    from the Application Scope covering the clause."""
    rows = _listed("TS29.212")

    assert {row["application_id"] for row in rows} >= {16777238}
    assert all(set(row) >= {"command_code", "is_request", "section"} for row in rows)


def test_commands_as_json_are_the_dictionarys_without_their_bodies(tmp_path):
    listed = json.loads(_run("commands", "TS29.229", "--json").stdout)
    written = _dictionary(tmp_path, "--document", "TS29.229")

    bodies = {"members", "dropped", "walk", "answer_message"}
    assert listed["applications"] == [
        {
            **application,
            "commands": [
                {key: value for key, value in command.items() if key not in bodies}
                for command in application["commands"]
            ],
        }
        for application in written["applications"]
    ]


def test_commands_takes_an_application_across_documents():
    built = Model.installed()
    expected = [
        message.name
        for application in built.applications(application_id=16777216)
        for message in application.messages
    ]

    rows = _listed("--application", "16777216")

    assert [row["name"] for row in rows] == expected
    assert {row["application_id"] for row in rows} == {16777216}


def test_commands_with_nothing_named_lists_the_corpus():
    rows = _listed()

    assert len(rows) == len(Model.installed().messages())


@pytest.mark.parametrize(
    "arguments",
    [("--application", "99"), ("TS29.229", "--application", "4"), ("TS99.999",)],
)
def test_commands_refuses_what_the_corpus_lacks(arguments):
    result = _run("commands", *arguments)

    assert result.exit_code == 1, result.output
    assert result.stderr.startswith("error: ")


def _dictionary(tmp_path, *arguments: str) -> dict:
    output = tmp_path / "out.json"
    result = _run("dictionary", "-o", str(output), *arguments)
    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text("utf-8"))
    Dictionary.model_validate(data)
    return data


def _bodies(data: dict):
    """Every member the file holds, with what it sits in."""
    for application in data.get("applications", ()):
        for command in application["commands"]:
            for member in (*command["members"], *command["dropped"]):
                yield command["name"], member
    for avp in data["avps"]:
        for member in (*avp["members"], *avp["dropped"]):
            yield avp["id"], member


def _assert_resolves(data: dict) -> None:
    ids = {avp["id"] for avp in data["avps"]}
    holes = {hole["id"] for hole in data["holes"]}
    assert len(ids) == len(data["avps"])
    assert len(holes) == len(data["holes"])
    members = list(_bodies(data))
    assert members
    for owner, member in members:
        kind = member["kind"]
        if kind == "avp":
            assert member["avp"] in ids, (owner, member)
        elif kind == "hole":
            assert member["hole"] in holes, (owner, member)
        elif kind == "placeholder":
            assert member["placeholder"]["section"], (owner, member)
        else:
            assert kind == "wildcard", (owner, member)
            assert member["name"] == "AVP", (owner, member)
    for application in data.get("applications", ()):
        for command in application["commands"]:
            assert set(command["walk"]) <= ids, command["name"]


@pytest.mark.parametrize("policy", ["hole", "drop", "placeholder"])
def test_every_member_resolves(tmp_path, policy):
    data = _dictionary(tmp_path, "--policy", policy)

    assert data["undefined_policy"] == policy
    _assert_resolves(data)


def test_no_member_is_a_body_among_its_own_descendants():
    """What `Dictionary.members` leaves out, since it names nothing to read."""
    built = Model.installed()
    from seanchai import model
    from seanchai.model._types import is_cut

    assert not [
        member
        for message in built.messages()
        for member in message.avps
        if is_cut(member)
    ]
    assert not [
        member
        for avp in built.avps()
        if isinstance(avp, model.Grouped)
        for member in avp.members
        if is_cut(member)
    ]


def test_the_file_says_what_produced_it(tmp_path):
    data = _dictionary(tmp_path)

    assert data["format_version"] == FORMAT_VERSION
    assert data["seanchai_version"] == seanchai.__version__
    assert data["corpus_version"] == Corpus.installed().version
    assert data["undefined_policy"] == "hole"
    assert data["documents"] == list(Model.installed().references())
    assert data["application_ids"] == []


def test_the_file_is_byte_stable(tmp_path):
    """Under two hash seeds, from a directory holding nothing of the repository,
    in the form a build reads."""
    outputs = []
    for seed in ("1", "2"):
        output = tmp_path / f"out-{seed}.json"
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from seanchai.cli import main; main()",
                "dictionary",
                "-o",
                str(output),
            ],
            cwd=tmp_path,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
        )
        outputs.append(output.read_bytes())

    assert outputs[0] == outputs[1]
    assert outputs[0].endswith(b"}\n")


def test_every_identity_has_one_reading_with_no_suffix(tmp_path):
    data = _dictionary(tmp_path)

    plain = [avp for avp in data["avps"] if "#" not in avp["id"]]
    identities = {(avp["vendor_id"], avp["code"]) for avp in data["avps"]}
    assert len(plain) == len(identities)
    assert all(avp["id"] == f"{avp['vendor_id']}:{avp['code']}" for avp in plain)
    assert not [avp for avp in data["avps"] if avp["defining"] and "#" in avp["id"]]
    assert [avp["id"] for avp in data["avps"]] == sorted(
        (avp["id"] for avp in data["avps"]),
        key=lambda each: (
            *map(int, each.partition("#")[0].split(":")),
            int(each.partition("#")[2] or 1),
        ),
    )


def test_a_printed_id_reaches_the_commands_whose_headers_omit_it():
    """TS 32.299 V11.20.0 states them in clauses 7.1.5 and 7.1.6, as V18.0.0."""
    built = Model.installed()

    assert [
        (each.name, message.abbreviation, message.application_id)
        for each in built.applications("TS32.299", version="11.20.0")
        for message in each.messages
    ] == [
        ("Rf", "ACR", 3),
        ("Rf", "ACA", 3),
        ("Ro", "CCR", 4),
        ("Ro", "CCA", 4),
        ("Ro", "RAR", 4),
        ("Ro", "RAA", 4),
    ]


def test_an_application_printing_no_command_still_states_its_id():
    """RFC 6942 runs RFC 4072's commands under id 13, and prints none."""
    entry = next(
        each for each in Corpus.installed().newest() if each.reference == "RFC6942"
    )

    assert [
        (section.name, section.application_id, section.source.section)
        for section in entry.spec.sections
        if isinstance(section, ast.ApplicationScope)
    ] == [("Diameter ERP", 13, "7")]


def test_every_identity_resolves_through_the_definition(tmp_path):
    data = _dictionary(tmp_path)
    built = Model.installed()

    assert not [
        avp["id"]
        for avp in data["avps"]
        if built.definition((avp["vendor_id"], avp["code"])) is None
    ]
    assert not [
        avp["id"]
        for avp in data["avps"]
        if "#" not in avp["id"] and not avp["defining"]
    ]


def test_show_answers_for_an_identity_only_an_older_copy_holds():
    """oneM2M TS-0004's Service-Information is TS 32.299 V11.20.0's, whose
    WLAN-Information later releases removed."""
    built = Model.installed()

    found = built.definition((10415, 875))
    assert found is not None
    assert (found.name, found.read_through) == (
        "WLAN-Information",
        "TS32.299 V11.20.0",
    )
    assert _run("show", "10415:875").exit_code == 0
    assert _run("show", "WLAN-Information").exit_code == 0


def test_a_v11_table_row_reads_its_definition_under_the_clauses_spelling():
    """Table 7.2 spells it LCS-Client-Id; left apart from clause 7.2.84's
    LCS-Client-ID, the body read as an IETF AVP, (0, 1232)."""
    built = Model.installed()

    assert built.readings((0, 1232)) == ()
    avp = built.resolve("TS32.299", "LCS-Client-ID", version="11.20.0")
    assert avp is not None
    assert avp.identity == (10415, 1232)


def test_a_cited_reading_is_what_the_citing_documents_commands_name(tmp_path):
    """TS 29.229's commands hold its reading of `Digest-Qop` through
    `SIP-Digest-Authenticate`, M in Must where RFC 4590 has it in May."""
    data = _dictionary(tmp_path, "--document", "TS29.229")
    readings = {avp["id"]: avp for avp in data["avps"]}

    (digest,) = (avp for avp in data["avps"] if avp["name"] == "Digest-Qop")

    assert digest["read_through"] == "TS29.229"
    assert digest["flag_rules"]["must"] == ["M"]
    (grouped,) = (avp for avp in data["avps"] if avp["name"] == "SIP-Auth-Data-Item")
    assert grouped["kind"] == "grouped"
    assert all(
        readings[member["avp"]]["name"] == member["name"]
        for member in grouped["members"]
        if member["kind"] == "avp"
    )


def test_an_application_keeps_what_its_commands_use(tmp_path):
    built = Model.installed()
    (cx,) = built.applications("TS29.229", application_id=16777216)
    used = {member.avp.identity for member in cx.walk() if member.avp is not None}
    # And what their answers take with the E bit set: TS 29.229 clause 7.3.1's
    # `<answer-message>`, and 3GPP2 X.S0013-006's, whose Cx shares the id.
    for application in built.applications(application_id=16777216):
        answer = built.answer_message(application.reference)
        assert answer is not None
        used |= {each.avp.identity for each in answer.walk() if each.avp is not None}

    data = _dictionary(tmp_path, "--application", "16777216")

    assert data["application_ids"] == [16777216]
    assert {a["application_id"] for a in data["applications"]} == {16777216}
    assert {(a["vendor_id"], a["code"]) for a in data["avps"]} == used
    _assert_resolves(data)


def test_a_document_keeps_what_its_tables_list_and_what_its_commands_use(tmp_path):
    built = Model.installed()

    data = _dictionary(tmp_path, "--document", "TS 29.229")

    assert data["documents"] == ["TS29.229"]
    identities = {(a["vendor_id"], a["code"]) for a in data["avps"]}
    assert {avp.identity for avp in built.avps("TS29.229")} <= identities
    assert (0, 263) in identities  # RFC 6733's, which no table of TS 29.229 lists
    _assert_resolves(data)


def test_a_document_defining_avps_alone_still_gives_them():
    built = Model.installed()

    written = build(built, documents=["RFC7683"])

    assert not written.applications
    assert written.avps


def test_the_policies_answer_for_undefined_names(tmp_path):
    held = _dictionary(tmp_path, "--document", "TS29.154")
    (hole,) = [m for _, m in _bodies(held) if m["name"] == "External-Group-Identifier"]
    assert hole["kind"] == "hole"
    (recorded,) = [h for h in held["holes"] if h["id"] == hole["hole"]]
    assert recorded["missing"] == ["undefined"]
    assert recorded["recorded"]

    dropped = _dictionary(tmp_path, "--document", "TS29.154", "--policy", "drop")
    assert not [
        each
        for application in dropped["applications"]
        for command in application["commands"]
        for each in command["members"]
        if each["name"] == "External-Group-Identifier"
    ]
    assert [
        each
        for _, each in _bodies(dropped)
        if each["name"] == "External-Group-Identifier" and each["kind"] == "hole"
    ]
    _assert_resolves(dropped)

    kept = _dictionary(tmp_path, "--document", "TS29.154", "--policy", "placeholder")
    (placeholder,) = [
        m for _, m in _bodies(kept) if m["name"] == "External-Group-Identifier"
    ]
    assert placeholder["kind"] == "placeholder"
    assert placeholder["placeholder"]["section"] == "A.6.6.2"
    assert placeholder["avp"] is None


def test_a_supplied_answer_is_an_avp_like_any_other(tmp_path):
    sidecar = tmp_path / "acme.dad"
    sidecar.write_text(
        "; Specification: RFC 9999\n"
        "; Vendor-ID: 99999\n"
        "\n"
        "; Type: AVP Table\n"
        "; Section: 1\n"
        "; Columns: Name Code Type Must May S.not M.not\n"
        "External-Group-Identifier 59999 UTF8String V,M - - -\n",
        encoding="utf-8",
    )

    data = _dictionary(
        tmp_path,
        "--document",
        "TS29.154",
        "--policy",
        "supply",
        "--supply",
        str(sidecar),
    )

    assert data["undefined_policy"] == "supply"
    (supplied,) = [a for a in data["avps"] if a["name"] == "External-Group-Identifier"]
    assert supplied["supplied"]
    assert supplied["id"] == "99999:59999"
    _assert_resolves(data)


@pytest.mark.parametrize(
    ("arguments", "status", "says"),
    [
        (("--application", "99"), 1, "no application 99"),
        (("--document", "TS99.999"), 1, "no copy of TS99.999"),
        (("--policy", "supply"), 2, "--policy supply and --supply"),
        (("--policy", "maybe"), 2, "maybe"),
    ],
)
def test_dictionary_refuses_and_writes_nothing(tmp_path, arguments, status, says):
    output = tmp_path / "out.json"

    result = _run("dictionary", "-o", str(output), *arguments)

    assert result.exit_code == status, result.output
    assert says in result.stderr
    assert not output.exists()


def test_dictionary_needs_somewhere_to_write():
    assert _run("dictionary").exit_code == 2


def test_policy_names_are_the_models():
    assert {each.value for each in UndefinedPolicy} == {
        "hole",
        "drop",
        "placeholder",
        "supply",
    }


def test_show_prints_a_bit_mask_s_bits():
    result = _run("show", "ULR-Flags")

    assert result.exit_code == 0, result.output
    assert "bits (TS29.272, clause 7.3.7, table 7.3.7/1):" in result.stdout
    assert "    0 Single-Registration-Indication\n" in result.stdout


def test_show_prints_result_codes_and_marks():
    result = _run("show", "Result-Code")
    assert "result-codes (RFC6733, clause 7.1):" in result.stdout
    assert "    2001 DIAMETER_SUCCESS ; 7.1.2\n" in result.stdout

    cx = _run("show", "Feature-List", "--document", "TS29.229")
    assert "features of Cx list 1 (TS29.229, clause 7.1.1, table 7.1.1):" in cx.stdout
    assert "    0 SiFC ; O\n" in cx.stdout


def test_the_dictionary_holds_the_selected_documents_value_tables():
    built = Model.build(Corpus.installed())

    selected = build(built, documents=("TS29.272",))
    assert {table.reference for table in selected.value_tables} == {"TS29.272"}
    flags = next(table for table in selected.value_tables if table.avp == "ULR-Flags")
    assert (flags.kind, flags.table, flags.vendor_id) == (
        ast.ValueKind.BITS,
        "7.3.7/1",
        10415,
    )
    assert flags.avp_id == next(
        avp.id for avp in selected.avps if avp.name == "ULR-Flags"
    )
    features = [t for t in selected.value_tables if t.kind is ast.ValueKind.FEATURES]
    assert [(t.application, t.feature_list_id) for t in features] == [
        ("S6a/S6d", 1),
        ("S6a/S6d", 2),
    ]
    assert features[0].rows[0].mark == "O"
    assert features[0].avp_id is None or features[0].avp_id.endswith(":630")

    by_application = build(built, application_ids=(16777216,))
    assert {table.reference for table in by_application.value_tables} == {"TS29.229"}
    assert Dictionary.model_validate(by_application.model_dump()) == by_application


def test_an_answer_names_the_answer_message_it_takes_with_the_e_bit(tmp_path):
    data = _dictionary(tmp_path, "--document", "TS29.272", "--document", "TS29.229")
    answers = {entry["id"]: entry for entry in data["answer_messages"]}
    readings = {avp["id"]: avp for avp in data["avps"]}

    assert set(answers) == {"TS29.229/TS29.229:7.3.1", "TS29.272/RFC6733:7.2"}
    for application in data["applications"]:
        for command in application["commands"]:
            if command["is_request"]:
                assert command["answer_message"] is None
            else:
                taken = command["answer_message"]
                assert answers[taken]["read_through"] == application["reference"]
    names = [member["name"] for member in answers["TS29.229/TS29.229:7.3.1"]["members"]]
    assert "Supported-Applications" in names
    assert all(each in readings for entry in answers.values() for each in entry["walk"])
