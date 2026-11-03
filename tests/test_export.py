"""`seanchai export` over the committed corpus, run as a site's build runs it:
a command in a directory holding nothing of the repository, reading the
corrections from the installed corpus's record."""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import _CORPUS_DIR

from seanchai import export_schema
from seanchai.cli import main
from seanchai.corpus import Corpus, CorpusError
from seanchai.downloader.catalog import load_catalog
from seanchai.export import SYNTAX_FILE, export_corpus
from seanchai.model import Model, ModelError

ROOT = Path(__file__).resolve().parent.parent
_ETSI = _CORPUS_DIR / "etsi"
_PIN = ROOT / "tests" / "export.sha256"


def _export(output: Path, cwd: Path, seed: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from seanchai.cli import main; main()",
            "export",
            "-o",
            str(output),
        ],
        cwd=cwd,
        env={**os.environ, "PYTHONHASHSEED": seed},
        check=True,
        capture_output=True,
    )


@dataclass(frozen=True)
class Exported:
    path: Path
    books: Corpus
    index: dict
    search: dict
    docs: dict[str, dict]
    raws: dict[str, dict]


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> Exported:
    cwd = tmp_path_factory.mktemp("elsewhere")
    path = tmp_path_factory.mktemp("export") / "out"
    _export(path, cwd, "1")
    files = {
        file.name.removesuffix(".json"): json.loads(file.read_text("utf-8"))
        for file in (path / "documents").glob("*.json")
    }
    return Exported(
        path,
        Corpus.installed(),
        json.loads((path / "index.json").read_text("utf-8")),
        json.loads((path / "search.json").read_text("utf-8")),
        {key: value for key, value in files.items() if not key.endswith(".raw")},
        {
            key.removesuffix(".raw"): value
            for key, value in files.items()
            if key.endswith(".raw")
        },
    )


def _tree(path: Path) -> dict[str, bytes]:
    return {
        file.relative_to(path).as_posix(): file.read_bytes()
        for file in path.rglob("*")
        if file.is_file()
    }


def _text(lines) -> str:
    return "".join(t["text"] for line in lines for t in line["tokens"])


def test_export_preserves_every_corrected_and_raw_byte(exported):
    for entry in exported.books:
        identifier = entry.path.stem
        assert _text(exported.docs[identifier]["lines"]) == entry.path.read_text(
            "utf-8"
        )
        raw = (
            _CORPUS_DIR
            / "raw"
            / entry.path.relative_to(_CORPUS_DIR).with_suffix(".raw.dad")
        )
        assert _text(exported.raws[identifier]["lines"]) == raw.read_text("utf-8")


def test_export_has_no_broken_links_or_duplicate_anchors(exported):
    anchors = {}
    for key, doc in exported.docs.items():
        values = [line["anchor"] for line in doc["lines"] if line.get("anchor")]
        assert len(values) == len(set(values))
        anchors[key] = set(values)
    targets = [e["target"] for e in exported.search["entries"] if e["target"]]
    for key, doc in exported.docs.items():
        for lines in (doc["lines"], exported.raws[key]["lines"]):
            for line in lines:
                for token in line["tokens"]:
                    if "target" in token:
                        targets.append(token["target"])
                    if "correction" in token:
                        assert token["correction"] in doc["corrections"]
    assert targets
    for target in targets:
        assert target["document"] in exported.docs
        if target.get("section"):
            assert target["section"] in anchors[target["document"]]


def test_the_default_export_reads_the_record_and_no_module(exported):
    """The fixture ran from a directory with no `edits/`, as an installed
    package does: every correction token still has a reason."""
    cited = {
        t["correction"]
        for doc in exported.docs.values()
        for line in doc["lines"]
        for t in line["tokens"]
        if "correction" in t
    }
    assert len(cited) > 500
    corrections = {
        cited: item
        for doc in exported.docs.values()
        for cited, item in doc["corrections"].items()
    }
    assert cited <= corrections.keys()
    assert all(item["reason"] for item in corrections.values())
    assert {item["kind"] for item in corrections.values()} == {
        "correction",
        "delete",
        "insert",
        "supply",
        "accept",
    }
    accepted = [
        finding
        for doc in exported.docs.values()
        for finding in doc["findings"]
        if finding["severity"] == "accepted"
    ]
    assert accepted
    assert all(
        corrections[finding["accepted_by"]]["kind"] == "accept" for finding in accepted
    )
    assert not any(
        finding["rule"] == "stale-acceptance"
        for doc in exported.docs.values()
        for finding in doc["findings"]
    )


def test_corrections_directory_overrides_the_record_and_agrees_with_it(tmp_path):
    books = Corpus.load([_ETSI])
    default = tmp_path / "default"
    named = tmp_path / "named"
    export_corpus(books, default)
    export_corpus(books, named, corrections_directory=ROOT / "edits" / "corrections")
    assert _tree(default) == _tree(named)

    modules = tmp_path / "modules"
    modules.mkdir()
    with pytest.raises(CorpusError, match="corrections record does not hold"):
        export_corpus(books, tmp_path / "other", corrections_directory=modules)


