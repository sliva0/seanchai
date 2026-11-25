"""Reader for a transcription: a document no extractor reads, copied by hand.

The ETSI, 3GPP2 and OMA documents the corpus holds exist only as PDF. Each is
written in `.dad` notation under `edits/transcriptions/<SpecRef>.dad`,
misprints included. The input patches of `edits/sources/<SpecRef>.toml` apply
to its text, the patched text must parse, and the result is the raw file that
corrections then take.

A patch's text unit is one line, `;;` comments included. Its `section` scope
is the `; Section:` of the block the line sits in. The transcription carries
its own `; Transcribed:` header; nothing here adds or checks it.

No extractor reads the document, so the interpreted constraints written for
it are held to the text of the PDF it was copied from (`pdf_clause_texts`).
"""

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from ..dad import ast, formatter, parser
from ..errors import MissingExtraError
from . import sources
from .errors import ExtractionError, boundary

__all__ = ["QUIRKS", "clause_texts_of", "patched", "pdf_clause_texts", "read"]

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


# The running header ETSI prints atop each page, the page number run on:
# "ETSI", then "ETSI TS 183 017 V3.2.1 (2010-02)15".
_PDF_HEADER_RE = re.compile(
    r"^ETSI(?: (?:TS|ES|EN|TR|EG) [\d ]+ V\d+\.\d+\.\d+ \(\d{4}-\d{2}\)\d*)?$"
)
# An outline title's clause number: "7.3.9", "A.1.2", "B.1".
_CLAUSE_RE = re.compile(r"^(?P<number>(?:\d+|[A-Z])(?:\.\d+)*)(?=\s)")


def clause_texts_of(
    pages: Sequence[str], outline: Sequence[tuple[int, str]]
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Each clause's text and page, from a PDF's pages' text and its outline
    of (1-based page, title) entries, in order: the text from the line a
    clause's heading opens to the next heading's, the running headers
    dropped, lines joined with a space, or with none after a word's hyphen
    breaking it across a line ("Binding-" over "Input-List"), and whitespace
    collapsed. What `interpretations.check_quotes` holds a transcription's
    quotes to, the clause's text one paragraph."""
    lines: list[tuple[int, str]] = []
    for number, text in enumerate(pages, start=1):
        for line in text.splitlines():
            line = line.strip()
            if line and not _PDF_HEADER_RE.match(line):
                lines.append((number, line))
    marks: list[tuple[str, int, int]] = []
    start = 0
    for page, title in outline:
        found = _CLAUSE_RE.match(title.strip())
        if found is None:
            continue
        heading = found["number"] + " "
        for index in range(start, len(lines)):
            at, line = lines[index]
            if at >= page and " ".join(line.split()).startswith(heading):
                marks.append((found["number"], page, index))
                start = index + 1
                break
    texts: dict[str, list[str]] = {}
    numbers: dict[str, int] = {}
    for position, (number, page, index) in enumerate(marks):
        end = marks[position + 1][2] if position + 1 < len(marks) else len(lines)
        joined = ""
        for _, line in lines[index + 1 : end]:
            if len(joined) > 1 and joined[-1] == "-" and joined[-2].isalnum():
                joined += line
            else:
                joined += f" {line}" if joined else line
        texts.setdefault(number, []).append(" ".join(joined.split()))
        numbers.setdefault(number, page)
    return texts, numbers


def pdf_clause_texts(
    pdf_path: Path | str,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Each clause's text and page in the PDF a transcription was copied
    from (`clause_texts_of`), read with pypdf, which the `extract` extra
    installs."""
    try:
        import pypdf
    except ImportError as error:  # pragma: no cover - the extra is the dev group's
        raise MissingExtraError("reading a transcription's PDF") from error
    with boundary(f"reading clause texts from {pdf_path}"):
        # A font pypdf cannot fully decode warns through logging; the text
        # read is the same.
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = pypdf.PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        outline: list[tuple[int, str]] = []

        def walk(entries) -> None:
            for entry in entries:
                if isinstance(entry, list):
                    walk(entry)
                    continue
                # pypdf types `get_page_number` as optional; it resolves for
                # a real outline, as `tgpp_docx.clause_pages` reads it.
                number = reader.get_page_number(entry.page or reader.pages[0])
                if number is not None:
                    outline.append((number + 1, str(entry.title or "")))

        walk(reader.outline)
        return clause_texts_of(pages, outline)
