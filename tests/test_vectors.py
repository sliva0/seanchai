"""`seanchai vectors`: the messages it writes, and the Wireshark plugin's
core as their end-to-end test. Every valid vector draws no error, warning
or note of an interpreted rule from `core.lua`, and every negative one
exactly the finding it expects, under
each Lua on PATH; the generated plugin under tshark reads the capture alike.
"""

import dataclasses
import gc
import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner
from seanchai_corpus import CORPUS_DIR

from seanchai import dictionary, vectors, wireshark
from seanchai.cli import main
from seanchai.corpus import Corpus
from seanchai.model import Model
from seanchai.wireshark import _rules as generator

CORE = Path(wireshark.__file__).parent / "core.lua"
LUAS = [name for name in ("lua5.1", "lua5.2", "lua5.3", "lua5.4") if shutil.which(name)]
S6A = 16777251


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
    # One finding each, but a Result-Code holding one of TS 29.272's own
    # codes (clause 7.4.3), which no Result-Code table names either.
    assert all(
        v.breaks is not None
        and (
            len(v.expected) == 1
            or [e.rule for e in v.expected] == ["constraint-exclude", "result-code"]
        )
        for v in negative
    )
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


def test_a_negative_another_print_of_the_command_accepts_is_skipped(built):
    s6b = _vectors(built, 16777272)
    # TS 29.273 prints S6b's AA-Answer twice, a rule of each print being no
    # rule of the other: the plugin may hold the message to either.
    assert {(s.command, s.what) for s in s6b.skipped} >= {
        ("16777272/AAA", "constraint-absent-if/APN-Configuration/9.1.2.2.1"),
        ("16777272/AAA", "constraint-present-if/MIP-Session-Key/9.1.2.6.1"),
    }
    assert any(v.request is not None for v in s6b.vectors)


def test_a_command_requiring_what_the_corpus_cannot_complete_is_skipped(built):
    nta = _vectors(built, 16777358)
    assert {(s.command, s.what) for s in nta.skipped} >= {
        ("Nta/ECR", "minimal"),
        ("Nta/ECR", "maximal"),
    }


def test_a_rule_no_negative_breaks_alone_is_skipped_with_why(s6a):
    """TS 29.272 clause 7.3.35 holds SCEF-ID and SCEF-Realm to the same
    siblings, so no vector breaks one's rule and not the other's: it is
    listed, not dropped. A condition on a path into the subject places it
    once: a Subscription-Data's AMBR, excluded with both its bandwidths 0."""
    skipped = {(s.command, s.what): s.reason for s in s6a.skipped}
    assert skipped[("16777251/ULA", "constraint-requires/SCEF-ID/7.3.35")] == (
        "breaking it breaks another predicate too"
    )
    assert all(s.reason for s in s6a.skipped)
    negative = {v.id for v in s6a.vectors if v.kind == "negative"}
    assert "16777251/ULA/negative/constraint-excludes/AMBR/7.3.2" in negative


def test_a_rule_on_an_avp_only_the_wildcard_admits_builds_it(built):
    """TS 32.299's CCA leaves Supported-Features to its `* [ AVP ]`, and
    clause 6.5.10.3 wants one in an answer to an initial request with
    DIAMETER_ERROR_FEATURE_UNSUPPORTED, TS 32.299's first 3GPP code, which
    Ro's dictionary alone gives its Experimental-Result-Code: the AVP is
    built, read as TS 32.299 reads it, Feature-List-ID's M bit set as its
    table prints it."""
    ro = _vectors(built, 4)
    (cca,) = [v for v in ro.vectors if v.id == "Ro/CCA/maximal"]
    (features,) = [node for node in cca.tree if node.name == "Supported-Features"]
    flags = {node.name: node.flags for node in features.children}
    assert flags["Feature-List-ID"] == "VM"


