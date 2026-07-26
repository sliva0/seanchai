import docx
from click.testing import CliRunner

from seanchai import main
from seanchai.dad import ast, formatter, parser


def test_extract_command_runs_docx_pdf_formatter_and_parser_end_to_end(
    tmp_path, synthetic_spec_docx, outlined_pdf
):
    output_path = tmp_path / "result.dad"

    result = CliRunner().invoke(
        main,
        [
            "extract",
            str(synthetic_spec_docx),
            "--pdf",
            str(outlined_pdf),
            "--link",
            "https://example.com/spec.pdf",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    spec = parser.parse(output_path.read_text())
    assert spec.specification == "3GPP TS 29.999"
    assert str(spec.link) == "https://example.com/spec.pdf"
    assert len(spec.sections) == 5
    assert spec.sections[0].source.page == 2
    assert spec.sections[1].source.page == 3
    assert spec.sections[3].source.page == 4
    assert spec.sections[4].source.page == 5
    assert "warning:" not in result.stderr
    assert f"wrote {output_path} (5 sections)" in result.stderr


def test_extract_command_prints_parseable_output_to_stdout(synthetic_spec_docx):
    result = CliRunner().invoke(main, ["extract", str(synthetic_spec_docx)])

    assert result.exit_code == 0
    spec = parser.parse(result.stdout)
    assert spec.specification == "3GPP TS 29.999"
    assert isinstance(spec.sections[0], ast.Message)
    assert all(section.source.page is None for section in spec.sections)
    assert result.stderr == ""


def test_extract_command_reports_source_warnings_even_when_the_pdf_is_rejected(
    tmp_path, synthetic_spec_docx, make_outlined_pdf
):
    # A mismatched PDF aborts the run — which is exactly when the warnings
    # collected while reading the docx are worth seeing.
    malformed = tmp_path / "heading-mismatch.docx"
    document = docx.Document(synthetic_spec_docx)
    for paragraph in document.paragraphs:
        if paragraph.text.startswith("6.1\t"):
            paragraph.text = "6.1\tExample-Requests (EXR) Command"
            break
    document.save(malformed)
    other_version = make_outlined_pdf("other.pdf", version="9.9.9")

    result = CliRunner().invoke(
        main, ["extract", str(malformed), "--pdf", str(other_version)]
    )

    assert result.exit_code == 1
    assert "warning: 6.1: heading name 'Example-Requests'" in result.stderr


def _first_message(spec: ast.Specification) -> ast.Message:
    section = spec.sections[0]
    assert isinstance(section, ast.Message)
    return section


def _corrections_dir(tmp_path):
    directory = tmp_path / "corrections"
    directory.mkdir()
    (directory / "TS29.999.py").write_text(
        "from seanchai.dad.corrections import Correction, definition\n"
        "CORRECTIONS = [Correction(target=definition('Example-Request'),"
        " field='application_id', expect=42, replace=16777308,"
        " reason='the header prints the wrong application')]\n"
    )
    return directory


def test_extract_command_applies_corrections_when_a_directory_is_given(
    tmp_path, synthetic_spec_docx
):
    result = CliRunner().invoke(
        main,
        [
            "extract",
            str(synthetic_spec_docx),
            "--corrections",
            str(_corrections_dir(tmp_path)),
        ],
    )

    assert result.exit_code == 0
    spec = parser.parse(result.stdout)
    assert _first_message(spec).application_id == 16777308
    assert "corrected: definition 'Example-Request' application_id" in result.stderr


def test_correct_command_reads_a_raw_dad_file(tmp_path, synthetic_spec_docx):
    from seanchai.extractor import tgpp_docx

    raw = tmp_path / "raw.dad"
    raw.write_text(formatter.format_spec(tgpp_docx.extract(synthetic_spec_docx)))
    corrected = tmp_path / "corrected.dad"

    result = CliRunner().invoke(
        main,
        [
            "correct",
            str(raw),
            "--corrections",
            str(_corrections_dir(tmp_path)),
            "-o",
            str(corrected),
        ],
    )

    assert result.exit_code == 0
    corrected_spec = parser.parse(corrected.read_text())
    assert _first_message(corrected_spec).application_id == 16777308


def test_correct_command_refuses_to_overwrite_its_input(tmp_path, synthetic_spec_docx):
    # Correcting in place would produce a file whose corrections can never be
    # re-applied or reviewed against the raw output.
    from seanchai.extractor import tgpp_docx

    raw = tmp_path / "raw.dad"
    raw.write_text(formatter.format_spec(tgpp_docx.extract(synthetic_spec_docx)))

    result = CliRunner().invoke(
        main,
        [
            "correct",
            str(raw),
            "--corrections",
            str(_corrections_dir(tmp_path)),
            "-o",
            str(raw),
        ],
    )

    assert result.exit_code == 1
    assert "refusing to correct a file in place" in result.stderr


def test_extract_command_rejects_a_missing_input_file():
    result = CliRunner().invoke(main, ["extract", "missing.docx"])

    assert result.exit_code == 2
    assert "File 'missing.docx' does not exist" in result.stderr
