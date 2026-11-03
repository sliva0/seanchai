"""The `seanchai` command.

Every library operation this drives promises exactly one exception type —
`DadParseError`, `ExtractionError`, `CorrectionError`, `DownloadError` — so
the whole of the CLI's error handling is `reported()`: turn those four into
the styled `error: ...` line, and let anything else through as a traceback,
because anything else is a bug in this program rather than a problem with the
user's document.
"""

import contextlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    # The `dad` modules are imported only by the commands that use them.
    from .dad.formatter import Comments

# The two declared edit layers live side by side; only the source
# declarations (input patches and quirks) are discovered automatically by
# every command, because loading a correction module executes Python from
# that directory. `regenerate` and `lint` default to the repository's own.
_DEFAULT_SOURCES = Path("edits") / "sources"
_DEFAULT_CORRECTIONS = Path("edits") / "corrections"
_DEFAULT_TRANSCRIPTIONS = Path("edits") / "transcriptions"
# What `regenerate` rebuilds in place: the repository's copy, the package's data.
_DEFAULT_CORPUS = Path("packages/seanchai-corpus/src/seanchai_corpus/dad")
# Wireshark's deliberate renames, which `crosscheck` accepts as agreement.
_DEFAULT_ALIASES = Path("integrations") / "wireshark" / "aliases.toml"


class _HelpFormatter(click.HelpFormatter):
    """Cargo-style help: `Usage:` and section headings in bold green.

    `term_len` strips ANSI codes before measuring, so the styled prefix does
    not disturb wrapping or alignment, and `click.echo` strips the codes
    themselves whenever output is not a terminal.
    """

    def write_usage(self, prog: str, args: str = "", prefix: str | None = None) -> None:
        if prefix is None:
            prefix = click.style("Usage", fg="green", bold=True) + ": "
        super().write_usage(prog, args, prefix=prefix)

    def write_heading(self, heading: str) -> None:
        super().write_heading(click.style(heading, fg="green", bold=True))


def _show_error(error: click.ClickException) -> None:
    """Click's message, with a cargo-style `error:` prefix."""
    prefix = click.style("error", fg="red", bold=True)
    click.echo(f"{prefix}: {error.format_message()}", err=True)


def _show_usage_error(error: click.UsageError) -> None:
    """Click's usage block and help hint, then the message, restyled."""
    if error.ctx is not None:
        hint = ""
        if error.ctx.command.get_help_option(error.ctx) is not None:
            option = max(error.ctx.command.get_help_option_names(error.ctx), key=len)
            hint = click.style(
                f"Try '{error.ctx.command_path} {option}' for help.", dim=True
            )
            hint = f"{hint}\n"
        click.echo(f"{error.ctx.get_usage()}\n{hint}", err=True)
    _show_error(error)


class _Context(click.Context):
    formatter_class = _HelpFormatter


class _Command(click.Command):
    context_class = _Context


class _Group(click.Group):
    """The `seanchai` group: its help through `_HelpFormatter`, its failures
    through `_show_error`, and nobody else's.

    Click renders a failure with the exception's own `show`, offering no hook
    for it, and only in standalone mode. So this runs Click's non-standalone
    `main`, which raises the failure instead, and does what standalone mode
    would around it.
    """

    context_class = _Context
    command_class = _Command

    def main(self, *args: Any, standalone_mode: bool = True, **extra: Any) -> Any:
        if not standalone_mode:
            return super().main(*args, standalone_mode=False, **extra)
        try:
            # Non-standalone `main` returns an `Exit`'s code as its value, and
            # no command here returns anything else.
            status = super().main(*args, standalone_mode=False, **extra)
        except click.UsageError as error:
            _show_usage_error(error)
            sys.exit(error.exit_code)
        except click.ClickException as error:
            _show_error(error)
            sys.exit(error.exit_code)
        except click.Abort:
            click.echo("Aborted!", err=True)
            sys.exit(1)
        sys.exit(status if isinstance(status, int) else 0)


@contextlib.contextmanager
def reported() -> Iterator[None]:
    """Present a library failure as a CLI error, not as a traceback."""
    from .corpus import CorpusError
    from .dad.corrections import CorrectionError
    from .dad.parser import DadParseError
    from .downloader import DownloadError
    from .extractor.errors import ExtractionError

    try:
        yield
    except (
        CorpusError,
        DadParseError,
        ExtractionError,
        CorrectionError,
        DownloadError,
    ) as error:
        raise click.ClickException(str(error)) from None


