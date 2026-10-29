"""The corpus rebuild's bookkeeping, on a manifest of one synthetic document.

The real corpus never exercises the version-replacement and not-in-manifest
paths (the moment it does, the fix is to regenerate and commit), so they are
pinned here.
"""

import json
import shutil

import pytest

from seanchai import regenerate


def _manifest(root, stem):
    document = root / "3gpp" / "Rel-18" / "TS_29.999" / f"{stem}.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "family": "3GPP",
                        "identifier": "TS 29.999",
                        "files": [str(document.relative_to(root))],
                        "url": "https://example.test/archive.zip",
                        "pdf_url": f"https://example.test/{stem}.pdf",
                    },
                    {
                        "family": "Wireshark",
                        "identifier": "Wireshark v0",
                        "files": ["wireshark/dictionary.xml"],
                        "url": "https://example.test/wireshark",
                    },
                ]
            }
        )
    )
    return path, document


def _run(manifest, corpus, output, add=()):
    return regenerate.regenerate(
        manifest, corpus, output, sources_dir=None, corrections_dir=None, add=add
    )


def test_a_rebuild_follows_the_manifest_version_and_reports_what_it_did(
    tmp_path, synthetic_spec_docx
):
    sources = tmp_path / "specifications"
    manifest, document = _manifest(sources, "29999-100")
    shutil.copy(synthetic_spec_docx, document)
    corpus = tmp_path / "dad"
    corpus.mkdir()

    # Nothing committed: only `add` builds anything.
    assert _run(manifest, corpus, corpus).outcomes == []
    (added,) = _run(manifest, corpus, corpus, add=["TS29.999"]).outcomes
    assert added.status == "new"
    assert added.version == "1.2.3"
    assert [p.relative_to(corpus).as_posix() for p in added.written] == [
        "3gpp/rel-18/29999-100.dad",
        "raw/3gpp/rel-18/29999-100.raw.dad",
    ]
    assert "; Link: https://example.test/29999-100.pdf" in added.written[0].read_text()

    # Committed now, so it is rebuilt without `add`, and the bytes match.
    (again,) = _run(manifest, corpus, corpus).outcomes
    assert again.status == "unchanged"

    # The manifest moves to a newer archive: the old pair is replaced, and
    # the run says so rather than keeping two versions.
    manifest, newer = _manifest(sources, "29999-110")
    shutil.copy(synthetic_spec_docx, newer)
    (replaced,) = _run(manifest, corpus, corpus).outcomes
    assert replaced.status == "new"
    assert replaced.replaced_version == "1.2.3"
    assert sorted(p.name for p in corpus.rglob("*.dad")) == [
        "29999-110.dad",
        "29999-110.raw.dad",
    ]
    assert "replaced" in regenerate.describe(replaced)

    # A committed document the manifest no longer lists is reported and left.
    manifest.write_text(json.dumps({"artifacts": []}))
    (orphan,) = _run(manifest, corpus, corpus).outcomes
    assert orphan.status == "not-in-manifest"
    assert (corpus / "3gpp" / "rel-18" / "29999-110.dad").is_file()