def test_a_corpus_with_no_record_exports_without_reasons(tmp_path):
    corpus = tmp_path / "dad"
    corpus.mkdir()
    source = _CORPUS_DIR / "rfc" / "rfc4004.dad"
    (corpus / source.name).write_bytes(source.read_bytes())
    output = tmp_path / "out"
    export_corpus(Corpus.load([corpus]), output)
    doc = json.loads((output / "documents/rfc4004.json").read_text("utf-8"))
    assert doc["corrections"] == {}
    assert doc["raw"] is None
    assert not (output / "documents/rfc4004.raw.json").exists()
    assert any("correction" in t for line in doc["lines"] for t in line["tokens"])


def test_a_stale_record_is_refused(tmp_path):
    corpus = tmp_path / "dad"
    (corpus / "rfc").mkdir(parents=True)
    source = _CORPUS_DIR / "rfc" / "rfc4004.dad"
    (corpus / "rfc" / source.name).write_bytes(source.read_bytes())
    (corpus / "corrections.json").write_text('{"documents": {}}', "utf-8")
    with pytest.raises(CorpusError, match="seanchai regenerate"):
        export_corpus(Corpus.load([corpus]), tmp_path / "out")


def test_export_prefers_definition_page_to_earlier_table_row(exported):
    entry = next(e for e in exported.books if e.path.stem == "29272-i70")
    section = next(
        s for s in entry.spec.sections if getattr(s, "name", None) == "Area-Scope"
    )
    doc = exported.docs[entry.path.stem]
    actual = next(s for s in doc["sections"] if s["section"] == section.source.section)
    assert actual["page"] == section.source.page
    line = next(
        line for line in doc["lines"] if line.get("anchor") == section.source.section
    )
    assert "Type:" in _text([line])


def test_export_carries_specific_release_resolution_and_diagnostics(exported):
    entry = next(
        e
        for e in exported.search["entries"]
        if e["document"] == "ts-0004-v2_35_0" and e["name"] == "Service-Information"
    )
    assert entry["target"]["document"] == "32299-bk0"
    assert entry["across_releases"]["version"] == "11.20.0"
    assert any(doc["holes"] for doc in exported.docs.values())
    assert "TS29.272.py#area-scope-code" in exported.docs["29272-i70"]["corrections"]
    assert all(d["source"]["local"] is None for d in exported.docs.values())
    assert all(
        e["target"] and e["target"]["section"]
        for e in exported.search["entries"]
        if e["kind"] == "avp" and e["identity"]
    )


def test_table_names_keep_row_locations_and_definition_targets(exported):
    for lines in (
        exported.docs["29329-i00"]["lines"],
        exported.raws["29329-i00"]["lines"],
    ):
        line = next(
            line
            for line in lines
            if any(
                t.get("source", {}).get("row") and t["text"] == "Supported-Features"
                for t in line["tokens"]
            )
        )
        name = next(t for t in line["tokens"] if t["text"] == "Supported-Features")
        assert name["source"] == {
            "section": "6.3",
            "page": 17,
            "name": "Supported-Features",
            "row": True,
        }
        assert name["target"] == {"document": "29229-i10", "section": "6.3.29"}
        section = next(t for t in line["tokens"] if t["text"] == "6.3.11")
        assert section["source"] == {"section": "6.3.11", "page": 17}


@pytest.mark.parametrize(
    ("document", "name", "target"),
    [
        (
            "29329-i00",
            "Session-Priority",
            {"document": "29229-i10", "section": "6.3.56"},
        ),
        (
            "29329-i00",
            "Wildcarded-IMPU",
            {"document": "29229-i10", "section": "6.3.43"},
        ),
        ("rfc8583", "SourceID", {"document": "rfc8581", "section": "7.3"}),
        (
            "29283-i00",
            "Sequence-Number",
            {"document": "29283-i00", "section": "7.3.21"},
        ),
    ],
)
def test_definition_citations_export_the_origin_target(
    exported, document, name, target
):
    entry = next(
        e
        for e in exported.search["entries"]
        if e["document"] == document and e["name"] == name
    )
    assert entry["target"] == target
    for lines in (exported.docs[document]["lines"], exported.raws[document]["lines"]):
        tokens = [t for line in lines for t in line["tokens"] if t["text"] == name]
        assert tokens
        assert all(t["target"] == target for t in tokens)


def test_version_specific_model_queries_read_the_selected_copy(exported):
    model = Model.build(exported.books)
    old = model.resolve("TS32.299", "Service-Information", version="11.20.0")
    assert old is not None
    assert old.across_releases is None
    # V11.20.0 lists this AVP in its own tables, V18.0.0 re-uses RFC 6733's.
    old_type = model.resolve("TS32.299", "Accounting-Record-Type", version="11.20.0")
    new_type = model.resolve("TS32.299", "Accounting-Record-Type")
    assert old_type is not None and old_type.section is None
    assert new_type is not None and new_type.section == "9.8.1"
    with pytest.raises(ModelError, match=r"V99\.0\.0"):
        model.resolve("TS32.299", "Service-Information", version="99.0.0")
    assert model.applications("TS32.299", version="11.20.0")
    assert model.messages("TS32.299", version="11.20.0")