@click.group(cls=_Group)
def main() -> None:
    """Seanchaí: Diameter specifications as reviewable `.dad` files."""


@main.command("export")
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to write, replaced whole. It must be absent, empty or a"
    " previous export.",
)
@click.option(
    "--corpus",
    "corpus_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory or file to export instead of the installed seanchai-corpus"
    " package. Repeatable.",
)
@click.option(
    "--dictionary",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Wireshark's Diameter dictionary, for its AVP names in the search index:"
    " specifications/wireshark after `seanchai download`. Without it the names"
    " are left out.",
)
@click.option(
    "--corrections",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Read correction reasons and acceptances from the modules in this"
    " directory (<SpecRef>.py) instead of the corpus's corrections.json. Loading"
    " one executes Python from that directory, as `correct` does.",
)
@click.option(
    "--specifications",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="A `seanchai download` directory. RFC texts found there are copied into"
    " the export; --include-pdfs reads it too.",
)
@click.option(
    "--include-pdfs",
    is_flag=True,
    help="Self-hosted mode: copy every source PDF into the export. Needs"
    " --specifications. ETSI's renderings are not for public redistribution.",
)
def export_command(
    output: Path,
    corpus_paths: tuple[Path, ...],
    dictionary: Path | None,
    corrections: Path | None,
    specifications: Path | None,
    include_pdfs: bool,
) -> None:
    """Export the corpus as JSON for the static site.

    Writes index.json, search.json, schema.json and, per document,
    documents/<id>.json and documents/<id>.raw.json (docs/website.md). The same
    corpus gives the same bytes.

    \b
    Public site, no source PDFs:
        seanchai export -o site/data
    Self-hosted, source PDFs beside it:
        seanchai export -o site/data \\
            --include-pdfs --specifications specifications

    The export is built beside the output directory and replaces it whole, once
    it has succeeded: files of an earlier export do not linger, and a failed
    run leaves the earlier one as it was. A directory holding anything else is
    refused, and so is a corpus with no documents.

    Correction reasons come from the corpus's corrections.json, which needs no
    checkout. --corrections reads edits/corrections while working inside one,
    before `seanchai regenerate` has recorded them.
    """
    from .corpus import Corpus
    from .export import export_corpus
    from .model import ModelError

    with reported():
        try:
            books = Corpus.load(corpus_paths) if corpus_paths else Corpus.installed()
            export_corpus(
                books,
                output,
                dictionary=dictionary,
                corrections_directory=corrections,
                specifications=specifications,
                include_pdfs=include_pdfs,
            )
        except (ModelError, OSError) as error:
            raise click.ClickException(str(error)) from None


@main.command()
@click.argument("docx", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--pdf",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Matching ETSI PDF rendering; attaches `; Page:` directives"
    " from its bookmark outline. Must be the exact same version"
    " as the docx.",
)
@click.option("--link", help="ETSI PDF URL for the file's `; Link:` header.")
@click.option(
    "--sources",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with source-declaration TOML files — input patches and"
    " quirks (default: ./edits/sources if present).",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with per-spec correction modules (<SpecRef>.py)."
    " Loading one executes Python from that directory, so it is never"
    " discovered automatically.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output .dad path (default: stdout).",
)
def extract(
    docx: Path,
    pdf: Path | None,
    link: str | None,
    sources: Path | None,
    corrections: Path | None,
    output: Path | None,
) -> None:
    """Extract a canonical `.dad` file from a 3GPP specification docx."""
    from .extractor import tgpp_docx

    if sources is None and _DEFAULT_SOURCES.is_dir():
        sources = _DEFAULT_SOURCES
    warnings: list[str] = []
    with reported():
        try:
            spec, comments = tgpp_docx.extract_with_comments(
                docx, link=link, warnings=warnings, sources_dir=sources
            )
            if pdf is not None:
                spec = tgpp_docx.attach_pages(spec, pdf, warnings=warnings)
        finally:
            # Report what the source document did even when a later stage fails —
            # a mismatched PDF aborts the run, and that is exactly when the
            # extraction warnings are worth reading.
            for warning in warnings:
                prefix = click.style("warning", fg="yellow")
                click.echo(f"{prefix}: {warning}", err=True)
        if corrections is not None:
            # A corpus run may pass a directory holding modules for only some
            # of its specifications, so a spec without one is not an error.
            spec, comments = _correct(spec, comments, corrections, required=False)
    _write(spec, output, comments)


