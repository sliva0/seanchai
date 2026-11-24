"""The consumer commands: `show`, `commands`, `dictionary`, `diff`, `vectors`,
`export` and `wireshark-plugin`, which read the installed corpus or
another."""

from __future__ import annotations

import difflib
from pathlib import Path

import click

from ._base import _EXPLORER, _as_json, _need_wireshark, main, reported


def _flags(rules) -> str:
    """Flag rules by column, empty columns left out."""
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
    """`(vendor-id, code)` from `10415:601`, or None for a name. AVP names hold
    no colon, so a malformed identity is an error."""
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
    """The AVP `seanchai show` shows; raises `ModelError` if there is none."""
    from ..model import ModelError

    identity = _identity_of(query)
    if document is None:
        found = built.definition(identity or query)
        holes = [hole for hole in built.holes() if hole.name == query]
    elif identity is None:
        found = built.resolve(document, query, version=version)
        hole = built.hole(document, query, version=version)
        holes = [] if hole is None else [hole]
    else:
        names = {avp.name for avp in built.readings(identity)}
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
    """The fields in which `other` differs from `avp`."""
    from ..model import Enumerated

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
    """Print one reading of an AVP and how the others differ from it."""
    from ..dad import ast, formatter
    from ..model import Enumerated, Grouped

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
            elif isinstance(value, ast.VoidValues):
                click.echo(f"    void {value.first}-{value.last}")
            else:
                click.echo(f"    vendor-specific {value.first}-{value.last}")
    for table in avp.value_tables:
        which = f" of {table.application}" if table.application else ""
        if table.feature_list_id is not None:
            which += f" list {table.feature_list_id}"
        label = f", table {table.table}" if table.table else ""
        click.echo(
            f"  {table.kind}{which} ({table.reference}, clause {table.section}{label}):"
        )
        for row in table.rows:
            tail = " ".join(
                part
                for part in (
                    row.section or row.mark,
                    row.origin and f"from {row.origin}",
                )
                if part
            )
            click.echo(f"    {row.value} {row.name}" + (f" ; {tail}" if tail else ""))
    if others:
        click.echo("  other readings:")
        for other in others:
            click.echo(f"    {other.read_through}: {_difference(avp, other)}")


def _corpus_options(command):
    """`--corpus` and `--with`, which choose the corpus a command reads."""
    command = click.option(
        "--with",
        "layers",
        multiple=True,
        type=click.Path(exists=True, path_type=Path),
        help="Your own `.dad` file or directory, read beside the corpus:"
        " proprietary AVPs and commands. Repeatable.",
    )(command)
    return click.option(
        "--corpus",
        "corpus_paths",
        multiple=True,
        type=click.Path(exists=True, path_type=Path),
        help="Directory or file to read instead of the installed corpus. Repeatable.",
    )(command)


def _corpus(corpus_paths: tuple[Path, ...], layers: tuple[Path, ...]):
    """The corpus a consumer command reads, and the holes its model allows:
    the installed corpus's recorded ones, or for another corpus or one with
    your own files beside it, any, which the output then lists."""
    from ..corpus import Corpus
    from ..model import HolePolicy

    if corpus_paths:
        return Corpus.load([*corpus_paths, *layers]), HolePolicy.ANY
    if layers:
        return Corpus.installed(extra=layers), HolePolicy.ANY
    return Corpus.installed(), HolePolicy.RECORDED


