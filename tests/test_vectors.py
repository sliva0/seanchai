"""`seanchai vectors`: the messages it writes, and the Wireshark plugin's
core as their end-to-end test. Every valid vector draws no error, warning
or note of an interpreted rule from `core.lua`, and every negative one
exactly the finding it expects, under
each Lua on PATH; the generated plugin under tshark reads the capture alike.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from seanchai_corpus import CORPUS_DIR

from seanchai import dictionary, vectors, wireshark
from seanchai.cli import main
from seanchai.corpus import Corpus
from seanchai.model import Model

CORE = Path(wireshark.__file__).parent / "core.lua"
LUAS = [name for name in ("lua5.1", "lua5.2", "lua5.3", "lua5.4") if shutil.which(name)]
S6A = 16777251
# The base protocol, DCCA (several documents' CCR), EAP (TS 29.234's DEA lists
# User-Name twice), Cx, Gx, S6a, PC3a's WiFi-P2P-Assistance-Info (a member
# listed twice) and T6a (APN-Rate-Control-Status, typed Grouped by a table
# that prints no rule).
_APPLICATIONS = (0, 4, 5, 16777216, 16777238, S6A, 16777340, 16777346)


@pytest.fixture(scope="module")
def built():
    books = Corpus.installed()
    return books, Model.build(books)


def _vectors(built, *applications: int) -> vectors.Vectors:
    books, model = built
    return vectors.build(
        dictionary.build(
            model, application_ids=applications, corpus_version=books.version
        ),
        vectors.pages_of(books),
    )


@pytest.fixture(scope="module")
def s6a(built):
    return _vectors(built, S6A)


def test_every_command_gets_valid_and_negative_vectors_in_a_fixed_order(s6a, built):
    assert vectors.dumps(s6a) == vectors.dumps(_vectors(built, S6A))
    assert vectors.Vectors.model_validate_json(vectors.dumps(s6a)) == s6a
    commands = {(v.abbreviation, v.is_request) for v in s6a.vectors}
    for kind in ("minimal", "maximal"):
        assert {
            (v.abbreviation, v.is_request) for v in s6a.vectors if v.kind == kind
        } == commands
    negative = [v for v in s6a.vectors if v.kind == "negative"]
    assert all(len(v.expected) == 1 and v.breaks is not None for v in negative)
    assert all(
        not v.expected and v.breaks is None for v in s6a.vectors if v.kind != "negative"
    )
    rules = {v.expected[0].rule for v in negative}
    assert rules >= {
        "avp-missing",
        "avp-occurrences",
        "avp-position",
        "flag-must",
        "flag-must-not",
        "utf8",
        "data-length",
        "bits",
        "e-bit-unexpected",
        "constraint-length",
        "constraint-range",
        "constraint-exclude",
        "constraint-encoding",
        "constraint-requires",
        "constraint-present-if",
        "constraint-absent-if",
        "constraint-bits",
    }
    assert "vectors" in json.dumps(vectors.json_schema())


def test_a_minimal_message_holds_its_fixed_and_required_members_only(s6a):
    (ulr,) = [v for v in s6a.vectors if v.id == "16777251/ULR/minimal"]
    assert [node.name for node in ulr.tree] == [
        "Session-Id",
        "Auth-Session-State",
        "Origin-Host",
        "Origin-Realm",
        "Destination-Realm",
        "User-Name",
        "RAT-Type",
        "ULR-Flags",
        "Visited-PLMN-Id",
    ]
    visited = next(node for node in ulr.tree if node.name == "Visited-PLMN-Id")
    # TS 29.272 clause 7.3.9's PLMN identity: MCC 123, MNC 45.
    assert (visited.vendor_id, visited.flags, visited.data) == (10415, "VM", "21f354")
    assert bytes.fromhex(ulr.octets)[4] & 0x80  # a request


def test_a_negative_vector_cites_the_rule_it_breaks(s6a):
    imei, *_ = [v for v in s6a.vectors if v.id.endswith("constraint-length/IMEI/7.3.4")]
    assert imei.breaks is not None
    assert (imei.breaks.reference, imei.breaks.section, imei.breaks.page) == (
        "TS29.272",
        "7.3.4",
        100,
    )
    assert imei.expected == (
        vectors.Expected(rule="constraint-length", severity="note"),
    )


def test_a_command_requiring_what_the_corpus_cannot_complete_is_skipped(built):
    nta = _vectors(built, 16777358)
    assert {(s.command, s.what) for s in nta.skipped} >= {
        ("Nta/ECR", "minimal"),
        ("Nta/ECR", "maximal"),
    }


_RUNNER = """
local core = dofile(arg[1])
local rules = dofile(arg[2])
local function unhex(text)
  return (text:gsub("..", function(pair) return string.char(tonumber(pair, 16)) end))