@main.command(name="extract-rfc")
@click.argument("text", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--link", help="Canonical URL for the file's `; Link:` header.")
@click.option(
    "--sources",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with source-declaration TOML files — input patches and"
    " quirks (default: ./edits/sources if present).",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with per-spec correction modules (<SpecRef>.py)."
    " Loading one executes Python from that directory, so it is never"
    " discovered automatically.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output .dad path (default: stdout).",
)
def extract_rfc(
    text: Path,
    link: str | None,
    sources: Path | None,
    corrections: Path | None,
    output: Path | None,
) -> None:
    """Extract a canonical `.dad` file from an RFC's plain-text rendering.

    `; Page:` directives come from the text's own printed page numbers — the
    text is the RFC's sole rendering, so there is no separate PDF step.
    """
    from .extractor import rfc_text

    if sources is None and _DEFAULT_SOURCES.is_dir():
        sources = _DEFAULT_SOURCES
    warnings: list[str] = []
    with reported():
        try:
            spec = rfc_text.extract(
                text, link=link, warnings=warnings, sources_dir=sources
            )
        finally:
            for warning in warnings:
                prefix = click.style("warning", fg="yellow")
                click.echo(f"{prefix}: {warning}", err=True)
        notes = None
        if corrections is not None:
            from .dad import formatter

            spec, notes = _correct(
                spec, formatter.Comments(), corrections, required=False
            )
    _write(spec, output, notes)


@main.command()
@click.option(
    "--manifest",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("specifications") / "manifest.json",
    show_default=True,
    help="The downloader's manifest; its files are the sources.",
)
@click.option(
    "--corpus",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=_DEFAULT_CORPUS,
    show_default=True,
    help="The committed corpus: decides which specifications to rebuild."
    " Defaulted for the repository's own workspace copy, never an installed one.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where to write (default: the corpus itself).",
)
@click.option(
    "--sources",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=_DEFAULT_SOURCES,
    show_default=True,
    help="Directory with source-declaration TOML files.",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=_DEFAULT_CORRECTIONS,
    show_default=True,
    help="Directory with per-spec correction modules. Defaulted here, unlike"
    " extract's and correct's, because this one exists to rebuild the repository's"
    " own corpus from its own edit layers.",
)
@click.option(
    "--transcriptions",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=_DEFAULT_TRANSCRIPTIONS,
    show_default=True,
    help="Directory with hand transcriptions of documents no extractor reads.",
)
@click.option(
    "--add",
    multiple=True,
    metavar="SPECREF",
    help="Also build a specification the corpus does not hold yet"
    " (e.g. TS29.273). Repeatable.",
)
@click.option(
    "--spec",
    "only",
    multiple=True,
    metavar="SPECREF",
    help="Rebuild only this specification instead of the whole corpus. Repeatable.",
)
@click.option(
    "--expand-ranges",
    is_flag=True,
    help="Widen, in --sources and --corrections, every declaration range a"
    " cleanly rebuilt specification's version falls outside.",
)
def regenerate(
    manifest: Path,
    corpus: Path,
    output: Path | None,
    sources: Path,
    corrections: Path,
    transcriptions: Path,
    add: tuple[str, ...],
    only: tuple[str, ...],
    expand_ranges: bool,
) -> None:
    """Rebuild the committed corpus from the downloaded sources.

    Every specification the corpus holds is re-extracted, paged and corrected
    from the manifest's files and written back, raw mirror included. The
    manifest decides the version: a newer download replaces the committed
    pair, and the replacement is reported. A specification the extractor
    cannot read fails on its own and the run continues; the exit status is
    non-zero if anything failed.

    Beside the documents it rewrites `corrections.json`, the record of every
    correction's reason an installed corpus is read with, unless something
    failed.

    With --expand-ranges, a declaration whose advisory version range does not
    cover the version it just applied cleanly to has the range rewritten in
    its edit file, comments and layout kept; the widened ranges print under
    the specification.

    An older version fetched with `seanchai download --spec SPECREF
    --version VERSION` is extracted for diffing with `--manifest
    specifications/versions/SPECREF/VERSION/manifest.json --spec SPECREF -o
    SCRATCH`; without -o it would replace the committed pair.
    """
    from . import regenerate as library

    report = library.regenerate(
        manifest,
        corpus,
        output if output is not None else corpus,
        sources_dir=sources,
        corrections_dir=corrections,
        transcriptions_dir=transcriptions,
        add=add,
        only=only,
        report=_echo_outcome,
        expand_ranges=expand_ranges,
    )
    counts = {}
    for outcome in report.outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    click.echo(f"{len(report.outcomes)} specifications: {summary}", err=True)
    if report.failed:
        raise click.exceptions.Exit(1)


def _echo_outcome(outcome) -> None:
    from .regenerate import describe

    status, _, rest = describe(outcome).partition(" ")
    colour = {
        "unchanged": "green",
        "changed": "yellow",
        "new": "cyan",
        "replaced": "magenta",
        "not-converted": "yellow",
    }.get(status, "red")
    click.echo(f"{click.style(status, fg=colour)} {rest}")
    # The extractor's warnings, under the specification they belong to: they
    # are the document doing something unusual, and worth a glance on every
    # rebuild, not only the first.
    for warning in outcome.warnings:
        click.echo(click.style(f"    warning: {warning}", dim=True), err=True)
    for widened in outcome.expanded:
        click.echo(f"    expanded: {widened}")


@main.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--corrections",
    required=True,
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with per-spec correction modules (<SpecRef>.py)."
    " Loading one executes Python from that directory.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output .dad path (default: stdout).",
)
def correct(source: Path, corrections: Path, output: Path | None) -> None:
    """Apply a specification's corrections to a raw `.dad` file.

    Input is raw extractor output. Correcting a corrected file fails, by
    design: every `expect` would already hold its replacement, and that is
    indistinguishable from the specification having been fixed upstream.

    Unlike `extract --corrections`, this requires the specification's module to
    exist and to declare at least one correction: correction is what was asked
    for here, and a mistyped path that quietly produced an uncorrected file
    would be indistinguishable from success.
    """
    from .dad import parser

    if output is not None and output.resolve() == source.resolve():
        raise click.ClickException("refusing to correct a file in place")
    with reported():
        # Explicit encoding both ways: `.dad` files are UTF-8 wherever they were
        # written, and the platform default would otherwise decide whether a
        # spec title with a non-ASCII character survives the round trip.
        # The raw file's own comments — struck members commented out — move
        # with their lines.
        spec, comments = parser.parse_with_comments(source.read_text(encoding="utf-8"))
        corrected, notes = _correct(spec, comments, corrections, required=True)
    _write(corrected, output, notes)


