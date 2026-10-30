"""A set of parsed `.dad` files, and the rules for resolving between them.

A single file names the documents it borrows from but not the versions:
`ReusedAvpRow.origin` is `TS29.272`, never `TS29.272 V18.6.0`. The rule this
module implements: **match the major version, and among the candidates that
match, take the newest**; RFC numbers name immutable documents and resolve to
whatever the corpus holds, as does a document outside 3GPP and IETF (ETSI,
3GPP2, OMA, oneM2M), whose versions are its publisher's and share no release
axis with the citing document's. The reasoning — why nothing resolves across a major
version, and why the corpus layout mirrors the rule — is in
docs/linter.md#resolving-an-origin.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .dad import ast, parser


class CorpusError(ValueError):
    pass


# A document its citers number otherwise than its publisher does, by the
# reference a From cell carries. TS 29.212 (clause 2, [37]: "ETSI TS 283 034
# v2.2.0"), 29.219, 29.273 and 32.299 cite the e4 document as a Technical
# Specification; ETSI publishes V2.2.0 as an ETSI Standard, ES 283 034, the
# title its transcription carries, and has no TS 283 034. One entry per
# misnaming, never a fuzzy match.
CITED_AS = {"ETSI-TS283.034": "ETSI-ES283.034"}


def _version_key(version: str | None) -> tuple[int, ...]:
    """`"18.6.0"` → `(18, 6, 0)`, for ordering. Non-numeric parts sort as 0
    rather than raising: the grammar already restricts a version to digits and
    dots, so this only ever softens a hand-edited file. A version-less file
    (an RFC) sorts as the empty key; RFC resolution never compares versions
    anyway, because one number names one immutable document."""
    if version is None:
        return ()
    parts = []
    for part in version.split("."):
        parts.append(int(part) if part.isdigit() else 0)
    return tuple(parts)


def _major(version: str) -> int:
    return _version_key(version)[0]


def _external(spec: ast.Specification) -> bool:
    """Whether `spec` is another publisher's document. A title naming no
    supported document (a hand-authored vendor extension) is not."""
    try:
        return ast.is_external(ast.spec_ref(spec.specification))
    except ast.SpecRefError:
        return False


@dataclass(frozen=True)
class Entry:
    """One parsed file and where it came from."""

    path: Path
    spec: ast.Specification

    @property
    def reference(self) -> str:
        """`TS29.272` — the spelling a re-used row uses."""
        return ast.spec_ref(self.spec.specification)


class Corpus:
    """Parsed `.dad` files, indexed by the reference re-used rows cite."""

    def __init__(self, entries: Iterable[Entry]) -> None:
        self._by_reference: dict[str, list[Entry]] = {}
        for entry in entries:
            self._by_reference.setdefault(entry.reference, []).append(entry)
        for candidates in self._by_reference.values():
            candidates.sort(key=lambda e: _version_key(e.spec.version), reverse=True)

    @classmethod
    def load(cls, paths: Iterable[Path], *, raw: bool = False) -> Corpus:
        """Parse every `.dad` file in `paths`, recursing into directories.

        Raw files are skipped by default. A corpus mixing raw and corrected
        copies of one specification would hold two versions of the same
        document that disagree on purpose, and resolution would pick between
        them by version number — which they share.
        """
        entries = []
        for path in cls._files(paths):
            if path.name.endswith(".raw.dad") != raw:
                continue
            try:
                spec = parser.parse(path.read_text(encoding="utf-8"))
            except ValueError as error:  # DadParseError and pydantic alike
                raise CorpusError(f"{path}: {error}") from error
            entries.append(Entry(path=path, spec=spec))
        return cls(entries)

    @staticmethod
    def _files(paths: Iterable[Path]) -> Iterator[Path]:
        for path in paths:
            if path.is_dir():
                yield from sorted(path.rglob("*.dad"))
            else:
                yield path

    def __iter__(self) -> Iterator[Entry]:
        for candidates in self._by_reference.values():
            yield from candidates

    def __len__(self) -> int:
        return sum(len(c) for c in self._by_reference.values())

    def versions(self, reference: str) -> list[str]:
        return [
            entry.spec.version
            for entry in self._candidates(reference)
            if entry.spec.version is not None
        ]

    def _candidates(self, reference: str) -> list[Entry]:
        """The copies `reference` names, newest first, through `CITED_AS`."""
        return self._by_reference.get(CITED_AS.get(reference, reference), [])

    def resolve(self, reference: str, *, like: ast.Specification) -> Entry | None:
        """The file `reference` names, read as the specification `like` would.

        `like` supplies the major version to match. A reference its citers
        spell otherwise than the publisher (`CITED_AS`) resolves to the
        publisher's document. Returns `None` when the
        corpus holds no copy in that major version — which is a gap in the
        corpus, not a defect in the document, and callers report it that way.
        """
        candidates = self._candidates(reference)
        if reference.startswith("RFC") or ast.is_external(reference):
            # An RFC number names one immutable document; there is no release
            # axis to match against. Nor is there for another publisher's
            # document: ETSI TS 283 034 V2.2.0 is no Release 2 of anything
            # 3GPP numbers. The corpus holds such a document only when someone
            # writes it by hand, and then the newest copy is the answer.
            return candidates[0] if candidates else None
        if _external(like):
            # An ETSI version is no 3GPP release, so it says nothing about
            # which release a citation means; the document says that in its
            # references (TS 183 017 V3.2.1 cites "3GPP TS 29.214 Release
            # 7"), and nothing resolves across releases.
            return None
        version = like.version
        if version is None:
            # A version-less document (an RFC) citing a versioned one has no
            # release of its own to match, so the newest copy is the answer.
            return candidates[0] if candidates else None
        wanted = _major(version)
        for entry in candidates:  # newest first
            # A version-less candidate has no major version to match; only an
            # RFC or an external document may be version-less, and neither
            # reaches this branch.
            if entry.spec.version is not None and _major(entry.spec.version) == wanted:
                return entry
        return None
