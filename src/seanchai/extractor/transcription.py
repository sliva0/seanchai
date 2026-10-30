"""Reader for a transcription: a document no extractor reads, copied by hand.

ETSI ES 283 034, TS 183 017 and 3GPP2 X.S0057 exist only as PDF. A person
writes each in `.dad` notation under `edits/transcriptions/<SpecRef>.dad`,
copying what the document prints, misprints included, even where the
grammar cannot hold it (TS 183 017's `< AVP Header: x >`, X.S0057's
`5535/9010` code cell). This module is the extractor's place in the
pipeline for it: the input patches of `edits/sources/<SpecRef>.toml` apply
to the transcription's text, and the patched text must parse. The result
is the raw file; corrections take it from there, as for any other.

    transcription → input patches → raw → corrections → corrected

A patch's text unit is one line of the transcription, a `;;` comment's
included, so a note quoting what a patch repairs counts as a match; its
`section` scope is the `; Section:` of the block the line sits in, so a
patch can be narrowed to one clause as a 3GPP patch is. The transcription
carries its `; Transcribed:` header itself; nothing here adds or checks
it.
"""

import re
from pathlib import Path

from ..dad import ast, formatter, parser
from . import sources
from .errors import ExtractionError, boundary

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

    The header is read before patching, to name the declarations file and
    the version their ranges are compared with; a transcription whose header
    the patches would have to repair is not one this reads.
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
