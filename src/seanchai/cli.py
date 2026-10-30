"""The `seanchai` command.

Every library operation this drives promises exactly one exception type —
`DadParseError`, `ExtractionError`, `CorrectionError`, `DownloadError` — so
the whole of the CLI's error handling is `reported()`: turn those four into
the styled `error: ...` line, and let anything else through as a traceback,
because anything else is a bug in this program rather than a problem with the
user's document.
"""

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

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


def _show_error(self: click.ClickException, file=None) -> None:
    prefix = click.style("error", fg="red", bold=True)
    click.echo(f"{prefix}: {self.format_message()}", file=file, err=file is None)


def _show_usage_error(self: click.UsageError, file=None) -> None:
    if self.ctx is not None:
        hint = ""
        if self.ctx.command.get_help_option(self.ctx) is not None:
            option = max(self.ctx.command.get_help_option_names(self.ctx), key=len)
            hint = click.style(
                f"Try '{self.ctx.command_path} {option}' for help.", dim=True
            )
            hint = f"{hint}\n"
        click.echo(f"{self.ctx.get_usage()}\n{hint}", file=file, err=file is None)
    _show_error(self, file)


# Click renders help through `Context.formatter_class` — a documented hook —
# but gives no equivalent for its exception rendering, so the two `show`
# methods are replaced directly. Both keep Click's structure (usage block,
# help hint, message) and change only the styling, cargo-style.
click.Context.formatter_class = _HelpFormatter
click.ClickException.show = _show_error  # type: ignore[method-assign]
click.exceptions.UsageError.show = _show_usage_error  # type: ignore[method-assign]


@contextlib.contextmanager
def reported() -> Iterator[None]:
    """Present a library failure as a CLI error, not as a traceback."""
    from .dad.corrections import CorrectionError
    from .dad.parser import DadParseError
    from .downloader import DownloadError
    from .extractor.errors import ExtractionError

    try:
        yield
    except (DadParseError, ExtractionError, CorrectionError, DownloadError) as error:
        raise click.ClickException(str(error)) from None


@click.group()
def main() -> None:
    """Seanchaí: Diameter specifications as reviewable `.dad` files."""


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
    default=Path("dad"),
    show_default=True,
    help="The committed corpus: decides which specifications to rebuild.",
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

    declared = corrections_module.load(directory, spec.specification, required=required)
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
    " cross-file rules; repeatable.",
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
    " deliberate overrides among a corrected file's findings; read with"
    " --corpus only. Defaulted, like regenerate's, for the repository's own"
    " corpus; a missing default directory is no acceptances.",
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
    output_format: str,
    corrections: Path,
    show_accepted: bool,
) -> None:
    """Report structural inconsistencies in `.dad` files.

    Exits non-zero when any error is found; notes alone do not fail, because
    they are things a single file cannot decide rather than defects.

    With `--corpus`, re-used AVPs are resolved against the other files it names
    and the cross-file rules run too. An origin the corpus does not hold is
    reported as a note and its rules are skipped, so a partial corpus is
    useful rather than an error. The specification's corrections module is
    read too: a note one of its acceptances acknowledges is reported as
    `accepted`, hidden unless `--show-accepted`, and an acceptance matching
    no finding is an error. A raw (`.raw.dad`) file is linted without them,
    since they describe the corrected one.
    """
    from .corpus import Corpus
    from .dad import corrections as corrections_module
    from .dad import parser
    from .linter import Severity, lint_with_corpus
    from .linter import lint as lint_spec

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
    with reported():
        books = Corpus.load(corpus_paths) if corpus_paths else None
        for source in sources:
            spec = parser.parse(source.read_text(encoding="utf-8"))
            if books is None:
                findings = lint_spec(spec)
            else:
                accepts = (
                    []
                    if source.name.endswith(".raw.dad")
                    else corrections_module.acceptances(
                        corrections_module.load(directory, spec.specification)
                    )
                )
                findings = lint_with_corpus(spec, books, accepts)
            if not notes:
                findings = [f for f in findings if f.severity is Severity.ERROR]
            checked += 1
            for finding in findings:
                counts[finding.severity] += 1
            if not show_accepted:
                findings = [f for f in findings if f.severity is not Severity.ACCEPTED]
            if output_format == "concise":
                for finding in findings:
                    click.echo(f"{source}: {finding}")
            elif findings:
                _echo_findings(source, findings)
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
        tgpp_specs, rfc_specs, wireshark, onem2m_specs, pinned_specs = catalog
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
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--dictionary",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=Path("specifications") / "wireshark",
    show_default=True,
    help="Directory holding Wireshark's Diameter dictionary files.",
)
def crosscheck(sources: tuple[Path, ...], dictionary: Path) -> None:
    """Cross-check `.dad` files against Wireshark's Diameter dictionary.

    Reports where the two projects read the specifications differently:
    an AVP's code resolving to a different name, a type that disagrees
    after Wireshark's dissector conveniences are mapped onto RFC 6733's
    vocabulary, and AVPs the pinned dictionary does not carry at all.
    Disagreement is a report for a reader with the documents open, not a
    verdict — so findings never fail the run.
    """
    from .dad import parser
    from .oracle import Oracle, OracleError
    from .oracle import crosscheck as check

    try:
        oracle = Oracle.load(dictionary)
    except OracleError as error:
        raise click.ClickException(str(error)) from None
    total = 0
    with reported():
        for source in sources:
            spec = parser.parse(source.read_text(encoding="utf-8"))
            findings = check(spec, oracle)
            total += len(findings)
            for finding in findings:
                click.echo(f"{source}: {finding}")
    click.echo(
        f"checked {len(sources)} files against the dictionary: {total} findings",
        err=True,
    )


def _write(spec, output: Path | None, notes: Comments | None = None) -> None:
    from .dad import formatter

    text = formatter.format_spec(spec, notes or formatter.Comments())
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        sections = click.style(f"({len(spec.sections)} sections)", dim=True)
        click.echo(f"wrote {click.style(str(output), bold=True)} {sections}", err=True)