def _correct(spec, comments: Comments, directory: Path, required: bool):
    """Returns the corrected tree, and `comments` moved with their lines
    beside the notes marking what was touched."""
    from .dad import corrections as corrections_module

    declared = corrections_module.in_release(
        corrections_module.load(directory, spec.specification, required=required),
        spec.version,
    )
    corrected, results, notes = corrections_module.apply_with_comments(
        spec, comments, declared
    )
    for result in results:
        edit = result.correction
        reason = click.style(f"({edit.reason})", dim=True)
        if isinstance(edit, corrections_module.Delete):
            verb = click.style("deleted", fg="red")
            click.echo(f"{verb}: {result.node} {reason}", err=True)
        elif isinstance(edit, corrections_module.Insert):
            verb = click.style("inserted", fg="green")
            click.echo(f"{verb}: {result.node} {reason}", err=True)
        elif isinstance(edit, corrections_module.Supply):
            verb = click.style("supplied", fg="green")
            click.echo(f"{verb}: {result.node} {reason}", err=True)
        else:
            verb = click.style("corrected", fg="green")
            click.echo(
                f"{verb}: {result.node} {edit.field}"
                f" {result.old!r} -> {result.new!r} {reason}",
                err=True,
            )
    return corrected, notes


@main.command(name="format")
@click.argument(
    "sources",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--check",
    is_flag=True,
    help="Print a diff for each file not in canonical form instead of"
    " rewriting it, and exit non-zero if there is one.",
)
def format_command(sources: tuple[Path, ...], check: bool) -> None:
    """Rewrite `.dad` files in canonical form, keeping their `;;` comments.

    Every file is parsed before any is written, so one that does not parse
    leaves all of them as they were. A trailing comment stays on its line,
    a whole-line comment stays before the line that followed it, and a
    block of comments stays before the section that followed it.
    """
    import difflib

    from .dad import formatter, parser

    changed: list[tuple[Path, str, str]] = []
    for source in sources:
        # Untranslated both ways: canonical form ends lines with "\n" alone,
        # and a file with "\r\n" endings is one to rewrite, not one that
        # reads as canonical because the newlines were translated away.
        text = source.read_text(encoding="utf-8", newline="")
        try:
            spec, comments = parser.parse_with_comments(text)
        except parser.DadParseError as error:
            raise click.ClickException(f"{source}: {error}") from None
        canonical = formatter.format_spec(spec, comments)
        if canonical != text:
            changed.append((source, text, canonical))
    for source, text, canonical in changed:
        if check:
            click.echo(
                "".join(
                    difflib.unified_diff(
                        text.splitlines(keepends=True),
                        canonical.splitlines(keepends=True),
                        fromfile=str(source),
                        tofile=str(source),
                    )
                ),
                nl=False,
            )
        else:
            source.write_text(canonical, encoding="utf-8", newline="")
    verb = "would reformat" if check else "reformatted"
    click.echo(
        f"{verb} {len(changed)} of {len(sources)} files",
        err=True,
    )
    if check and changed:
        raise SystemExit(1)


