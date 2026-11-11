"""The `seanchai` command: its exit statuses and error reporting, and what each
command does with the files it is given."""

import sys
from pathlib import Path

import click
import docx
import pytest
import seanchai_corpus
from click.testing import CliRunner
from conftest import _CORPUS_DIR, _corpus

import seanchai
from seanchai.cli import main
from seanchai.dad import ast, formatter, parser

_REPO = Path(__file__).parent.parent
_RFC6733 = _CORPUS_DIR / "rfc" / "rfc6733.dad"


def _invoke(*arguments: object):
    return CliRunner().invoke(main, [str(each) for each in arguments])


def _dad_with(*lines: str) -> str:
    header = "; Specification: 3GPP TS 29.329\n; Version: 18.0.0\n; Vendor-ID: 10415"
    return header + "\n\n" + "\n".join(lines) + "\n"


_CLASH = _dad_with(
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
# A file only a corpus can judge: it re-uses a name its origin lacks.
_BORROWING = _dad_with(
    "; Type: Reused AVPs",
    "; Section: 6.3",
    "; Table: 6.3/2",
    "; Columns: Name From",
    "No-Such-Avp TS29.229",
)


# --- exit status and error reporting ---------------------------------------------


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    """A working directory holding a file of each kind the commands refuse."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bad.dad").write_text("not a dad file\n", "utf-8")
    (tmp_path / "binary.dad").write_bytes(b"\xff\xfe\x00")
    (tmp_path / "unformatted.dad").write_text(_RFC6733.read_text("utf-8") + "\n\n")
    (tmp_path / "clash.dad").write_text(_CLASH, "utf-8")
    for directory in ("empty", "specifications", "corrections", "rawonly"):
        (tmp_path / directory).mkdir()
    (tmp_path / "rawonly" / "rfc6733.raw.dad").write_text("", "utf-8")
    (tmp_path / "dictionary").mkdir()
    (tmp_path / "dictionary" / "dictionary.xml").write_text(
        '<?xml version="1.0"?><dictionary><base name="base">'
        '<avp name="Renamed" code="263"><type type-name="UTF8String"/></avp>'
        "</base></dictionary>",
        "utf-8",
    )
    return tmp_path


_MOVED = ["download", "regenerate", "extract", "extract-rfc", "correct", "crosscheck"]

# (arguments, exit status, the stream the phrase is on, the phrase). Status 2 is
# a usage error, 1 an error or a finding that fails the run.
_OUTCOMES = [
    # Usage errors.
    ([], 2, "err", "Commands:"),
    (["corpus"], 2, "err", "Commands:"),
    (["no-such-command"], 2, "err", "error: No such command 'no-such-command'"),
    *(([name], 2, "err", f"error: No such command '{name}'") for name in _MOVED),
    (["corpus", "no-such-command"], 2, "err", "error: No such command"),
    (["--no-such-option"], 2, "err", "error: No such option '--no-such-option'"),
    (["format"], 2, "err", "error: Missing argument 'SOURCES...'"),
    (["lint", "/no/such/file.dad"], 2, "err", "does not exist"),
    (["lint", "--no-corpus", "--corpus", ".", "clash.dad"], 2, "err", "--no-corpus"),
    (["lint", "--corrections", "missing", "clash.dad"], 2, "err", "does not exist"),
    (["corpus", "correct"], 2, "err", "error: Missing argument 'SOURCE'"),
    (["corpus", "download", "--spec", "TS29.272"], 2, "err", "go together"),
    (["corpus", "download", "--version", "18.6.0"], 2, "err", "go together"),
    (["corpus", "download", "--only", "pdfs"], 2, "err", "'pdfs' is not one of"),
    (
        ["corpus", "download", "--only", "rfc", "--spec", "TS29.272", "--version", "1"],
        2,
        "err",
        "--only and --spec exclude each other",
    ),
    (["export"], 2, "err", "error: Missing option '-o'"),
    (["export", "-o", "out", "--include-pdfs"], 2, "err", "needs --specifications"),
    (["show"], 2, "err", "error: Missing argument"),
    (["show", "1:x"], 2, "err", "an identity is VENDOR:CODE"),
    (["show", "Session-Id", "--version", "1"], 2, "err", "--version needs --document"),
    (["commands", "--application", "cx"], 2, "err", "is not a valid integer"),
    (["dictionary"], 2, "err", "error: Missing option '-o'"),
    # Errors, which name the file or the download that would fix them.
    (["lint", "bad.dad"], 1, "err", "error: bad.dad: "),
    (["lint", "binary.dad"], 1, "err", "error: binary.dad: "),
    (["format", "bad.dad"], 1, "err", "error: bad.dad: "),
    (
        ["corpus", "correct", "bad.dad", "--corrections", "corrections"],
        1,
        "err",
        "error: bad.dad: ",
    ),
    (["corpus", "extract", "bad.dad"], 1, "err", "error: extracting"),
    (["lint", "empty"], 1, "err", "holds no .dad files"),
    (["lint", "--raw", "empty"], 1, "err", "holds no .dad files"),
    (["format", "empty"], 1, "err", "holds no .dad files"),
    (["lint", "--no-corpus", "rawonly"], 1, "err", "--raw reads its raw files"),
    (["show", "no-such-avp"], 1, "err", "error: no AVP no-such-avp"),
    (["commands", "--application", "99"], 1, "err", "error: no application 99"),
    (["export", "--corpus", "empty", "-o", "out"], 1, "err", "no documents"),
    (
        ["export", "-o", "out", "--include-pdfs", "--specifications", "absent"],
        1,
        "err",
        "run `seanchai corpus download --only 3gpp`",
    ),
    (
        ["export", "-o", "out", "--include-pdfs", "--specifications", "specifications"],
        1,
        "err",
        "run `seanchai corpus download --only 3gpp`",
    ),
    (
        ["export", "-o", "out", "--specifications", "absent"],
        1,
        "err",
        "run `seanchai corpus download --only rfc`",
    ),
    (
        ["export", "-o", "out", "--wireshark", "absent"],
        1,
        "err",
        "run `seanchai corpus download --only wireshark`",
    ),
    (
        ["corpus", "regenerate"],
        1,
        "err",
        "does not exist: run `seanchai corpus download`",
    ),
    (
        ["corpus", "regenerate", "--manifest", "absent/manifest.json"],
        1,
        "err",
        "does not exist: run `seanchai corpus download`",
    ),
    (
        ["corpus", "crosscheck"],
        1,
        "err",
        "run `seanchai corpus download --only wireshark`",
    ),
    # Findings that fail the run, and reports that do not.
    (["format", "--check", "unformatted.dad"], 1, "out", "+++ unformatted.dad"),
    (["lint", "--no-corpus", "clash.dad"], 1, "out", "error[duplicate-identity]"),
    (
        ["corpus", "crosscheck", "--wireshark", "dictionary", _RFC6733],
        0,
        "out",
        "Session-Id",
    ),
    (["--version"], 0, "out", seanchai.__version__),
]


@pytest.mark.parametrize(
    ("arguments", "status", "stream", "phrase"),
    _OUTCOMES,
    ids=[" ".join(map(str, row[0])) or "bare" for row in _OUTCOMES],
)
def test_each_outcome_has_its_exit_status_and_says_why(
    workspace, arguments, status, stream, phrase
):
    result = _invoke(*arguments)

    assert result.exit_code == status, result.output
    assert phrase in (result.stdout if stream == "out" else result.stderr)
    assert "Traceback" not in result.output
    if status == 1 and stream == "err":
        assert result.stderr.startswith("error: ") or "\nerror: " in result.stderr
        assert not result.stdout
    if status == 2 and phrase != "Commands:":
        assert click.unstyle(result.stderr).startswith("Usage: ")
        assert "\nerror: " in result.stderr
    if status:
        assert not (workspace / "out").exists()


def test_the_commands_are_the_documented_ones():
    """The consumer commands at the top, the maintainers' under `corpus`."""
    corpus = main.commands["corpus"]
    assert isinstance(corpus, click.Group)

    assert set(main.commands) == {
        "show",
        "commands",
        "dictionary",
        "export",
        "lint",
        "format",
        "corpus",
    }
    assert set(corpus.commands) == set(_MOVED)


def test_every_command_and_option_says_what_it_is_for():
    def described(group: click.Group, prefix: str = ""):
        for name, command in group.commands.items():
            yield f"{prefix}{name}", command.help
            for parameter in command.params:
                if isinstance(parameter, click.Option):
                    yield f"{prefix}{name} {parameter.opts[0]}", parameter.help
            if isinstance(command, click.Group):
                yield from described(command, f"{prefix}{name} ")

    assert not [name for name, text in described(main) if not (text or "").strip()]


# --- extract and correct ---------------------------------------------------------


def test_extract_reads_a_docx_and_attaches_the_pdfs_pages(
    tmp_path, synthetic_spec_docx, outlined_pdf
):
    output = tmp_path / "result.dad"

    result = _invoke(
        "corpus",
        "extract",
        synthetic_spec_docx,
        "--pdf",
        outlined_pdf,
        "--link",
        "https://example.com/spec.pdf",
        "--output",
        output,
    )

    assert result.exit_code == 0, result.output
    spec = parser.parse(output.read_text())
    assert spec.specification == "3GPP TS 29.999"
    assert str(spec.link) == "https://example.com/spec.pdf"
    assert [section.source.page for section in spec.sections] == [2, 3, 3, 4, 5, 6]
    assert "warning:" not in result.stderr


def test_extract_reports_the_docx_s_warnings_even_when_the_pdf_is_refused(
    tmp_path, synthetic_spec_docx, make_outlined_pdf
):
    """The run aborts on a PDF of another version, which is when the warnings
    collected while reading the docx are worth seeing."""
    malformed = tmp_path / "heading-mismatch.docx"
    document = docx.Document(synthetic_spec_docx)
    for paragraph in document.paragraphs:
        if paragraph.text.startswith("6.1\t"):
            paragraph.text = "6.1\tExample-Requests (EXR) Command"
            break
    document.save(malformed)

    result = _invoke(
        "corpus", "extract", malformed, "--pdf", make_outlined_pdf("o.pdf", version="9")
    )

    assert result.exit_code == 1
    assert "warning: 6.1: heading name 'Example-Requests'" in result.stderr


def _corrections(tmp_path: Path, module: str, text: str) -> Path:
    directory = tmp_path / "corrections"
    directory.mkdir(exist_ok=True)
    (directory / module).write_text(text, "utf-8")
    return directory


def test_a_corrections_module_is_optional_to_extract_and_required_to_correct(
    tmp_path, synthetic_spec_docx
):
    """A corpus run passes one directory for every document, and most have no
    module; asking to correct one that has none is an error."""
    empty = tmp_path / "empty"
    empty.mkdir()

    extracted = _invoke(
        "corpus", "extract", synthetic_spec_docx, "--corrections", empty
    )
    assert extracted.exit_code == 0, extracted.output
    raw = tmp_path / "raw.dad"
    raw.write_text(extracted.stdout, "utf-8")

    corrected = _invoke("corpus", "correct", raw, "--corrections", empty)
    assert corrected.exit_code == 1
    assert "error: no corrections module for '3GPP TS 29.999'" in corrected.stderr


def test_correct_marks_the_lines_it_changed_and_keeps_the_raw_comments(tmp_path):
    raw = tmp_path / "raw.dad"
    raw.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: Example",
            "; Section: 6.3.1",
            "Example ::= < AVP header: 700 10415 >",
            # TS 32.299's struck members are commented out in its raw file.
            ";;      [ Struck ] ; strikethrough",
            "        [ Kept ]",
            "",
            "",
            ";; end of file",
        )
    )
    directory = _corrections(
        tmp_path,
        "TS29.329.py",
        "from seanchai.dad.corrections import Correction, definition\n"
        "CORRECTIONS = [Correction(id='example-code', target=definition('Example'),"
        " field='code', expect=700, replace=701,"
        " reason='clause 6.3.1 misprints the code')]\n",
    )
    output = tmp_path / "corrected.dad"

    refused = _invoke("corpus", "correct", raw, "--corrections", directory, "-o", raw)
    result = _invoke("corpus", "correct", raw, "--corrections", directory, "-o", output)

    assert refused.exit_code == 1
    assert "refusing to correct a file in place" in refused.stderr
    assert result.exit_code == 0, result.output
    text = output.read_text()
    # The note names the declaration; the reason lives there, the old value in
    # the raw file.
    assert text.endswith(
        "Example ::= < AVP header: 701 10415 > ;; corrected:"
        " (TS29.329.py#example-code)\n"
        ";;      [ Struck ] ; strikethrough\n"
        "        [ Kept ]\n\n\n;; end of file\n"
    )
    (grouped,) = parser.parse(text).sections
    assert isinstance(grouped, ast.GroupedAvp)
    assert grouped.code == 701


