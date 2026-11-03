import subprocess
import sys
from pathlib import Path

import click
import docx
import pytest
from click.testing import CliRunner
from conftest import _CORPUS_DIR, _corpus

import seanchai
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

    result = CliRunner().invoke(main, ["lint", "--no-corpus", str(source)])

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

    reported = CliRunner().invoke(main, ["lint", "--no-corpus", str(source)])
    silenced = CliRunner().invoke(
        main, ["lint", "--no-corpus", "--no-notes", str(source)]
    )

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

    result = CliRunner().invoke(main, ["lint", "--no-corpus", str(source)])

    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[0] == str(source)
    assert lines[1].startswith("  error[duplicate-identity]")
    assert lines[-1] == "found 1 error in 1 file"


_REPO = Path(__file__).parent.parent
_V2X = "V2X-Subscription-Data's body, against TS29.272's definition"


def _lint_v2x(*options, corrections=_REPO / "edits" / "corrections", raw=False):
    """TS 29.388 against the committed corpus, whose module accepts clause
    6.3.2's V4 body for V2X-Subscription-Data, its one cross-file note."""
    source = (
        _CORPUS_DIR / "raw" / "3gpp" / "rel-18" / "29388-i10.raw.dad"
        if raw
        else _CORPUS_DIR / "3gpp" / "rel-18" / "29388-i10.dad"
    )
    return CliRunner().invoke(
        main,
        [
            "lint",
            "--corpus",
            str(_CORPUS_DIR),
            "--corrections",
            str(corrections),
            *options,
            str(source),
        ],
    )


def test_lint_counts_accepted_findings_apart_and_prints_them_on_request():
    hidden = _lint_v2x()
    shown = _lint_v2x("--show-accepted")

    assert hidden.exit_code == 0
    assert hidden.output == "found 1 accepted in 1 file\n"
    assert shown.exit_code == 0
    (line,) = [line for line in shown.output.splitlines() if _V2X in line]
    assert line.startswith("  accepted[reused-body-differs]")
    assert line.endswith("(TS29.388.py#v2x-subscription-data-v4-body)")


def test_lint_reports_the_corpus_record_once_as_a_file_of_its_own(tmp_path):
    """A corpus directory's record is part of what `--corpus` lints: an entry
    naming no hole fails the run, however many files are linted, and the record
    counts as no linted file."""
    corpus_dir = tmp_path / "dad"
    corpus_dir.mkdir()
    source = corpus_dir / "rfc6733.dad"
    source.write_bytes((_CORPUS_DIR / "rfc" / "rfc6733.dad").read_bytes())
    record = corpus_dir / "holes.toml"
    record.write_text(
        '[[hole]]\ndocument = "RFC6733"\nname = "Worked-Off"\n'
        'missing = ["definition"]\nreason = "clause 1"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        main,
        [
            "lint",
            "--no-notes",
            "--output-format",
            "concise",
            "--corpus",
            str(corpus_dir),
            str(source),
            str(source),
        ],
    )

    assert result.exit_code == 1
    assert result.output.count("stale-hole-record") == 1
    assert result.output.startswith(f"{record}: error: [stale-hole-record]")


def _borrowing(tmp_path):
    """A file only a corpus can judge: it re-uses a name its origin lacks."""
    source = tmp_path / "borrowing.dad"
    source.write_text(
        _dad_with(
            "; Type: Reused AVPs",
            "; Section: 6.3",
            "; Table: 6.3/2",
            "; Columns: Name From",
            "No-Such-Avp TS29.229",
        )
    )
    return source


def test_lint_without_a_corpus_uses_the_installed_one(tmp_path):
    source = _borrowing(tmp_path)

    defaulted = CliRunner().invoke(main, ["lint", str(source)])
    named = CliRunner().invoke(
        main, ["lint", "--corpus", str(_CORPUS_DIR), str(source)]
    )
    alone = CliRunner().invoke(main, ["lint", "--no-corpus", str(source)])

    assert defaulted.output == named.output
    assert defaulted.output != alone.output


