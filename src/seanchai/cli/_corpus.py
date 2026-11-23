"""`seanchai corpus`: the maintainers' commands, which download, extract,
correct, rebuild and cross-check the corpus in a checkout."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ..downloader.catalog import RELEASE, SOURCES
from ._base import (
    _DEFAULT_ALIASES,
    _DEFAULT_CORPUS,
    _DEFAULT_CORRECTIONS,
    _DEFAULT_SOURCES,
    _DEFAULT_TRANSCRIPTIONS,
    _naming,
    _need_wireshark,
    _require_extract,
    main,
    reported,
)

if TYPE_CHECKING:
    from ..dad.formatter import Comments
    from ..downloader.catalog import Catalog


@main.group()
def corpus() -> None:
    """Download, extract and rebuild the corpus; needs a checkout.

    Maintainer commands. Their defaults are paths in the repository
    (specifications/, edits/, the seanchai-corpus data, and
    integrations/wireshark/aliases.toml), so run them from its root.
    """


@corpus.command()
@click.option("--release", type=int, default=RELEASE, help="3GPP release.")
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("specifications"),
    help="Directory for downloaded sources.",
)
@click.option("--workers", type=int, default=6, help="Parallel downloads.")
@click.option(
    "--no-extract",
    is_flag=True,
    help="Keep 3GPP ZIPs without extracting or converting their documents.",
)
@click.option(
    "--no-convert",
    is_flag=True,
    help="Do not convert legacy DOC files to DOCX, so LibreOffice is not"
    " needed; `regenerate` skips those specifications.",
)
@click.option(
    "--pdfs/--no-pdfs",
    default=True,
    help="Download the ETSI PDFs and prefer the newest version with a"
    " published PDF. --no-pdfs is for catalog experiments only.",
)
@click.option("--list", "list_only", is_flag=True, help="Print the catalog and exit.")
@click.option(
    "--only",
    multiple=True,
    type=click.Choice(SOURCES),
    help="Fetch only this source, keeping the manifest's entries for the others."
    " Repeatable.",
)
@click.option(
    "--spec",
    metavar="SPECREF",
    help="With --version: fetch one 3GPP specification (e.g. TS29.272) into versions/.",
)
@click.option(
    "--version",
    "spec_version",
    metavar="VERSION",
    help="With --spec: the archived version to fetch (e.g. 18.6.0).",
)
def download(
    release: int,
    output: Path,
    workers: int,
    no_extract: bool,
    no_convert: bool,
    pdfs: bool,
    list_only: bool,
    only: tuple[str, ...],
    spec: str | None,
    spec_version: str | None,
) -> None:
    """Download the source documents: 3GPP, RFC, oneM2M, Wireshark, and the
    PDFs behind the hand transcriptions (`transcribed`).

    The new download replaces the previous one only if every entry succeeds.
    Legacy `.doc` files and oneM2M documents are converted to `.docx` with
    LibreOffice (`soffice` on PATH); without it the run fails unless
    --no-convert. Cached files are not fetched again.

    With --spec and --version, one older version goes to
    `versions/<SPECREF>/<VERSION>/` with its own manifest, for
    `seanchai corpus regenerate --manifest ... --spec ... -o SCRATCH`.

    3GPP, oneM2M and `transcribed` downloads need the `seanchai[extract]`
    extra; `wireshark` and `rfc` do not.
    """
    from ..downloader import download_corpus, download_version, load_catalog

    if (spec is None) != (spec_version is None):
        raise click.UsageError("--spec and --version go together")
    if spec is not None and only:
        raise click.UsageError("--only and --spec exclude each other")

    # Catalog loading is inside the boundary too: an unreadable or malformed
    # specs.toml is a user-facing error, not a traceback.
    with reported():
        catalog = load_catalog()
        if list_only:
            _echo_catalog(catalog, only or SOURCES)
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
            only=only or None,
        )


def _echo_catalog(catalog: Catalog, sources: Sequence[str]) -> None:
    """Print the catalog entries of `sources`."""
    if "3gpp" in sources:
        click.echo(f"3GPP specifications ({len(catalog.tgpp)}):")
        for entry in catalog.tgpp:
            click.echo(f"  {entry.document_type} {entry.number}: {entry.title}")
        click.echo(f"\n3GPP versions pinned beside it ({len(catalog.pinned)}):")
        for pin in catalog.pinned:
            last = (
                "final version"
                if pin.final == "document"
                else f"Release {pin.release}'s last"
            )
            click.echo(
                f"  {pin.document_type} {pin.number} V{pin.version}"
                f" ({last}): {pin.title}"
            )
    if "rfc" in sources:
        click.echo(f"\nRFCs ({len(catalog.rfc)}):")
        for rfc in catalog.rfc:
            click.echo(f"  RFC {rfc.number}: {rfc.title}")
    if "onem2m" in sources:
        click.echo(f"\noneM2M specifications ({len(catalog.onem2m)}):")
        for onem2m in catalog.onem2m:
            click.echo(
                f"  {onem2m.identifier} V{onem2m.version} (Release"
                f" {onem2m.release}): {onem2m.title}"
            )
    if "transcribed" in sources:
        click.echo(f"\nHand transcriptions' PDFs ({len(catalog.transcribed)}):")
        for document in catalog.transcribed:
            click.echo(f"  {document.reference}: {document.title}")
    if "wireshark" in sources:
        click.echo(
            f"\nWireshark Diameter dictionary: {catalog.wireshark.path}"
            f" at {catalog.wireshark.tag}"
        )


@corpus.command()
@click.option(
    "--manifest",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("specifications") / "manifest.json",
    help="The downloader's manifest; its files are the sources.",
)
@click.option(
    "--corpus",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_CORPUS,
    help="The committed corpus, which decides what to rebuild.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=False, path_type=Path),
    show_default="the corpus itself",
    help="Where to write.",
)
@click.option(
    "--sources",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_SOURCES,
    help="Directory with source-declaration TOML files.",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_CORRECTIONS,
    help="Directory with per-spec correction modules. Executes Python from it.",
)
@click.option(
    "--transcriptions",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_TRANSCRIPTIONS,
    help="Directory with hand transcriptions.",
)
@click.option(
    "--add",
    multiple=True,
    metavar="SPECREF",
    help="Also build a specification new to the corpus (e.g. TS29.273). Repeatable.",
)
@click.option(
    "--spec",
    "only",
    multiple=True,
    metavar="SPECREF",
    help="Rebuild only this specification. Repeatable.",
)
@click.option(
    "--expand-ranges",
    is_flag=True,
    help="Widen edit declaration version ranges to cover versions they applied"
    " to cleanly.",
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

    Re-extracts, pages and corrects every specification in the corpus from the
    manifest's files and writes it back with its raw mirror. A newer download
    replaces the committed version. Also rewrites `corrections.json` unless
    something failed. A failing specification does not stop the run; the exit
    status is 1 if any failed.

    To extract an older version fetched with `corpus download --spec --version`:

    \b
        seanchai corpus regenerate --spec SPECREF -o SCRATCH \\
            --manifest specifications/versions/SPECREF/VERSION/manifest.json

    Without -o it would replace the committed version. Needs the
    `seanchai[extract]` extra and a checkout. Executes Python from
    --corrections.
    """
    _require_extract()
    from .. import _regenerate as library

    if not manifest.is_file():
        raise click.ClickException(
            f"{manifest} does not exist: run `seanchai corpus download`,"
            " which writes it"
        )
    # Checked here and not by the options' types, so that an install with no
    # checkout hears about the extra first.
    for option, directory in (
        ("--corpus", corpus),
        ("--sources", sources),
        ("--corrections", corrections),
        ("--transcriptions", transcriptions),
    ):
        if not directory.is_dir():
            raise click.BadParameter(
                f"directory {str(directory)!r} does not exist", param_hint=f"'{option}'"
            )
    with reported():
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
    if report.missing_sources:
        fetch = " ".join(f"--only {name}" for name in report.missing_sources)
        raise click.ClickException(
            f"{manifest} holds no {', '.join(report.missing_sources)}: run"
            f" `seanchai corpus download {fetch}`, or name what it holds with --spec"
        )
    if report.failed:
        raise click.exceptions.Exit(1)