def test_from_cells_target_the_named_avp_and_raw_changes_are_marked(exported):
    document = next(
        d
        for d in exported.docs.values()
        if d["reference"] == "TS29.214" and d["version"] == "18.4.0"
    )
    line = next(
        line
        for line in document["lines"]
        if any(t["text"] == "3GPP-MS-TimeZone" for t in line["tokens"])
        and any(t["text"] == "TS29.061" for t in line["tokens"])
    )
    reference = next(t for t in line["tokens"] if t["text"] == "TS29.061")
    assert reference["target"]["name"] == "3GPP-MS-TimeZone"
    assert reference["target"]["section"]
    assert exported.docs[reference["target"]["document"]]["reference"] == "TS29.061"
    raw = exported.raws["29229-i10"]["lines"]
    renamed = [
        line
        for line in raw
        if any(t.get("avp") == "Digest-QoP" for t in line["tokens"])
    ]
    assert renamed and all(line.get("warning") for line in renamed)
    session = [
        line
        for line in raw
        if line.get("section") == "6.1.10"
        and any(t.get("avp") == "Session-Id" for t in line["tokens"])
    ]
    assert len(session) == 2
    assert sum(bool(line.get("warning")) for line in session) == 1
    assert any(
        "Callee-Information" in mention["avps"]
        for mention in exported.search["mentions"]
    )


def test_raw_spelling_links_through_its_declared_name_correction(exported):
    raw = exported.raws["29229-i10"]["lines"]
    tokens = [t for line in raw for t in line["tokens"] if t["text"] == "Digest-QoP"]
    assert len(tokens) == 3
    assert all(t["target"] == {"document": "rfc4590", "section": "3.8"} for t in tokens)


def test_tokens_carry_no_highlighting_classes_and_mark_comments(exported):
    allowed = {"text", "kind", "target", "source", "avp", "correction"}
    kinds = set()
    for doc in exported.docs.values():
        for line in doc["lines"]:
            assert set(line) <= {"tokens", "anchor", "section", "warning"}
            for token in line["tokens"]:
                assert set(token) <= allowed
                if "kind" in token:
                    kinds.add(token["kind"])
                    assert token["text"].startswith(";;")
                    assert (token["kind"] == "correction-note") == (
                        "correction" in token
                    )
    assert kinds == {"comment", "correction-note"}


def test_plain_text_merges_into_one_token(exported):
    """Without classes a span earns a token only by saying something."""
    for doc in exported.docs.values():
        for line in doc["lines"]:
            for first, second in zip(line["tokens"], line["tokens"][1:], strict=False):
                assert set(first) != {"text"} or set(second) != {"text"}


def test_repeated_command_names_link_to_their_own_interface(exported):
    """TS 29.212 prints CC-Request once per interface, with one spelling."""
    sections = {"5.6.2", "5a.6.2", "5b.6.4", "E.6.6.2"}
    for lines in (
        exported.docs["29212-i20"]["lines"],
        exported.raws["29212-i20"]["lines"],
    ):
        found: dict[str, list[dict]] = {}
        for line in lines:
            for token in line["tokens"]:
                if token["text"] == "CC-Request":
                    found.setdefault(line["section"], []).append(token["target"])
        assert sections <= found.keys()
        for section, targets in found.items():
            assert targets
            assert all(
                target == {"document": "29212-i20", "section": section}
                for target in targets
            )


def test_repeated_names_in_a_synthetic_file_keep_their_clauses(tmp_path):
    corpus = tmp_path / "dad"
    corpus.mkdir()
    body = """; Type: Message
; Section: {section}
; Name: Example-Request, EXR
<Example-Request> ::= < Diameter Header: 321, REQ, PXY, {application} >
  < Session-Id >
"""
    (corpus / "rfc9999.dad").write_text(
        "; Specification: RFC 9999\n; Vendor-ID: 0\n\n"
        + body.format(section="5.1", application=7)
        + "\n"
        + body.format(section="6.1", application=8),
        "utf-8",
    )
    output = tmp_path / "out"
    export_corpus(Corpus.load([corpus]), output)
    doc = json.loads((output / "documents/rfc9999.json").read_text("utf-8"))
    targets = {
        (line["section"], token["target"]["section"])
        for line in doc["lines"]
        for token in line["tokens"]
        if token["text"] == "Example-Request"
    }
    assert targets == {("5.1", "5.1"), ("6.1", "6.1")}


