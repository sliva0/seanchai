"""Reader for a transcription: a document no extractor reads, copied by hand.

The ETSI, 3GPP2 and OMA documents the corpus holds exist only as PDF. Each is
written in `.dad` notation under `edits/transcriptions/<SpecRef>.dad`,
misprints included. The input patches of `edits/sources/<SpecRef>.toml` apply
to its text, the patched text must parse, and the result is the raw file that
corrections then take.

A patch's text unit is one line, `;;` comments included. Its `section` scope
is the `; Section:` of the block the line sits in. The transcription carries
its own `; Transcribed:` header; nothing here adds or checks it.
"""

import re
from pathlib import Path

from ..dad import ast, formatter, parser
from . import sources
from .errors import ExtractionError, boundary

__all__ = ["QUIRKS", "patched", "read"]

# A transcription has no extractor readings to enable.
QUIRKS: dict[str, str] = {}

_SPECIFICATION_RE = re.compile(r"^; Specification: (?P<value>.+)$", re.MULTILINE)
_VERSION_RE = re.compile(r"^; Version: (?P<value>.+)$", re.MULTILINE)
# A directive may carry a trailing `;;` comment, as any `.dad` line may.
_SECTION_RE = re.compile(r"^; Section: (?P<value>\S+)(?: *;;.*)?$")


def patched(
    path: Path,
    sources_dir: Path | None = None,
    warnings: list[str] | None = None,
) -> str:
    """The transcription's text with its input patches applied.

    The header is read before patching, for the declarations file and the
    version their ranges are compared with, so patches cannot repair it.
    """
    with boundary(f"reading transcription {path}"):
        text = path.read_text(encoding="utf-8")
        specification = _SPECIFICATION_RE.search(text)
        if specification is None:
            raise ExtractionError(f"{path}: no '; Specification:' line")
        version = _VERSION_RE.search(text)
        declarations = (
            sources_dir / f"{ast.spec_ref(specification['value'])}.toml"
            if sources_dir is not None
            else None
        )
        patcher, _ = sources.load(
            declarations,
            None if version is None else version["value"],
            QUIRKS,
            warnings,
        )
        lines = []
        for block in text.split("\n\n"):
            section = next(
                (
                    match["value"]
                    for line in block.splitlines()
                    if (match := _SECTION_RE.match(line))
                ),
                None,
            )
            lines.append(
                "\n".join(patcher.apply(line, section) for line in block.split("\n"))
            )
        patcher.finish()
        return "\n\n".join(lines)


def read(
    path: Path,
    sources_dir: Path | None = None,
    warnings: list[str] | None = None,
) -> tuple[ast.Specification, formatter.Comments]:
    """The raw tree and its comments: the patched transcription, parsed."""
    text = patched(path, sources_dir, warnings)
    try:
        return parser.parse_with_comments(text)
    except ValueError as error:
        raise ExtractionError(f"{path}, patched: {error}") from error