def test_nothing_inside_a_failed_avp_is_broken(built):
    """RFC 6733 section 7.5 lets Failed-AVP hold the failed AVP as received,
    so a checker holds it to its `1* { AVP }` alone: a negative changes
    nothing inside it (TS 29.338's ALA, whose Failed-AVP holds a Vendor-Id:
    its one integer to shorten is the Vendor-Id of the
    Vendor-Specific-Application-Id an agent may add, clause 5.3.2.2)."""
    s6c = _vectors(built, 16777312)

    def inside(vector: vectors.Vector) -> set[tuple[str, str, str | None]]:
        return {
            (child.name, child.flags, child.data)
            for node in vector.tree
            if node.name == "Failed-AVP"
            for child in node.children
        }

    valid = set().union(*(inside(v) for v in s6c.vectors if v.kind != "negative"))
    assert valid
    assert all(inside(v) <= valid for v in s6c.vectors if v.kind == "negative")
    shortened = [
        v for v in s6c.vectors if v.id.startswith("16777312/ALA/negative/data")
    ]
    assert [v.id for v in shortened] == ["16777312/ALA/negative/data-length/Vendor-Id"]
    (vendor,) = [
        child
        for node in shortened[0].tree
        if node.name == "Vendor-Specific-Application-Id"
        for child in node.children
        if child.name == "Vendor-Id"
    ]
    assert vendor.data is not None and len(vendor.data) < 8


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


@dataclasses.dataclass(frozen=True)
class _Kept:
    """What the plugin's test reads of a vector."""

    id: str
    document: str
    expected: tuple[vectors.Expected, ...]


@dataclasses.dataclass(frozen=True)
class _Checked:
    """Every application's vectors, as lines the runner reads, and the
    plugin's rules: the whole corpus's, and each application's own."""

    kept: dict[int | None, list[_Kept]]
    rules: Path
    own_rules: dict[int | None, Path]
    lines: dict[int | None, Path]
    runner: Path


@pytest.fixture(scope="module")
def checked(built, tmp_path_factory) -> _Checked:
    """The vectors of every application the corpus holds, so of every
    document with interpreted rules, but an obsoleted document's, which the
    plugin holds to the newer one, and the plugin's rules for them, from the
    whole dictionary and from each application's; of each vector only what
    the test reads is kept."""
    books, model = built
    work = tmp_path_factory.mktemp("vectors")
    whole = dictionary.build(model, corpus_version=books.version)
    places = generator.Places(books)
    rules = work / "rules.lua"
    rules.write_text(generator.rules_chunk(whole, model, places), "utf-8")
    obsolete = {r for r in model.references() if model.obsoleted_by(r)}
    # Each interpreted document's applications are among them.
    assert {each.application_id for each in whole.applications} >= {
        16777217,  # TS 29.329's Sh
        16777250,  # TS 29.273's STa and SWd, SWa's commands with them
        16777251,  # TS 29.272's S6a/S6d
        16777252,  # S13
        16777264,  # SWm
        16777265,  # SWx
        16777272,  # S6b
        16777308,  # S7a/S7d
    }
    groups: dict[int | None, list[dictionary.Application]] = {}
    for each in whole.applications:
        groups.setdefault(each.application_id, []).append(each)
    pages = vectors.pages_of(books)
    checked = _Checked({}, rules, {}, {}, work / "runner.lua")
    checked.runner.write_text(_RUNNER, "utf-8")
    # One application id at a time, as `seanchai vectors --application`
    # builds them: from the dictionary of that application alone, whose
    # value tables, and so the values chosen, are its own (TS 32.299's CCA
    # reaches a rule on its Supported-Features only with TS 32.299's first
    # Experimental-Result-Code). The commands printing no id, which no
    # selection names, from the whole dictionary's. All at once hold over a
    # gigabyte.
    for key in sorted(groups, key=lambda key: (key is None, key or 0)):
        part = (
            whole.model_copy(update={"applications": groups[key]})
            if key is None
            else dictionary.build(
                model, application_ids=(key,), corpus_version=books.version
            )
        )
        own = work / f"rules-{key}.lua"
        own.write_text(generator.rules_chunk(part, model, places), "utf-8")
        checked.own_rules[key] = own
        kept = checked.kept[key] = []
        lines = checked.lines[key] = work / f"vectors-{key}.txt"
        with lines.open("w") as out:
            for v in vectors.build(part, pages).vectors:
                if v.document in obsolete:
                    continue
                request = v.request.octets if v.request else ""
                out.write(f"{v.document}\t{v.octets}\t{request}\n")
                kept.append(_Kept(v.id, v.document, v.expected))
        del part
        gc.collect()
    return checked