# --- lint ---------------------------------------------------------------------


def test_lint_fails_on_errors_and_reports_notes_without_failing(tmp_path):
    clean = tmp_path / "clean.dad"
    clean.write_text(
        _dad_with(
            "; Type: Grouped AVP",
            "; Name: Only",
            "; Section: 6.3.1",
            "Only ::= < AVP header: 700 10415 >",
        )
    )
    noted = tmp_path / "note.dad"
    noted.write_text(
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
    clash = tmp_path / "clash.dad"
    clash.write_text(_CLASH)

    def lint(*arguments):
        return _invoke("lint", "--no-corpus", *arguments)

    assert (lint(clean).exit_code, lint(clean).output) == (0, "")
    assert lint(noted).exit_code == 0
    assert "local-and-reused" in lint(noted).output
    assert lint("--no-notes", noted).output == ""
    full = lint(clash)
    assert full.exit_code == 1
    assert full.output.splitlines()[-1] == "found 1 error in 1 file"
    # One line per finding and no summary, for a parser to read.
    concise = lint("--output-format", "concise", clash)
    assert concise.exit_code == 1
    (line,) = concise.output.splitlines()
    assert line.startswith(f"{clash}: error: [duplicate-identity]")


_V2X = "V2X-Subscription-Data's body, against TS29.272's definition"


def _lint_v2x(*options, corrections=_REPO / "edits" / "corrections", raw=False):
    """TS 29.388 against the committed corpus, whose module accepts clause
    6.3.2's V4 body for V2X-Subscription-Data, its one cross-file note."""
    source = (
        _CORPUS_DIR / "raw/3gpp/rel-19/29388-j10.raw.dad"
        if raw
        else _CORPUS_DIR / "3gpp/rel-19/29388-j10.dad"
    )
    return _invoke(
        "lint", "--corpus", _CORPUS_DIR, "--corrections", corrections, *options, source
    )


def test_an_accepted_finding_is_counted_apart_and_a_stale_acceptance_fails(tmp_path):
    hidden = _lint_v2x()
    shown = _lint_v2x("--show-accepted")
    raw = _lint_v2x("--output-format", "concise", raw=True)
    (tmp_path / "TS29.388.py").write_text(
        "from seanchai.dad.corrections import Accept, definition\n"
        "CORRECTIONS = [Accept(id='v2x-body', rule='reused-body-differs',"
        " target=definition('V2X-Subscription-Data'), expect='an older message',"
        " reason='clause 6.3.2')]\n"
    )
    stale = _lint_v2x("--output-format", "concise", corrections=tmp_path)

    assert (hidden.exit_code, hidden.output) == (0, "found 1 accepted in 1 file\n")
    (line,) = [line for line in shown.output.splitlines() if _V2X in line]
    assert line.startswith("  accepted[reused-body-differs]")
    assert line.endswith("(TS29.388.py#v2x-subscription-data-v4-body)")
    # A raw file is linted without acceptances.
    assert f"note: [reused-body-differs] {_V2X}" in raw.output
    assert stale.exit_code == 1
    assert "error: [stale-acceptance] TS29.388.py#v2x-body accepts" in stale.output


@pytest.mark.parametrize(
    ("setup", "runs"),
    [("plain", False), ("symlinked-corpus", False), ("named", True)],
)
def test_lint_executes_a_corrections_module_only_when_asked(
    tmp_path, monkeypatch, setup, runs
):
    """A plain `lint` in a directory holding `edits/corrections/` runs none of
    it, even beside a symlink posing as the repository's corpus."""
    source = tmp_path / "borrowing.dad"
    source.write_text(_BORROWING)
    modules = tmp_path / "edits" / "corrections"
    modules.mkdir(parents=True)
    ran = tmp_path / "ran"
    (modules / "TS29.329.py").write_text(
        f"from pathlib import Path\nPath({str(ran)!r}).touch()\nCORRECTIONS = []\n"
    )
    monkeypatch.chdir(tmp_path)
    if setup == "symlinked-corpus":
        link = tmp_path / "packages/seanchai-corpus/src/seanchai_corpus/dad"
        link.parent.mkdir(parents=True)
        link.symlink_to(_CORPUS_DIR)

    result = _invoke(
        "lint", *(["--corrections", modules] if setup == "named" else []), source
    )

    # Linted in every case: the cited TS 29.229 is another version's.
    assert result.exit_code == 0, result.output
    assert "note[origin-not-in-corpus]" in result.output
    assert result.output.endswith("found 1 note in 1 file\n")
    assert ran.exists() == runs


def test_plain_lint_in_the_repository_reads_its_acceptances(monkeypatch):
    monkeypatch.chdir(_REPO)

    result = _invoke("lint", _CORPUS_DIR / "3gpp/rel-19/29388-j10.dad")

    assert (result.exit_code, result.output) == (0, "found 1 accepted in 1 file\n")


def test_lint_defaults_to_the_installed_corpus_and_lints_alone_without_it(
    tmp_path, monkeypatch
):
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "rfc6733.dad").write_bytes(_RFC6733.read_bytes())
    (installed / "clash.dad").write_text(_CLASH)
    monkeypatch.setattr(seanchai_corpus, "CORPUS_DIR", installed)
    source = tmp_path / "borrowing.dad"
    source.write_text(_BORROWING)

    defaulted = _invoke("lint", source)
    named = _invoke("lint", "--corpus", installed, source)
    alone = _invoke("lint", "--no-corpus", source)
    everything = _invoke("lint", "--output-format", "concise")

    assert defaulted.output == named.output != alone.output
    assert everything.exit_code == 1
    assert str(installed / "clash.dad") in everything.output

    monkeypatch.setitem(sys.modules, "seanchai_corpus", None)
    missing = _invoke("lint", source)
    assert (missing.exit_code, missing.output) == (alone.exit_code, alone.output)