def _echo_outcome(outcome) -> None:
    from .._regenerate import describe

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


@corpus.command()
@click.argument("docx", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--pdf",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="The ETSI PDF of the same version, to add `; Page:` directives.",
)
@click.option("--link", help="ETSI PDF URL for the file's `; Link:` header.")
@click.option(
    "--sources",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    show_default="./edits/sources, if present",
    help="Directory with source-declaration TOML files.",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with correction modules (<SpecRef>.py). Executes Python"
    " from it, so it has no default.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    show_default="stdout",
    help="Output .dad path.",
)
def extract(
    docx: Path,
    pdf: Path | None,
    link: str | None,
    sources: Path | None,
    corrections: Path | None,
    output: Path | None,
) -> None:
    """Extract a canonical `.dad` file from a 3GPP specification docx.

    Needs the `seanchai[extract]` extra.
    """
    _require_extract()
    from ..extractor import tgpp_docx

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


@corpus.command(name="extract-rfc")
@click.argument("text", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--link", help="Canonical URL for the file's `; Link:` header.")
@click.option(
    "--sources",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    show_default="./edits/sources, if present",
    help="Directory with source-declaration TOML files.",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with correction modules (<SpecRef>.py). Executes Python"
    " from it, so it has no default.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    show_default="stdout",
    help="Output .dad path.",
)
def extract_rfc(
    text: Path,
    link: str | None,
    sources: Path | None,
    corrections: Path | None,
    output: Path | None,
) -> None:
    """Extract a canonical `.dad` file from an RFC's plain-text rendering.

    `; Page:` directives come from the text's printed page numbers.
    """
    from ..extractor import rfc_text

    if sources is None and _DEFAULT_SOURCES.is_dir():
        sources = _DEFAULT_SOURCES
    warnings: list[str] = []
    with reported():
        try:
            spec, comments = rfc_text.extract_with_comments(
                text, link=link, warnings=warnings, sources_dir=sources
            )
        finally:
            for warning in warnings:
                prefix = click.style("warning", fg="yellow")
                click.echo(f"{prefix}: {warning}", err=True)
        if corrections is not None:
            spec, comments = _correct(spec, comments, corrections, required=False)
    _write(spec, output, comments)


@corpus.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--corrections",
    required=True,
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with correction modules (<SpecRef>.py). Executes Python from it.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    show_default="stdout",
    help="Output .dad path.",
)
def correct(source: Path, corrections: Path, output: Path | None) -> None:
    """Apply a specification's corrections to a raw `.dad` file.

    SOURCE must be raw extractor output; an already corrected file fails,
    because its `expect` values no longer match. Unlike `extract
    --corrections`, the specification's module must exist and declare at
    least one correction.
    """
    from ..dad import parser

    if output is not None and output.resolve() == source.resolve():
        raise click.ClickException("refusing to correct a file in place")
    with reported():
        # Explicit encoding both ways: `.dad` files are UTF-8 wherever they were
        # written, and the platform default would otherwise decide whether a
        # spec title with a non-ASCII character survives the round trip.
        # The raw file's own comments — struck members commented out — move
        # with their lines.
        with _naming(source):
            text = source.read_text(encoding="utf-8")
            spec, comments = parser.parse_with_comments(text)
        corrected, notes = _correct(spec, comments, corrections, required=True)
    _write(corrected, output, notes)