def _judged(
    lua: str, checked: _Checked, rules: Path, keys: Sequence[int | None]
) -> tuple[int, int, list[tuple[str, list[tuple[str, str]], list[str]]]]:
    """How many of the vectors of the applications `keys` the core read,
    how many it held to another document's definition, and those it reports
    otherwise than they expect."""
    lines = rules.parent / f"judged-{rules.stem}.txt"
    with lines.open("w") as out:
        for key in keys:
            out.write(checked.lines[key].read_text())
    done = subprocess.run(
        [lua, str(checked.runner), str(CORE), str(rules), str(lines)],
        check=True,
        capture_output=True,
        text=True,
    )
    kept = [vector for key in keys for vector in checked.kept[key]]
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
    return len(kept), held, wrong


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_plugin_reports_exactly_what_each_vector_expects(lua, checked):
    count, held, wrong = _judged(lua, checked, checked.rules, list(checked.kept))
    assert not wrong, wrong[:5]
    assert held < count / 50


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
def test_the_plugin_of_one_application_reports_what_its_vectors_expect(checked):
    """`seanchai wireshark-plugin --application`'s rules hold only what the
    application reaches: its vectors draw from them what they expect, as
    from the whole corpus's (Gx's Result-Code reads RFC 6733's codes, which
    TS 29.212's own table adds to)."""
    wrong = []
    for key, rules in checked.own_rules.items():
        wrong += _judged(LUAS[-1], checked, rules, [key])[2]
    assert not wrong, wrong[:5]


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
        [ Ex-Set ]
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
        [ Ex-Set ]
        [ Example-Note ]
        [ Ex-Pair ]
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
"It is sent only if the request carried an identity, and not with a report."
    requires request/Example-Id and not Example-Report


; Type: Interpreted Constraints
; AVP: Example-Id
; Command: Example-Answer
; Section: 6.1.2
; Versions: 19.0.0
"It is the request's."
    equals request/Example-Id


; Type: Interpreted Constraints
; AVP: Example-Never
; Command: Example-Answer
; Section: 6.1.2
; Versions: 19.0.0
"It is never sent, though * [ AVP ] admits it."
    absent


; Type: Interpreted Constraints
; AVP: Example-Note
; Command: Example-Answer
; Section: 6.1.2
; Versions: 19.0.0
"It is present if the request's group asks, and the answer's does not."
    present-if request/Ex-Set/Example-Flags bit 2 and not Ex-Set/Example-Flags bit 2


; Type: Grouped AVP
; Name: Ex-Set
; Section: 6.3.8
Ex-Set ::= < AVP header: 7 10415 >
        [ Example-Flags ]


; Type: Grouped AVP
; Name: Ex-Pair
; Section: 6.3.12
Ex-Pair ::= < AVP header: 11 10415 >
        [ Example-Mode ]
        [ Example-Count ]


; Type: Interpreted Constraints
; AVP: Example-Count
; Within: Ex-Pair
; Section: 6.3.12
; Versions: 19.0.0
"A count goes with a mode."
    requires Example-Mode


; Type: Interpreted Constraints
; AVP: Ex-Pair
; Section: 6.3.12
; Versions: 19.0.0
"It is not sent with mode 2."
    excludes Ex-Pair/Example-Mode = 2


