import docx
import pytest
from click.testing import CliRunner
from conftest import _corpus

from seanchai.cli import main
from seanchai.dad import ast, formatter, parser
from seanchai.extractor.errors import ExtractionError


@pytest.mark.parametrize("to_stdout", [False, True], ids=["file", "stdout"])
def test_extract_command_runs_docx_pdf_formatter_and_parser_end_to_end(
    tmp_path, synthetic_spec_docx, outlined_pdf, to_stdout
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
            *([] if to_stdout else ["--output", str(output_path)]),
        ],
    )

    assert result.exit_code == 0
    spec = parser.parse(result.stdout if to_stdout else output_path.read_text())
    assert spec.specification == "3GPP TS 29.999"
    assert str(spec.link) == "https://example.com/spec.pdf"
    assert len(spec.sections) == 5
    assert spec.sections[0].source.page == 2
    assert spec.sections[1].source.page == 3
    assert spec.sections[3].source.page == 4
    assert spec.sections[4].source.page == 5
    assert "warning:" not in result.stderr
    if to_stdout:
        assert result.stderr == ""
    else:
        assert f"wrote {output_path} (5 sections)" in result.stderr


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


def _corrections_dir(tmp_path):
    directory = tmp_path / "corrections"
    directory.mkdir()
    (directory / "TS29.999.py").write_text(
        "from seanchai.dad.corrections import Correction, definition\n"
        "CORRECTIONS = [Correction(id='application',"
        " target=definition('Example-Request'),"
        " field='application_id', expect=42, replace=16777308,"
        " reason='the header prints the wrong application')]\n"
    )
    return directory


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


@pytest.mark.parametrize("exception_class", [parser.DadParseError, ExtractionError])
def test_correct_command_reports_a_malformed_dad_as_an_error_not_a_traceback(
    tmp_path,
    exception_class,
):
    if exception_class is parser.DadParseError:
        broken = tmp_path / "broken.dad"
        broken.write_text(
            "; Specification: 3GPP TS 29.999\n"
            "; Version: not a version\n; Vendor-ID: 10415\n"
        )
        arguments = [
            "correct",
            str(broken),
            "--corrections",
            str(_corrections_dir(tmp_path)),
        ]
        message = "error: line 2:"
    else:
        broken = tmp_path / "not-really.docx"
        broken.write_bytes(b"this is not a Word document")
        arguments = ["extract", str(broken)]
        message = "error: extracting"
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert message in result.stderr


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


def _dad_with(*lines: str) -> str:
    header = "; Specification: 3GPP TS 29.329\n; Version: 18.0.0\n; Vendor-ID: 10415"
    return header + "\n\n" + "\n".join(lines) + "\n"


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

    assert result.exit_code == 1
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
        "        id='example-code',\n"
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
    # Only the declaration's module and id: the change and its reason live at
    # the declaration, and the old value in the raw file.
    assert note == "corrected: (TS29.329.py#example-code)"
    # Still a `.dad` file, and still exactly the canonical text plus the note.
    stripped = "\n".join(line.split(" ;; ")[0] for line in text.splitlines())
    assert formatter.format_spec(parser.parse(text)) == stripped + "\n"

    (grouped,) = parser.parse(text).sections
    assert isinstance(grouped, ast.GroupedAvp)
    assert grouped.code == 701


def test_every_committed_dad_file_is_a_format_fixed_point():
    """`format` keeps comments, so a committed file — corrected files and the
    notes citing their corrections included — is already what it writes."""
    paths = _corpus(raw=True) + _corpus(raw=False)

    result = CliRunner().invoke(main, ["format", "--check", *map(str, paths)])

    assert result.exit_code == 0, result.stdout
    assert result.stdout == ""
    assert f"would reformat 0 of {len(paths)} files" in result.stderr


_HAND_EDITED = """\
; Specification: X
; Vendor-ID: 10415


; Type: Grouped AVP
; Name: G
; Section: 1
;; why the rule is optional
G ::= < AVP header: 5 >
  [ X ] ;;see clause 1
"""


def test_format_command_rewrites_in_place_and_keeps_comments(tmp_path):
    source = tmp_path / "edited.dad"
    source.write_text(_HAND_EDITED)

    result = CliRunner().invoke(main, ["format", str(source)])

    assert result.exit_code == 0
    assert source.read_text() == _HAND_EDITED.replace(
        "  [ X ] ;;see clause 1", "        [ X ] ;; see clause 1"
    )
    assert "reformatted 1 of 1 files" in result.stderr


def test_format_check_reports_a_diff_and_leaves_the_file_alone(tmp_path):
    source = tmp_path / "edited.dad"
    source.write_text(_HAND_EDITED)

    result = CliRunner().invoke(main, ["format", "--check", str(source)])

    assert result.exit_code == 1
    assert "-  [ X ] ;;see clause 1\n+        [ X ] ;; see clause 1\n" in result.stdout
    assert source.read_text() == _HAND_EDITED


def test_format_command_rewrites_crlf_line_endings(tmp_path):
    source = tmp_path / "windows.dad"
    canonical = formatter.format_spec(parser.parse(_HAND_EDITED))
    source.write_bytes(canonical.replace("\n", "\r\n").encode())

    checked = CliRunner().invoke(main, ["format", "--check", str(source)])
    rewritten = CliRunner().invoke(main, ["format", str(source)])

    assert checked.exit_code == 1
    assert rewritten.exit_code == 0
    assert source.read_bytes() == canonical.encode()


def test_format_command_writes_nothing_when_any_file_fails_to_parse(tmp_path):
    edited = tmp_path / "edited.dad"
    edited.write_text(_HAND_EDITED)
    broken = tmp_path / "broken.dad"
    broken.write_text("; Specification: X\n; Vendor-ID: ten\n")

    result = CliRunner().invoke(main, ["format", str(edited), str(broken)])

    assert result.exit_code == 1
    assert f"error: {broken}: line 2:" in result.stderr
    assert edited.read_text() == _HAND_EDITED