def test_commands_carry_the_application_their_scope_states(exported):
    entries = {
        e["target"]["section"]: e
        for e in exported.search["entries"]
        if e["document"] == "29212-i20"
        and e["kind"] == "command"
        and e["name"] == "CC-Request"
    }
    gx = entries["5.6.2"]
    assert gx["identity"] == {
        "kind": "command",
        "command_code": 272,
        "application_id": 16777238,
        "header_application_id": None,
        "application": "Gx",
    }
    assert gx["abbreviation"] == "CCR"
    assert gx["wireshark_name"] is None
    assert entries["E.6.6.2"]["identity"]["application_id"] == 16777318
    assert entries["E.6.6.2"]["identity"]["application"] == "S15"


def test_a_header_printing_an_id_keeps_it_on_both_fields(exported):
    identities = [
        e["identity"]
        for e in exported.search["entries"]
        if e["kind"] == "command" and e["identity"]["header_application_id"] is not None
    ]
    assert identities
    assert all(i["application_id"] == i["header_application_id"] for i in identities)


def test_one_clause_printing_a_command_per_application_keeps_both(exported):
    """TS 29.272 clause 7.2.9 prints Insert-Subscriber-Data-Request twice."""
    identities = [
        e["identity"]
        for e in exported.search["entries"]
        if e["document"] == "29272-i70"
        and e["name"] == "Insert-Subscriber-Data-Request"
        and e["target"]["section"] == "7.2.9"
    ]
    assert sorted(i["application_id"] for i in identities) == [16777251, 16777308]
    assert all(i["application_id"] == i["header_application_id"] for i in identities)


def test_search_entries_name_their_identity_by_kind(exported):
    fields = {
        "avp": {"kind", "vendor_id", "code"},
        "command": {
            "kind",
            "command_code",
            "application_id",
            "header_application_id",
            "application",
        },
        "application": {"kind", "application_id"},
        "registry": {"kind", "registry", "code"},
    }
    seen = set()
    for entry in exported.search["entries"]:
        seen.add(entry["kind"])
        assert isinstance(entry["defined_in"], list)
        if entry["identity"] is not None:
            assert entry["identity"]["kind"] == entry["kind"]
            assert set(entry["identity"]) == fields[entry["kind"]]
    assert seen == set(fields)
    registry = next(
        e
        for e in exported.search["entries"]
        if e["kind"] == "registry" and len(e["defined_in"]) > 1
    )
    assert all(", " not in cited for cited in registry["defined_in"])


def test_every_document_has_its_catalog_title(exported):
    documents = exported.index["documents"]
    assert not [d["id"] for d in documents if d["title"] == d["specification"]]
    titles = {doc["id"]: doc["title"] for doc in documents}
    assert titles["29209-680"] == "Policy control over Gq interface"
    assert titles["29210-670"] == "Charging rule provisioning over Gx interface"
    assert titles["29211-640"] == "Rx Interface and Rx/Gx signalling flows"
    assert titles["29140-700"].endswith("Stage 3")
    assert titles["29234-b20"].endswith("Stage 3")
    assert titles["xs0057-0_v2.0"].startswith("E-UTRAN - eHRPD")
    assert "e4 interface" in titles["es283034-020200"]
    assert "Service Policy Decision Function" in titles["ts183017-030201"]


def test_the_source_says_what_kind_it_is(exported):
    kinds = {d["id"]: d["source"]["kind"] for d in exported.index["documents"]}
    assert kinds["29212-i20"] == "etsi-pdf"
    assert kinds["es283034-020200"] == "etsi-pdf"
    assert kinds["rfc6733"] == "rfc-text"
    assert kinds["xs0057-0_v2.0"] == "other"
    assert kinds["ts-0004-v2_35_0"] == "other"


def test_the_files_are_split_as_their_pages_need_them(exported):
    assert exported.index["generator"] == "seanchai"
    assert set(exported.index) == {
        "schema_version",
        "generator",
        "seanchai_version",
        "corpus_version",
        "mode",
        "documents",
    }
    assert set(exported.search) == {"schema_version", "entries", "mentions"}
    assert set(exported.docs) == {d["id"] for d in exported.index["documents"]}
    assert set(exported.raws) == set(exported.docs)
    for summary in exported.index["documents"]:
        assert (exported.path / summary["path"]).is_file()
        assert (exported.path / summary["raw"]).is_file()
        assert "lines" not in summary
    assert all("raw" not in line for d in exported.docs.values() for line in d["lines"])
    size = (exported.path / "index.json").stat().st_size
    assert size < 100_000


def test_every_file_is_compact_sorted_and_says_its_schema_version(exported):
    for name, data in _tree(exported.path).items():
        if name == SYNTAX_FILE:  # The editors' grammar, as it stands.
            continue
        text = data.decode("utf-8")
        value = json.loads(text)
        compact = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        assert text == compact + "\n", name
        if name != "schema.json":
            assert value["schema_version"] == export_schema.SCHEMA_VERSION