; Type: AVP Table
; Section: 6.3.1
; Columns: Name     Code   Section   Type          Must
Example-Flags       1      6.3.2     Unsigned32    M,V
Example-Id          2      6.3.3     UTF8String    M,V
Example-Report      3      6.3.4     OctetString   M,V
Example-Data        4      6.3.5     OctetString   M,V
Example-Kept        5      6.3.6     OctetString   M,V
Example-Never       6      6.3.7     OctetString   M,V
Ex-Set       7      6.3.8     Grouped       M,V
Example-Note        8      6.3.9     OctetString   M,V
Example-Mode        9      6.3.10    Unsigned32    M,V
Example-Count       10     6.3.11    Unsigned32    M,V
Ex-Pair      11     6.3.12    Grouped       M,V
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
        ("present-if", "Example-Note"),
    ):
        valid = paired[f"16777999/EXA/maximal/request/{kind}/{name}/6.1.2"]
        broken = paired[f"16777999/EXA/negative/constraint-{kind}/{name}/6.1.2"]
        assert valid.expected == ()
        assert broken.expected == (
            vectors.Expected(rule=f"constraint-{kind}", severity="note"),
        )
    # A predicate of a grouped AVP's scope, broken in the answer's Ex-Pair.
    (count,) = [
        v for v in found.vectors if "/constraint-requires/Example-Count" in v.id
    ]
    assert count.id == "16777999/EXA/negative/constraint-requires/Example-Count/6.3.12"
    (pair,) = [node for node in count.tree if node.name == "Ex-Pair"]
    assert [node.name for node in pair.children] == ["Example-Count"]
    # An AVP only `* [ AVP ]` admits, which a rule keeps out.
    (never,) = [v for v in found.vectors if "/constraint-absent/" in v.id]
    assert never.id == "16777999/EXA/negative/constraint-absent/Example-Never/6.1.2"
    assert never.tree[-1].name == "Example-Never"
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
    # once per answer, and no finding of them is reported (Example-Count's
    # reads the answer's Ex-Pair alone): the five of the document's own and
    # RFC 6733's two on every answer's Session-Id (section 6.2).
    alone = vectors.Vectors.model_validate(
        {
            **found.model_dump(),
            "vectors": [
                {**v.model_dump(), "request": None}
                for v in answers
                if v.request and "/Example-Count/" not in v.id
            ],
        }
    )
    capture = tmp_path / "alone.pcap"
    capture.write_bytes(vectors.pcap(alone))
    rows = _shown(
        work / "plugin.lua", capture, "seanchai.request_missing", "seanchai.rule"
    )
    assert rows and all(missing == "7" for missing, _ in rows)
    reading = {"present-if", "absent-if", "requires", "equals"}
    assert not any(rule.removeprefix("constraint-") in reading for _, rule in rows)


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_core_checks_a_predicate_of_a_block_with_no_scope(lua, asked, tmp_path):
    work, found = asked
    # Ex-Pair's own rule, wherever read: its path starts at Ex-Pair itself.
    held = next(
        v
        for v in found.vectors
        if v.kind == "maximal" and not v.is_request and "Ex-Pair" in str(v.tree)
    )
    mode = "00000009c0000010000028af"  # Example-Mode, V and M, vendor 10415
    assert held.octets.count(mode + "00000000") == 1
    lines = tmp_path / "lines.txt"
    request = held.request.octets if held.request else ""
    lines.write_text(
        "".join(
            f"{held.document}\t{octets}\t{request}\n"
            for octets in (
                held.octets,
                held.octets.replace(mode + "00000000", mode + "00000002"),
            )
        )
    )
    runner = tmp_path / "runner.lua"
    runner.write_text(_RUNNER, "utf-8")
    done = subprocess.run(
        [lua, str(runner), str(CORE), str(work / "rules.lua"), str(lines)],
        check=True,
        capture_output=True,
        text=True,
    )
    valid, broken = done.stdout.splitlines()
    assert valid.split("\t")[1:] == []
    assert broken.split("\t")[1:] == ["note constraint-excludes"]


# A request whose required grouped AVP holds exactly one of two identities,
# a rule of the command on its members, as TS 29.336's CIR holds its
# User-Identifier's External-Identifier or MSISDN.
_ONE_OF = """\
; Specification: 3GPP TS 29.998
; Version: 19.0.0
; Vendor-ID: 10415
; Bases: RFC6733


; Type: Message
; Name: Choice-Request, CHR
; Section: 6.1.1
<Choice-Request> ::= < Diameter Header: 9, REQ, PXY, 16777998 >
        < Session-Id >
        { Auth-Session-State }
        { Origin-Host }
        { Origin-Realm }
        { Destination-Realm }
        { Ch-Id }
        *[ AVP ]


; Type: Grouped AVP
; Name: Ch-Id
; Section: 6.2.1
Ch-Id ::= < AVP header: 1 10415 >
        [ Ch-Name ]
        [ Ch-Number ]
        [ Ch-Other ]


; Type: Interpreted Constraints
; AVP: Ch-Id
; Command: Choice-Request
; Section: 6.1.1
; Versions: 19.0.0
"It holds a name or a number, not both."
    requires Ch-Id/Ch-Name or Ch-Id/Ch-Number
    excludes Ch-Id/Ch-Name and Ch-Id/Ch-Number


; Type: Interpreted Constraints
; AVP: Ch-Id
; Section: 6.2.1
; Versions: 19.0.0
"It is never empty."
    members at-least-one Ch-Other Ch-Name Ch-Number


; Type: AVP Table
; Section: 6.2
; Columns: Name   Code   Section   Type         Must
Ch-Id             1      6.2.1     Grouped      M,V
Ch-Name           2      6.2.2     UTF8String   M,V
Ch-Number         3      6.2.3     UTF8String   M,V
Ch-Other          4      6.2.4     UTF8String   M,V
"""