end
for line in io.lines(arg[3]) do
  local pin, octets, request = line:match("^(%S+)\\t(%x+)\\t(%x*)$")
  local values = request ~= "" and core.request_values(rules, unhex(request)) or nil
  local result = core.validate(rules, unhex(octets), { pin = pin }, values)
  local parts = { result.command and result.command.document or "-" }
  for _, each in ipairs(result.findings) do
    parts[#parts + 1] = each.severity .. " " .. each.rule
  end
  io.write(table.concat(parts, "\\t"), "\\n")
end
"""


@pytest.fixture(scope="module")
def checked(built, tmp_path_factory):
    """The vectors of `_APPLICATIONS` but an obsoleted document's, which
    the plugin holds to the newer one, and the plugin's rules for them."""
    _, model = built
    work = tmp_path_factory.mktemp("vectors")
    rules = work / "rules.lua"
    options = [arg for each in _APPLICATIONS for arg in ("--application", str(each))]
    done = CliRunner().invoke(
        main, ["wireshark-plugin", *options, "--rules-only", "-o", str(rules)]
    )
    assert done.exit_code == 0, done.output
    obsolete = {r for r in model.references() if model.obsoleted_by(r)}
    kept = [
        v for v in _vectors(built, *_APPLICATIONS).vectors if v.document not in obsolete
    ]
    lines = work / "vectors.txt"
    lines.write_text(
        "".join(
            f"{v.document}\t{v.octets}\t{v.request.octets if v.request else ''}\n"
            for v in kept
        )
    )
    runner = work / "runner.lua"
    runner.write_text(_RUNNER, "utf-8")
    return kept, rules, lines, runner


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_plugin_reports_exactly_what_each_vector_expects(lua, checked):
    kept, rules, lines, runner = checked
    done = subprocess.run(
        [lua, str(runner), str(CORE), str(rules), str(lines)],
        check=True,
        capture_output=True,
        text=True,
    )
    held, wrong = 0, []
    for vector, line in zip(kept, done.stdout.splitlines(), strict=True):
        chosen, *found = line.split("\t")
        if chosen != vector.document:
            # Held to another document's definition of the command: one printing
            # no application id goes out in application 0 (TS 29.234's RAR),
            # or two copies of a document print it (TS 32.299 V11.20.0 and
            # V19.4.0's ACR).
            held += 1
            continue
        # Every error, warning and note of an interpreted rule exactly; other
        # notes (what the corpus cannot complete) only where expected.
        reported = sorted(
            (severity, rule)
            for severity, rule in (each.split(" ") for each in found)
            if severity != "note" or rule.startswith("constraint-")
        )
        expected = sorted(
            (e.severity, e.rule)
            for e in vector.expected
            if e.severity != "note" or e.rule.startswith("constraint-")
        )
        notes = {each.split(" ")[1] for each in found if each.startswith("note ")}
        if reported != expected or not all(
            e.rule in notes for e in vector.expected if e.severity == "note"
        ):
            wrong.append((vector.id, expected, found))
    assert not wrong, wrong[:5]
    assert held < len(kept) / 50


@pytest.mark.skipif(shutil.which("tshark") is None, reason="no tshark on PATH")
def test_tshark_reads_the_capture_as_the_core_does(s6a, tmp_path):
    plugin = tmp_path / "seanchai_diameter.lua"
    capture = tmp_path / "s6a.pcap"
    result = CliRunner().invoke(
        main,
        [
            "vectors",
            "--application",
            str(S6A),
            "-o",
            str(tmp_path / "s6a.json"),
            "--pcap",
            str(capture),
        ],
    )
    assert result.exit_code == 0, result.output
    done = CliRunner().invoke(
        main, ["wireshark-plugin", "--application", str(S6A), "-o", str(plugin)]
    )
    assert done.exit_code == 0, done.output
    shown = subprocess.run(
        [
            "tshark",
            "-n",
            "-r",
            str(capture),
            "-X",
            f"lua_script:{plugin}",
            "-T",
            "fields",
            "-e",
            "seanchai.errors",
            "-e",
            "seanchai.rule",
            "-Y",
            "seanchai",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Lua" not in shown.stderr, shown.stderr
    errors = [
        int(line.split("\t")[0]) for line in shown.stdout.splitlines() if line.strip()
    ]
    # An answer's request is a frame of its own, just before it.
    paired = sum(1 for v in s6a.vectors if v.request is not None)
    assert len(errors) == len(s6a.vectors) + paired
    failing = [v for v in s6a.vectors if any(e.severity == "error" for e in v.expected)]
    assert sum(1 for count in errors if count) == len(failing)
    # A breach of an interpreted rule is expert info of its own, a note.
    noted = subprocess.run(
        [
            "tshark",
            "-n",
            "-r",
            str(capture),
            "-X",
            f"lua_script:{plugin}",
            "-T",
            "fields",
            "-e",
            "_ws.expert.severity",
            "-Y",
            "seanchai.interpreted",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    interpreted = [
        v
        for v in s6a.vectors
        if any(e.rule.startswith("constraint-") for e in v.expected)
    ]
    lines = [line for line in noted.stdout.splitlines() if line.strip()]
    assert len(lines) == len(interpreted)
    # PI_NOTE among the frame's expert infos, which Wireshark's own Diameter
    # dissector adds to.
    assert all(str(0x00400000) in line.split(",") for line in lines)


# A document whose answer's rules read the request it answers, one of each
# form: a bit of a request's flags, a request's AVP present, and an echo.
_ASKED = """\
; Specification: 3GPP TS 29.999
; Version: 19.0.0
; Vendor-ID: 10415
; Bases: RFC6733


; Type: Message
; Name: Example-Request, EXR
; Section: 6.1.1
<Example-Request> ::= < Diameter Header: 9, REQ, PXY, 16777999 >
        < Session-Id >
        { Auth-Session-State }
        { Origin-Host }
        { Origin-Realm }
        { Destination-Realm }
        [ Example-Flags ]
        [ Example-Id ]
        *[ AVP ]


; Type: Message
; Name: Example-Answer, EXA
; Section: 6.1.2
<Example-Answer> ::= < Diameter Header: 9, PXY, 16777999 >
        < Session-Id >
        { Auth-Session-State }
        { Origin-Host }
        { Origin-Realm }
        [ Result-Code ]
        [ Example-Id ]
        [ Example-Report ]
        [ Example-Data ]
        [ Example-Kept ]
        *[ AVP ]


; Type: Interpreted Constraints
; AVP: Example-Report
; Command: Example-Answer
; Section: 6.1.2
; Versions: 19.0.0
"It is present if the request asks for it."
    present-if request/Example-Flags bit 0


; Type: Interpreted Constraints
; AVP: Example-Data
; Command: Example-Answer
; Section: 6.1.2
; Versions: 19.0.0
"It is absent if the request withholds it."
    absent-if request/Example-Flags bit 1


; Type: Interpreted Constraints
; AVP: Example-Kept
; Command: Example-Answer
; Section: 6.1.2
; Versions: 19.0.0
"It is sent only if the request carried an identity."
    requires request/Example-Id


; Type: Interpreted Constraints
; AVP: Example-Id
; Command: Example-Answer
; Section: 6.1.2
; Versions: 19.0.0
"It is the request's."
    equals request/Example-Id


; Type: AVP Table
; Section: 6.3.1
; Columns: Name     Code   Section   Type          Must
Example-Flags       1      6.3.2     Unsigned32    M,V
Example-Id          2      6.3.3     UTF8String    M,V
Example-Report      3      6.3.4     OctetString   M,V
Example-Data        4      6.3.5     OctetString   M,V
Example-Kept        5      6.3.6     OctetString   M,V
"""


@pytest.fixture(scope="module")
def asked(tmp_path_factory):
    """Vectors, rules and a plugin for `_ASKED` beside RFC 6733."""
    work = tmp_path_factory.mktemp("asked")
    shutil.copy(CORPUS_DIR / "rfc" / "rfc6733.dad", work / "rfc6733.dad")
    (work / "29999-j00.dad").write_text(_ASKED, "utf-8")
    options = ["--corpus", str(work), "--application", "16777999"]
    for command in (
        [
            "vectors",
            *options,
            "-o",
            str(work / "v.json"),
            "--pcap",
            str(work / "v.pcap"),
        ],
        ["wireshark-plugin", *options, "--rules-only", "-o", str(work / "rules.lua")],
        ["wireshark-plugin", *options, "-o", str(work / "plugin.lua")],
    ):
        done = CliRunner().invoke(main, command)
        assert done.exit_code == 0, done.output
    found = vectors.Vectors.model_validate_json((work / "v.json").read_text("utf-8"))
    return work, found


def test_an_answer_reading_its_request_is_sent_with_it(asked):
    _, found = asked
    paired = {v.id: v for v in found.vectors if v.request is not None}
    # Each rule reading the request: a valid pair and a pair breaking it.
    for kind, name in (
        ("present-if", "Example-Report"),
        ("absent-if", "Example-Data"),
        ("requires", "Example-Kept"),
        ("equals", "Example-Id"),
    ):
        valid = paired[f"16777999/EXA/maximal/request/{kind}/{name}/6.1.2"]
        broken = paired[f"16777999/EXA/negative/constraint-{kind}/{name}/6.1.2"]
        assert valid.expected == ()
        assert broken.expected == (
            vectors.Expected(rule=f"constraint-{kind}", severity="note"),
        )
    # A pair shares its identifiers, which no other vector's are.
    identifiers = [bytes.fromhex(v.octets)[12:20] for v in found.vectors]
    assert len(set(identifiers)) == len(identifiers)
    for vector in paired.values():
        assert vector.request is not None
        request = bytes.fromhex(vector.request.octets)
        assert (
            request[4] & 0x80 and request[12:20] == bytes.fromhex(vector.octets)[12:20]
        )


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_core_reads_an_answer_against_its_request(lua, asked):
    work, found = asked
    lines = work / "lines.txt"
    lines.write_text(
        "".join(
            f"{v.document}\t{v.octets}\t{v.request.octets if v.request else ''}\n"
            for v in found.vectors
        )
    )
    runner = work / "runner.lua"
    runner.write_text(_RUNNER, "utf-8")
    done = subprocess.run(
        [lua, str(runner), str(CORE), str(work / "rules.lua"), str(lines)],
        check=True,
        capture_output=True,
        text=True,
    )
    for vector, line in zip(found.vectors, done.stdout.splitlines(), strict=True):
        _, *reported = line.split("\t")
        assert sorted(reported) == sorted(
            f"{e.severity} {e.rule}" for e in vector.expected
        ), vector.id


def _shown(plugin: Path, capture: Path, *fields: str) -> list[list[str]]:
    shown = subprocess.run(
        [
            "tshark",
            "-n",
            "-r",
            str(capture),
            "-X",
            f"lua_script:{plugin}",
            "-T",
            "fields",
            *(arg for field in fields for arg in ("-e", field)),
            "-Y",
            "seanchai and diameter.flags.request == 0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Lua" not in shown.stderr, shown.stderr
    return [line.split("\t") for line in shown.stdout.splitlines()]


@pytest.mark.skipif(shutil.which("tshark") is None, reason="no tshark on PATH")
def test_the_plugin_pairs_an_answer_with_its_request_in_the_capture(asked, tmp_path):
    work, found = asked
    answers = [v for v in found.vectors if not v.is_request]
    rows = _shown(
        work / "plugin.lua",
        work / "v.pcap",
        "frame.number",
        "seanchai.request_frame",
        "seanchai.request_missing",
        "seanchai.rule",
    )
    assert len(rows) == len(answers)
    for vector, (frame, request, missing, rules) in zip(answers, rows, strict=True):
        assert sorted(filter(None, rules.split(","))) == sorted(
            e.rule for e in vector.expected
        ), vector.id
        if vector.request is not None:
            # The request is the frame before; each finding links it too.
            assert set(request.split(",")) == {str(int(frame) - 1)}
            assert missing == ""
    # Without the requests, the answers' rules on them go unchecked, said
    # once per answer, and no finding of them is reported.
    alone = vectors.Vectors.model_validate(
        {
            **found.model_dump(),
            "vectors": [
                {**v.model_dump(), "request": None} for v in answers if v.request
            ],
        }
    )
    capture = tmp_path / "alone.pcap"
    capture.write_bytes(vectors.pcap(alone))
    rows = _shown(
        work / "plugin.lua", capture, "seanchai.request_missing", "seanchai.rule"
    )
    assert rows and all(missing == "4" for missing, _ in rows)
    assert not any(rule.startswith("constraint-") for _, rule in rows)
