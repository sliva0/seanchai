"""The corpus rebuild's bookkeeping, on a manifest of one synthetic document.

The real corpus never exercises the version-replacement, not-in-manifest and
not-converted paths (the moment it does, the fix is to regenerate and commit,
or download again), so they are pinned here.
"""

import json
import shutil

import pytest
from conftest import _CORPUS_DIR

from seanchai import _correction_record, _regenerate
from seanchai.downloader import load_catalog


def _manifest(root, stem, release=18):
    document = root / "3gpp" / f"Rel-{release}" / "TS_29.999" / f"{stem}.docx"
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
    return _regenerate.regenerate(
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
    assert "replaced" in _regenerate.describe(replaced)

    # A committed document the manifest no longer lists is reported and left.
    manifest.write_text(json.dumps({"artifacts": []}))
    (orphan,) = _run(manifest, corpus, corpus).outcomes
    assert orphan.status == "not-in-manifest"
    assert (corpus / "3gpp" / "rel-18" / "29999-110.dad").is_file()


def test_a_rebuild_follows_a_document_into_a_later_releases_tree(
    tmp_path, synthetic_spec_docx
):
    sources = tmp_path / "specifications"
    manifest, document = _manifest(sources, "29999-100")
    shutil.copy(synthetic_spec_docx, document)
    corpus = tmp_path / "dad"
    corpus.mkdir()
    _run(manifest, corpus, corpus, add=["TS29.999"])

    # The manifest moves to the next release: the committed copy is replaced
    # there and its tree goes, rather than the document being reported lost.
    manifest, newer = _manifest(sources, "29999-110", release=19)
    shutil.copy(synthetic_spec_docx, newer)
    (replaced,) = _run(manifest, corpus, corpus).outcomes
    assert replaced.status == "new"
    assert replaced.replaced_version == "1.2.3"
    assert sorted(p.relative_to(corpus).as_posix() for p in corpus.rglob("*.dad")) == [
        "3gpp/rel-19/29999-110.dad",
        "raw/3gpp/rel-19/29999-110.raw.dad",
    ]
    assert not (corpus / "3gpp" / "rel-18").exists()

    # An earlier release's manifest, an older version's say, moves nothing.
    manifest, older = _manifest(sources, "29999-100", release=18)
    shutil.copy(synthetic_spec_docx, older)
    (orphan,) = _run(manifest, corpus, corpus).outcomes
    assert orphan.status == "not-in-manifest"
    assert (corpus / "3gpp" / "rel-19" / "29999-110.dad").is_file()


def test_an_older_version_rebuilds_alone_into_a_scratch_directory(
    tmp_path, synthetic_spec_docx
):
    # The route `seanchai corpus download --spec --version` leads to: a one-record
    # manifest, `only` so the corpus's other specifications are not reported
    # missing from it, and an output that is not the corpus.
    corpus = tmp_path / "dad"
    manifest, document = _manifest(tmp_path / "specifications", "29999-110")
    shutil.copy(synthetic_spec_docx, document)
    _run(manifest, corpus, corpus, add=["TS29.999"])
    other = _CORPUS_DIR / "rfc" / "rfc4004.dad"
    shutil.copy(other, corpus / "rfc4004.dad")
    committed = {path: path.read_bytes() for path in corpus.rglob("*.dad")}
    older, document = _manifest(
        tmp_path / "versions" / "TS29.999" / "1.2.3", "29999-100"
    )
    shutil.copy(synthetic_spec_docx, document)
    scratch = tmp_path / "scratch"

    (outcome,) = _regenerate.regenerate(
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
    assert "--no-convert" in _regenerate.describe(skipped)

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
    ("first", "last", "expected"), [("1.3", "1.9", 3), ("1.2.3", "1.2.3", 0)]
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
        "from seanchai.dad.corrections import Correction, VersionRange, definition\n"
        'CORRECTIONS = [Correction(id="code", target=definition("Example-Group"), '
        'field="code", expect=10, replace=12, reason="out-of-range correction", '
        f"versions=VersionRange({first!r}, {last!r}))]\n"
    )
    corpus = tmp_path / "dad"
    corpus.mkdir()
    result = CliRunner().invoke(
        main,
        [
            "corpus",
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
    warnings = [line for line in result.output.splitlines() if "warning:" in line]
    assert len(warnings) == expected
    assert all("does not cover parsed version 1.2.3" in w for w in warnings)
    if expected:
        patch, quirk, correction = warnings
        assert "input patch" in patch and "quirk" in quirk
        assert "TS29.999.py#code" in correction
    corrected = parser.parse((corpus / "3gpp/rel-18/29999-123.dad").read_text())
    assert any(
        isinstance(s, ast.GroupedAvp) and s.code == 12 for s in corrected.sections
    )


_MODULE = """
from seanchai.dad.corrections import Correction, table_row

CORRECTIONS = [
    Correction(
        id="mode-code",
        target=table_row("Example-Mode"),
        field="code",
        expect=11,
        replace=12,
        reason="the reason",
        versions="1.2.3",
    ),
]
"""


def test_a_rebuild_records_its_corrections_beside_the_documents(
    tmp_path, synthetic_spec_docx
):
    manifest, document = _manifest(tmp_path / "specifications", "29999-123")
    shutil.copyfile(synthetic_spec_docx, document)
    modules = tmp_path / "edits"
    modules.mkdir()
    (modules / "TS29.999.py").write_text(_MODULE)
    corpus = tmp_path / "dad"
    corpus.mkdir()

    report = _regenerate.regenerate(
        manifest,
        corpus,
        corpus,
        sources_dir=None,
        corrections_dir=modules,
        add=["TS29.999"],
    )

    assert report.record is not None
    assert report.record == corpus / _correction_record.RECORD_NAME
    record = _correction_record.load(report.record)
    edit = record.documents["29999-123"].edits["TS29.999.py#mode-code"]
    assert (edit.kind, edit.reason) == ("correction", "the reason")


def test_a_failed_rebuild_leaves_the_corrections_record_alone(
    tmp_path, synthetic_spec_docx
):
    manifest, document = _manifest(tmp_path / "specifications", "29999-123")
    shutil.copyfile(synthetic_spec_docx, document)
    modules = tmp_path / "edits"
    modules.mkdir()
    (modules / "TS29.999.py").write_text(_MODULE)
    corpus = tmp_path / "dad"
    corpus.mkdir()
    kept = _regenerate.regenerate(
        manifest,
        corpus,
        corpus,
        sources_dir=None,
        corrections_dir=modules,
        add=["TS29.999"],
    ).record
    assert kept is not None
    before = kept.read_bytes()
    (modules / "TS29.999.py").write_text(_MODULE.replace("the reason", "another"))
    document.write_bytes(b"not a docx")

    report = _regenerate.regenerate(
        manifest, corpus, corpus, sources_dir=None, corrections_dir=modules
    )

    assert report.failed
    assert report.record is None
    assert kept.read_bytes() == before


def test_a_corrections_record_that_cannot_be_built_fails_the_run(
    tmp_path, synthetic_spec_docx
):
    manifest, document = _manifest(tmp_path / "specifications", "29999-123")
    shutil.copyfile(synthetic_spec_docx, document)
    modules = tmp_path / "edits"
    modules.mkdir()
    corpus = tmp_path / "dad"
    corpus.mkdir()
    # A corpus file with a module the rebuild did not read: `--spec` picks one.
    shutil.copy(_CORPUS_DIR / "rfc" / "rfc4004.dad", corpus / "rfc4004.dad")
    (modules / "RFC4004.py").write_text("raise ValueError('broken')\n")

    report = _regenerate.regenerate(
        manifest,
        corpus,
        corpus,
        sources_dir=None,
        corrections_dir=modules,
        add=["TS29.999"],
        only=["TS29.999"],
    )

    assert report.record is None
    (failed,) = report.failed
    assert failed.reference == _correction_record.RECORD_NAME


def test_declarations_for_another_release_do_not_apply(tmp_path, synthetic_spec_docx):
    """A document read at a release no declaration spans, with none for an
    earlier release either, gets none: TS 32.299's Release 18 quirks say
    nothing about its Release 11 template. The dotted flag cell then fails
    as undeclared, and the Release 2 correction is not applied."""
    import docx

    manifest, document = _manifest(tmp_path / "specifications", "29999-123")
    source = docx.Document(synthetic_spec_docx)
    source.tables[1].cell(2, 4).text = "M.V"
    source.save(document)
    declarations = tmp_path / "edits"
    declarations.mkdir()
    (declarations / "TS29.999.toml").write_text(
        '[[quirk]]\nname = "dotted-flags"\nreason = "Release 2 only"\n'
        'first_version = "2.0.0"\nlast_version = "2.0.0"\n'
    )
    corpus = tmp_path / "dad"
    corpus.mkdir()

    (outcome,) = _regenerate.regenerate(
        manifest,
        corpus,
        corpus,
        sources_dir=declarations,
        corrections_dir=None,
        add=["TS29.999"],
    ).outcomes

    assert outcome.status == "failed"
    assert outcome.error is not None and "`dotted-flags` quirk" in outcome.error


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
        "corpus",
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
            "corpus",
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
        return _regenerate.regenerate(
            manifest,
            corpus,
            corpus,
            sources_dir=sources,
            corrections_dir=edits,
            transcriptions_dir=transcriptions,
            **options,
        ).outcomes

    return corpus, sources, edits, run


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


_TGPP2_TRANSCRIPTION = """\
; Specification: 3GPP2 X.S0057
; Version: 2.0
; Vendor-ID: 5535
; Transcribed: by hand from http://example.test/Specs/X.S0057-0_v2.0_091215.pdf


; Type: AVP Table
; Section: 5.6.2.1.1
; Table: 1
; Columns: Name Code
3GPP2-BSID 9010
"""


def _run_transcriptions(tmp_path, text):
    transcriptions = tmp_path / "transcriptions"
    transcriptions.mkdir()
    (transcriptions / "3GPP2-X.S0057.dad").write_text(text, encoding="utf-8")
    corpus = tmp_path / "dad"
    corpus.mkdir()
    manifest, _ = _manifest(tmp_path / "specifications", "29999-100")
    return (
        corpus,
        lambda: (
            _regenerate.regenerate(
                manifest,
                corpus,
                corpus,
                sources_dir=None,
                corrections_dir=None,
                transcriptions_dir=transcriptions,
                add=["3GPP2-X.S0057"],
            ).outcomes
        ),
    )


def test_an_oma_transcription_of_another_version_is_refused(tmp_path):
    """OMA's rendering name holds the version as well as the approval date and
    status, so a transcription of another version cannot name its file."""
    transcriptions = tmp_path / "transcriptions"
    transcriptions.mkdir()
    url = "https://example.org/OMA-DDS-Charging_Data-V1_0-20110201-A.pdf"
    (transcriptions / "OMA-DDS-Charging_Data.dad").write_text(
        "; Specification: OMA-DDS-Charging_Data\n"
        f"; Version: 1.1\n; Transcribed: by hand from {url}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="OMA's rendering of its name and version"):
        _regenerate._transcriptions(transcriptions)


def test_a_3gpp2_transcription_from_another_versions_rendering_is_refused(
    tmp_path,
):
    _, run = _run_transcriptions(
        tmp_path, _TGPP2_TRANSCRIPTION.replace("; Version: 2.0", "; Version: 1.0")
    )

    with pytest.raises(ValueError, match=r"X\.S0057-<revision>_v1\.0_<date>\.pdf"):
        run()


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"artifacts": 7}',
        '{"artifacts": [{"files": [], "family": "IETF"}, 7]}',
    ],
)
def test_a_malformed_manifest_fails_the_run_and_names_the_file(tmp_path, text):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(text)

    report = _run(manifest, corpus, corpus)

    (failed,) = report.outcomes
    assert report.failed
    assert failed.status == "failed"
    assert failed.reference == "manifest.json"
    assert "no download manifest" in _regenerate.describe(failed)


def test_a_missing_manifest_fails_the_run(tmp_path):
    report = _run(tmp_path / "manifest.json", tmp_path, tmp_path)

    assert report.failed


def test_adding_an_out_of_scope_document_says_why(tmp_path):
    reference = next(iter(load_catalog().out_of_scope()))
    sources = tmp_path / "sources"
    sources.mkdir()
    manifest, _ = _manifest(sources, "29999-100")
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    report = _run(manifest, corpus, corpus, add=[reference])

    (refused,) = report.outcomes
    assert (refused.reference, refused.status) == (reference, "failed")
    assert "out of scope: " in _regenerate.describe(refused)


_ORPHAN = "; Specification: 3GPP TS 29.999\n; Version: 1.0.0\n; Vendor-ID: 10415\n"


def _rfc_only_manifest(root):
    """What `seanchai corpus download --only rfc` leaves, of an RFC the corpus lacks."""
    (root / "rfc").mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({"artifacts": [], "sources": ["rfc", "wireshark"]})
    )
    return root / "manifest.json"


def test_a_document_missing_from_the_manifest_names_the_download_it_needs(
    tmp_path,
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "29999-100.dad").write_text(_ORPHAN)

    partial = _run(_rfc_only_manifest(tmp_path / "specifications"), corpus, corpus)

    assert partial.missing_sources == ("3gpp",)
    (outcome,) = partial.failed
    assert outcome.status == "not-in-manifest"
    assert "seanchai corpus download --only 3gpp" in (outcome.error or "")

    whole = tmp_path / "manifest.json"
    whole.write_text(json.dumps({"artifacts": []}))
    report = _run(whole, corpus, corpus)
    assert report.missing_sources == ()
    assert report.failed[0].status == "not-in-manifest"
