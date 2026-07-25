from click.testing import CliRunner

from seanchai import main
from seanchai.dad import ast, parser


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


def test_extract_command_rejects_a_missing_input_file():
    result = CliRunner().invoke(main, ["extract", "missing.docx"])

    assert result.exit_code == 2
    assert "File 'missing.docx' does not exist" in result.stderr
