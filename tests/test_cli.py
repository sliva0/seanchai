import re
from pathlib import Path

import docx
from click.testing import CliRunner

from seanchai.cli import main
from seanchai.dad import ast, formatter, parser

_ROOT = Path(__file__).parent.parent


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


def test_correct_command_reports_a_malformed_dad_as_an_error_not_a_traceback(
    tmp_path,
):
    broken = tmp_path / "broken.dad"
    broken.write_text(
        "; Specification: 3GPP TS 29.999\n"
        "; Version: not a version\n; Vendor-ID: 10415\n"
    )

    result = CliRunner().invoke(
        main, ["correct", str(broken), "--corrections", str(_corrections_dir(tmp_path))]
    )

    assert result.exit_code == 1
    # A Click error handled by the CLI, not a library exception that escaped.
    assert isinstance(result.exception, SystemExit)
    assert "error: line 2:" in result.stderr


def test_correct_command_fails_when_the_specification_has_no_corrections_module(
    tmp_path, synthetic_spec_docx
):
    # Correction is what was asked for here, so a directory without this
    # specification's module must not produce a cheerful uncorrected file.
    from seanchai.extractor import tgpp_docx

    raw = tmp_path / "raw.dad"
    raw.write_text(formatter.format_spec(tgpp_docx.extract(synthetic_spec_docx)))
    empty = tmp_path / "empty"
    empty.mkdir()

    result = CliRunner().invoke(
        main, ["correct", str(raw), "--corrections", str(empty)]
    )

    assert result.exit_code == 1
    assert "error: no corrections module for '3GPP TS 29.999'" in result.stderr


def test_extract_command_tolerates_a_corrections_directory_without_this_spec(
    tmp_path, synthetic_spec_docx
):
    # The other side of the same choice: a corpus run passes one directory for
    # every specification, and most of them have no module.
    empty = tmp_path / "empty"
    empty.mkdir()

    result = CliRunner().invoke(
        main, ["extract", str(synthetic_spec_docx), "--corrections", str(empty)]
    )

    assert result.exit_code == 0
    assert parser.parse(result.stdout).specification == "3GPP TS 29.999"


def test_extract_command_reports_a_source_document_failure_as_an_error(tmp_path):
    not_a_docx = tmp_path / "not-really.docx"
    not_a_docx.write_bytes(b"this is not a Word document")

    result = CliRunner().invoke(main, ["extract", str(not_a_docx)])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "error: extracting" in result.stderr


def _dad_with(*lines: str) -> str:
    header = "; Specification: 3GPP TS 29.329\n; Version: 18.0.0\n; Vendor-ID: 10415"
    return header + "\n\n" + "\n".join(lines) + "\n"


def test_lint_command_reports_errors_and_exits_non_zero(tmp_path):
    source = tmp_path / "clash.dad"
    source.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: First",
            "; Section: 6.3.1",
            "First ::= < AVP header: 700 10415 >",
            "",
            "",
            "; Type: Grouped AVP",
            "; Name: Second",
            "; Section: 6.3.2",
            "Second ::= < AVP header: 700 10415 >",
        )
    )

    result = CliRunner().invoke(main, ["lint", str(source)])

    assert result.exit_code == 1
    assert "duplicate-identity" in result.output


def test_lint_command_is_quiet_and_succeeds_on_a_clean_file(tmp_path):
    source = tmp_path / "clean.dad"
    source.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: Only",
            "; Section: 6.3.1",
            "Only ::= < AVP header: 700 10415 >",
        )
    )

    result = CliRunner().invoke(main, ["lint", str(source)])

    assert result.exit_code == 0
    assert result.output == ""


def test_lint_notes_do_not_fail_the_run_and_can_be_silenced(tmp_path):
    source = tmp_path / "note.dad"
    source.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: Borrowed",
            "; Section: 6.3.1",
            "Borrowed ::= < AVP header: 700 10415 >",
            "",
            "",
            "; Type: Reused AVPs",
            "; Section: 6.3",
            "; Table: 6.3/2",
            "; Columns: Name From",
            "Borrowed TS29.212",
        )
    )

    reported = CliRunner().invoke(main, ["lint", str(source)])
    silenced = CliRunner().invoke(main, ["lint", "--no-notes", str(source)])

    assert reported.exit_code == 0
    assert "local-and-reused" in reported.output
    assert silenced.exit_code == 0
    assert silenced.output == ""


def test_lint_default_output_groups_findings_under_the_file_with_a_summary(tmp_path):
    source = tmp_path / "clash.dad"
    source.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: First",
            "; Section: 6.3.1",
            "First ::= < AVP header: 700 10415 >",
            "",
            "",
            "; Type: Grouped AVP",
            "; Name: Second",
            "; Section: 6.3.2",
            "Second ::= < AVP header: 700 10415 >",
        )
    )

    result = CliRunner().invoke(main, ["lint", str(source)])

    lines = result.output.splitlines()
    assert lines[0] == str(source)
    assert lines[1].startswith("  error[duplicate-identity]")
    assert lines[-1] == "found 1 error in 1 file"


def test_lint_concise_output_keeps_the_one_line_per_finding_shape(tmp_path):
    source = tmp_path / "clash.dad"
    source.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: First",
            "; Section: 6.3.1",
            "First ::= < AVP header: 700 10415 >",
            "",
            "",
            "; Type: Grouped AVP",
            "; Name: Second",
            "; Section: 6.3.2",
            "Second ::= < AVP header: 700 10415 >",
        )
    )

    result = CliRunner().invoke(
        main, ["lint", "--output-format", "concise", str(source)]
    )

    (line,) = result.output.splitlines()
    assert line.startswith(f"{source}: error: [duplicate-identity]")
    assert "found" not in result.output  # no summary line to trip a parser


def test_correct_command_marks_the_lines_it_changed(tmp_path):
    """A corrected file is the one anyone actually uses, so it has to say which
    of its values a human overrode and where to read why.

    Self-contained rather than reading the corpus: the committed corpus is
    already corrected, and `correct` takes raw input by design.
    """
    raw = tmp_path / "raw.dad"
    raw.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: Example",
            "; Section: 6.3.1",
            "Example ::= < AVP header: 700 10415 >",
        )
    )
    directory = tmp_path / "corrections"
    directory.mkdir()
    (directory / "TS29.329.py").write_text(
        "from seanchai.dad.corrections import Correction, definition\n"
        "CORRECTIONS = [\n"
        "    Correction(\n"
        "        target=definition('Example'),\n"
        "        field='code',\n"
        "        expect=700,\n"
        "        replace=701,\n"
        "        reason='clause 6.3.1 misprints the code',\n"
        "    )\n"
        "]\n"
    )
    output = tmp_path / "corrected.dad"

    result = CliRunner().invoke(
        main, ["correct", str(raw), "--corrections", str(directory), "-o", str(output)]
    )

    assert result.exit_code == 0
    text = output.read_text()
    # The note trails the corrected line itself.
    (noted,) = [line for line in text.splitlines() if ";;" in line]
    header, _, note = noted.partition(" ;; ")
    assert header == "Example ::= < AVP header: 701 10415 >"
    # Only the declaration's location: the change and its reason live at the
    # cited line, and the old value in the raw file.
    assert re.fullmatch(r"corrected: \(TS29\.329\.py:\d+\)", note)
    # Still a `.dad` file, and still exactly the canonical text plus the note.
    stripped = "\n".join(line.split(" ;; ")[0] for line in text.splitlines())
    assert formatter.format_spec(parser.parse(text)) == stripped + "\n"