def test_a_required_grouped_avp_is_mended_for_its_commands_rules(tmp_path):
    shutil.copy(CORPUS_DIR / "rfc" / "rfc6733.dad", tmp_path / "rfc6733.dad")
    (tmp_path / "29998-j00.dad").write_text(_ONE_OF, "utf-8")
    out = tmp_path / "v.json"
    done = CliRunner().invoke(
        main,
        [
            "vectors",
            "--corpus",
            str(tmp_path),
            "--application",
            "16777998",
            "-o",
            str(out),
        ],
    )
    assert done.exit_code == 0, done.output
    found = vectors.Vectors.model_validate_json(out.read_text("utf-8"))
    built = {v.kind: v for v in found.vectors if v.kind != "negative"}

    def held(vector: vectors.Vector) -> set[str]:
        (identity,) = (node for node in vector.tree if node.name == "Ch-Id")
        return {child.name for child in identity.children}

    # The minimal message, its Ch-Other built for the members rule, gains
    # the member the command's rule asks for; the maximal one drops one of
    # the two it may not hold together.
    assert set(built) == {"minimal", "maximal"}
    assert len(held(built["minimal"]) & {"Ch-Name", "Ch-Number"}) == 1
    assert len(held(built["maximal"]) & {"Ch-Name", "Ch-Number"}) == 1
    # Emptying Ch-Id would break the command's rule too: no vector breaks
    # the members rule alone.
    ids = {v.id for v in found.vectors}
    assert "16777998/CHR/negative/constraint-members/Ch-Id/6.2.1" not in ids
    assert "16777998/CHR/negative/constraint-excludes/Ch-Id/6.1.1" in ids


# A request whose required grouped AVP holds a member of a given number, a
# rule of the command on its member, beside a rule within the grouped AVP
# keeping that member apart from its sibling, as TS 29.154's BTR holds Nt's
# Auth-Application-Id in its Vendor-Specific-Application-Id.
_NUMBERED = """\
; Specification: 3GPP TS 29.997
; Version: 19.0.0
; Vendor-ID: 10415
; Bases: RFC6733


; Type: Message
; Name: Number-Request, NUR
; Section: 6.1.1
<Number-Request> ::= < Diameter Header: 9, REQ, PXY, 16777997 >
        < Session-Id >
        { Auth-Session-State }
        { Origin-Host }
        { Origin-Realm }
        { Destination-Realm }
        { Nu-Id }
        *[ AVP ]


; Type: Grouped AVP
; Name: Nu-Id
; Section: 6.2.1
Nu-Id ::= < AVP header: 1 10415 >
        [ Nu-Auth ]
        [ Nu-Acct ]


; Type: Interpreted Constraints
; AVP: Nu-Id
; Command: Number-Request
; Section: 6.1.1
; Versions: 19.0.0
"It holds the application's number."
    requires Nu-Id/Nu-Auth = 16777997


; Type: Interpreted Constraints
; AVP: Nu-Auth
; Within: Nu-Id
; Section: 6.2.1
; Versions: 19.0.0
"It holds one of the two."
    excludes Nu-Acct


; Type: AVP Table
; Section: 6.2
; Columns: Name   Code   Section   Type         Must
Nu-Id             1      6.2.1     Grouped      M,V
Nu-Auth           2      6.2.2     Unsigned32   M,V
Nu-Acct           3      6.2.3     Unsigned32   M,V
"""


