"""The corpus's record of its corrections, as data.

A corrected `.dad` file cites `TS29.272.py#area-scope-code`, and what that
citation means lives in `edits/corrections/`: executable Python, which no wheel
ships and nothing should have to run to read a corpus. So `seanchai regenerate`
writes what a reader needs from those modules into the corpus, next to
`holes.toml`: `corrections.json`, per document, each declaration's kind and
reason, what an acceptance accepts, and the renames a raw file's spellings link
through (docs/corrections.md#the-corrections-record).

The modules stay the source. A test holds the committed file to them, as the
sources test holds the committed `.dad` files to the downloads.
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import pydantic

from .corpus import Corpus, CorpusError
from .dad import ast, corrections

RECORD_NAME = "corrections.json"

_NOTE = "Written by `seanchai regenerate` from edits/corrections; do not edit."


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class RecordedEdit(_Model):
    """A declaration that changes the file."""

    kind: Literal["correction", "delete", "insert", "supply"]
    reason: str


class RecordedAcceptance(_Model):
    """An acceptance: the linter finding it acknowledges, with the tree paths
    its selector reached in the corrected file, so that matching it against a
    finding needs no module."""

    kind: Literal["accept"]
    reason: str
    rule: str
    expect: str
    targets: tuple[ast.TreePath, ...]


class Rename(_Model):
    """A correction of a name: a raw file spells `expect` what the corrected
    one spells `replace`."""

    expect: str
    replace: str


class RecordedDocument(_Model):
    """What one corpus file's module declares for that file's release."""

    reference: str
    version: str | None
    # By citation, `TS29.272.py#area-scope-code`.
    edits: dict[
        str,
        Annotated[
            RecordedEdit | RecordedAcceptance, pydantic.Field(discriminator="kind")
        ],
    ]
    # In declaration order, which is the order a raw spelling is followed in.
    renames: tuple[Rename, ...]

    @classmethod
    def of(
        cls,
        spec: ast.Specification,
        declarations: Sequence[corrections.Declaration],
    ) -> RecordedDocument:
        """The record of `declarations`, read against the corrected `spec`."""
        edits: dict[str, RecordedEdit | RecordedAcceptance] = {}
        renames = []
        for item in declarations:
            if isinstance(item, corrections.Accept):
                edits[item.cited] = RecordedAcceptance(
                    kind="accept",
                    reason=item.reason,
                    rule=item.rule,
                    expect=item.expect,
                    targets=tuple(path for path, _ in item.target.locate(spec)),
                )
                continue
            kind = type(item).__name__.lower()
            edits[item.cited] = RecordedEdit.model_validate(
                {"kind": kind, "reason": item.reason}
            )
            if (
                isinstance(item, corrections.Correction)
                and item.field == "name"
                and isinstance(item.expect, str)
                and isinstance(item.replace, str)
            ):
                renames.append(Rename(expect=item.expect, replace=item.replace))
        return cls(
            reference=ast.spec_ref(spec.specification),
            version=spec.version,
            edits=edits,
            renames=tuple(renames),
        )

    def acceptances(self) -> list[corrections.Accept]:
        """The acceptances as `linter.accept` takes them, sorted by citation."""
        found = []
        for cited, item in sorted(self.edits.items()):
            if isinstance(item, RecordedAcceptance):
                origin, _, identifier = cited.partition("#")
                found.append(
                    corrections.Accept(
                        id=identifier,
                        rule=item.rule,
                        target=_Recorded(item.targets),
                        expect=item.expect,
                        reason=item.reason,
                        origin=origin,
                    )
                )
        return found


@dataclass(frozen=True)
class _Recorded(corrections.Selector):
    """The nodes an acceptance's selector reached when the record was written.
    A path the tree no longer has matches nothing, so the acceptance reads as
    stale, as a selector matching nothing does."""

    paths: tuple[ast.TreePath, ...]

    def locate(
        self, spec: ast.Specification
    ) -> Iterator[tuple[ast.TreePath, ast.Node]]:
        for path in self.paths:
            try:
                yield path, ast.node_at(spec, path)
            except AttributeError, IndexError, TypeError:
                continue

    def describe(self) -> str:
        return "its recorded target"


class CorrectionRecord(_Model):
    """A corpus's corrections, by document file stem. A file whose module
    declares nothing for its release has no entry."""

    note: str = _NOTE
    documents: dict[str, RecordedDocument]

    def render(self) -> str:
        """The file's text: sorted, one field per line, so that a changed
        reason is a one-line diff."""
        return (
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                indent=1,
            )
            + "\n"
        )


def build(books: Corpus, corrections_directory: Path) -> CorrectionRecord:
    """The record of every file in `books`, from the modules in
    `corrections_directory`, which loading executes."""
    documents = {}
    for entry in books:
        declarations = corrections.in_release(
            corrections.load(corrections_directory, entry.spec.specification),
            entry.spec.version,
        )
        if declarations:
            documents[entry.path.stem] = RecordedDocument.of(entry.spec, declarations)
    return CorrectionRecord(documents=documents)


def write(corpus: Path, corrections_directory: Path) -> Path | None:
    """Rewrite `corpus`'s record from what it now holds, if it holds anything."""
    books = Corpus.load([corpus])
    if not len(books):
        return None
    path = corpus / RECORD_NAME
    path.write_text(build(books, corrections_directory).render(), encoding="utf-8")
    return path


def load(path: Path) -> CorrectionRecord:
    """Read a record, refusing with `CorpusError` what is not one."""
    try:
        return CorrectionRecord.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise CorpusError(f"{path}: {error}") from error
