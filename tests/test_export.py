import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from seanchai.cli import main
from seanchai.corpus import Corpus, CorpusError
from seanchai.export import export_corpus
from seanchai.model import Model, ModelError

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    path = tmp_path_factory.mktemp("export")
    books = Corpus.installed()
    index = export_corpus(books, path, corrections_directory=ROOT / "edits/corrections")
    docs = {
        file.stem: json.loads(file.read_text())
        for file in (path / "documents").glob("*.json")
    }
    return path, books, index, docs


def test_export_preserves_every_corrected_and_raw_byte(exported):
    _, books, _, docs = exported
    for entry in books:
        doc = docs[entry.path.stem]
        text = "".join(t["text"] for line in doc["lines"] for t in line["tokens"])
        assert text == entry.path.read_text()
        root = next(p for p in entry.path.parents if (p / "raw").is_dir())
        raw = root / "raw" / entry.path.relative_to(root).with_suffix(".raw.dad")
        assert (
            "".join(t["text"] for line in doc["raw"] for t in line["tokens"])
            == raw.read_text()
        )


def test_export_has_no_broken_links_or_duplicate_anchors(exported):
    _, _, index, docs = exported
    anchors = {}
    for key, doc in docs.items():
        values = [line["anchor"] for line in doc["lines"] if line["anchor"]]
        assert len(values) == len(set(values))
        anchors[key] = set(values)
    targets = [entry["target"] for entry in index["search"] if entry["target"]]
    for doc in docs.values():
        for variant in ("lines", "raw"):
            for line in doc[variant] or []:
                for token in line["tokens"]:
                    if "target" in token:
                        targets.append(token["target"])
                    if "correction" in token:
                        assert token["correction"] in doc["corrections"]
    for target in targets:
        assert target["document"] in docs
        if target["section"]:
            assert target["section"] in anchors[target["document"]]


def test_export_prefers_definition_page_to_earlier_table_row(exported):
    _, books, _, docs = exported
    entry = next(e for e in books if e.path.stem == "29272-i70")
    section = next(
        s for s in entry.spec.sections if getattr(s, "name", None) == "Area-Scope"
    )
    doc = docs[entry.path.stem]
    actual = next(s for s in doc["sections"] if s["section"] == section.source.section)
    assert actual["page"] == section.source.page
    line = next(
        line for line in doc["lines"] if line["anchor"] == section.source.section
    )
    assert "Type:" in "".join(t["text"] for t in line["tokens"])


def test_export_carries_specific_release_resolution_and_diagnostics(exported):
    _, _, index, docs = exported
    entry = next(
        e
        for e in index["search"]
        if e["document"] == "ts-0004-v2_35_0" and e["name"] == "Service-Information"
    )
    assert entry["target"]["document"] == "32299-bk0"
    assert entry["across_releases"]["version"] == "11.20.0"
    assert any(doc["holes"] for doc in docs.values())
    assert any(
        f["severity"] == "accepted" for d in docs.values() for f in d["findings"]
    )
    assert "area-scope-code" in " ".join(docs["29272-i70"]["corrections"])
    assert all(d["source"]["local"] is None for d in docs.values())
    assert all(
        e["target"] and e["target"]["section"]
        for e in index["search"]
        if e["kind"] == "AVP" and e["identity"]
    )