def test_lint_without_the_package_lints_each_file_alone(tmp_path, monkeypatch):
    source = _borrowing(tmp_path)
    alone = CliRunner().invoke(main, ["lint", "--no-corpus", str(source)])

    monkeypatch.setitem(sys.modules, "seanchai_corpus", None)
    result = CliRunner().invoke(main, ["lint", str(source)])

    assert result.exit_code == alone.exit_code
    assert result.output == alone.output


def test_lint_refuses_a_corpus_and_no_corpus_together(tmp_path):
    source = _borrowing(tmp_path)

    result = CliRunner().invoke(
        main, ["lint", "--no-corpus", "--corpus", str(_CORPUS_DIR), str(source)]
    )

    assert result.exit_code != 0
    assert "--no-corpus" in result.output


def _untrusted_checkout(tmp_path, monkeypatch):
    """A working directory holding a corrections module for the linted file,
    which leaves a mark when it runs."""
    source = _borrowing(tmp_path)
    modules = tmp_path / "edits" / "corrections"
    modules.mkdir(parents=True)
    ran = tmp_path / "ran"
    (modules / "TS29.329.py").write_text(
        f"from pathlib import Path\nPath({str(ran)!r}).touch()\nCORRECTIONS = []\n"
    )
    monkeypatch.chdir(tmp_path)
    return source, modules, ran


def test_plain_lint_runs_no_module_from_the_working_directory(tmp_path, monkeypatch):
    source, _, ran = _untrusted_checkout(tmp_path, monkeypatch)

    CliRunner().invoke(main, ["lint", str(source)])

    assert not ran.exists()


def test_a_symlink_to_the_installed_corpus_is_not_the_repository(tmp_path, monkeypatch):
    source, _, ran = _untrusted_checkout(tmp_path, monkeypatch)
    link = tmp_path / "packages" / "seanchai-corpus" / "src" / "seanchai_corpus" / "dad"
    link.parent.mkdir(parents=True)
    link.symlink_to(_CORPUS_DIR)

    CliRunner().invoke(main, ["lint", str(source)])

    assert not ran.exists()


def test_lint_runs_the_module_a_named_directory_holds(tmp_path, monkeypatch):
    source, modules, ran = _untrusted_checkout(tmp_path, monkeypatch)

    CliRunner().invoke(main, ["lint", "--corrections", str(modules), str(source)])

    assert ran.exists()


def test_plain_lint_in_the_repository_reads_its_acceptances(monkeypatch):
    monkeypatch.chdir(_REPO)
    source = _CORPUS_DIR / "3gpp" / "rel-18" / "29388-i10.dad"

    result = CliRunner().invoke(main, ["lint", str(source)])

    assert result.exit_code == 0
    assert result.output == "found 1 accepted in 1 file\n"


def test_lint_reports_a_malformed_record_as_a_usage_error(tmp_path):
    corpus_dir = tmp_path / "dad"
    corpus_dir.mkdir()
    source = corpus_dir / "rfc6733.dad"
    source.write_bytes((_CORPUS_DIR / "rfc" / "rfc6733.dad").read_bytes())
    record = corpus_dir / "holes.toml"
    record.write_text("[[hole]]\n", encoding="utf-8")

    result = CliRunner().invoke(
        main, ["lint", "--corpus", str(corpus_dir), str(source)]
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, SystemExit)
    assert str(record) in result.output


def test_lint_reads_no_acceptances_for_a_raw_file():
    result = _lint_v2x("--output-format", "concise", raw=True)

    assert f"note: [reused-body-differs] {_V2X}" in result.output


def test_lint_fails_on_an_acceptance_that_matches_no_finding(tmp_path):
    (tmp_path / "TS29.388.py").write_text(
        "from seanchai.dad.corrections import Accept, definition\n"
        "CORRECTIONS = [Accept(id='v2x-body', rule='reused-body-differs',"
        " target=definition('V2X-Subscription-Data'), expect='an older message',"
        " reason='clause 6.3.2')]\n"
    )

    result = _lint_v2x("--output-format", "concise", corrections=tmp_path)

    assert result.exit_code == 1
    assert "error: [stale-acceptance] TS29.388.py#v2x-body accepts" in result.output