@main.command()
@click.argument("name_or_identity", metavar="NAME_OR_IDENTITY")
@click.option(
    "--document",
    metavar="REF",
    help="Read the AVP as this document does.",
)
@click.option(
    "--version",
    "version",
    metavar="V",
    help="With --document: read an older copy of that document.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print JSON in the dictionary's shapes.",
)
@_corpus_options
def show(
    name_or_identity: str,
    document: str | None,
    version: str | None,
    as_json: bool,
    corpus_paths: tuple[Path, ...],
    layers: tuple[Path, ...],
) -> None:
    """Show one AVP of the installed corpus.

    NAME_OR_IDENTITY is a name or VENDOR:CODE, such as `Session-Id` or
    `10415:601`. Prints the defining document's reading and how other
    documents' readings differ. A name two AVPs claim is refused, and a name
    the corpus cannot complete is reported with the reason.

    --json prints a `seanchai.dictionary.Lookup`: the requested reading first,
    then the other readings, then every AVP their bodies name
    (docs/consumers.md).
    """
    from ..dictionary import lookup
    from ..model import Model

    if version is not None and document is None:
        raise click.UsageError("--version needs --document")
    with reported():
        books, holes = _corpus(corpus_paths, layers)
        built = Model.build(books, holes=holes)
        avp = _reading(built, name_or_identity, document, version)
        found = lookup(built, avp, corpus_version=books.version) if as_json else None
        others = [other for other in built.readings(avp.identity) if other != avp]
    if found is not None:
        _as_json(found.model_dump(mode="json"))
    else:
        _echo_avp(avp, others)


@main.command()
@click.argument("reference", metavar="[REF]", required=False)
@click.option(
    "--application",
    type=int,
    metavar="ID",
    help="Only commands of this application id.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print JSON in the dictionary's shapes.",
)
@_corpus_options
def commands(
    reference: str | None,
    application: int | None,
    as_json: bool,
    corpus_paths: tuple[Path, ...],
    layers: tuple[Path, ...],
) -> None:
    """List the installed corpus's commands.

    REF is a document, as `TS29.229` or "TS 29.229". With neither REF nor
    --application, lists every command. Each line has the command code,
    request or answer, the application id (`-` if none is stated), the name,
    and the defining document and section.

    --json prints a `seanchai.dictionary.Listing`, commands without bodies.
    """
    from ..dictionary import listing
    from ..model import Model, ModelError

    with reported():
        books, holes = _corpus(corpus_paths, layers)
        applications = Model.build(books, holes=holes).applications(
            reference, application_id=application
        )
        if application is not None and not applications:
            raise ModelError(
                f"no application {application}"
                f"{'' if reference is None else f' in {reference}'}:"
                " `seanchai commands` lists them"
            )
    if as_json:
        found = listing(applications, corpus_version=books.version)
        _as_json(found.model_dump(mode="json"))
        return
    table = [("CODE", "KIND", "APPLICATION", "NAME", "DOCUMENT", "SECTION")] + [
        (
            str(message.command_code),
            "request" if message.is_request else "answer",
            "-" if message.application_id is None else str(message.application_id),
            f"{message.name} ({message.abbreviation})",
            message.defined_in,
            message.section,
        )
        for each in applications
        for message in each.messages
    ]
    widths = [max(len(cells[i]) for cells in table) for i in range(len(table[0]))]
    for cells in table:
        line = "  ".join(
            cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
        )
        click.echo(line.rstrip())


def _write_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise click.ClickException(str(error)) from None