def test_lint_reports_the_corpus_record_once_as_a_file_of_its_own(tmp_path):
    """An entry naming no hole fails the run however many files are linted, and
    an unreadable record is an error naming it."""
    corpus_dir = tmp_path / "dad"
    corpus_dir.mkdir()
    source = corpus_dir / "rfc6733.dad"
    source.write_bytes(_RFC6733.read_bytes())
    record = corpus_dir / "holes.toml"
    record.write_text(
        '[[hole]]\ndocument = "RFC6733"\nname = "Worked-Off"\n'
        'missing = ["definition"]\nreason = "clause 1"\n',
        encoding="utf-8",
    )
    arguments = ["lint", "--no-notes", "--output-format", "concise"]

    stale = _invoke(*arguments, "--corpus", corpus_dir, source, source)
    record.write_text("[[hole]]\n", encoding="utf-8")
    malformed = _invoke(*arguments, "--corpus", corpus_dir, source)

    assert stale.exit_code == 1
    assert stale.output.count("stale-hole-record") == 1
    assert stale.output.startswith(f"{record}: error: [stale-hole-record]")
    assert malformed.exit_code == 1
    assert str(record) in malformed.output


# --- format and the files a directory names ------------------------------------------


def test_every_committed_dad_file_is_a_format_fixed_point():
    """`format` keeps comments, so a committed file, corrected files and the
    notes citing their corrections included, is already what it writes."""
    paths = _corpus(raw=True) + _corpus(raw=False)

    result = _invoke("format", "--check", *paths)

    assert result.exit_code == 0, result.stdout
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