def test_lint_rejects_a_corrections_directory_given_that_does_not_exist(tmp_path):
    result = _lint_v2x(corrections=tmp_path / "missing")

    assert result.exit_code == 2
    assert "does not exist" in result.output


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
        main, ["lint", "--no-corpus", "--output-format", "concise", str(source)]
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


@pytest.mark.parametrize(
    "arguments",
    [["--spec", "TS29.272"], ["--version", "18.6.0"]],
    ids=["spec-only", "version-only"],
)
def test_download_takes_spec_and_version_together(tmp_path, arguments):
    result = CliRunner().invoke(main, ["download", "-o", str(tmp_path), *arguments])

    assert result.exit_code == 2
    assert "--spec and --version go together" in result.output
    assert not list(tmp_path.iterdir())


def test_correct_command_keeps_the_raw_files_commented_out_members(tmp_path):
    # TS 32.299's struck members are commented out in its raw file.
    raw = tmp_path / "raw.dad"
    raw.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: Example",
            "; Section: 6.3.1",
            "Example ::= < AVP header: 700 10415 >",
            ";;      [ Struck ] ; strikethrough",
            "        [ Kept ]",
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
    assert output.read_text().splitlines()[-2:] == [
        ";;      [ Struck ] ; strikethrough",
        "        [ Kept ]",
    ]


def test_correct_command_keeps_a_comment_block_ending_the_file(tmp_path):
    raw = tmp_path / "raw.dad"
    raw.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: Example",
            "; Section: 6.3.1",
            "Example ::= < AVP header: 700 10415 >",
            "",
            "",
            ";; end of file",
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

    assert result.exit_code == 0, result.output
    assert output.read_text().endswith(
        "Example ::= < AVP header: 701 10415 > ;; corrected:"
        " (TS29.329.py#example-code)\n\n\n;; end of file\n"
    )


def test_importing_the_cli_leaves_other_click_apps_alone():
    """Run apart, since this process has imported `seanchai.cli` already."""
    script = """
import click
from click.testing import CliRunner

before = (
    click.Context.formatter_class,
    click.ClickException.show,
    click.UsageError.show,
)
import seanchai.cli

assert before == (
    click.Context.formatter_class,
    click.ClickException.show,
    click.UsageError.show,
)


@click.command()
def other():
    "Help."
    raise click.ClickException("broken")


@click.command()
def plain():
    "Help."


context = click.Context(plain)
assert type(context.make_formatter()) is click.HelpFormatter
assert context.command.context_class is click.Context
result = CliRunner().invoke(other, color=True)
assert result.exit_code == 1
assert result.stderr == "Error: broken\\n", result.stderr
help_text = CliRunner().invoke(plain, ["--help"], color=True).output
assert help_text.startswith("Usage: "), help_text
"""
    run = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr


def test_the_cli_renders_its_own_failures_and_help():
    runner = CliRunner()

    failed = runner.invoke(main, ["lint", "/nonexistent.dad"], color=True)
    assert failed.exit_code == 2
    assert "\x1b[" in failed.stderr
    assert "for help." in failed.stderr
    assert "\nerror: " in click.unstyle(failed.stderr)
    assert click.unstyle(failed.stderr).startswith("Usage: main lint")

    assert runner.invoke(main, ["format", "--help"], color=True).output.startswith(
        click.style("Usage", fg="green", bold=True)
    )
    assert main.commands["format"].context_class is not click.Context


def test_an_exit_keeps_its_status_and_a_clean_run_exits_zero(tmp_path):
    source = _CORPUS_DIR / "rfc" / "rfc6733.dad"
    copied = tmp_path / "file.dad"
    copied.write_text(source.read_text("utf-8") + "\n\n", "utf-8")

    runner = CliRunner()
    assert runner.invoke(main, ["format", "--check", str(copied)]).exit_code == 1
    assert runner.invoke(main, ["format", str(copied)]).exit_code == 0


def test_version_names_the_installed_library():
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert seanchai.__version__ in result.output