def test_the_export_carries_the_grammar_the_editors_use(exported):
    source = ROOT / "src" / "seanchai" / "dad" / "syntax" / "dad.tmLanguage.json"

    assert SYNTAX_FILE == "syntax/dad.tmLanguage.json"
    assert (exported.path / SYNTAX_FILE).read_bytes() == source.read_bytes()
    assert json.loads(source.read_bytes())["scopeName"] == "source.dad"


def test_the_editors_copy_of_the_grammar_is_the_package_data():
    """`src/seanchai/dad/syntax/` is the source (editors/README.md): copy it."""
    source = ROOT / "src" / "seanchai" / "dad" / "syntax" / "dad.tmLanguage.json"
    copy = ROOT / "editors" / "vscode" / "syntaxes" / "dad.tmLanguage.json"

    assert copy.read_bytes() == source.read_bytes()


def test_each_section_says_what_the_file_places_there(exported):
    def titled(document: str, clause: str) -> str:
        sections = exported.docs[document]["sections"]
        (found,) = (each for each in sections if each["section"] == clause)
        return found["title"]

    assert titled("29229-i10", "6.1.1") == "Message User-Authorization-Request"
    assert titled("29229-i10", "6.3.0") == "AVP Table, Reused AVPs"
    assert titled("29229-i10", "6.3.4") == "Grouped AVP Server-Capabilities"
    # One kind named once: four registries, and one message printed twice.
    assert titled("29230-i60", "5.1") == "Registry"
    assert titled("29272-i70", "7.2.9") == "Message Insert-Subscriber-Data-Request"
    for doc in exported.docs.values():
        assert all(each["title"] for each in doc["sections"]), doc["id"]


def test_a_clause_only_table_rows_name_takes_its_first_rows_name(exported):
    def titled(document: str, clause: str) -> str:
        sections = exported.docs[document]["sections"]
        (found,) = (each for each in sections if each["section"] == clause)
        return found["title"]

    assert titled("29229-i10", "6.3.75") == "AVP PCSCF-FQDN"
    assert titled("29061-i10", "16.4.7") == "AVP 3GPP-IMSI and 37 more"


def test_sections_run_in_document_order(exported):
    from seanchai.dad.ast import section_sort_key

    for doc in exported.docs.values():
        clauses = [each["section"] for each in doc["sections"]]
        assert clauses == sorted(clauses, key=section_sort_key), doc["id"]
        assert len(clauses) == len(set(clauses)), doc["id"]


def test_section_order_is_natural():
    from seanchai.dad.ast import section_sort_key

    clauses = ["E.6.3.6", "6.3.10", "6.3.7A", "6.3.4", "6.3.7", "A.1", "5a", "5.1"]

    assert sorted(clauses, key=section_sort_key) == [
        "5.1",
        "5a",
        "6.3.4",
        "6.3.7",
        "6.3.7A",
        "6.3.10",
        "A.1",
        "E.6.3.6",
    ]


def test_every_file_validates_against_its_model(exported):
    def read(name):
        return (exported.path / name).read_bytes()

    export_schema.Index.model_validate_json(read("index.json"))
    export_schema.Search.model_validate_json(read("search.json"))
    for key in exported.docs:
        model = export_schema.Document.model_validate_json(
            read(f"documents/{key}.json")
        )
        assert export_schema.dumps(model).encode() == read(f"documents/{key}.json")
        export_schema.RawDocument.model_validate_json(read(f"documents/{key}.raw.json"))