def _correct(spec, comments: Comments, directory: Path, required: bool):
    """The corrected tree, and `comments` moved with their lines plus notes
    marking what changed."""
    from ..dad import corrections as corrections_module

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
        elif isinstance(edit, corrections_module.Interpret):
            verb = click.style("interpreted", fg="green")
            click.echo(f"{verb}: {result.node} {reason}", err=True)
        else:
            verb = click.style("corrected", fg="green")
            click.echo(
                f"{verb}: {result.node} {edit.field}"
                f" {result.old!r} -> {result.new!r} {reason}",
                err=True,
            )
    return corrected, notes


@corpus.command()
@click.argument(
    "sources",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--wireshark",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("specifications") / "wireshark",
    help="Wireshark's Diameter dictionary directory, from"
    " `seanchai corpus download --only wireshark`.",
)
@click.option(
    "--aliases",
    type=click.Path(dir_okay=False, path_type=Path),
    default=_DEFAULT_ALIASES,
    help="File of Wireshark's deliberate renames to accept. The default may be"
    " missing.",
)
@click.option(
    "--show-accepted",
    is_flag=True,
    help="Also print the renames an alias accepts (always counted).",
)
def crosscheck(
    sources: tuple[Path, ...], wireshark: Path, aliases: Path, show_accepted: bool
) -> None:
    """Cross-check `.dad` files against Wireshark's Diameter dictionary.

    Reports AVP codes with a different name, types that disagree after
    mapping Wireshark's types onto RFC 6733's, and AVPs the dictionary
    lacks. Findings never fail the run.

    SOURCES are files or directories, raw files skipped; with none, checks
    the installed corpus. Only the newest copy of each document is checked;
    older copies are listed as skipped. Two files of one document and
    version are refused.

    A rename listed in --aliases counts as accepted while the type agrees,
    and prints only with --show-accepted. A listed alias that no longer
    holds is a `stale-alias` finding.
    """
    from ..corpus import Corpus, CorpusError, Entry, installed_directory
    from ..dad import parser
    from ..oracle import Oracle, OracleError, load_aliases
    from ..oracle import crosscheck as check

    explicit = (
        click.get_current_context().get_parameter_source("aliases")
        is not click.core.ParameterSource.DEFAULT
    )
    if explicit and not aliases.is_file():
        raise click.BadParameter(
            f"file {str(aliases)!r} does not exist", param_hint="'--aliases'"
        )
    _need_wireshark(wireshark)
    try:
        oracle = Oracle.load(wireshark)
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
                with _naming(source):
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
    from ..dad import formatter

    text = formatter.format_spec(spec, notes or formatter.Comments())
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        sections = click.style(f"({len(spec.sections)} sections)", dim=True)
        click.echo(f"wrote {click.style(str(output), bold=True)} {sections}", err=True)