def test_a_required_grouped_avp_is_given_the_number_its_commands_rule_wants(
    tmp_path,
):
    shutil.copy(CORPUS_DIR / "rfc" / "rfc6733.dad", tmp_path / "rfc6733.dad")
    (tmp_path / "29997-j00.dad").write_text(_NUMBERED, "utf-8")
    out = tmp_path / "v.json"
    done = CliRunner().invoke(
        main,
        [
            "vectors",
            "--corpus",
            str(tmp_path),
            "--application",
            "16777997",
            "-o",
            str(out),
        ],
    )
    assert done.exit_code == 0, done.output
    found = vectors.Vectors.model_validate_json(out.read_text("utf-8"))
    built = {v.kind: v for v in found.vectors if v.kind != "negative"}

    def held(vector: vectors.Vector) -> dict[str, str | None]:
        (identity,) = (node for node in vector.tree if node.name == "Nu-Id")
        return {child.name: child.data for child in identity.children}

    # Both messages hold the number the command's rule wants; the maximal
    # one keeps it and drops the sibling the grouped AVP's rule forbids.
    assert set(built) == {"minimal", "maximal"}
    assert held(built["minimal"]) == {"Nu-Auth": "0100030d"}
    assert held(built["maximal"]) == {"Nu-Auth": "0100030d"}


def test_a_grouped_avps_rule_for_one_application_is_broken_there_alone(built):
    """TS 29.273 sets Feature-List-ID to 1 for each of its applications in a
    clause of its own, the 3GPP list's: SWm's vectors break clause
    7.2.3.2's rule, with the 3GPP Vendor-Id, and no other application's."""
    swm = _vectors(built, 16777264)
    broken = {
        v.id.rsplit("/", 1)[1]
        for v in swm.vectors
        if "/constraint-values/Feature-List-ID/" in v.id
    }
    assert broken == {"7.2.3.2"}
    for vector in swm.vectors:
        if vector.kind != "negative":
            for node in vector.tree:
                if node.name == "Supported-Features":
                    fields = {child.name: child.data for child in node.children}
                    assert fields["Vendor-Id"] == f"{10415:08x}"
                    assert fields["Feature-List-ID"] == f"{1:08x}"


def test_a_rule_on_each_instance_is_broken_beside_one_keeping_it(built):
    """TS 29.128 clause 5.2.2.0: every Monitoring-Event-Report of an RIR holds
    its SCEF-ID and Monitoring-Type, the rule's paths from the AVP reading
    the one checked. Its negative holds one that does beside one that does
    not, which a checker reading any one would pass."""
    (vector,) = [
        vector
        for vector in _vectors(built, 16777346).vectors
        if vector.id
        == "16777346/RIR/negative/constraint-requires/Monitoring-Event-Report/5.2.2.0"
    ]
    held = [
        {child.name for child in node.children}
        for node in vector.tree
        if node.name == "Monitoring-Event-Report"
    ]
    assert sorted("SCEF-ID" in each for each in held) == [False, True]


def test_a_condition_naming_an_integer_avps_value_is_its_tables_number(built):
    """TS 29.128 clause 5.7.1: a CMR establishing a connection, its
    Connection-Action CONNECTION_ESTABLISHMENT, an Unsigned32 clause 6.4.18
    names the values of, carries its Service-Selection. The name is the
    values table's 0, so the negative holds that and no Service-Selection,
    and clause 5.2.2.7's PDN_CONNECTIVITY_STATUS is TS 29.336's 10."""
    t6a = _vectors(built, 16777346)
    (vector,) = [
        vector
        for vector in t6a.vectors
        if vector.id
        == "16777346/CMR/negative/constraint-present-if/Service-Selection/5.7.1"
    ]
    fields = {node.name: node.data for node in vector.tree}
    assert fields["Connection-Action"] == f"{0:08x}"
    assert "Service-Selection" not in fields
    (report,) = [
        vector
        for vector in t6a.vectors
        if vector.id
        == "16777346/RIR/negative/constraint-excludes/Monitoring-Event-Report/5.2.2.7"
    ]
    types = [
        child.data
        for node in report.tree
        if node.name == "Monitoring-Event-Report"
        and not any(c.name == "PDN-Connectivity-Status-Report" for c in node.children)
        for child in node.children
        if child.name == "Monitoring-Type"
    ]
    assert types == [f"{10:08x}"]