def test_a_legacy_doc_is_read_through_the_manifest_conversion(
    tmp_path, synthetic_spec_docx
):
    sources = tmp_path / "specifications"
    manifest, document = _manifest(sources, "29999-100")
    data = json.loads(manifest.read_text())
    legacy = document.with_suffix(".doc")
    converted = sources / "converted" / legacy.relative_to(sources)
    converted = converted.with_suffix(".docx")
    converted.parent.mkdir(parents=True)
    shutil.copy(synthetic_spec_docx, converted)
    conversion = {
        "source": str(legacy.relative_to(sources)),
        "file": str(converted.relative_to(sources)),
    }
    tgpp = data["artifacts"][0]
    tgpp["files"] = [conversion["source"]]
    # Without the record, a `.doc` is unreadable however many converted
    # files lie around: the manifest is the only route.
    manifest.write_text(json.dumps(data))
    corpus = tmp_path / "dad"
    corpus.mkdir()
    (missing,) = _run(manifest, corpus, corpus, add=["TS29.999"]).outcomes
    assert missing.status == "not-in-manifest"

    tgpp["conversions"] = [conversion]
    # A TR has no reference a corpus file can carry; it is passed over.
    data["artifacts"].append(dict(tgpp, identifier="TR 29.999"))
    manifest.write_text(json.dumps(data))

    (added,) = _run(manifest, corpus, corpus, add=["TS29.999"]).outcomes

    assert added.status == "new"
    assert [p.relative_to(corpus).as_posix() for p in added.written] == [
        "3gpp/rel-18/29999-100.dad",
        "raw/3gpp/rel-18/29999-100.raw.dad",
    ]


def test_a_document_the_extractor_rejects_fails_alone(tmp_path):
    sources = tmp_path / "specifications"
    manifest, document = _manifest(sources, "29999-100")
    document.write_bytes(b"not a docx")
    corpus = tmp_path / "dad"
    corpus.mkdir()

    report = _run(manifest, corpus, corpus, add=["TS29.999"])

    (failed,) = report.failed
    assert failed.status == "failed"
    assert failed.error
    assert not list(corpus.rglob("*.dad"))


@pytest.mark.parametrize(
    "first,last,expected", [("2.0", "3.0", 3), ("0.1", "1.1", 3), ("1.2.3", "1.2.3", 0)]
)
def test_ranges_warn_for_all_layers_without_gating_application(
    tmp_path, synthetic_spec_docx, first, last, expected
):
    import docx
    from click.testing import CliRunner

    from seanchai.cli import main
    from seanchai.dad import ast, parser

    manifest, document = _manifest(tmp_path / "specifications", "29999-123")
    source = docx.Document(synthetic_spec_docx)
    source.tables[1].cell(2, 4).text = "M.V"
    source.save(document)
    declarations = tmp_path / "edits"
    declarations.mkdir()
    bounds = f'first_version = "{first}"\nlast_version = "{last}"\n'
    (declarations / "TS29.999.toml").write_text(
        '[[patch]]\nfind = "Value Type"\nreplace = "Value Type (NOTE 2)"\n'
        'exact = true\nreason = "exercise an out-of-range patch"\n'
        + bounds
        + '[[quirk]]\nname = "dotted-flags"\nreason = "out-of-range quirk"\n'
        + bounds
    )
    (declarations / "TS29.999.py").write_text(
        "from seanchai.dad.corrections import Correction, definition\n"
        "from seanchai.versions import VersionRange\n"
        'CORRECTIONS = [Correction(id="code", target=definition("Example-Group"), '
        'field="code", expect=10, replace=12, reason="out-of-range correction", '
        f"versions=VersionRange({first!r}, {last!r}))]\n"
    )
    corpus = tmp_path / "dad"
    corpus.mkdir()
    result = CliRunner().invoke(
        main,
        [
            "regenerate",
            "--manifest",
            str(manifest),
            "--corpus",
            str(corpus),
            "--sources",
            str(declarations),
            "--corrections",
            str(declarations),
            "--add",
            "TS29.999",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "new       TS29.999 1.2.3"
    warnings = [line for line in lines if "warning:" in line]
    assert len(warnings) == expected
    if expected:
        assert lines[1:4] == warnings
        assert all(w.startswith("    warning:") for w in warnings)
        assert all("does not cover parsed version 1.2.3" in w for w in warnings)
        assert "input patch" in warnings[0]
        assert "quirk" in warnings[1]
        assert "TS29.999.py#code" in warnings[2]
    corrected = parser.parse((corpus / "3gpp/rel-18/29999-123.dad").read_text())
    assert any(
        isinstance(s, ast.GroupedAvp) and s.code == 12 for s in corrected.sections
    )