def test_format_checks_with_a_diff_and_rewrites_keeping_comments(tmp_path):
    source = tmp_path / "edited.dad"
    source.write_text(_HAND_EDITED)
    windows = tmp_path / "windows.dad"
    canonical = formatter.format_spec(parser.parse(_HAND_EDITED))
    windows.write_bytes(canonical.replace("\n", "\r\n").encode())

    checked = _invoke("format", "--check", source, windows)
    assert checked.exit_code == 1
    assert "-  [ X ] ;;see clause 1\n+        [ X ] ;; see clause 1\n" in checked.stdout
    assert source.read_text() == _HAND_EDITED

    rewritten = _invoke("format", source, windows)
    assert rewritten.exit_code == 0
    assert source.read_text() == _HAND_EDITED.replace(
        "  [ X ] ;;see clause 1", "        [ X ] ;; see clause 1"
    )
    assert windows.read_bytes() == canonical.encode()
    assert "reformatted 2 of 2 files" in rewritten.stderr


def test_format_writes_nothing_when_any_file_fails_to_parse(tmp_path):
    edited = tmp_path / "edited.dad"
    edited.write_text(_HAND_EDITED)
    broken = tmp_path / "broken.dad"
    broken.write_text("; Specification: X\n; Vendor-ID: ten\n")

    result = _invoke("format", edited, broken)

    assert result.exit_code == 1
    assert f"error: {broken}: line 2:" in result.stderr
    assert edited.read_text() == _HAND_EDITED