@main.command()
@click.argument(
    "sources",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--notes/--no-notes",
    default=True,
    help="Report findings a single file cannot judge (default: report them).",
)
@click.option(
    "--corpus",
    "corpus_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory or file to resolve re-used AVPs against. Enables the"
    " cross-file rules; repeatable. Default: the installed seanchai-corpus"
    " package, if there is one.",
)
@click.option(
    "--no-corpus",
    is_flag=True,
    help="Lint each file alone, even with seanchai-corpus installed.",
)
@click.option(
    "--output-format",
    type=click.Choice(["full", "concise"]),
    default="full",
    help="`full` groups findings under their file with a summary (default);"
    " `concise` prints one greppable `file: severity: [rule] ...` line per"
    " finding.",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_CORRECTIONS,
    show_default=True,
    help="Directory with per-spec correction modules, whose acceptances mark"
    " deliberate overrides among a corrected file's findings; read with a"
    " corpus only. Defaulted, like regenerate's, for the repository's own"
    " corpus; a missing default directory is no acceptances, and an installed"
    " corpus read outside the repository leaves the default unread.",
)
@click.option(
    "--show-accepted",
    is_flag=True,
    help="Also print the findings an acceptance acknowledges (always counted).",
)
def lint(
    sources: tuple[Path, ...],
    notes: bool,
    corpus_paths: tuple[Path, ...],
    no_corpus: bool,
    output_format: str,
    corrections: Path,
    show_accepted: bool,
) -> None:
    """Report structural inconsistencies in `.dad` files.

    Exits non-zero when any error is found; notes alone do not fail, because
    they are things a single file cannot decide rather than defects.

    With `--corpus`, re-used AVPs are resolved against the other files it names
    and the cross-file rules run too. Without it the installed seanchai-corpus
    package is the corpus; with no such package, or with `--no-corpus`, each
    file is linted alone. An origin the corpus does not hold is reported as a
    note and its rules are skipped, so a partial corpus is useful rather than
    an error. The specification's corrections module is
    read too: a note one of its acceptances acknowledges is reported as
    `accepted`, hidden unless `--show-accepted`, and an acceptance matching
    no finding is an error. A raw (`.raw.dad`) file is linted without them,
    since they describe the corrected one. A corpus directory's record of known
    holes is linted once, as a file of its own: a hole it does not list and an
    entry naming no hole are errors.
    """
    from .corpus import Corpus, CorpusNotInstalledError, installed_directory
    from .dad import corrections as corrections_module
    from .dad import parser
    from .linter import Severity, lint_record, lint_with_corpus
    from .linter import lint as lint_spec

    if no_corpus and corpus_paths:
        raise click.UsageError("--corpus and --no-corpus exclude each other")
    explicit = (
        click.get_current_context().get_parameter_source("corrections")
        is not click.core.ParameterSource.DEFAULT
    )
    if explicit and not corrections.is_dir():
        raise click.BadParameter(
            f"directory {str(corrections)!r} does not exist",
            param_hint="'--corrections'",
        )
    directory = corrections if corrections.is_dir() else None
    counts = dict.fromkeys(Severity, 0)
    checked = 0

    def report(source: Path, findings: list) -> None:
        if not notes:
            findings = [f for f in findings if f.severity is Severity.ERROR]
        for finding in findings:
            counts[finding.severity] += 1
        if not show_accepted:
            findings = [f for f in findings if f.severity is not Severity.ACCEPTED]
        if output_format == "concise":
            for finding in findings:
                click.echo(f"{source}: {finding}")
        elif findings:
            _echo_findings(source, findings)

    with reported():
        books = None
        if corpus_paths:
            books = Corpus.load(corpus_paths)
        elif not no_corpus:
            with contextlib.suppress(CorpusNotInstalledError):
                books = Corpus.installed()
                # A plain `lint` must not execute what the working directory
                # holds, so the default directory counts only in the repository
                # whose copy is the installed corpus. Naming a corpus or
                # `--corrections` is the asking `corrections.load` requires. The
                # path stays unresolved below the working directory, where a
                # symlink to the installed corpus would otherwise pass for it.
                in_repository = (
                    installed_directory().resolve()
                    == Path.cwd().resolve() / _DEFAULT_CORPUS
                )
                if not (explicit or in_repository):
                    directory = None
        for source in sources:
            spec = parser.parse(source.read_text(encoding="utf-8"))
            if books is None:
                findings = lint_spec(spec)
            else:
                accepts = (
                    []
                    if source.name.endswith(".raw.dad")
                    else corrections_module.acceptances(
                        corrections_module.in_release(
                            corrections_module.load(directory, spec.specification),
                            spec.version,
                        )
                    )
                )
                findings = lint_with_corpus(spec, books, accepts)
            checked += 1
            report(source, findings)
        if books is not None and books.record is not None:
            report(books.record.path, lint_record(books))
    if output_format == "full" and any(counts.values()):
        click.echo(_summary(counts, checked))
    if counts[Severity.ERROR]:
        raise SystemExit(1)


