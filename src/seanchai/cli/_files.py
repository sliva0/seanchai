"""`seanchai lint` and `seanchai format`: check and rewrite `.dad` files, the
corpus's or a consumer's own."""

from __future__ import annotations

import contextlib
from pathlib import Path

import click

from ._base import (
    _DEFAULT_CORPUS,
    _DEFAULT_CORRECTIONS,
    _dad_files,
    _naming,
    main,
    reported,
)


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
    help="Directory or file to resolve re-used AVPs against, enabling the"
    " cross-file rules. Repeatable.",
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
    help="`full` groups findings by file with a summary; `concise` prints one"
    " `file: severity: [rule] ...` line per finding.",
)
@click.option(
    "--corrections",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_CORRECTIONS,
    help="Directory with correction modules whose acceptances mark deliberate"
    " overrides; used only with a corpus. Executes Python from it. The default"
    " is read only inside the repository and may be missing.",
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

    SOURCES are files or directories; a directory means its `.dad` and `.dadx`
    files, without the raw mirror unless --raw. With no SOURCES, lints the
    installed corpus. Exits 1 if any error is found; notes alone do not fail.

    A `.dadx` file, a document's interpretations, is read as its blocks: their
    syntax, rules, ids and clause order, and with a corpus the constraint
    rules in each copy of the document a block's range spans, as if merged.

    Re-used AVPs resolve against --corpus, else the installed corpus; with
    neither, or with --no-corpus, each file is linted alone. An origin missing
    from the corpus is a note. A finding a correction module accepts is
    `accepted` and hidden unless --show-accepted; an acceptance matching no
    finding is an error. Raw (`.raw.dad`) files are linted without
    acceptances. The corpus's record of known holes is linted too: an unlisted
    hole and an entry naming no hole are errors.
    """
    from ..corpus import Corpus, CorpusNotInstalledError, installed_directory
    from ..dad import corrections as corrections_module
    from ..dad import interpretations, parser
    from ..linter import Severity, lint_interpretations, lint_record, lint_with_corpus
    from ..linter import lint as lint_spec

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

    def report(source: Path | str, findings: list) -> None:
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
            if source.suffix == interpretations.SUFFIX:
                tree, declared = interpretations.read(source)
                checked += 1
                for entry, findings in lint_interpretations(
                    tree.interprets, declared, books
                ):
                    report(f"{source} (in {entry.path.name})", findings)
                continue
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


def _echo_findings(source: Path | str, findings) -> None:
    """Print one file's findings under its path, errors first."""
    from ..linter import Severity

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
    from ..linter import Severity

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
    help="Print diffs instead of rewriting, and exit 1 if any file would change.",
)
@click.option(
    "--raw",
    is_flag=True,
    help="Also read the raw files under a directory named in SOURCES.",
)
def format_command(sources: tuple[Path, ...], check: bool, raw: bool) -> None:
    """Rewrite `.dad` files in canonical form, keeping their `;;` comments.

    SOURCES are files or directories; a directory means its `.dad` and `.dadx`
    files, without the raw mirror unless --raw. A `.dadx` file holds a
    document's interpretations. Every file is parsed before any is
    written, so a parse error leaves all files unchanged. Comments stay with
    the line or section they precede, or on their line if trailing.
    """
    import difflib

    from ..dad import formatter, parser

    files = _dad_files(sources, raw=raw)
    changed: list[tuple[Path, str, str]] = []
    for source in files:
        # Untranslated both ways: canonical form ends lines with "\n" alone,
        # and a file with "\r\n" endings is one to rewrite, not one that
        # reads as canonical because the newlines were translated away.
        with _naming(source):
            text = source.read_bytes().decode("utf-8")
            if source.suffix == ".dadx":
                tree, notes = parser.parse_interpretations_with_comments(text)
                canonical = formatter.format_interpretations(tree, notes)
            else:
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
