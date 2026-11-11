"""`seanchai show`, `commands` and `dictionary` over the committed corpus,
and the JSON shapes `seanchai.dictionary` gives them (docs/consumers.md)."""

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
from seanchai.model import Model


@pytest.fixture(scope="module")
def built() -> Model:
    return Model.installed()


def _run(*arguments: str):
    return CliRunner().invoke(main, list(arguments))


def _shown(*arguments: str) -> dict:
    result = _run("show", *arguments, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    Lookup.model_validate(data)
    return data


def _asked(data: dict) -> dict:
    (asked,) = (avp for avp in data["avps"] if avp["id"] == data["avp"])
    return asked


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


def _dictionary(tmp_path, *arguments: str) -> dict:
    output = tmp_path / "out.json"
    result = _run("dictionary", "-o", str(output), *arguments)
    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text("utf-8"))
    Dictionary.model_validate(data)
    return data


def _bodies(data: dict):
    """Every member the output holds, with what it sits in."""
    for application in data.get("applications", ()):
        for command in application["commands"]:
            for member in (*command["members"], *command["dropped"]):
                yield command["name"], member
    for avp in data["avps"]:
        for member in (*avp["members"], *avp["dropped"]):
            yield avp["id"], member


def _assert_resolves(data: dict) -> None:
    """Every id a member or a walk names is in the output, once."""
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
            assert (kind, member["name"]) == ("wildcard", "AVP"), (owner, member)
    for application in data.get("applications", ()):
        for command in application["commands"]:
            assert set(command["walk"]) <= ids, command["name"]


# --- show --------------------------------------------------------------------


def test_show_prints_the_defining_reading_and_how_the_others_differ():
    result = _run("show", "Session-Id")

    assert result.exit_code == 0, result.output
    for line in (
        "Session-Id 0:263",
        "type: UTF8String",
        "flags: must M; must not V",
        "defined in: RFC6733, clause 8.8",
        "OMA-DDS-Charging_Data: flags must M; may P; must not V",
    ):
        assert line in result.stdout
    assert _run("show", "0:263").stdout == result.stdout
    assert "other readings" not in _run("show", "Data-Reference").stdout


@pytest.mark.parametrize(
    ("arguments", "lines"),
    [
        (
            ("Server-Capabilities",),
            ["* [ Mandatory-Capability ]  10415:604", "* [ AVP ]"],
        ),
        (("CC-Request-Type",), ["values:", "INITIAL_REQUEST = 1"]),
        (
            ("ULR-Flags",),
            [
                "bits (TS29.272, clause 7.3.7, table 7.3.7/1):",
                "    0 Single-Registration-Indication\n",
            ],
        ),
        (
            ("Result-Code",),
            [
                "result-codes (RFC6733, clause 7.1):",
                "    2001 DIAMETER_SUCCESS ; 7.1.2\n",
            ],
        ),
        (
            ("Feature-List", "--document", "TS29.229"),
            [
                "features of Cx list 1 (TS29.229, clause 7.1.1, table 7.1.1):",
                "    0 SiFC ; O\n",
            ],
        ),
        # Only TS 32.299 V11.20.0 holds it, through oneM2M TS-0004.
        (("10415:875",), ["WLAN-Information 10415:875"]),
        (("VAS-ID", "--document", "TS32.299", "--version", "11.20.0"), ["VAS-ID"]),
    ],
    ids=["members", "values", "bits", "result-codes", "features", "older", "version"],
)
def test_show_prints_what_the_reading_holds(arguments, lines):
    result = _run("show", *arguments)

    assert result.exit_code == 0, result.output
    for line in lines:
        assert line in result.stdout


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        (("Originator",), "names 2 AVPs"),
        (("External-Group-Identifier",), "undefined"),
        (("Sessoin-Id",), "did you mean Session-Id"),
        (("Session-Id", "--document", "TS99.999"), "no copy of TS99.999"),
    ],
)
def test_show_refuses_saying_why(arguments, says):
    result = _run("show", *arguments)

    assert result.exit_code == 1, result.output
    assert says in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_show_as_json_is_the_dictionarys_reading_then_the_others(tmp_path):
    data = _shown("Session-Id")

    assert data["format_version"] == FORMAT_VERSION
    assert data["seanchai_version"] == seanchai.__version__
    assert data["corpus_version"] == Corpus.installed().version
    assert data["undefined_policy"] == "hole"
    first, *others = data["avps"]
    assert first["id"] == data["avp"] == "0:263"
    assert first["defining"]
    assert [(each["id"], each["read_through"]) for each in others] == [
        ("0:263#2", "OMA-DDS-Charging_Data")
    ]
    dictionary = {avp["id"]: avp for avp in _dictionary(tmp_path)["avps"]}
    assert dictionary["0:263"] == first