def test_a_values_rule_on_a_result_code_is_broken_by_a_numbered_code(built):
    """TS 29.128 clause 5.6.3: a TDA with TDA-Flags' Acknowledged Delivery
    bit answers DIAMETER_SUCCESS. Its negative holds another code a document
    numbers, so that the plugin warns of no unnamed one beside."""
    (vector,) = [
        vector
        for vector in _vectors(built, 16777346).vectors
        if vector.id == "16777346/TDA/negative/constraint-values/Result-Code/5.6.3"
    ]
    (code,) = [node.data for node in vector.tree if node.name == "Result-Code"]
    assert code is not None and int(code, 16) not in (0, 2001)
    assert [e.rule for e in vector.expected] == ["constraint-values"]


def test_the_base_protocols_rules_on_every_answer_hold_in_each(built):
    """RFC 6733 section 6.2's echo of the request's Session-Id and Proxy-Info
    holds in every answer: S6a's valid answers carry the request's, and
    their negatives are the base protocol's own commands', not S6a's."""
    s6a = _vectors(built, 16777251)
    (ula,) = [v for v in s6a.vectors if v.id == "16777251/ULA/maximal"]
    assert ula.request is not None
    asked = [n for n in ula.request.tree if n.name == "Proxy-Info"]
    assert asked
    assert [n for n in ula.tree if n.name == "Proxy-Info"] == asked
    session = [n.data for n in ula.tree if n.name == "Session-Id"]
    assert session == [n.data for n in ula.request.tree if n.name == "Session-Id"]
    assert not [v.id for v in s6a.vectors if v.id.endswith(("/6.2", "/6.5", "/6.6"))]
    base = _vectors(built, 0)
    assert any(
        v.id.endswith("/constraint-absent/Destination-Host/6.5") for v in base.vectors
    )


def test_a_feature_named_in_a_condition_is_its_lists_bit(built):
    """TS 29.329 clause 7.1: a Sh feature list 1 naming Update-Eff-Enhance
    names Update-Eff, each by its name in table 7.1.1. The negative sets
    bit 2 and leaves bit 1 clear, the two conditions on one Feature-List
    each kept."""
    (vector,) = [
        vector
        for vector in _vectors(built, 16777217).vectors
        if vector.id == "16777217/UDR/negative/constraint-excludes/Feature-List/7.1"
    ]
    lists = [
        {child.name: child.data or "" for child in node.children}
        for node in vector.tree
        if node.name == "Supported-Features"
    ]
    broken = [
        fields
        for fields in lists
        if int(fields["Feature-List"], 16) & 0b110 == 0b100
        and fields["Feature-List-ID"] == f"{1:08x}"
    ]
    assert len(broken) == 1


def test_a_members_value_rule_is_broken_at_its_own_place(built):
    """TS 29.273 clause 5.2.3.26 holds PDN-Type in TWAN-Connectivity-Parameters
    to IPv4, IPv6 or IPv4v6: STa's answer breaks that PDN-Type, not the
    APN-Configuration's of the same reading and value before it."""
    (vector,) = [
        vector
        for vector in _vectors(built, 16777250).vectors
        if vector.id == "16777250/DEA/negative/constraint-range/PDN-Type/5.2.3.26"
        and vector.section == "5.2.2.1.2"
    ]
    held = {
        node.name: {child.name: child.data for child in node.children}
        for node in vector.tree
        if node.name in ("TWAN-Connectivity-Parameters", "APN-Configuration")
    }
    assert held["TWAN-Connectivity-Parameters"]["PDN-Type"] == f"{3:08x}"
    assert held["APN-Configuration"]["PDN-Type"] != f"{3:08x}"


def test_a_copy_beside_a_broken_instance_keeps_a_unique_member_apart(built):
    """TS 29.273 clause 8.2.3.1 keeps a non-IP APN-Configuration out of
    Non-3GPP-User-Data, a rule on each instance; a valid copy beside the
    broken one would repeat its Context-Identifier, which TS 29.272 keeps
    apart in APN-Configurations beside each other, so none is added."""
    broken = [
        vector
        for vector in _vectors(built, 16777265).vectors
        if "/constraint-excludes/APN-Configuration/8.2.3.1" in vector.id
    ]
    assert broken
    for vector in broken:
        for node in vector.tree:
            if node.name != "Non-3GPP-User-Data":
                continue
            contexts = [
                grand.data
                for child in node.children
                if child.name == "APN-Configuration"
                for grand in child.children
                if grand.name == "Context-Identifier"
            ]
            assert len(contexts) == len(set(contexts))