@main.command("dictionary")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="The JSON file to write. Required unless --schema is given.",
)
@click.option(
    "--document",
    "documents",
    multiple=True,
    metavar="REF",
    help="Only this document's applications and AVPs. Repeatable.",
)
@click.option(
    "--version",
    "version",
    metavar="V",
    help="With one --document: read that held version of it.",
)
@click.option(
    "--application",
    "application_ids",
    multiple=True,
    type=int,
    metavar="ID",
    help="Only this application id's commands and their AVPs. Repeatable.",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Refuse, writing nothing, if the selection reaches a name the corpus"
    " cannot complete.",
)
@click.option(
    "--policy",
    type=click.Choice(["hole", "drop", "placeholder", "supply"]),
    default="hole",
    help="How to handle names the corpus declares undefined: keep as holes,"
    " drop, keep as untyped placeholders, or read from --supply and --alias.",
)
@click.option(
    "--supply",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="A `.dad` sidecar defining undefined names, for --policy supply. Repeatable.",
)
@click.option(
    "--alias",
    "aliases",
    multiple=True,
    nargs=3,
    metavar="NAME REF TARGET",
    help="Read the undefined NAME as REF's AVP TARGET, for --policy supply."
    " Repeatable.",
)
@click.option(
    "--wireshark",
    type=click.Path(file_okay=False, path_type=Path),
    help="Wireshark's Diameter dictionary (specifications/wireshark), to give"
    " each AVP its `wireshark_name`.",
)
@click.option(
    "--schema",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the file's JSON Schema here.",
)
@_corpus_options
def dictionary_command(
    output: Path | None,
    documents: tuple[str, ...],
    version: str | None,
    application_ids: tuple[int, ...],
    strict: bool,
    policy: str,
    supply: tuple[Path, ...],
    aliases: tuple[tuple[str, str, str], ...],
    wireshark: Path | None,
    schema: Path | None,
    corpus_paths: tuple[Path, ...],
    layers: tuple[Path, ...],
) -> None:
    """Write the installed corpus as one JSON dictionary.

    The file holds applications with their commands, and AVPs with identity,
    type, flags, values and members (docs/consumers.md). The same corpus and
    options give the same bytes. --schema writes the JSON Schema of this file,
    of `show --json` and of `commands --json`.

    \b
    S6a, refusing what the corpus cannot complete:
        seanchai dictionary --application 16777251 --strict -o s6a.json
    Your own AVPs beside the corpus:
        seanchai dictionary --document TS29.272 --with acme.dad -o out.json
    """
    import json

    from ..dictionary import build, dumps, json_schema
    from ..model import (
        Alias,
        Model,
        Supplied,
        SupplyKey,
        UndefinedPolicy,
        supplied_from,
    )

    if output is None and schema is None:
        raise click.UsageError("give -o/--output, --schema or both")
    if version is not None and len(documents) != 1:
        raise click.UsageError("--version needs exactly one --document")
    undefined = UndefinedPolicy(policy)
    if (undefined is UndefinedPolicy.SUPPLY) != bool(supply or aliases):
        raise click.UsageError(
            "--policy supply goes with --supply or --alias, and they with it"
        )
    if wireshark is not None:
        _need_wireshark(wireshark)
    if schema is not None:
        _write_text(
            schema,
            json.dumps(json_schema(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
        )
        click.echo(f"wrote {click.style(str(schema), bold=True)}", err=True)
    if output is None:
        return
    with reported():
        books, holes = _corpus(corpus_paths, layers)
        answers: dict[SupplyKey, Supplied | Alias] = {
            name: answer for name, answer in supplied_from(*supply).items()
        }
        for name, reference, target in aliases:
            if name in answers:
                raise click.BadParameter(
                    f"{name} is both supplied and aliased", param_hint="'--alias'"
                )
            answers[name] = Alias(
                reference, target, source=f"--alias {name} {reference} {target}"
            )
        built = Model.build(
            books,
            holes=holes,
            wireshark=wireshark,
            undefined=undefined,
            supply=answers or None,
        )
        written = build(
            built,
            corpus_version=books.version,
            documents=documents,
            application_ids=application_ids,
            version=version,
            strict=strict,
        )
    _write_text(output, dumps(written))
    commands = sum(len(each.commands) for each in written.applications)
    click.echo(
        f"wrote {click.style(str(output), bold=True)}"
        f" ({len(written.applications)} applications, {commands} commands,"
        f" {len(written.avps)} AVPs, {len(written.holes)} holes,"
        f" {len(written.conflicts)} conflicts)",
        err=True,
    )


@main.command("export")
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to replace. It must be absent, empty or a previous export.",
)
@click.option(
    "--corpus",
    "corpus_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory or file to export instead of the installed corpus. Repeatable.",
)
@click.option(
    "--wireshark",
    type=click.Path(file_okay=False, path_type=Path),
    help="Wireshark's Diameter dictionary (specifications/wireshark), to add its"
    " AVP names to the search index.",
)
@click.option(
    "--corrections",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Read correction reasons from the <SpecRef>.py modules here instead of"
    " corrections.json. This executes Python from the directory.",
)
@click.option(
    "--specifications",
    type=click.Path(file_okay=False, path_type=Path),
    help="A `seanchai corpus download` directory to copy RFC texts from.",
)
@click.option(
    "--include-pdfs",
    is_flag=True,
    help="Copy every source PDF into the export, for self-hosting. Needs"
    " --specifications.",
)
def export_command(
    output: Path,
    corpus_paths: tuple[Path, ...],
    wireshark: Path | None,
    corrections: Path | None,
    specifications: Path | None,
    include_pdfs: bool,
) -> None:
    """Export the corpus as JSON for the static site.

    Writes index.json, search.json, schema.json, syntax/dad.tmLanguage.json
    and, per document, documents/<id>.json and documents/<id>.raw.json
    (docs/website.md). The export replaces the output directory only once it
    succeeds. ETSI's PDFs are not for public redistribution, so a public site
    leaves out --include-pdfs.

    \b
    Public site, no source PDFs:
        seanchai export -o site/data
    Self-hosted, source PDFs beside it:
        seanchai export -o site/data \\
            --include-pdfs --specifications specifications
    """
    from ..corpus import Corpus
    from ..export import export_corpus

    if include_pdfs and specifications is None:
        raise click.UsageError(
            "--include-pdfs needs --specifications,"
            " a `seanchai corpus download` directory"
        )
    if wireshark is not None:
        _need_wireshark(wireshark)
    if specifications is not None and not specifications.is_dir():
        fetch = "--only 3gpp" if include_pdfs else "--only rfc"
        raise click.ClickException(
            f"{specifications} does not exist: run `seanchai corpus download {fetch}`"
        )
    with reported():
        try:
            books = Corpus.load(corpus_paths) if corpus_paths else Corpus.installed()
            export_corpus(
                books,
                output,
                wireshark=wireshark,
                corrections_directory=corrections,
                specifications=specifications,
                include_pdfs=include_pdfs,
            )
        except OSError as error:
            raise click.ClickException(str(error)) from None


@main.command("wireshark-plugin")
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="The Lua file to write.",
)
@click.option(
    "--application",
    "application_ids",
    multiple=True,
    type=int,
    metavar="ID",
    help="Only this application id's commands and their AVPs. Repeatable.",
)
@click.option(
    "--document",
    "documents",
    multiple=True,
    metavar="REF",
    help="Only this document's applications and AVPs. Repeatable.",
)
@click.option(
    "--corpus",
    "corpus_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory or file to read instead of the installed corpus. Repeatable.",
)
@click.option(
    "--explorer",
    default=_EXPLORER,
    metavar="URL",
    help="The explorer site references link to, the plugin's default for its"
    " seanchai.explorer_url preference; '' for none.",
)
@click.option(
    "--rules-only",
    is_flag=True,
    help="Write the rules alone, as a Lua chunk returning them, for running"
    " core.lua outside Wireshark.",
)
def wireshark_plugin_command(
    output: Path,
    application_ids: tuple[int, ...],
    documents: tuple[str, ...],
    corpus_paths: tuple[Path, ...],
    explorer: str,
    rules_only: bool,
) -> None:
    """Write a Wireshark plugin that checks Diameter traffic against the corpus.

    One Lua file for Wireshark's plugin directory, which reports each message's
    breaches of its documents as a subtree, expert info and seanchai.* fields,
    each citing the clause its rule is written at (docs/wireshark-plugin.md).
    Regenerate it after upgrading the corpus.

    \b
    Installed for Wireshark:
        seanchai wireshark-plugin \\
            -o ~/.local/lib/wireshark/plugins/seanchai_diameter.lua
    Cx and Rx only:
        seanchai wireshark-plugin --application 16777216 \\
            --application 16777236 -o seanchai_diameter.lua
    """
    from ..corpus import Corpus
    from ..wireshark import PluginError, generate

    with reported():
        books = Corpus.load(corpus_paths) if corpus_paths else Corpus.installed()
        try:
            plugin = generate(
                books,
                documents=documents,
                application_ids=application_ids,
                explorer=explorer,
                rules_only=rules_only,
            )
        except PluginError as error:
            raise click.BadParameter(str(error), param_hint="'--explorer'") from None
    try:
        plugin.write(output)
    except OSError as error:
        raise click.ClickException(str(error)) from None
    click.echo(
        f"wrote {click.style(str(output), bold=True)} ({plugin.versions},"
        f" {plugin.applications} applications, {plugin.avps} AVPs)",
        err=True,
    )