def test_show_as_json_holds_everything_a_body_names_and_its_value_tables():
    data = _shown("Server-Capabilities")

    assert _asked(data)["kind"] == "grouped"
    assert {"Mandatory-Capability", "Server-Name"} <= {a["name"] for a in data["avps"]}
    _assert_resolves(data)
    _assert_resolves(_shown("SIP-Auth-Data-Item", "--document", "TS29.229"))
    tables = _shown("ULR-Flags")["value_tables"]
    assert [(t["kind"], t["table"], t["avp_id"]) for t in tables] == [
        ("bits", "7.3.7/1", "10415:1405")
    ]


def test_show_reads_a_name_as_a_document_does():
    """TS 29.229 table 6.3.0.1 puts M in Must for RFC 4590's Digest-Qop."""
    defining = _asked(_shown("Digest-Qop"))
    cited_data = _shown("Digest-Qop", "--document", "TS 29.229")
    cited = _asked(cited_data)

    assert (defining["defining"], defining["flag_rules"]["must"]) == (True, [])
    assert (cited["defining"], cited["flag_rules"]["must"]) == (False, ["M"])
    assert [avp["read_through"] for avp in cited_data["avps"]] == [
        "TS29.229",
        "RFC4590",
    ]
    assert _shown("0:110", "--document", "TS29.229") == cited_data


# --- commands ----------------------------------------------------------------


def test_commands_lists_one_document_as_a_table():
    result = _run("commands", "TS 29.229")

    assert result.exit_code == 0, result.output
    header, first, second, *_ = result.stdout.splitlines()
    assert header.split() == [
        "CODE",
        "KIND",
        "APPLICATION",
        "NAME",
        "DOCUMENT",
        "SECTION",
    ]
    assert first.split() == [
        "300",
        "request",
        "16777216",
        "User-Authorization-Request",
        "(UAR)",
        "TS29.229",
        "6.1.1",
    ]
    assert second.split()[:2] == ["300", "answer"]


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
    # TS 29.212's CCR prints a bare header: the id on the wire is its block's.
    ccr = next(row for row in _listed("TS29.212") if row["abbreviation"] == "CCR")
    assert ccr["application_id"] == 16777238


def test_commands_takes_an_application_across_documents_or_the_whole_corpus(built):
    expected = [
        message.name
        for application in built.applications(application_id=16777216)
        for message in application.messages
    ]

    rows = _listed("--application", "16777216")

    assert [row["name"] for row in rows] == expected
    assert {row["reference"] for row in rows} == {"TS29.229", "3GPP2-X.S0013-006"}
    assert len(_listed()) == len(built.messages())


@pytest.mark.parametrize(
    "arguments", [("TS29.229", "--application", "4"), ("TS99.999",)]
)
def test_commands_refuses_what_the_corpus_lacks(arguments):
    result = _run("commands", *arguments)

    assert result.exit_code == 1, result.output
    assert result.stderr.startswith("error: ")


# --- dictionary --------------------------------------------------------------


def test_the_file_says_what_produced_it(tmp_path, built):
    data = _dictionary(tmp_path)

    assert data["format_version"] == FORMAT_VERSION
    assert data["seanchai_version"] == seanchai.__version__
    assert data["corpus_version"] == Corpus.installed().version
    assert data["undefined_policy"] == "hole"
    assert data["documents"] == list(built.references())
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


@pytest.mark.parametrize("policy", ["hole", "drop", "placeholder"])
def test_every_member_names_an_entry_of_the_file(tmp_path, policy):
    data = _dictionary(tmp_path, "--policy", policy)

    assert data["undefined_policy"] == policy
    _assert_resolves(data)


def test_an_avp_id_is_its_identity_and_further_readings_are_numbered(tmp_path, built):
    """The entry without `#` is the definition's reading, `defining`."""
    data = _dictionary(tmp_path)

    plain = [avp for avp in data["avps"] if "#" not in avp["id"]]

    assert len(plain) == len({(a["vendor_id"], a["code"]) for a in data["avps"]})
    for avp in plain:
        assert avp["id"] == f"{avp['vendor_id']}:{avp['code']}"
        assert avp["defining"], avp["id"]
        assert built.definition((avp["vendor_id"], avp["code"])) is not None
    assert not [a for a in data["avps"] if a["defining"] and "#" in a["id"]]


