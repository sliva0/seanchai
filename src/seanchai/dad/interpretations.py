"""Interpreted constraints: what a clause's prose says of an AVP's value or
presence, as a person read it, pinned to the sentences read.

A document's are written by hand, in the block syntax itself, in its
interpretations file, `edits/interpretations/<SpecRef>.dadx`: a
`; Interprets:` header naming the document, then one Interpreted
Constraints block per AVP and scope a clause speaks of, each with an
`; Id:` and no `; Page:`, in the document's clause order
(`parser.parse_interpretations`). The suffix keeps a corpus loader, which
reads `*.dad`, from taking the file for a document.

`corrections.apply` merges each `Interpretation` into the corrected file as
an `Interpreted Constraints` block, in clause order beside the clause it
reads, after the document's corrections; the regenerate step checks every
quote against the source document's clause first (`check_quotes`) and
places the block on that clause's page in the copy (`paged`).
docs/constraints.md describes the kinds and codecs.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import ast, parser
from ._errors import CorrectionError

__all__ = [
    "SUFFIX",
    "Interpretation",
    "check_quotes",
    "file_path",
    "load",
    "paged",
    "parse",
    "read",
]

SUFFIX = ".dadx"


@dataclass(frozen=True)
class Interpretation:
    """One block of an interpretations file, as `corrections.apply` merges
    it: constraints read from one clause about one AVP, in one scope.

    `path` is the file it was read from and `lines` the line each of its
    lines prints on, the `; Type:` line first, then each quote and rule, so
    a failure names the line to fix. `page` is the clause's page in the
    copy being corrected (`paged`); a block merged without the source
    carries none. `from_pdf` marks a transcription's block, whose quotes are
    held to the text of the PDF the document was copied from rather than an
    extracted source: its note in the corrected file says so.
    """

    block: ast.InterpretationBlock
    path: Path | None = None
    lines: tuple[int, ...] = ()
    page: int | None = None
    from_pdf: bool = False

    @property
    def id(self) -> str:
        return self.block.id

    @property
    def origin(self) -> str:
        """The file a `.dad` note cites, `TS29.272.dadx`."""
        return "" if self.path is None else self.path.name

    @property
    def cited(self) -> str:
        """How a `.dad` note and the corrections record cite the block:
        `TS29.272.dadx#imei-digits`."""
        return f"{self.origin}#{self.id}" if self.origin else self.id

    @property
    def section(self) -> str:
        return self.block.source.section

    @property
    def versions(self) -> str:
        """The block's range, every version where its document has none (an
        RFC's block names no `; Versions:`, `check_versions`)."""
        return self.block.versions or "*..*"

    @property
    def readings(self) -> tuple[ast.Reading, ...]:
        return self.block.readings

    @property
    def node(self) -> ast.InterpretedConstraints:
        """The block the corrected file prints: no id, the copy's page."""
        merged = self.block.merged
        if self.page is None:
            return merged
        return merged.model_copy(
            update={"source": ast.SourceRef(section=self.section, page=self.page)}
        )

    @property
    def reason(self) -> str:
        """What the record says of it: the clause and the quotes read."""
        quotes = "; ".join(
            f"'{quote}'" for each in self.readings for quote in each.quotes
        )
        table = self.block.table
        where = f"table {table}" if table else f"clause {self.section}"
        of = " of the PDF" if self.from_pdf else ""
        return f"interpreted from {where}{of}: {quotes}"

    def at(self, index: int | None = None) -> str:
        """Where the block, or its body's `index`-th line, is written, for a
        message: `edits/interpretations/TS29.272.dadx:640: imei-digits`."""
        if self.path is None or not self.lines:
            return self.id
        line = self.lines[0] if index is None else self.lines[index + 1]
        return f"{self.path}:{line}: {self.id}"

    def scope(self) -> str:
        """The AVP and where it is constrained, for messages."""
        block = self.block
        if block.command is not None and block.command_section is not None:
            return f"{block.avp} in {block.command} ({block.command_section})"
        if block.command is not None:
            return f"{block.avp} in {block.command}"
        if block.within is not None and block.application_id is not None:
            return f"{block.avp} in {block.within} (application {block.application_id})"
        if block.within is not None:
            return f"{block.avp} in {block.within}"
        return block.avp


def file_path(directory: Path, specification: str) -> Path:
    """The interpretations file for `specification` in `directory`, named by
    its `SpecRef`: `TS29.272.dadx`."""
    try:
        reference = ast.spec_ref(specification)
    except ast.SpecRefError as error:
        raise CorrectionError(str(error)) from None
    return directory / f"{reference}{SUFFIX}"