def test_a_directory_means_its_files_once_each_and_its_raw_mirror_on_request(
    tmp_path,
):
    root = tmp_path / "corpus"
    corrected = root / "rfc" / "rfc6733.dad"
    mirror = root / "raw" / "rfc" / "rfc6733.raw.dad"
    for path in (corrected, mirror):
        path.parent.mkdir(parents=True)
        path.write_text(_RFC6733.read_text("utf-8") + "\n\n", "utf-8")
    (root / "rfc" / "stray.raw.dad").write_text("nope\n", "utf-8")

    named_twice = _invoke("format", "--check", root, corrected)
    assert "would reformat 1 of 1 files" in named_twice.stderr
    assert _invoke("lint", "--no-corpus", root).exit_code == 0
    (root / "rfc" / "stray.raw.dad").unlink()

    assert "reformatted 1 of 1 files" in _invoke("format", root).stderr
    assert mirror.read_text("utf-8").endswith("\n\n")
    assert "reformatted 1 of 2 files" in _invoke("format", "--raw", root).stderr
    assert not mirror.read_text("utf-8").endswith("\n\n")

    (root / "raw" / "rfc" / "broken.raw.dad").write_text("nope\n", "utf-8")
    for arguments in (["--raw", root], [root / "raw"]):
        asked = _invoke("lint", "--no-corpus", *arguments)
        assert asked.exit_code == 1, arguments
        assert "broken.raw.dad" in asked.stderr