def _echo_findings(source: Path, findings) -> None:
    """One file's findings, grouped under its path, errors first."""
    from .linter import Severity

    click.secho(str(source), bold=True)
    color = {Severity.ERROR: "red", Severity.NOTE: "cyan", Severity.ACCEPTED: "green"}
    order = list(Severity)
    for finding in sorted(findings, key=lambda f: order.index(f.severity)):
        severity = click.style(finding.severity.value, fg=color[finding.severity])
        rule = click.style(f"[{finding.rule}]", dim=True)
        where = (
            click.style(f" (clause {finding.section})", dim=True)
            if finding.section
            else ""
        )
        by = (
            click.style(f" ({finding.accepted_by})", dim=True)
            if finding.accepted_by
            else ""
        )
        click.echo(f"  {severity}{rule} {finding.message}{where}{by}")
    click.echo()


def _summary(counts, checked: int) -> str:
    from .linter import Severity

    def plural(count: int, noun: str) -> str:
        return f"{count} {noun}{'' if count == 1 else 's'}"

    # "accepted" is no noun to pluralise.
    found = ", ".join(
        click.style(
            f"{count} accepted"
            if severity is Severity.ACCEPTED
            else plural(count, severity.value),
            fg={Severity.ERROR: "red", Severity.NOTE: "cyan"}.get(severity, "green"),
            bold=severity is Severity.ERROR,
        )
        for severity, count in counts.items()
        if count
    )
    return f"found {found} in {plural(checked, 'file')}"


