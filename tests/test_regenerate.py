"""The corpus rebuild's bookkeeping, on a manifest of one synthetic document.

The real corpus never exercises the version-replacement, not-in-manifest and
not-converted paths (the moment it does, the fix is to regenerate and commit,
or download again), so they are pinned here.
"""

import json
import shutil
from pathlib import Path

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


def test_an_older_version_rebuilds_alone_into_a_scratch_directory(
    tmp_path, synthetic_spec_docx
):
    # The route `seanchai download --spec --version` leads to: a one-record
    # manifest, `only` so the corpus's other specifications are not reported
    # missing from it, and an output that is not the corpus.
    corpus = tmp_path / "dad"
    manifest, document = _manifest(tmp_path / "specifications", "29999-110")
    shutil.copy(synthetic_spec_docx, document)
    _run(manifest, corpus, corpus, add=["TS29.999"])
    other = Path(__file__).parent.parent / "dad" / "rfc" / "rfc4004.dad"
    shutil.copy(other, corpus / "rfc4004.dad")
    committed = {path: path.read_bytes() for path in corpus.rglob("*.dad")}
    older, document = _manifest(
        tmp_path / "versions" / "TS29.999" / "1.2.3", "29999-100"
    )
    shutil.copy(synthetic_spec_docx, document)
    scratch = tmp_path / "scratch"

    (outcome,) = regenerate.regenerate(
        older,
        corpus,
        scratch,
        sources_dir=None,
        corrections_dir=None,
        only=["TS29.999"],
    ).outcomes

    assert outcome.reference == "TS29.999"
    assert outcome.replaced_version == "1.2.3"
    assert [p.relative_to(scratch).as_posix() for p in outcome.written] == [
        "3gpp/rel-18/29999-100.dad",
        "raw/3gpp/rel-18/29999-100.raw.dad",
    ]
    assert {path: path.read_bytes() for path in corpus.rglob("*.dad")} == committed


def test_two_releases_of_one_document_are_two_copies_in_two_trees(
    tmp_path, synthetic_spec_docx
):
    """A pinned version (`seanchai download`'s `[[tgpp_pinned]]`) shares
    its reference with the catalog's release of the document: each is
    rebuilt in its own release's tree, and neither replaces the other."""
    sources = tmp_path / "specifications"
    manifest, document = _manifest(sources, "29999-i00")
    shutil.copy(synthetic_spec_docx, document)
    data = json.loads(manifest.read_text())
    old = sources / "3gpp" / "Rel-7" / "TS_29.999" / "29999-7c0.docx"
    old.parent.mkdir(parents=True)
    shutil.copy(synthetic_spec_docx, old)
    data["artifacts"].append(
        dict(data["artifacts"][0], files=[str(old.relative_to(sources))])
    )
    manifest.write_text(json.dumps(data))
    corpus = tmp_path / "dad"
    corpus.mkdir()

    added = _run(manifest, corpus, corpus, add=["TS29.999"]).outcomes
    assert [(o.status, o.written[0].relative_to(corpus).as_posix()) for o in added] == [
        ("new", "3gpp/rel-18/29999-i00.dad"),
        ("new", "3gpp/rel-7/29999-7c0.dad"),
    ]
    assert [o.status for o in _run(manifest, corpus, corpus).outcomes] == [
        "unchanged",
        "unchanged",
    ]

    # A one-release manifest rebuilds that release's copy only.
    data["artifacts"].pop(0)
    manifest.write_text(json.dumps(data))
    (outcome,) = regenerate.regenerate(
        manifest,
        corpus,
        tmp_path / "scratch",
        sources_dir=None,
        corrections_dir=None,
        only=["TS29.999"],
    ).outcomes
    assert (outcome.status, outcome.written[0].parent.name) == ("unchanged", "rel-7")


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
    # files lie around: the manifest is the only route. A `.doc` downloaded
    # with `--no-convert` is skipped on its own line, not failed.
    tgpp["conversions"] = []
    manifest.write_text(json.dumps(data))
    corpus = tmp_path / "dad"
    corpus.mkdir()
    report = _run(manifest, corpus, corpus, add=["TS29.999"])
    (skipped,) = report.outcomes
    assert skipped.status == "not-converted"
    assert report.failed == []
    assert not list(corpus.rglob("*.dad"))
    assert regenerate.describe(skipped) == (
        "not-converted TS29.999: 29999-100.doc was downloaded without conversion"
        " (`seanchai download --no-convert`); the committed files were left alone"
    )

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


