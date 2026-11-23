"""The `seanchai` group and what its commands share.

Library failures are `SeanchaiError`s; `reported()` prints them as an
`error: ...` line. Any other exception is a bug and is left as a traceback.
Exit status 1 means an error or a finding, 2 a usage error.

Commands that read source documents need the `seanchai[extract]` extra and
import it themselves.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from ..errors import SeanchaiError

if TYPE_CHECKING:
    # The `dad` modules are imported only by the commands that use them.
    pass

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
# `wireshark.EXPLORER`, spelt here so that help imports no corpus code.
_EXPLORER = "https://sliva0.github.io/seanchai-explorer/"


class _HelpFormatter(click.HelpFormatter):
    """Help with `Usage:` and section headings in bold green.

    Wrapping ignores the ANSI codes, and `click.echo` strips them when output
    is not a terminal.
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
    """A group whose help uses `_HelpFormatter` and whose failures print
    through `_show_error`.

    Click has no hook for how it prints a failure, so `main` runs Click in
    non-standalone mode and handles the raised failure itself. Only the
    outermost group's `main` runs. Help lists commands in definition order.
    """

    context_class = _Context
    command_class = _Command
    group_class = type

    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(self.commands)

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
def reported() -> Generator[None]:
    """Turn a `SeanchaiError` into a CLI error."""
    try:
        yield
    except SeanchaiError as error:
        raise click.ClickException(str(error)) from None


@contextlib.contextmanager
def _naming(source: Path) -> Generator[None]:
    """Report a `.dad` file that fails to parse or decode as an error naming it."""
    from ..dad.parser import DadParseError

    try:
        yield
    except (DadParseError, UnicodeDecodeError) as error:
        raise click.ClickException(f"{source}: {error}") from None


def _dad_files(sources: Iterable[Path], *, raw: bool = False) -> list[Path]:
    """The files `sources` name, each once, a directory expanded to its `.dad`
    files. A directory's raw mirror is skipped unless `raw` or the directory is
    the mirror itself."""
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


def _need_wireshark(directory: Path) -> None:
    """Refuse a directory with no Wireshark dictionary, saying how to fetch one."""
    if not (directory / "dictionary.xml").is_file():
        raise click.ClickException(
            f"{directory} holds no Wireshark dictionary: run"
            " `seanchai corpus download --only wireshark`"
        )


def _require_extract() -> None:
    """Refuse to run without the `seanchai[extract]` extra."""
    from ..downloader.core import require_extra

    with reported():
        require_extra()


@click.group(cls=_Group, context_settings={"show_default": True})
@click.version_option(package_name="seanchai")
def main() -> None:
    """Seanchaí: Diameter specifications as reviewable `.dad` files.

    `show`, `commands`, `dictionary`, `export` and `wireshark-plugin` read the
    installed corpus.
    `lint` and `format` check and rewrite `.dad` files. The `corpus` group
    maintains the corpus in a checkout of the repository.
    """


def _as_json(value: object) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))