def parse(
    text: str, path: Path | None = None
) -> tuple[ast.Interpretations, list[Interpretation]]:
    """Parse an interpretations file's `text`: its tree, and each block as
    `corrections.apply` merges it, read from `path` where one is given. A
    malformed file raises `parser.DadParseError` at the line."""
    tree, lines = parser.parse_interpretations(text)
    return tree, [
        Interpretation(
            block=block,
            path=path,
            lines=(
                lines[("sections", index, "type")],
                *(
                    lines[("sections", index, "body", item)]
                    for item in range(len(block.body))
                ),
            ),
        )
        for index, block in enumerate(tree.sections)
    ]


def read(path: Path) -> tuple[ast.Interpretations, list[Interpretation]]:
    """`parse` the interpretations file at `path`; a malformed one raises
    `CorrectionError` naming it and the line."""
    try:
        return parse(path.read_text(encoding="utf-8"), path)
    except (parser.DadParseError, UnicodeDecodeError) as error:
        raise CorrectionError(f"{path}: {error}") from None


def load(directory: Path | None, specification: str) -> list[Interpretation]:
    """The blocks of `specification`'s interpretations file in `directory`,
    in the file's order; none without a directory or a file. A file whose
    `; Interprets:` names another document is refused."""
    if directory is None:
        return []
    path = file_path(directory, specification)
    if not path.is_file():
        return []
    tree, found = read(path)
    if ast.spec_ref(tree.interprets) != ast.spec_ref(specification):
        raise CorrectionError(
            f"{path}: interprets {tree.interprets!r}, not {specification!r}"
        )
    return found


def _normalize(text: str) -> str:
    """Whitespace collapsed as the extractors collapse it, so a quote spans
    a line break or a double space as the clause prints it."""
    return " ".join(text.replace("\xa0", " ").split())


def _enclosing(section: str) -> list[str]:
    """`section` and each clause containing it, nearest first: a quote may
    be what a clause above prints for its subclauses, as RFC 6733 clause 10
    gives the symbols of clause 10.1's table, "0 The AVP MUST NOT be present
    in the message".
    """
    parts = section.split(".")
    return [".".join(parts[:count]) for count in range(len(parts), 0, -1)]


def check_versions(declared: Sequence[Interpretation], version: str | None) -> None:
    """Check that every block of `declared` names the range of versions its
    quotes were checked against where its document, at `version`, has
    versions, and none where it has one edition and no version, an RFC.

    Raises `CorrectionError` naming every block that does not, at its line.
    """
    misses = []
    for each in declared:
        if version is None and each.block.versions is not None:
            misses.append(
                f"{each.at()}: names '; Versions: {each.block.versions}', and"
                " the document has one edition and no version"
            )
        elif version is not None and each.block.versions is None:
            misses.append(
                f"{each.at()}: names no '; Versions:', the range of the"
                " document's versions its quotes were checked against"
            )
    if misses:
        raise CorrectionError("; ".join(misses))


def check_quotes(
    declared: Sequence[Interpretation], clauses: Mapping[str, Sequence[str]]
) -> None:
    """Check every quote of `declared` against the text of its clause:
    `clauses` maps a clause number to its paragraphs and table cells, as the
    extractor read and normalized them. A quote must be within one of them,
    or of a clause containing it (`_enclosing`).

    Raises `CorrectionError` naming every miss with its file and line, as a
    correction's `expect` fails once upstream changes.
    """
    misses = []
    for each in declared:
        if each.section not in clauses:
            misses.append(f"{each.at()}: the document has no clause {each.section}")
            continue
        texts = [
            text
            for clause in _enclosing(each.section)
            for text in clauses.get(clause, ())
        ]
        for index, item in enumerate(each.block.body):
            if not isinstance(item, ast.Quote):
                continue
            if not any(_normalize(item.text) in text for text in texts):
                misses.append(
                    f"{each.at(index)}: clause {each.section} does not print"
                    f" {item.text!r}"
                )
    if misses:
        raise CorrectionError("; ".join(misses))


def paged(
    item: Interpretation,
    pages: Mapping[str, int] | None,
    *,
    from_pdf: bool = False,
) -> Interpretation:
    """`item` placed on its clause's page in `pages`, a clause number's page
    in the copy corrected, its page unchanged without `pages`; with
    `from_pdf`, marked as quoted from a transcription's PDF."""
    if from_pdf:
        item = dataclasses.replace(item, from_pdf=True)
    if pages is None:
        return item
    return dataclasses.replace(item, page=pages.get(item.section))