@main.command("diff")
@click.argument("old", type=click.Path(exists=True, path_type=Path))
@click.argument("new", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--document",
    "documents",
    multiple=True,
    metavar="REF",
    help="Compare this document's applications and AVPs. Repeatable. Two files:"
    " their documents by default; two corpora: every document.",
)
@click.option(
    "--application",
    "application_ids",
    multiple=True,
    type=int,
    metavar="ID",
    help="Compare only this application id's commands. Repeatable.",
)
@click.option(
    "--corpus",
    "corpus_paths",
    multiple=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="With two files: the corpus they are read in, instead of the installed"
    " one. Repeatable.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the diff as JSON.")
@click.option(
    "--schema",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the JSON Schema of `--json`'s output here, and exit.",
)
def diff_command(
    old: Path,
    new: Path,
    documents: tuple[str, ...],
    application_ids: tuple[int, ...],
    corpus_paths: tuple[Path, ...],
    as_json: bool,
    schema: Path | None,
) -> None:
    """Compare OLD with NEW as a Diameter stack sees them.

    OLD and NEW are two `.dad` files of one document, each read in the
    installed corpus (or --corpus) in place of its copy, or two corpus
    directories. Commands match by application id, code and direction, AVPs
    by vendor-id and code; each change is breaking, compatible or editorial,
    with the command paths it affects. Where the raw mirror of both sides is
    found (a `raw/` tree beside the file, as `corpus regenerate -o` writes
    it), each change also says whether it comes from the document, our
    corrections or our extraction.

    \b
    Two versions of TS 29.272, the older extracted into a scratch directory:
        seanchai corpus regenerate --spec TS29.272 -o old \\
            --manifest specifications/versions/TS29.272/18.6.0/manifest.json
        seanchai diff old/3gpp/rel-18/29272-i60.dad NEW.dad
    """
    import json

    from .. import diff as library

    if schema is not None:
        _write_text(
            schema,
            json.dumps(
                library.json_schema(), ensure_ascii=False, sort_keys=True, indent=2
            )
            + "\n",
        )
        click.echo(f"wrote {click.style(str(schema), bold=True)}", err=True)
        return
    if old.is_dir() != new.is_dir():
        raise click.UsageError("give two .dad files or two corpus directories")
    if corpus_paths and old.is_dir():
        raise click.UsageError("--corpus goes with two files")
    with reported():
        found = _diff(library, old, new, documents, application_ids, corpus_paths)
    if as_json:
        click.echo(library.dumps(found), nl=False)
    else:
        click.echo(library.render(found), nl=False)


