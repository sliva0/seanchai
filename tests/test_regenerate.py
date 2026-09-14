"""The corpus rebuild's bookkeeping, on a manifest of one synthetic document.

The real corpus never exercises the version-replacement and not-in-manifest
paths (the moment it does, the fix is to regenerate and commit), so they are
pinned here.
"""

import json
import shutil

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
