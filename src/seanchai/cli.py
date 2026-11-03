"""The `seanchai` command.

Every library operation this drives refuses with a `SeanchaiError`, so the whole
of the CLI's error handling is `reported()`: turn that into the styled
`error: ...` line, and let anything else through as a traceback, because
anything else is a bug in this program rather than a problem with the user's
document. Exit status 1 is an error or a finding, and 2 a usage error, as Click
has it.

`click` is a core dependency, since the entry point is installed with the
library and the lookup commands need nothing more. Reading source documents is
the `seanchai[extract]` extra: the commands that do it import it themselves.
"""

import contextlib
import difflib
import json
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from .downloader.catalog import SOURCES
from .errors import SeanchaiError

if TYPE_CHECKING:
    # The `dad` modules are imported only by the commands that use them.
    from .dad.formatter import Comments
    from .downloader.catalog import Catalog

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
        except click.exceptions.NoArgsIsHelpError as error:
            # Its message is the help, which is no error to prefix.
            click.echo(error.format_message(), err=True)
            sys.exit(error.exit_code)
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
    try:
        yield
    except SeanchaiError as error:
        raise click.ClickException(str(error)) from None


@contextlib.contextmanager
def _naming(source: Path) -> Iterator[None]:
    """A `.dad` file that does not parse, or is no text, as an error naming it."""
    from .dad.parser import DadParseError

    try:
        yield
    except (DadParseError, UnicodeDecodeError) as error:
        raise click.ClickException(f"{source}: {error}") from None


def _dad_files(sources: Iterable[Path], *, raw: bool = False) -> list[Path]:
    """The files `sources` name, a directory standing for the `.dad` files under
    it, and a file named twice counting once. A directory's raw mirror is left
    out unless `raw`, as the corpus loader leaves it out; naming the mirror
    itself is asking for it."""
    files: dict[Path, None] = {}
    for source in sources:
        if not source.is_dir():
            files[source] = None
            continue
        found = sorted(source.rglob("*.dad"))
        kept = (
            found
            if raw or source.name == "raw"
            else [
                path
                for path in found
                if not path.name.endswith(".raw.dad")
                and "raw" not in path.relative_to(source).parts
            ]
        )
        if not kept:
            hint = "; --raw reads its raw files" if found else ""
            raise click.ClickException(f"{source} holds no .dad files{hint}")
        files.update(dict.fromkeys(kept))
    return list(files)


def _need_dictionary(directory: Path) -> None:
    """Refuse a Wireshark dictionary directory that holds none, saying where one
    comes from: all `crosscheck` and the export's names need of a download."""
    if not (directory / "dictionary.xml").is_file():
        raise click.ClickException(
            f"{directory} holds no Wireshark dictionary: run"
            " `seanchai download --only wireshark`"
        )


def _require_extract() -> None:
    """Refuse a command reading source documents without `seanchai[extract]`,
    before it does anything else."""
    from .downloader.core import require_extra

    with reported():
        require_extra()


@click.group(cls=_Group, context_settings={"show_default": True})
@click.version_option(package_name="seanchai")
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
    type=click.Path(file_okay=False, path_type=Path),
    help="Wireshark's Diameter dictionary, for its AVP names in the search index:"
    " specifications/wireshark after `seanchai download --only wireshark`. Without"
    " it the names are left out.",
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
    type=click.Path(file_okay=False, path_type=Path),
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

    Writes index.json, search.json, schema.json, syntax/dad.tmLanguage.json and,
    per document, documents/<id>.json and documents/<id>.raw.json
    (docs/website.md). The same corpus gives the same bytes.

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

    if include_pdfs and specifications is None:
        raise click.UsageError(
            "--include-pdfs needs --specifications, a `seanchai download` directory"
        )
    if dictionary is not None:
        _need_dictionary(dictionary)
    if specifications is not None and not specifications.is_dir():
        fetch = "--only 3gpp" if include_pdfs else "--only rfc"
        raise click.ClickException(
            f"{specifications} does not exist: run `seanchai download {fetch}`"
        )
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
        except OSError as error:
            raise click.ClickException(str(error)) from None