@pytest.mark.parametrize("converted", [True, False], ids=["converted", "unconverted"])
def test_a_onem2m_document_is_read_through_its_conversion_into_its_own_tree(
    tmp_path, converted
):
    """oneM2M's record has no PDF; the pair is named as oneM2M names the
    file, less its title, under `onem2m/`."""
    source = "onem2m/Release-2/TS-0004/TS-0004-Core-V2_35_0(cl).doc"
    conversion = {
        "source": source,
        "file": f"converted/{source.removesuffix('.doc')}.docx",
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "family": "oneM2M",
                        "identifier": "oneM2M TS-0004",
                        "files": ["archives/onem2m/TS-0004-V2_35_0.zip", source],
                        "url": "https://example.test/download?docID=36771",
                        "source_version": "2.35.0",
                        "conversions": [conversion] if converted else [],
                    }
                ]
            }
        )
    )

    found = regenerate._sources(manifest)["oneM2M-TS-0004", "onem2m"]

    assert found.document == tmp_path / (conversion["file"] if converted else source)
    assert (found.pdf, found.link) == (
        None,
        "https://example.test/download?docID=36771",
    )
    assert (found.tree, found.stem) == ("onem2m", "ts-0004-v2_35_0")
    assert found.unconverted is not converted


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


def test_expanding_ranges_rewrites_the_edit_files_and_retires_the_warnings(
    tmp_path, synthetic_spec_docx
):
    import docx
    from click.testing import CliRunner

    from seanchai.cli import main

    manifest, document = _manifest(tmp_path / "specifications", "29999-123")
    source = docx.Document(synthetic_spec_docx)
    source.tables[1].cell(2, 4).text = "M.V"
    source.save(document)
    declarations = tmp_path / "edits"
    declarations.mkdir()
    toml = declarations / "TS29.999.toml"
    toml.write_text(
        '[[quirk]]\nname = "dotted-flags"  # table 6.3.1\nreason = "dotted cell"\n'
        'first_version = "1.0.0"\nlast_version = "1.0.0"\n'
    )
    module = declarations / "TS29.999.py"
    module.write_text(
        "from seanchai.dad.corrections import Correction, definition\n"
        'CORRECTIONS = [Correction(id="code", target=definition("Example-Group"), '
        'field="code", expect=10, replace=12, reason="reviewed on 1.0.0", '
        'versions="1.0.0")]\n'
    )
    corpus = tmp_path / "dad"
    corpus.mkdir()
    arguments = [
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
    ]

    result = CliRunner().invoke(main, [*arguments, "--expand-ranges"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[1:3] == [
        "    expanded: TS29.999.toml: quirk 'dotted-flags' 1.0.0 -> 1.0.0..1.2.3",
        "    expanded: TS29.999.py:2: versions 1.0.0 -> 1.0.0..1.2.3",
    ]
    assert not [line for line in lines if "warning:" in line]
    assert 'last_version = "1.2.3"' in toml.read_text()
    assert "# table 6.3.1" in toml.read_text()
    assert 'versions="1.0.0..1.2.3"' in module.read_text()

    again = CliRunner().invoke(main, arguments)
    assert again.exit_code == 0, again.output
    assert "warning:" not in again.output


def test_expanding_ranges_widens_only_the_acceptances_still_matching(
    tmp_path, synthetic_spec_docx
):
    """An acceptance changes nothing a rebuild checks, so its range moves
    only once the rebuilt file is linted and it still matches its finding.
    The corpus's RFC 6733 re-uses `Other-AVP` itself, which makes the
    synthetic document's citation an indirect origin."""
    from click.testing import CliRunner

    from seanchai.cli import main

    manifest, document = _manifest(tmp_path / "specifications", "29999-123")
    shutil.copy(synthetic_spec_docx, document)
    corpus = tmp_path / "dad"
    (corpus / "rfc").mkdir(parents=True)
    (corpus / "rfc" / "rfc6733.dad").write_text(
        "; Specification: RFC 6733\n"
        "; Vendor-ID: 0\n"
        "\n"
        "\n"
        "; Type: Reused AVPs\n"
        "; Section: 4.5\n"
        "; Table: 4.5/2\n"
        "; Columns: Name From\n"
        "Other-AVP RFC4005\n"
    )
    declarations = tmp_path / "edits"
    declarations.mkdir()
    module = declarations / "TS29.999.py"
    module.write_text(
        "from seanchai.dad.corrections import Accept, reused_row\n"
        "CORRECTIONS = [\n"
        "    Accept(id='indirect', rule='reused-origin-indirect',"
        " target=reused_row('Other-AVP'), expect='Other-AVP is listed as re-used"
        " from RFC6733, which re-uses it from RFC4005 rather than defining it',"
        " reason='r', versions='1.0.0'),\n"
        "    Accept(id='gone', rule='reused-origin-indirect',"
        " target=reused_row('Other-AVP'), expect='an older message',"
        " reason='r', versions='1.0.0'),\n"
        "]\n"
    )

    result = CliRunner().invoke(
        main,
        [
            "regenerate",
            "--manifest",
            str(manifest),
            "--corpus",
            str(corpus),
            "--corrections",
            str(declarations),
            "--spec",
            "TS29.999",
            "--expand-ranges",
        ],
    )

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "    expanded: TS29.999.py:3: versions 1.0.0 -> 1.0.0..1.2.3" in lines
    assert (
        "    warning: not widened, stale: TS29.999.py:4: versions 1.0.0:"
        " acceptance TS29.999.py#gone matches no finding"
    ) in lines
    text = module.read_text()
    assert text.count("versions='1.0.0..1.2.3'") == 1
    assert "expect='an older message', reason='r', versions='1.0.0')" in text


_TRANSCRIPTION = """\
; Specification: ETSI TS 183 017
; Version: 3.2.1
; Vendor-ID: 13019
; Transcribed: by hand from https://example.test/ts.pdf


; Type: AVP Table
; Section: 7.3
; Table: 7.3.1
; Columns: Name Code
Port-number x
"""

_TRANSCRIPTION_PATCHES = """\
[[patch]]
find = "Port-number x"
replace = "Port-number 455"
section = "7.3"
reason = "the code cell prints 'x'; clause 7.3.6 gives 455"
first_version = "3.2.1"
last_version = "3.2.1"
"""

_TRANSCRIPTION_CORRECTIONS = """\
from seanchai.dad.corrections import Correction, table_row

CORRECTIONS = [
    Correction(
        id="port-number-row-case",
        target=table_row("Port-number"),
        field="name",
        expect="Port-number",
        replace="Port-Number",
        reason="clause 7.3.6's sentence spells Port-Number",
        versions="3.2.1",
    )
]
"""


def _transcribed(tmp_path, version="3.2.1", declared="3.2.1"):
    """A transcription of `version` needing one input patch and one
    correction, both declared for `declared`."""
    transcriptions = tmp_path / "transcriptions"
    transcriptions.mkdir()
    (transcriptions / "ETSI-TS183.017.dad").write_text(
        _TRANSCRIPTION.replace("3.2.1", version), encoding="utf-8"
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "ETSI-TS183.017.toml").write_text(
        _TRANSCRIPTION_PATCHES.replace("3.2.1", declared)
    )
    edits = tmp_path / "corrections"
    edits.mkdir()
    (edits / "ETSI-TS183.017.py").write_text(
        _TRANSCRIPTION_CORRECTIONS.replace("3.2.1", declared)
    )
    corpus = tmp_path / "dad"
    corpus.mkdir()
    manifest, _ = _manifest(tmp_path / "specifications", "29999-100")

    def run(**options):
        return regenerate.regenerate(
            manifest,
            corpus,
            corpus,
            sources_dir=sources,
            corrections_dir=edits,
            transcriptions_dir=transcriptions,
            **options,
        ).outcomes

    return corpus, sources, edits, run


def test_a_transcription_is_read_through_its_input_patches(tmp_path):
    """No manifest lists a document no extractor reads; its transcription
    is the source, patched into the raw file and corrected from there."""
    corpus, _, _, run = _transcribed(tmp_path)

    (added,) = run(add=["ETSI-TS183.017"])
    assert (added.reference, added.status) == ("ETSI-TS183.017", "new")
    assert [p.relative_to(corpus).as_posix() for p in added.written] == [
        "etsi/ts183017-030201.dad",
        "raw/etsi/ts183017-030201.raw.dad",
    ]
    raw, corrected = (
        (corpus / "raw" / "etsi" / "ts183017-030201.raw.dad"),
        (corpus / "etsi" / "ts183017-030201.dad"),
    )
    assert "Port-number       455" in raw.read_text(encoding="utf-8")
    assert "Port-Number" in corrected.read_text(encoding="utf-8")
    assert "; Transcribed: by hand from" in raw.read_text(encoding="utf-8")

    (again,) = run()
    assert again.status == "unchanged"


def test_a_transcription_answers_to_its_declarations_version_ranges(tmp_path):
    """A V2.2.1 transcription under declarations reviewed on V2.2.0 is
    patched and corrected all the same, with the warnings an extraction
    gets; `--expand-ranges` widens both files once it rebuilt cleanly."""
    corpus, sources, edits, run = _transcribed(tmp_path, "2.2.1", "2.2.0")

    (added,) = run(add=["ETSI-TS183.017"])
    assert added.status == "new"
    assert len(added.warnings) == 2
    assert all("does not cover parsed version 2.2.1" in w for w in added.warnings)
    assert "input patch 'Port-number x'" in added.warnings[0]
    assert "ETSI-TS183.017.py#port-number-row-case" in added.warnings[1]
    corrected = corpus / "etsi" / "ts183017-020201.dad"
    assert "Port-Number" in corrected.read_text(encoding="utf-8")

    (expanded,) = run(expand_ranges=True)
    assert expanded.status == "unchanged"
    assert expanded.warnings == []
    assert len(expanded.expanded) == 2
    assert 'last_version = "2.2.1"' in (sources / "ETSI-TS183.017.toml").read_text()
    assert 'versions="2.2.0..2.2.1"' in (edits / "ETSI-TS183.017.py").read_text()

    (again,) = run()
    assert again.warnings == []