def test_table_names_keep_row_locations_and_definition_targets(exported):
    _, _, _, docs = exported
    for variant in ("lines", "raw"):
        line = next(
            line
            for line in docs["29329-i00"][variant]
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
    _, _, index, docs = exported
    entry = next(
        e for e in index["search"] if e["document"] == document and e["name"] == name
    )
    assert entry["target"] == target
    for variant in ("lines", "raw"):
        tokens = [
            t
            for line in docs[document][variant]
            for t in line["tokens"]
            if t["text"] == name
        ]
        assert tokens
        assert all(t["target"] == target for t in tokens)


def test_version_specific_model_queries_read_the_selected_copy(exported):
    _, books, _, _ = exported
    model = Model.build(books)
    old = model.resolve("TS32.299", "Service-Information", version="11.20.0")
    assert old is not None
    assert old.across_releases is None
    old_identifier = model.resolve(
        "TS32.299", "AF-Charging-Identifier", version="11.20.0"
    )
    new_identifier = model.resolve("TS32.299", "AF-Charging-Identifier")
    assert old_identifier is not None and old_identifier.section == "5.3.6"
    assert new_identifier is not None and new_identifier.section is None
    with pytest.raises(ModelError, match=r"V99\.0\.0"):
        model.resolve("TS32.299", "Service-Information", version="99.0.0")


def test_from_cells_target_the_named_avp_and_raw_changes_are_marked(exported):
    _, _, index, docs = exported
    document = next(
        d
        for d in docs.values()
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
    assert docs[reference["target"]["document"]]["reference"] == "TS29.061"
    raw = docs["29229-i10"]["raw"]
    renamed = [
        line
        for line in raw
        if any(t.get("avp") == "Digest-QoP" for t in line["tokens"])
    ]
    assert renamed and all(line.get("warning") for line in renamed)
    session = [
        line
        for line in raw
        if line["section"] == "6.1.10"
        and any(t.get("avp") == "Session-Id" for t in line["tokens"])
    ]
    assert len(session) == 2
    assert sum(bool(line.get("warning")) for line in session) == 1
    assert any("Callee-Information" in mention["avps"] for mention in index["mentions"])


def test_raw_spelling_links_through_its_declared_name_correction(exported):
    _, _, _, docs = exported
    raw = docs["29229-i10"]["raw"]
    tokens = [t for line in raw for t in line["tokens"] if t["text"] == "Digest-QoP"]
    assert len(tokens) == 3
    assert all(t["target"] == {"document": "rfc4590", "section": "3.8"} for t in tokens)


def test_export_is_byte_stable_over_the_committed_corpus(exported, tmp_path):
    path, books, _, _ = exported
    export_corpus(books, tmp_path, corrections_directory=ROOT / "edits/corrections")
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*.json")):
        relative = file.relative_to(path)
        assert file.read_bytes() == (tmp_path / relative).read_bytes()
        digest.update(relative.as_posix().encode())
        digest.update(file.read_bytes())
    assert digest.hexdigest() == (ROOT / "tests/export.sha256").read_text().strip()


def test_local_export_copies_matching_pdfs_and_rejects_missing_ones(tmp_path):
    books = Corpus.load(
        [ROOT / "packages/seanchai-corpus/src/seanchai_corpus/dad/etsi"]
    )
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
    assert index["mode"] == "self-hosted"
    for doc in index["documents"]:
        assert (output / doc["source"]["local"]).read_bytes() == b"%PDF-test"


def test_export_copies_available_rfc_text_without_pdfs(tmp_path):
    books = Corpus.load([ROOT / "packages/seanchai-corpus/src/seanchai_corpus/dad/rfc"])
    sources = tmp_path / "specifications"
    (sources / "rfc").mkdir(parents=True)
    text = b"RFC 6733\n\f6.7.2.  Proxy-Info AVP\n"
    (sources / "rfc/rfc6733.txt").write_bytes(text)
    output = tmp_path / "export"
    index = export_corpus(books, output, specifications=sources)
    doc = next(d for d in index["documents"] if d["reference"] == "RFC6733")
    assert (output / doc["source"]["text"]).read_bytes() == text
    assert doc["source"]["local"] is None
    assert all(
        "text" not in d["source"]
        for d in index["documents"]
        if d["reference"] != "RFC6733"
    )


def test_export_cli_uses_explicit_corpus_and_reports_missing_sources(tmp_path):
    corpus = ROOT / "packages/seanchai-corpus/src/seanchai_corpus/dad/etsi"
    result = CliRunner().invoke(
        main, ["export", "--corpus", str(corpus), "-o", str(tmp_path / "data")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data/index.json").is_file()
    result = CliRunner().invoke(
        main,
        [
            "export",
            "--corpus",
            str(corpus),
            "--include-pdfs",
            "-o",
            str(tmp_path / "invalid"),
        ],
    )
    assert result.exit_code == 1
    assert "specifications directory" in result.output


def test_every_document_has_its_catalog_title(exported):
    _, _, index, _ = exported
    untitled = [
        doc["id"] for doc in index["documents"] if doc["title"] == doc["specification"]
    ]
    assert not untitled
    titles = {doc["id"]: doc["title"] for doc in index["documents"]}
    assert titles["29209-680"] == "Policy control over Gq interface"
    assert titles["xs0057-0_v2.0"].startswith("E-UTRAN - eHRPD")
    assert "e4 interface" in titles["es283034-020200"]