def _as_json(value: object) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _flags(rules) -> str:
    """Flag rules as a table's columns place them, the empty columns left out."""
    columns = (
        ("must", rules.must),
        ("may", rules.may),
        ("should not", rules.should_not),
        ("must not", rules.must_not),
        ("application-defined", rules.application_defined),
    )
    return (
        "; ".join(
            f"{name} {','.join(sorted(flags))}" for name, flags in columns if flags
        )
        or "none stated"
    )


def _identity_of(query: str) -> tuple[int, int] | None:
    """`(vendor-id, code)` from `10415:601`, None for anything an AVP's name
    could be. No name holds a colon, so one that does not parse is a mistake."""
    if ":" not in query:
        return None
    vendor_id, _, code = query.partition(":")
    if not (vendor_id.isdecimal() and code.isdecimal()):
        raise click.BadParameter(
            f"{query!r}: an identity is VENDOR:CODE, as 10415:601",
            param_hint="'NAME_OR_IDENTITY'",
        )
    return int(vendor_id), int(code)


def _reading(built, query: str, document: str | None, version: str | None):
    """What `seanchai show` shows, or an error saying why there is none."""
    from .model import ModelError

    identity = _identity_of(query)
    if document is None:
        found = built.definition(identity or query)
        holes = [hole for hole in built.holes() if hole.name == query]
    elif identity is None:
        found = built.resolve(document, query, version=version)
        hole = built.hole(document, query, version=version)
        holes = [] if hole is None else [hole]
    else:
        names = {avp.name for avp in built.identified(*identity)}
        readings = (built.resolve(document, name, version=version) for name in names)
        found = next(
            (avp for avp in readings if avp and avp.identity == identity), None
        )
        holes = []
    if found is not None:
        return found
    if holes:
        raise ModelError("\n".join(map(str, holes)))
    where = "" if document is None else f" in {built.canonical(document)}"
    names = sorted({avp.name for avp in built.avps()})
    close = difflib.get_close_matches(query, names, n=3)
    hint = f"; did you mean {', '.join(close)}?" if close else ""
    raise ModelError(f"no AVP {query}{where}{hint}")


def _difference(avp, other) -> str:
    """How `other` reads what `avp` does, in the fields that differ."""
    from .model import Enumerated

    parts = []
    if other.name != avp.name:
        parts.append(f"named {other.name}")
    if other.identity != avp.identity:
        parts.append(f"identity {other.vendor_id}:{other.code}")
    if other.data_type != avp.data_type:
        parts.append(f"type {other.data_type}")
    if other.defined_in != avp.defined_in:
        parts.append(f"defined in {other.defined_in}")
    if other.flag_rules != avp.flag_rules:
        parts.append(f"flags {_flags(other.flag_rules)}")
    if (
        isinstance(avp, Enumerated)
        and isinstance(other, Enumerated)
        and other.values != avp.values
    ):
        parts.append("other values")
    return ", ".join(parts) or "its members read otherwise"


def _echo_avp(avp, others) -> None:
    """One reading of an AVP, and how the others differ from it."""
    from .dad import ast, formatter
    from .model import Enumerated, Grouped

    click.secho(f"{avp.name} {avp.vendor_id}:{avp.code}", bold=True)
    click.echo(f"  type: {avp.data_type}")
    click.echo(f"  flags: {_flags(avp.flag_rules)}")
    clause = "" if avp.section is None else f", clause {avp.section}"
    click.echo(f"  defined in: {avp.defined_in}{clause}")
    if avp.read_through != avp.defined_in:
        click.echo(f"  read through: {avp.read_through}")
    for field_name, document in avp.completed_by:
        click.echo(f"  {field_name} from: {document}")
    if avp.supplied is not None:
        click.echo(f"  supplied by: {avp.supplied}")
    if isinstance(avp, Grouped):
        click.echo("  members:")
        for member in avp.members:
            found = member.avp or member.hole
            where = ""
            if found is not None and found.vendor_id is not None:
                where = f"  {found.vendor_id}:{found.code}"
            click.echo(f"    {formatter.avp_line(member.rule).strip()}{where}")
    if isinstance(avp, Enumerated):
        if avp.values_source is not None:
            click.echo(f"  values defined by: {avp.values_source}")
        if avp.values:
            click.echo("  values:")
        for value in avp.values:
            if isinstance(value, ast.EnumValue):
                click.echo(f"    {value.name} = {value.value}")
            elif isinstance(value, ast.ReservedValues):
                click.echo(f"    reserved {value.first}-{value.last}")
            else:
                click.echo(f"    vendor-specific {value.first}-{value.last}")
    if others:
        click.echo("  other readings:")
        for other in others:
            click.echo(f"    {other.read_through}: {_difference(avp, other)}")


