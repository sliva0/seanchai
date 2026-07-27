"""The `seanchai` command.

Every library operation this drives promises exactly one exception type —
`DadParseError`, `ExtractionError`, `CorrectionError`, `DownloadError` — so
the whole of the CLI's error handling is `reported()`: turn those four into
Click's own `Error: ...`, and let anything else through as a traceback,
because anything else is a bug in this program rather than a problem with the
user's document.
"""

import contextlib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import click

# The two declared edit layers live side by side; only the input patches are
# discovered automatically, because loading a correction module executes
# Python from that directory.
_DEFAULT_PATCHES = Path("edits") / "patches"


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
    "--patches",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with input-patch TOML files (default: ./edits/patches if present).",
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
    patches: Path | None,
    corrections: Path | None,
    output: Path | None,
) -> None:
    """Extract a canonical `.dad` file from a 3GPP specification docx."""
    from .extractor import tgpp_docx

    if patches is None and _DEFAULT_PATCHES.is_dir():
        patches = _DEFAULT_PATCHES
    warnings: list[str] = []
    with reported():
        try:
            spec = tgpp_docx.extract(
                docx, link=link, warnings=warnings, patches_dir=patches
            )
            if pdf is not None:
                spec = tgpp_docx.attach_pages(spec, pdf, warnings=warnings)
        finally:
            # Report what the source document did even when a later stage fails —
            # a mismatched PDF aborts the run, and that is exactly when the
            # extraction warnings are worth reading.
            for warning in warnings:
                click.echo(f"warning: {warning}", err=True)
        notes: dict[int, list[str]] = {}
        if corrections is not None:
            # A corpus run may pass a directory holding modules for only some
            # of its specifications, so a spec without one is not an error.
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
    notes: dict[int, list[str]] = {}
    for result in results:
        click.echo(
            f"corrected: {result.node} {result.correction.field}"
            f" {result.old!r} -> {result.new!r} ({result.correction.reason})",
            err=True,
        )
        # The note says what changed and where to read why, and no more: a
        # `.dad` file carries definitions, and the correction's `reason` is a
        # sentence that belongs next to the correction.
        notes.setdefault(result.node_id, []).append(
            f"corrected: {result.correction.field} {result.old!r} -> {result.new!r}"
            f" [{result.correction.origin}]"
        )
    return corrected, notes


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
def lint(
    sources: tuple[Path, ...], notes: bool, corpus_paths: tuple[Path, ...]
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

    total_errors = 0
    with reported():
        books = Corpus.load(corpus_paths) if corpus_paths else None
        for source in sources:
            spec = parser.parse(source.read_text(encoding="utf-8"))
            findings = (
                lint_spec(spec) if books is None else lint_with_corpus(spec, books)
            )
            if not notes:
                findings = [f for f in findings if f.severity is Severity.ERROR]
            for finding in findings:
                click.echo(f"{source}: {finding}")
            total_errors += sum(1 for f in findings if f.severity is Severity.ERROR)
    if total_errors:
        raise SystemExit(1)


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
@click.option("--pdfs", is_flag=True, help="Also download the ETSI PDF renderings.")
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
        tgpp_specs, rfc_specs = load_catalog()
        if list_only:
            click.echo(f"3GPP specifications ({len(tgpp_specs)}):")
            for spec in tgpp_specs:
                click.echo(f"  {spec.document_type} {spec.number}: {spec.title}")
            click.echo(f"\nRFCs ({len(rfc_specs)}):")
            for spec in rfc_specs:
                click.echo(f"  RFC {spec.number}: {spec.title}")
            return
        download_corpus(
            output,
            release=release,
            workers=workers,
            extract=not no_extract,
            pdfs=pdfs,
            catalog=(tgpp_specs, rfc_specs),
            report=lambda message: click.echo(message, err=True),
        )


def _write(
    spec, output: Path | None, notes: Mapping[int, Sequence[str]] | None = None
) -> None:
    from .dad import formatter

    text = formatter.format_spec(spec, notes or {})
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        click.echo(f"wrote {output} ({len(spec.sections)} sections)", err=True)
