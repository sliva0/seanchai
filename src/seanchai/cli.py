"""The `seanchai` command.

Every library operation this drives promises exactly one exception type —
`DadParseError`, `ExtractionError`, `CorrectionError`, `DownloadError` — so
the whole of the CLI's error handling is `reported()`: turn those four into
the styled `error: ...` line, and let anything else through as a traceback,
because anything else is a bug in this program rather than a problem with the
user's document.
"""

import contextlib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import click

# The two declared edit layers live side by side; only the source
# declarations (input patches and quirks) are discovered automatically,
# because loading a correction module executes Python from that directory.
_DEFAULT_SOURCES = Path("edits") / "sources"

# The `(trailing, standing, detached)` note triple `corrections.notes`
# produces and `formatter.format_spec` takes.
_NoteMap = Mapping[int, Sequence[str]]
_Notes = tuple[_NoteMap, _NoteMap, _NoteMap]


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
            spec = tgpp_docx.extract(
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
        notes: _Notes = ({}, {}, {})
        if corrections is not None:
            # A corpus run may pass a directory holding modules for only some
            # of its specifications, so a spec without one is not an error.
            spec, notes = _correct(spec, corrections, required=False)
    _write(spec, output, notes)


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
        notes: _Notes = ({}, {}, {})
        if corrections is not None:
            spec, notes = _correct(spec, corrections, required=False)
    _write(spec, output, notes)


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
        spec = parser.parse(source.read_text(encoding="utf-8"))
        corrected, notes = _correct(spec, corrections, required=True)
    _write(corrected, output, notes)


def _correct(spec, directory: Path, required: bool):
    """Returns the corrected tree and the notes marking what was touched."""
    from .dad import corrections as corrections_module

    declared = corrections_module.load(directory, spec.specification, required=required)
    corrected, results = corrections_module.apply(spec, declared)
    for result in results:
        edit = result.correction
        reason = click.style(f"({edit.reason})", dim=True)
        if isinstance(edit, corrections_module.Delete):
            verb = click.style("deleted", fg="red")
            click.echo(f"{verb}: {result.node} {reason}", err=True)
        elif isinstance(edit, corrections_module.Insert):
            verb = click.style("inserted", fg="green")
            click.echo(f"{verb}: {result.node} {reason}", err=True)
        else:
            verb = click.style("corrected", fg="green")
            click.echo(
                f"{verb}: {result.node} {edit.field}"
                f" {result.old!r} -> {result.new!r} {reason}",
                err=True,
            )
    return corrected, corrections_module.notes(results)


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
def lint(
    sources: tuple[Path, ...],
    notes: bool,
    corpus_paths: tuple[Path, ...],
    output_format: str,
) -> None:
    """Report structural inconsistencies in `.dad` files.

    Exits non-zero when any error is found; notes alone do not fail, because
    they are things a single file cannot decide rather than defects.

    With `--corpus`, re-used AVPs are resolved against the other files it names
    and the cross-file rules run too. An origin the corpus does not hold is
    reported as a note and its rules are skipped, so a partial corpus is
    useful rather than an error.
    """
    from .corpus import Corpus
    from .dad import parser
    from .linter import Severity, lint_with_corpus
    from .linter import lint as lint_spec

    counts = {Severity.ERROR: 0, Severity.NOTE: 0}
    checked = 0
    with reported():
        books = Corpus.load(corpus_paths) if corpus_paths else None
        for source in sources:
            spec = parser.parse(source.read_text(encoding="utf-8"))
            findings = (
                lint_spec(spec) if books is None else lint_with_corpus(spec, books)
            )
            if not notes:
                findings = [f for f in findings if f.severity is Severity.ERROR]
            checked += 1
            for finding in findings:
                counts[finding.severity] += 1
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
    color = {Severity.ERROR: "red", Severity.NOTE: "cyan"}
    for finding in sorted(findings, key=lambda f: f.severity is not Severity.ERROR):
        severity = click.style(finding.severity.value, fg=color[finding.severity])
        rule = click.style(f"[{finding.rule}]", dim=True)
        where = (
            click.style(f" (clause {finding.section})", dim=True)
            if finding.section
            else ""
        )
        click.echo(f"  {severity}{rule} {finding.message}{where}")
    click.echo()


def _summary(counts, checked: int) -> str:
    from .linter import Severity

    def plural(count: int, noun: str) -> str:
        return f"{count} {noun}{'' if count == 1 else 's'}"

    found = ", ".join(
        click.style(
            plural(count, severity.value),
            fg="red" if severity is Severity.ERROR else "cyan",
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
    help="Keep 3GPP ZIPs without extracting their DOC/DOCX files.",
)
@click.option(
    "--pdfs/--no-pdfs",
    default=True,
    help="Download the ETSI PDF renderings and prefer the newest version"
    " whose PDF is published (default: on). --no-pdfs is for catalog"
    " experiments only: it strips pdf_url from the manifest and lets"
    " Specs/latest replace a committed spec's docx with a version whose"
    " PDF is unpublished.",
)
@click.option("--list", "list_only", is_flag=True, help="Print the catalog and exit.")
def download(
    release: int,
    output: Path,
    workers: int,
    no_extract: bool,
    pdfs: bool,
    list_only: bool,
) -> None:
    """Download the curated 3GPP and RFC specification corpus."""
    from .downloader import download_corpus, load_catalog

    # Catalog loading is inside the boundary too: an unreadable or malformed
    # specs.toml is a user-facing error, not a traceback.
    with reported():
        tgpp_specs, rfc_specs, wireshark = load_catalog()
        if list_only:
            click.echo(f"3GPP specifications ({len(tgpp_specs)}):")
            for spec in tgpp_specs:
                click.echo(f"  {spec.document_type} {spec.number}: {spec.title}")
            click.echo(f"\nRFCs ({len(rfc_specs)}):")
            for spec in rfc_specs:
                click.echo(f"  RFC {spec.number}: {spec.title}")
            click.echo(
                f"\nWireshark Diameter dictionary: {wireshark.path}"
                f" at {wireshark.tag}"
            )
            return
        download_corpus(
            output,
            release=release,
            workers=workers,
            extract=not no_extract,
            pdfs=pdfs,
            catalog=(tgpp_specs, rfc_specs, wireshark),
            report=lambda message: click.echo(message, err=True),
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
    from .oracle import Oracle, OracleError, crosscheck as check

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
        f"checked {len(sources)} files against the dictionary:"
        f" {total} findings",
        err=True,
    )


def _write(spec, output: Path | None, notes: _Notes | None = None) -> None:
    from .dad import formatter

    trailing, standing, detached = notes or ({}, {}, {})
    text = formatter.format_spec(spec, trailing, standing, detached)
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        sections = click.style(f"({len(spec.sections)} sections)", dim=True)
        click.echo(f"wrote {click.style(str(output), bold=True)} {sections}", err=True)