def test_a_cited_reading_is_what_the_citing_documents_commands_name(tmp_path):
    """TS 29.229's commands hold its reading of Digest-Qop through
    SIP-Auth-Data-Item, M in Must where RFC 4590 has it in May."""
    data = _dictionary(tmp_path, "--document", "TS29.229")
    readings = {avp["id"]: avp for avp in data["avps"]}

    (digest,) = (avp for avp in data["avps"] if avp["name"] == "Digest-Qop")
    (grouped,) = (avp for avp in data["avps"] if avp["name"] == "SIP-Auth-Data-Item")

    assert (digest["read_through"], digest["flag_rules"]["must"]) == ("TS29.229", ["M"])
    assert grouped["kind"] == "grouped"
    assert all(
        readings[member["avp"]]["name"] == member["name"]
        for member in grouped["members"]
        if member["kind"] == "avp"
    )


def test_an_application_keeps_what_its_commands_and_error_answers_use(tmp_path, built):
    """TS 29.229 clause 7.3.1's `<answer-message>`, and 3GPP2 X.S0013-006's,
    whose Cx shares the id."""
    used = set()
    for application in built.applications(application_id=16777216):
        answer = built.answer_message(application.reference)
        assert answer is not None
        for member in (*application.walk(), *answer.walk()):
            if member.avp is not None:
                used.add(member.avp.identity)

    data = _dictionary(tmp_path, "--application", "16777216")

    assert data["application_ids"] == [16777216]
    assert {a["application_id"] for a in data["applications"]} == {16777216}
    assert {(a["vendor_id"], a["code"]) for a in data["avps"]} == used
    _assert_resolves(data)


def test_a_document_keeps_what_its_tables_list_and_what_its_commands_use(
    tmp_path, built
):
    data = _dictionary(tmp_path, "--document", "TS 29.229")

    assert data["documents"] == ["TS29.229"]
    identities = {(a["vendor_id"], a["code"]) for a in data["avps"]}
    assert {avp.identity for avp in built.avps("TS29.229")} <= identities
    assert (0, 263) in identities  # RFC 6733's, which no table of TS 29.229 lists
    _assert_resolves(data)
    # RFC 7683 prints no command, and still gives the AVPs it defines.
    alone = build(built, documents=["RFC7683"])
    assert not alone.applications and alone.avps


def test_an_answer_names_the_answer_message_it_takes_with_the_e_bit(tmp_path):
    data = _dictionary(tmp_path, "--document", "TS29.272", "--document", "TS29.229")
    answers = {entry["id"]: entry for entry in data["answer_messages"]}
    readings = {avp["id"] for avp in data["avps"]}

    assert set(answers) == {"TS29.229/TS29.229:7.3.1", "TS29.272/RFC6733:7.2"}
    for application in data["applications"]:
        for command in application["commands"]:
            if command["is_request"]:
                assert command["answer_message"] is None
            else:
                taken = answers[command["answer_message"]]
                assert taken["read_through"] == application["reference"]
    names = [m["name"] for m in answers["TS29.229/TS29.229:7.3.1"]["members"]]
    assert "Supported-Applications" in names
    assert all(each in readings for entry in answers.values() for each in entry["walk"])


def test_the_dictionary_holds_the_selected_documents_value_tables(built):
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
    by_application = build(built, application_ids=(16777216,))
    assert {table.reference for table in by_application.value_tables} == {"TS29.229"}
    assert Dictionary.model_validate(by_application.model_dump()) == by_application


def test_the_policies_answer_for_undefined_names(tmp_path):
    """TS 29.154's ECR names External-Group-Identifier, which no document
    defines."""
    name = "External-Group-Identifier"

    held = _dictionary(tmp_path, "--document", "TS29.154")
    (hole,) = [m for _, m in _bodies(held) if m["name"] == name]
    assert hole["kind"] == "hole"
    (recorded,) = [h for h in held["holes"] if h["id"] == hole["hole"]]
    assert recorded["missing"] == ["undefined"] and recorded["recorded"]

    dropped = _dictionary(tmp_path, "--document", "TS29.154", "--policy", "drop")
    (ecr,) = [
        command
        for application in dropped["applications"]
        for command in application["commands"]
        if command["abbreviation"] == "ECR"
    ]
    assert name not in {m["name"] for m in ecr["members"]}
    assert [(m["name"], m["kind"]) for m in ecr["dropped"]] == [(name, "hole")]
    _assert_resolves(dropped)

    kept = _dictionary(tmp_path, "--document", "TS29.154", "--policy", "placeholder")
    (placeholder,) = [m for _, m in _bodies(kept) if m["name"] == name]
    assert (placeholder["kind"], placeholder["avp"]) == ("placeholder", None)
    assert placeholder["placeholder"]["section"] == "A.6.6.2"


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
    assert (supplied["id"], bool(supplied["supplied"])) == ("99999:59999", True)
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