# --- download and regenerate -------------------------------------------------------


@pytest.mark.parametrize(
    ("only", "listed", "unlisted"),
    [
        ("rfc", "RFC 6733", ["3GPP specifications", "Wireshark"]),
        ("transcribed", "ETSI-ES283.034", ["RFC 6733"]),
    ],
)
def test_download_lists_the_sources_only_names(only, listed, unlisted):
    result = _invoke("corpus", "download", "--list", "--only", only)

    assert result.exit_code == 0, result.output
    assert listed in result.stdout
    assert not [each for each in unlisted if each in result.stdout]


def test_regenerate_names_the_source_a_partial_download_lacks(tmp_path):
    specifications = tmp_path / "specifications"
    specifications.mkdir()
    manifest = specifications / "manifest.json"
    manifest.write_text('{"artifacts": [], "sources": ["wireshark"]}')
    corpus = tmp_path / "corpus"
    (corpus / "rfc").mkdir(parents=True)
    (corpus / "rfc" / "rfc6733.dad").write_bytes(_RFC6733.read_bytes())
    options = []
    for option in ("sources", "corrections", "transcriptions"):
        (tmp_path / option).mkdir()
        options += [f"--{option}", tmp_path / option]

    result = _invoke(
        "corpus", "regenerate", "--manifest", manifest, "--corpus", corpus, *options
    )

    assert result.exit_code == 1
    assert "not-in-manifest" in result.stdout
    assert "holds no rfc: run `seanchai corpus download --only rfc`" in result.stderr