def test_the_schema_file_describes_the_four_roots(exported):
    schema = json.loads((exported.path / "schema.json").read_text("utf-8"))
    assert schema == export_schema.json_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert {"$ref": "#/$defs/Document"} in schema["oneOf"]
    definitions = schema["$defs"]
    for root in ("Index", "Search", "Document", "RawDocument"):
        assert "schema_version" in definitions[root]["required"]
        version = definitions[root]["properties"]["schema_version"]
        assert version["minimum"] == version["maximum"]
        assert version["minimum"] == export_schema.SCHEMA_VERSION
    assert "class" not in definitions["Token"]["properties"]
    assert definitions["Token"]["required"] == ["text"]
    assert "discriminator" not in json.dumps(schema)
    assert definitions["Source"]["properties"]["kind"]["enum"] == [
        "etsi-pdf",
        "rfc-text",
        "other",
    ]

    def references(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref":
                    yield value
                else:
                    yield from references(value)
        elif isinstance(node, list):
            for value in node:
                yield from references(value)

    for reference in references(schema):
        assert reference.removeprefix("#/$defs/") in definitions


def test_the_index_names_its_versions_and_no_time(exported):
    import seanchai_corpus

    assert exported.index["corpus_version"] == seanchai_corpus.__version__
    assert exported.index["seanchai_version"]
    assert "2026-" not in (exported.path / "schema.json").read_text("utf-8")


def test_a_corpus_read_from_elsewhere_has_no_corpus_version(tmp_path):
    corpus = tmp_path / "dad"
    corpus.mkdir()
    source = _CORPUS_DIR / "rfc" / "rfc4004.dad"
    (corpus / source.name).write_bytes(source.read_bytes())
    index = export_corpus(Corpus.load([corpus]), tmp_path / "out")
    assert index.corpus_version is None


def test_an_export_holds_no_path_of_this_machine(exported):
    for name, data in _tree(exported.path).items():
        assert str(ROOT).encode() not in data, name


def test_export_is_byte_stable_under_any_hash_seed(exported, tmp_path):
    again = tmp_path / "again"
    _export(again, tmp_path, "2")
    first, second = _tree(exported.path), _tree(again)
    assert first.keys() == second.keys()
    assert [name for name in first if first[name] != second[name]] == []


def _pinned_bytes(name: str, data: bytes) -> bytes:
    """A file as the pin reads it. A release changes the versions and nothing
    else, so they are left out, and the pin need not move with one."""
    if name != "index.json":
        return data
    index = export_schema.Index.model_validate_json(data)
    return export_schema.dumps(
        index.model_copy(update={"seanchai_version": None, "corpus_version": None})
    ).encode()


def test_the_export_is_what_the_pin_says(exported, request):
    """Regenerate with `uv run pytest --update-export-pin` (docs/development.md)."""
    actual = {
        name: hashlib.sha256(_pinned_bytes(name, data)).hexdigest()
        for name, data in _tree(exported.path).items()
    }
    if request.config.getoption("--update-export-pin"):
        _PIN.write_text(
            "".join(f"{actual[name]}  {name}\n" for name in sorted(actual)), "utf-8"
        )
    pinned = {
        name: digest
        for digest, name in (
            line.split("  ", 1) for line in _PIN.read_text("utf-8").splitlines()
        )
    }
    changed = sorted(
        name for name in actual.keys() & pinned if actual[name] != pinned[name]
    )
    added = sorted(actual.keys() - pinned.keys())
    removed = sorted(pinned.keys() - actual.keys())
    assert not (changed or added or removed), (
        f"changed: {changed}\nnew: {added}\ngone: {removed}\n"
        "review the export, then run `uv run pytest --update-export-pin`"
    )


def test_the_pin_is_sorted_with_one_file_per_line():
    lines = _PIN.read_text("utf-8").splitlines()
    names = [line.split("  ", 1)[1] for line in lines]
    assert names == sorted(names)
    assert "index.json" in names
    assert "documents/29212-i20.raw.json" in names


def test_local_export_copies_matching_pdfs_and_rejects_missing_ones(tmp_path):
    books = Corpus.load([_ETSI])
    sources = tmp_path / "sources"
    sources.mkdir()
    with pytest.raises(CorpusError, match="no downloaded PDF"):
        export_corpus(
            books, tmp_path / "missing", include_pdfs=True, specifications=sources
        )
    for entry in books:
        (sources / str(entry.spec.link).rsplit("/", 1)[-1]).write_bytes(b"%PDF-test")
    output = tmp_path / "local"
    index = export_corpus(books, output, include_pdfs=True, specifications=sources)
    assert index.mode == "self-hosted"
    for doc in index.documents:
        assert doc.source.local is not None
        assert (output / doc.source.local).read_bytes() == b"%PDF-test"


def test_conflicting_pdf_copies_are_refused(tmp_path):
    books = Corpus.load([_ETSI])
    sources = tmp_path / "sources"
    for directory in ("one", "two"):
        (sources / directory).mkdir(parents=True)
        for entry in books:
            name = str(entry.spec.link).rsplit("/", 1)[-1]
            (sources / directory / name).write_bytes(directory.encode())
    with pytest.raises(CorpusError, match="conflicting PDF copies"):
        export_corpus(
            books, tmp_path / "out", include_pdfs=True, specifications=sources
        )


def test_export_copies_available_rfc_text_without_pdfs(tmp_path):
    books = Corpus.load([_CORPUS_DIR / "rfc"])
    sources = tmp_path / "specifications"
    (sources / "rfc").mkdir(parents=True)
    text = b"RFC 6733\n\f6.7.2.  Proxy-Info AVP\n"
    (sources / "rfc/rfc6733.txt").write_bytes(text)
    output = tmp_path / "export"
    index = export_corpus(books, output, specifications=sources)
    doc = next(d for d in index.documents if d.reference == "RFC6733")
    assert doc.source.text is not None
    assert (output / doc.source.text).read_bytes() == text
    assert doc.source.local is None
    assert all(d.source.text is None for d in index.documents if d is not doc)


def test_a_transcriptions_missing_pdf_names_its_download(tmp_path):
    empty = tmp_path / "specifications"
    empty.mkdir()

    with pytest.raises(CorpusError, match=r"seanchai download --only transcribed"):
        export_corpus(
            Corpus.load([_ETSI]),
            tmp_path / "out",
            include_pdfs=True,
            specifications=empty,
        )


def test_an_export_finds_a_transcriptions_pdf_where_the_download_puts_it(tmp_path):
    books = Corpus.load([_ETSI])
    specifications = tmp_path / "specifications"
    fetched = specifications / "transcriptions"
    fetched.mkdir(parents=True)
    for document in load_catalog().transcribed:
        (fetched / document.file_name).write_bytes(b"%PDF-test")

    output = tmp_path / "out"
    index = export_corpus(
        books, output, include_pdfs=True, specifications=specifications
    )

    assert all(doc.source.local for doc in index.documents)


def test_export_cli_uses_explicit_corpus_and_reports_missing_sources(tmp_path):
    result = CliRunner().invoke(
        main, ["export", "--corpus", str(_ETSI), "-o", str(tmp_path / "data")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data/index.json").is_file()
    result = CliRunner().invoke(
        main,
        [
            "export",
            "--corpus",
            str(_ETSI),
            "--include-pdfs",
            "-o",
            str(tmp_path / "invalid"),
        ],
    )
    assert result.exit_code == 2
    assert "--include-pdfs needs --specifications" in result.output
    assert not (tmp_path / "invalid").exists()


def test_export_help_says_what_each_mode_needs():
    result = CliRunner().invoke(main, ["export", "--help"])
    assert result.exit_code == 0
    text = " ".join(result.output.split())
    assert "seanchai export -o site/data" in text
    assert "--include-pdfs --specifications specifications" in text
    assert "executes Python" in text
    assert "specifications/wireshark" in text
    assert "replaces" in text


def _with_pdfs(books, tmp_path):
    sources = tmp_path / "specifications"
    sources.mkdir()
    for entry in books:
        (sources / str(entry.spec.link).rsplit("/", 1)[-1]).write_bytes(b"%PDF-test")
    return sources


def test_a_public_export_replaces_a_self_hosted_one_whole(tmp_path):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(
        books, output, include_pdfs=True, specifications=_with_pdfs(books, tmp_path)
    )
    assert list((output / "sources").glob("*.pdf"))

    export_corpus(books, output)

    index = json.loads((output / "index.json").read_text("utf-8"))
    assert index["mode"] == "public"
    assert not (output / "sources").exists()
    fresh = tmp_path / "fresh"
    export_corpus(books, fresh)
    assert _tree(output) == _tree(fresh)
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_a_self_hosted_export_replaces_a_public_one(tmp_path):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    export_corpus(
        books, output, include_pdfs=True, specifications=_with_pdfs(books, tmp_path)
    )
    index = json.loads((output / "index.json").read_text("utf-8"))
    assert index["mode"] == "self-hosted"
    assert len(list((output / "sources").glob("*.pdf"))) == len(books)


def test_a_removed_document_leaves_the_export(tmp_path):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    first = min(e.path.stem for e in books)
    assert (output / "documents" / f"{first}.json").is_file()

    smaller = Corpus(e for e in books if e.path.stem != first)
    export_corpus(smaller, output)

    assert not (output / "documents" / f"{first}.json").exists()
    assert not (output / "documents" / f"{first}.raw.json").exists()


def test_a_failed_export_leaves_the_previous_one_as_it_was(tmp_path):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    before = _tree(output)
    empty = tmp_path / "specifications"
    empty.mkdir()

    with pytest.raises(CorpusError, match="no downloaded PDF"):
        export_corpus(books, output, include_pdfs=True, specifications=empty)

    assert _tree(output) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out", "specifications"]


def _fail_renames(
    monkeypatch,
    staged: BaseException | None = None,
    backup: BaseException | None = None,
) -> None:
    """Make renaming the staged export, or the backup back, raise these."""
    rename = Path.rename

    def failing(self, target):
        if staged and self.name == "new":
            raise staged
        if backup and ".previous-" in self.name:
            raise backup
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", failing)


def test_replacing_an_export_leaves_no_backup(tmp_path):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    export_corpus(books, output)
    assert [p.name for p in tmp_path.iterdir()] == ["out"]


@pytest.mark.parametrize("error", [OSError("no room"), KeyboardInterrupt()])
def test_a_failed_publish_restores_the_previous_export(tmp_path, monkeypatch, error):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    before = _tree(output)
    _fail_renames(monkeypatch, staged=error)

    with pytest.raises(type(error)):
        export_corpus(books, output)

    assert _tree(output) == before
    assert [p.name for p in tmp_path.iterdir()] == ["out"]


def test_an_interruption_after_the_backup_rename_restores_the_previous_export(
    tmp_path, monkeypatch
):
    """The rename is done when the interruption arrives, so nothing but the
    backup holds the previous export."""
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    before = _tree(output)
    rename = Path.rename

    def interrupted(self, target):
        moved = rename(self, target)
        if self == output:
            raise KeyboardInterrupt
        return moved

    monkeypatch.setattr(Path, "rename", interrupted)

    with pytest.raises(KeyboardInterrupt):
        export_corpus(books, output)

    assert _tree(output) == before
    assert [p.name for p in tmp_path.iterdir()] == ["out"]


@pytest.mark.parametrize("error", [OSError("no room"), KeyboardInterrupt()])
def test_a_failed_restoration_keeps_the_backup_and_names_it(
    tmp_path, monkeypatch, error
):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    before = _tree(output)
    backup = tmp_path / f"out.previous-{os.getpid()}"
    _fail_renames(monkeypatch, staged=error, backup=OSError("read-only"))

    with pytest.raises(CorpusError) as refused:
        export_corpus(books, output)

    assert str(backup) in str(refused.value)
    assert "read-only" in str(refused.value)
    assert not output.exists()
    assert _tree(backup) == before
    assert [p.name for p in tmp_path.iterdir()] == [backup.name]


def test_a_backup_already_there_is_not_overwritten(tmp_path):
    """The name holds a pid, which comes round again: what an earlier run could
    not restore stops this one rather than being replaced."""
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    before = _tree(output)
    backup = tmp_path / f"out.previous-{os.getpid()}"
    backup.mkdir()
    (backup / "index.json").write_text("earlier", "utf-8")

    with pytest.raises(OSError):
        export_corpus(books, output)

    assert _tree(output) == before
    assert (backup / "index.json").read_text("utf-8") == "earlier"


def test_an_export_keeps_to_the_mode_of_a_new_or_replaced_directory(tmp_path):
    books = Corpus.load([_ETSI])
    output = tmp_path / "out"
    export_corpus(books, output)
    assert output.stat().st_mode & 0o777 != 0o700
    output.chmod(0o750)
    export_corpus(books, output)
    assert output.stat().st_mode & 0o777 == 0o750


def test_an_export_follows_a_symlinked_output(tmp_path):
    books = Corpus.load([_ETSI])
    real = tmp_path / "real"
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    export_corpus(books, link)
    assert link.is_symlink()
    assert (real / "index.json").is_file()


@pytest.mark.parametrize("name", ["notes.txt", "index.json"])
def test_a_directory_holding_anything_else_is_refused(tmp_path, name):
    output = tmp_path / "out"
    output.mkdir()
    (output / name).write_text("mine", "utf-8")
    before = _tree(output)
    with pytest.raises(CorpusError, match="not empty"):
        export_corpus(Corpus.load([_ETSI]), output)
    assert _tree(output) == before


_V2_INDEX = {
    "schema_version": 2,
    "seanchai_version": None,
    "corpus_version": None,
    "mode": "public",
    "documents": [],
}


@pytest.mark.parametrize(
    "index",
    [
        {"schema_version": None},
        {"schema_version": 3},
        {"name": "my-package", "version": "1.0.0"},
        ["schema_version"],
        {"generator": "someone-else", "schema_version": 4},
        {**_V2_INDEX, "schema_version": 4},
        {**_V2_INDEX, "schema_version": None},
        {**_V2_INDEX, "schema_version": True},
        {**_V2_INDEX, "schema_version": [2]},
        {**_V2_INDEX, "mode": "other"},
        {**_V2_INDEX, "documents": {}},
        {**_V2_INDEX, "extra": 1},
    ],
)
def test_an_unrelated_index_is_refused(tmp_path, index):
    output = tmp_path / "out"
    output.mkdir()
    (output / "index.json").write_text(json.dumps(index), "utf-8")
    (output / "mine.txt").write_text("mine", "utf-8")
    before = _tree(output)
    with pytest.raises(CorpusError, match="no Seanchaí export"):
        export_corpus(Corpus.load([_ETSI]), output)
    assert _tree(output) == before


@pytest.mark.parametrize(
    "index",
    [
        {
            "schema_version": 1,
            "mode": "self-hosted",
            "documents": [],
            "search": [],
            "mentions": [],
        },
        _V2_INDEX,
        {**_V2_INDEX, "schema_version": 3},
        {"schema_version": 99, "generator": "seanchai"},
    ],
)
def test_an_export_of_any_version_is_replaced(tmp_path, index):
    output = tmp_path / "out"
    output.mkdir()
    (output / "index.json").write_text(json.dumps(index), "utf-8")
    (output / "stale.json").write_text("{}", "utf-8")
    export_corpus(Corpus.load([_ETSI]), output)
    assert not (output / "stale.json").exists()
    assert json.loads((output / "index.json").read_text("utf-8"))["generator"]


def test_a_file_as_output_is_refused(tmp_path):
    output = tmp_path / "out"
    output.write_text("mine", "utf-8")
    with pytest.raises(CorpusError, match="not a directory"):
        export_corpus(Corpus.load([_ETSI]), output)
    assert output.read_text("utf-8") == "mine"


def test_an_empty_output_directory_is_used(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    export_corpus(Corpus.load([_ETSI]), output)
    assert (output / "index.json").is_file()


def test_an_empty_corpus_is_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    output = tmp_path / "out"
    with pytest.raises(CorpusError, match="no documents"):
        export_corpus(Corpus.load([empty]), output)
    assert not output.exists()
    result = CliRunner().invoke(
        main, ["export", "--corpus", str(empty), "-o", str(output)]
    )
    assert result.exit_code == 1
    assert "no documents" in result.output
    assert not output.exists()