@main.command()
@click.argument("name_or_identity", metavar="NAME_OR_IDENTITY")
@click.option(
    "--document",
    metavar="REF",
    help="Read it as this document does, instead of as its defining document.",
)
@click.option(
    "--version",
    "version",
    metavar="V",
    help="With --document: an older copy of that document the corpus holds.",
)
@click.option("--json", "as_json", is_flag=True, help="Print `to_dict()` as JSON.")
def show(
    name_or_identity: str, document: str | None, version: str | None, as_json: bool
) -> None:
    """Show one AVP of the installed corpus.

    NAME_OR_IDENTITY is a name or a VENDOR:CODE: `Session-Id`, `10415:601`. Prints
    the defining document's reading (`Model.definition`) and how the others
    differ, each a citing table's. A name two AVPs claim is refused, listing
    them; a name the corpus cannot complete says why. --json adds the other
    readings to `to_dict()` as `other_readings`.
    """
    from .model import Model

    if version is not None and document is None:
        raise click.UsageError("--version needs --document")
    with reported():
        built = Model.installed()
        avp = _reading(built, name_or_identity, document, version)
        others = [other for other in built.identified(*avp.identity) if other != avp]
    if as_json:
        _as_json({**avp.to_dict(), "other_readings": [o.to_dict() for o in others]})
    else:
        _echo_avp(avp, others)


@main.command()
@click.argument("reference", metavar="[REF]", required=False)
@click.option(
    "--application",
    type=int,
    metavar="ID",
    help="Only the commands of this application id, in any document.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the list as JSON.")
def commands(reference: str | None, application: int | None, as_json: bool) -> None:
    """List the installed corpus's commands.

    REF is a document, spelled as `TS29.229` or "TS 29.229"; with neither it nor
    --application, every command. Each line has the command code, whether it is
    the request or the answer, the effective application id (`-` where nothing
    states one), its name, and its defining document and section.
    """
    from .model import Model, ModelError

    with reported():
        applications = Model.installed().applications(
            reference, application_id=application
        )
        if application is not None and not applications:
            raise ModelError(
                f"no application {application}"
                f"{'' if reference is None else f' in {reference}'}:"
                " `seanchai commands` lists them"
            )
    rows = [
        {
            "command_code": message.command_code,
            "kind": "request" if message.is_request else "answer",
            "application_id": message.application_id,
            "application": each.name,
            "name": message.name,
            "abbreviation": message.abbreviation,
            "defined_in": message.defined_in,
            "section": message.section,
        }
        for each in applications
        for message in each.messages
    ]
    if as_json:
        _as_json(rows)
        return
    table = [("CODE", "KIND", "APPLICATION", "NAME", "DOCUMENT", "SECTION")] + [
        (
            str(row["command_code"]),
            str(row["kind"]),
            "-" if row["application_id"] is None else str(row["application_id"]),
            f"{row['name']} ({row['abbreviation']})",
            str(row["defined_in"]),
            str(row["section"]),
        )
        for row in rows
    ]
    widths = [max(len(cells[i]) for cells in table) for i in range(len(table[0]))]
    for cells in table:
        line = "  ".join(
            cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
        )
        click.echo(line.rstrip())