@main.command()
@click.option("--release", type=int, default=18, help="3GPP release (default: 18).")
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("specifications"),
    help="Directory for downloaded sources (default: ./specifications).",
)
@click.option("--workers", type=int, default=6, help="Parallel downloads (default: 6).")
@click.option(
    "--no-extract",
    is_flag=True,
    help="Keep 3GPP ZIPs without extracting their DOC/DOCX files (and so"
    " without converting a legacy DOC).",
)
@click.option(
    "--no-convert",
    is_flag=True,
    help="Extract a legacy DOC without converting it to DOCX, so LibreOffice"
    " is not needed; the manifest records it unconverted and `regenerate`"
    " skips its specification.",
)
@click.option(
    "--pdfs/--no-pdfs",
    default=True,
    help="Download the ETSI PDF renderings and prefer the newest version"
    " whose PDF is published (default: on). --no-pdfs is for catalog"
    " experiments only: it strips pdf_url from the manifest and lets"
    " the newest archive replace a committed spec's docx with a version whose"
    " PDF is unpublished.",
)
@click.option("--list", "list_only", is_flag=True, help="Print the catalog and exit.")
@click.option(
    "--spec",
    metavar="SPECREF",
    help="With --version: fetch one catalogued 3GPP specification"
    " (e.g. TS29.272) into versions/ instead of the whole catalog.",
)
@click.option(
    "--version",
    "spec_version",
    metavar="VERSION",
    help="With --spec: the archived version to fetch (e.g. 18.6.0); its"
    " major is the release.",
)
def download(
    release: int,
    output: Path,
    workers: int,
    no_extract: bool,
    no_convert: bool,
    pdfs: bool,
    list_only: bool,
    spec: str | None,
    spec_version: str | None,
) -> None:
    """Download the curated 3GPP, RFC and oneM2M specification corpus.

    Every entry is staged and the whole set replaces the previous download
    only when all of it succeeded; a failed run leaves the previous one and
    its manifest as they were. A 3GPP archive holding only a legacy `.doc`,
    and a oneM2M document, is converted to `.docx` with headless LibreOffice
    (`soffice` on PATH), and the conversion is recorded in the manifest;
    without LibreOffice the run fails unless --no-convert says to skip the
    conversions.

    With --spec and --version, one older version is fetched into
    `versions/<SPECREF>/<VERSION>/` with a manifest of its own, for
    `seanchai regenerate --manifest ... --spec ... -o SCRATCH`.
    """
    from .downloader import download_corpus, download_version, load_catalog

    if (spec is None) != (spec_version is None):
        raise click.UsageError("--spec and --version go together")

    # Catalog loading is inside the boundary too: an unreadable or malformed
    # specs.toml is a user-facing error, not a traceback.
    with reported():
        catalog = load_catalog()
        tgpp_specs, rfc_specs, wireshark, onem2m_specs, pinned_specs, transcribed = (
            catalog
        )
        if list_only:
            click.echo(f"3GPP specifications ({len(tgpp_specs)}):")
            for entry in tgpp_specs:
                click.echo(f"  {entry.document_type} {entry.number}: {entry.title}")
            click.echo(f"\nRFCs ({len(rfc_specs)}):")
            for rfc in rfc_specs:
                click.echo(f"  RFC {rfc.number}: {rfc.title}")
            click.echo(f"\n3GPP versions pinned beside it ({len(pinned_specs)}):")
            for pin in pinned_specs:
                last = (
                    "final version"
                    if pin.final == "document"
                    else f"Release {pin.release}'s last"
                )
                click.echo(
                    f"  {pin.document_type} {pin.number} V{pin.version}"
                    f" ({last}): {pin.title}"
                )
            click.echo(f"\noneM2M specifications ({len(onem2m_specs)}):")
            for onem2m in onem2m_specs:
                click.echo(
                    f"  {onem2m.identifier} V{onem2m.version} (Release"
                    f" {onem2m.release}): {onem2m.title}"
                )
            click.echo(f"\nHand transcriptions, not downloaded ({len(transcribed)}):")
            for document in transcribed:
                click.echo(f"  {document.reference}: {document.title}")
            click.echo(
                f"\nWireshark Diameter dictionary: {wireshark.path} at {wireshark.tag}"
            )
            return
        if spec is not None and spec_version is not None:
            download_version(
                spec,
                spec_version,
                output,
                extract=not no_extract,
                pdfs=pdfs,
                catalog=catalog,
                report=lambda message: click.echo(message, err=True),
                convert=not no_convert,
            )
            return
        download_corpus(
            output,
            release=release,
            workers=workers,
            extract=not no_extract,
            pdfs=pdfs,
            catalog=catalog,
            report=lambda message: click.echo(message, err=True),
            convert=not no_convert,
        )