def _diff(library, old, new, documents, application_ids, corpus_paths):
    """Build both sides' models, and their raw mirrors' where found, and
    compare them."""
    from ..corpus import Corpus
    from ..dad import ast, parser
    from ..model import HolePolicy, Model

    def built(books):
        return Model.build(books, holes=HolePolicy.ANY)

    if old.is_dir():
        sides = [Corpus.load([old]), Corpus.load([new])]
        raws = (
            [Corpus.load([old], raw=True), Corpus.load([new], raw=True)]
            if (old / "raw").is_dir() and (new / "raw").is_dir()
            else None
        )
    else:
        base = Corpus.load(list(corpus_paths)) if corpus_paths else Corpus.installed()
        sides = [library.overlay(base, [old]), library.overlay(base, [new])]
        mirrors = [_raw_mirror(old), _raw_mirror(new)]
        raws = None
        if None not in mirrors:
            raw_base = (
                Corpus.load(list(corpus_paths), raw=True)
                if corpus_paths
                else Corpus.installed(raw=True)
            )
            raws = [library.overlay(raw_base, [path]) for path in mirrors]
        if not documents:
            documents = tuple(
                sorted(
                    {
                        ast.spec_ref(
                            parser.parse(path.read_text("utf-8")).specification
                        )
                        for path in (old, new)
                    }
                )
            )
    models = [built(books) for books in sides]
    return library.diff(
        models[0],
        models[1],
        documents=documents,
        application_ids=application_ids,
        raw=None if raws is None else (raws[0], raws[1]),
        corpus_versions=(sides[0].version, sides[1].version),
    )