@main.command("dictionary")
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="The JSON file to write.",
)
@click.option(
    "--document",
    "documents",
    multiple=True,
    metavar="REF",
    help="Only this document's applications and AVPs. Repeatable.",
)
@click.option(
    "--application",
    "application_ids",
    multiple=True,
    type=int,
    metavar="ID",
    help="Only this application id's commands, and the AVPs they use. Repeatable.",
)
@click.option(
    "--policy",
    type=click.Choice(["hole", "drop", "placeholder", "supply"]),
    default="hole",
    help="What becomes of the names the corpus declares undefined: left as holes,"
    " dropped from their bodies, kept as untyped placeholders, or read from --supply.",
)
@click.option(
    "--supply",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="A hand-authored `.dad` sidecar stating undefined names, with --policy"
    " supply. Repeatable.",
)
def dictionary_command(
    output: Path,
    documents: tuple[str, ...],
    application_ids: tuple[int, ...],
    policy: str,
    supply: tuple[Path, ...],
) -> None:
    """Write the installed corpus as one JSON dictionary, for a stack not in Python.

    Applications with their commands, each member naming its AVP, and the AVPs
    with identity, type, flags, enumerated values and grouped members
    (docs/consumers.md). It records both versions and the policy. The same corpus
    and options give the same bytes.
    """
    from .corpus import Corpus
    from .dictionary import build, dumps
    from .model import Alias, Model, Supplied, SupplyKey, UndefinedPolicy, supplied_from

    undefined = UndefinedPolicy(policy)
    if (undefined is UndefinedPolicy.SUPPLY) != bool(supply):
        raise click.UsageError("--policy supply and --supply go together")
    with reported():
        books = Corpus.installed()
        answers: dict[SupplyKey, Supplied | Alias] = {
            name: answer for name, answer in supplied_from(*supply).items()
        }
        built = Model.build(books, undefined=undefined, supply=answers or None)
        written = build(
            built,
            corpus_version=books.version,
            documents=documents,
            application_ids=application_ids,
        )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dumps(written), encoding="utf-8")
    except OSError as error:
        raise click.ClickException(str(error)) from None
    commands = sum(len(each.commands) for each in written.applications)
    click.echo(
        f"wrote {click.style(str(output), bold=True)}"
        f" ({len(written.applications)} applications, {commands} commands,"
        f" {len(written.avps)} AVPs, {len(written.holes)} holes)",
        err=True,
    )


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
    show_default="./edits/sources, if present",
    help="Directory with source-declaration TOML files — input patches and quirks.",
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
    show_default="./edits/sources, if present",
    help="Directory with source-declaration TOML files — input patches and quirks.",
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
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("specifications") / "manifest.json",
    help="The downloader's manifest; its files are the sources.",
)
@click.option(
    "--corpus",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_CORPUS,
    help="The committed corpus: decides which specifications to rebuild."
    " Defaulted for the repository's own workspace copy, never an installed one.",
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
    help="Directory with per-spec correction modules. Defaulted here, unlike"
    " extract's and correct's, because this one exists to rebuild the repository's"
    " own corpus from its own edit layers.",
)
@click.option(
    "--transcriptions",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_TRANSCRIPTIONS,
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

    Needs the `seanchai[extract]` extra and a checkout: the defaults name its
    corpus and edit layers.
    """
    _require_extract()
    from . import regenerate as library

    if not manifest.is_file():
        raise click.ClickException(
            f"{manifest} does not exist: run `seanchai download`, which writes it"
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
            f" `seanchai download {fetch}`, or name what it holds with --spec"
        )
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
    show_default="stdout",
    help="Output .dad path.",
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
        with _naming(source):
            text = source.read_text(encoding="utf-8")
            spec, comments = parser.parse_with_comments(text)
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
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--check",
    is_flag=True,
    help="Print a diff for each file not in canonical form instead of"
    " rewriting it, and exit non-zero if there is one.",
)
@click.option(
    "--raw",
    is_flag=True,
    help="Also read the raw files under a directory named in SOURCES.",
)
def format_command(sources: tuple[Path, ...], check: bool, raw: bool) -> None:
    """Rewrite `.dad` files in canonical form, keeping their `;;` comments.

    SOURCES are files or directories, a directory standing for the `.dad` files
    under it, less its raw mirror unless --raw. Every file is parsed before any
    is written, so one that does not parse leaves all of them as they were. A
    trailing comment stays on its line,
    a whole-line comment stays before the line that followed it, and a
    block of comments stays before the section that followed it.
    """
    import difflib

    from .dad import formatter, parser

    files = _dad_files(sources, raw=raw)
    changed: list[tuple[Path, str, str]] = []
    for source in files:
        # Untranslated both ways: canonical form ends lines with "\n" alone,
        # and a file with "\r\n" endings is one to rewrite, not one that
        # reads as canonical because the newlines were translated away.
        with _naming(source):
            text = source.read_text(encoding="utf-8", newline="")
            spec, comments = parser.parse_with_comments(text)
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
        f"{verb} {len(changed)} of {len(files)} files",
        err=True,
    )
    if check and changed:
        raise SystemExit(1)


@main.command()
@click.argument(
    "sources",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--raw",
    is_flag=True,
    help="Also read the raw files under a directory named in SOURCES.",
)
@click.option(
    "--notes/--no-notes",
    default=True,
    help="Report findings a single file cannot judge.",
)
@click.option(
    "--corpus",
    "corpus_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    show_default="the installed seanchai-corpus, if any",
    help="Directory or file to resolve re-used AVPs against. Enables the"
    " cross-file rules; repeatable.",
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
    help="`full` groups findings under their file with a summary;"
    " `concise` prints one greppable `file: severity: [rule] ...` line per"
    " finding.",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_CORRECTIONS,
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
    raw: bool,
    notes: bool,
    corpus_paths: tuple[Path, ...],
    no_corpus: bool,
    output_format: str,
    corrections: Path,
    show_accepted: bool,
) -> None:
    """Report structural inconsistencies in `.dad` files.

    SOURCES are files or directories, a directory standing for the `.dad` files
    under it, less its raw mirror unless --raw; none means the corpus the
    seanchai-corpus package installed. Exits non-zero when any error is found;
    notes alone do not fail, because they are things a single file cannot decide
    rather than defects.

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
        for source in _dad_files(sources or (installed_directory(),), raw=raw):
            with _naming(source):
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
@click.option("--release", type=int, default=18, help="3GPP release.")
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
    " whose PDF is published. --no-pdfs is for catalog"
    " experiments only: it strips pdf_url from the manifest and lets"
    " the newest archive replace a committed spec's docx with a version whose"
    " PDF is unpublished.",
)
@click.option("--list", "list_only", is_flag=True, help="Print the catalog and exit.")
@click.option(
    "--only",
    multiple=True,
    type=click.Choice(SOURCES),
    help="Fetch only this source, keeping what the manifest holds of the others;"
    " `wireshark` and `rfc` are small and need no extra. Repeatable.",
)
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
    only: tuple[str, ...],
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

    With --only, one source is fetched and the manifest keeps what it holds of
    the others. What the download cache holds is not fetched again, by this run
    or a later full one.

    A 3GPP or oneM2M download needs the `seanchai[extract]` extra, to validate
    what it fetched.
    """
    from .downloader import download_corpus, download_version, load_catalog

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
    """What `sources` of the catalog hold, the hand transcriptions with a full
    listing, since no download fetches them."""
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
    if len(sources) == len(SOURCES):
        click.echo(
            f"\nHand transcriptions, not downloaded ({len(catalog.transcribed)}):"
        )
        for document in catalog.transcribed:
            click.echo(f"  {document.reference}: {document.title}")
    if "wireshark" in sources:
        click.echo(
            f"\nWireshark Diameter dictionary: {catalog.wireshark.path}"
            f" at {catalog.wireshark.tag}"
        )


@main.command()
@click.argument(
    "sources",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--dictionary",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("specifications") / "wireshark",
    help="Directory holding Wireshark's Diameter dictionary files, which"
    " `seanchai download --only wireshark` fetches.",
)
@click.option(
    "--aliases",
    type=click.Path(dir_okay=False, path_type=Path),
    default=_DEFAULT_ALIASES,
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
    _need_dictionary(dictionary)
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
    from .dad import formatter

    text = formatter.format_spec(spec, notes or formatter.Comments())
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        sections = click.style(f"({len(spec.sections)} sections)", dim=True)
        click.echo(f"wrote {click.style(str(output), bold=True)} {sections}", err=True)