@main.command()
@click.argument(
    "sources",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--dictionary",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=Path("specifications") / "wireshark",
    show_default=True,
    help="Directory holding Wireshark's Diameter dictionary files.",
)
@click.option(
    "--aliases",
    type=click.Path(dir_okay=False, path_type=Path),
    default=_DEFAULT_ALIASES,
    show_default=True,
    help="Accepted-aliases file listing Wireshark's deliberate renames, which"
    " are agreement while vendor, code and type agree. Defaulted for the"
    " repository's own corpus; a missing default file is no aliases.",
)
@click.option(
    "--show-accepted",
    is_flag=True,
    help="Also print the renames an alias accepts (always counted).",
)
def crosscheck(
    sources: tuple[Path, ...], dictionary: Path, aliases: Path, show_accepted: bool
) -> None:
    """Cross-check `.dad` files against Wireshark's Diameter dictionary.

    Reports where the two projects read the specifications differently:
    an AVP's code resolving to a different name, a type that disagrees
    after Wireshark's dissector conveniences are mapped onto RFC 6733's
    vocabulary, and AVPs the pinned dictionary does not carry at all.
    Disagreement is a report for a reader with the documents open, not a
    verdict — so findings never fail the run.

    SOURCES are files or directories, a directory's raw files skipped as
    the corpus loader skips them; none means the corpus the seanchai-corpus
    package installed. Only the
    newest copy of each document is checked: an older one the corpus holds
    for a citation (TS 32.299 V11.20.0) is no reading of the document the
    dictionary describes, and is listed as skipped. Two files of one
    document and version are refused.

    A name disagreement the accepted-aliases file lists for the document is
    agreement while the dictionary's entry carries the listed name and
    agrees in type: it is counted as an accepted rename, printed only with
    `--show-accepted`. A listed alias that no longer holds is a
    `stale-alias` finding.
    """
    from .corpus import Corpus, CorpusError, Entry, installed_directory
    from .dad import parser
    from .oracle import Oracle, OracleError, load_aliases
    from .oracle import crosscheck as check

    explicit = (
        click.get_current_context().get_parameter_source("aliases")
        is not click.core.ParameterSource.DEFAULT
    )
    if explicit and not aliases.is_file():
        raise click.BadParameter(
            f"file {str(aliases)!r} does not exist", param_hint="'--aliases'"
        )
    try:
        oracle = Oracle.load(dictionary)
        accepted = load_aliases(aliases) if aliases.is_file() else ()
    except OracleError as error:
        raise click.ClickException(str(error)) from None
    total = 0
    renames = 0
    with reported():
        entries: list[Entry] = []
        for source in sources or (installed_directory(),):
            if source.is_dir():
                try:
                    entries.extend(Corpus.load([source]))
                except CorpusError as error:
                    raise click.ClickException(str(error)) from None
            else:
                spec = parser.parse(source.read_text(encoding="utf-8"))
                entries.append(Entry(path=source, spec=spec))
        books = Corpus(entries)
        newest = sorted(books.newest(), key=lambda entry: entry.path.as_posix())
        checked = {entry.path for entry in newest}
        for entry in sorted(books, key=lambda entry: entry.path.as_posix()):
            if entry.path not in checked:
                click.echo(
                    f"skipped {entry.path}: {entry.reference}"
                    f" {entry.spec.version}, an older copy than the one checked",
                    err=True,
                )
        for entry in newest:
            for finding in check(entry.spec, oracle, accepted):
                if finding.accepted_by is None:
                    total += 1
                else:
                    renames += 1
                    if not show_accepted:
                        continue
                click.echo(f"{entry.path}: {finding}")
    summary = f"checked {len(newest)} files against the dictionary: {total} findings"
    if renames:
        summary += f", {renames} accepted rename{'' if renames == 1 else 's'}"
    click.echo(summary, err=True)


def _write(spec, output: Path | None, notes: Comments | None = None) -> None:
    from .dad import formatter

    text = formatter.format_spec(spec, notes or formatter.Comments())
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        sections = click.style(f"({len(spec.sections)} sections)", dim=True)
        click.echo(f"wrote {click.style(str(output), bold=True)} {sections}", err=True)