def _raw_mirror(path: Path) -> Path | None:
    """The raw file beside a corrected one: `raw/` under an ancestor, at the
    same place (`corpus regenerate -o` writes them so), or None."""
    path = path.resolve()
    for root in path.parents:
        candidate = (
            root / "raw" / path.relative_to(root).with_name(f"{path.stem}.raw.dad")
        )
        if candidate.is_file():
            return candidate
    return None


@main.command("vectors")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="The JSON file to write. Required unless --schema is given.",
)
@click.option(
    "--application",
    "application_ids",
    multiple=True,
    type=int,
    metavar="ID",
    help="Only this application id's commands. Repeatable.",
)
@click.option(
    "--document",
    "documents",
    multiple=True,
    metavar="REF",
    help="Only this document's commands. Repeatable.",
)
@click.option(
    "--policy",
    type=click.Choice(["hole", "drop", "placeholder"]),
    default="hole",
    help="How to handle names the corpus declares undefined, as `dictionary`"
    " does; a required one the corpus cannot complete skips its command.",
)
@click.option(
    "--pcap",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the vectors as a capture, TCP to port 3868.",
)
@click.option(
    "--schema",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the file's JSON Schema here.",
)
@_corpus_options
def vectors_command(
    output: Path | None,
    application_ids: tuple[int, ...],
    documents: tuple[str, ...],
    policy: str,
    pcap: Path | None,
    schema: Path | None,
    corpus_paths: tuple[Path, ...],
    layers: tuple[Path, ...],
) -> None:
    """Write test messages for a stack's own tests.

    Per command: a minimal valid message, a maximal one, and negative ones,
    each breaking one rule (a required AVP missing, an M bit against its rule,
    a void value, an interpreted constraint...), with its octets, a readable
    tree, the rule and where it is written, and the finding the Wireshark
    plugin reports (docs/consumers.md).

    \b
    S6a's, as JSON and as a capture:
        seanchai vectors --application 16777251 -o s6a.json --pcap s6a.pcap
    """
    import json

    from .. import vectors
    from ..dictionary import build
    from ..model import Model, UndefinedPolicy

    if output is None and schema is None:
        raise click.UsageError("give -o/--output, --schema or both")
    if schema is not None:
        _write_text(
            schema,
            json.dumps(
                vectors.json_schema(), ensure_ascii=False, sort_keys=True, indent=2
            )
            + "\n",
        )
        click.echo(f"wrote {click.style(str(schema), bold=True)}", err=True)
    if output is None:
        return
    with reported():
        books, holes = _corpus(corpus_paths, layers)
        built = Model.build(books, holes=holes, undefined=UndefinedPolicy(policy))
        written = vectors.build(
            build(
                built,
                corpus_version=books.version,
                documents=documents,
                application_ids=application_ids,
            ),
            vectors.pages_of(books),
        )
    _write_text(output, vectors.dumps(written))
    if pcap is not None:
        try:
            pcap.parent.mkdir(parents=True, exist_ok=True)
            pcap.write_bytes(vectors.pcap(written))
        except OSError as error:
            raise click.ClickException(str(error)) from None
    negative = sum(1 for each in written.vectors if each.kind == "negative")
    click.echo(
        f"wrote {click.style(str(output), bold=True)}"
        f" ({len(written.vectors)} vectors, {negative} negative,"
        f" {len(written.skipped)} skipped)",
        err=True,
    )
