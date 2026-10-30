"""A set of parsed `.dad` files, and the rules for resolving between them.

A single file names the documents it borrows from but not the versions:
`ReusedAvpRow.origin` is `TS29.272`, never `TS29.272 V18.6.0`. The rule this
module implements is the drafting rules' on references (3GPP TR 21.801
clauses 6.6.6.5.2-6.6.6.5.3, ETSI SR 001 262 clauses 12.3-12.4, and each
citing document's clause 2): **a specific reference means the version it
names; a non-specific one the latest version in the citing document's
release, the newest copy of that major**; and where the cited document
ended before that release, its final version. The version a specific
reference names is not in the `.dad` file but in the citing document's
references clause, so it is recorded here (`CITED_VERSIONS`), as are the
final versions (`FINAL_VERSIONS`, which the downloader verifies). RFC
numbers name immutable documents and resolve to whatever the corpus holds,
as does a document outside 3GPP and IETF (ETSI, 3GPP2, OMA, oneM2M), whose
versions are its publisher's and share no release axis with the citing
document's. The reasoning, and what a resolution across releases reports,
is in docs/consumers.md#resolution-across-releases and
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


# The version a *specific* reference names, by (citing, cited) reference,
# read from the citing document's references clause: "For a specific
# reference, subsequent revisions do not apply" (TS 183 017 V3.2.1 clause 2,
# oneM2M TS-0004 V2.35.0 clause 2: "only the cited version applies"). A
# reference naming a release means that release's last version, which the
# downloader's catalog pins with `final = "release"` and checks against the
# 3GPP archive. A citation absent here is non-specific.
CITED_VERSIONS: dict[tuple[str, str], str] = {
    # ETSI TS 183 017 V3.2.1 clause 2.1, [4] ETSI TS 129 209: "Universal
    # Mobile Telecommunications System (UMTS); Policy control over Gq
    # interface (3GPP TS 29.209 Release 6)". V6.8.0 is Release 6's last.
    ("ETSI-TS183.017", "TS29.209"): "6.8.0",
    # The same clause, [19] ETSI TS 129 214: "Universal Mobile
    # Telecommunications System (UMTS); LTE; Policy and charging control
    # over Rx reference point (3GPP TS 29.214 Release 7)". V7.12.0 is
    # Release 7's last.
    ("ETSI-TS183.017", "TS29.214"): "7.12.0",
    # oneM2M TS-0004 V2.35.0 clause 2.1, [31] 3GPP TS 32.299:
    # "Telecommunication management; Charging management; Diameter charging
    # applications (Release 11)". V11.20.0 is Release 11's last.
    ("oneM2M-TS-0004", "TS32.299"): "11.20.0",
}

# A document's final version: the last 3GPP published, in any release. A
# non-specific reference from a release after it means it, there being no
# version in the citing document's release to mean (the extension of TR
# 21.801 clause 6.6.6.5.3, "the latest version of the referenced TS or TR
# in the Release in question", this corpus makes; docs/consumers.md). The
# downloader's catalog pins each with `final = "document"` and fails a
# download whose archive listing holds a later version.
FINAL_VERSIONS: dict[str, str] = {
    # TS 29.140 (MM10) ends at Release 7; TS 32.299 clause 2 [213] cites it
    # non-specifically.
    "TS29.140": "7.0.0",
    # TS 29.209 (Gq) ends at Release 6, superseded by TS 29.214; ETSI ES
    # 283 034 V2.2.0 clause 2 [5] cites it non-specifically, "ETSI TS 129
    # 209: ... (3GPP TS 29.209)".
    "TS29.209": "6.8.0",
}

# `CrossRelease.rule`'s values: the drafting rule a resolution followed.
SPECIFIC = "specific"
NON_SPECIFIC = "non-specific"


@dataclass(frozen=True)
class CrossRelease:
    """A citation resolved outside the citing document's release, and the
    rule that allowed it: `SPECIFIC`, the version the citing document's
    references name (`CITED_VERSIONS`), or `NON_SPECIFIC`, the cited
    document's final version (`FINAL_VERSIONS`). A document outside 3GPP
    has no release, so each of its 3GPP citations that resolves is one."""

    citing: str  # "TS32.299"
    cited: str  # "TS29.140"
    version: str  # "7.0.0", the copy resolved to
    rule: str

    def __str__(self) -> str:
        if self.rule == SPECIFIC:
            why = f"the reference names V{self.version} (corpus.CITED_VERSIONS)"
        else:
            why = (
                f"the reference is non-specific and V{self.version} is the"
                " document's final version (corpus.FINAL_VERSIONS)"
            )
        return f"{self.citing} cites {self.cited}: {why}"


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

    def newest(self) -> Iterator[Entry]:
        """The newest copy of each reference: what the corpus answers for a
        document when no citation asks for an older release. TS 32.299
        V11.20.0, held for oneM2M TS-0004's "Release 11" citation, is
        reached through `resolve` only."""
        for candidates in self._by_reference.values():
            yield candidates[0]

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
        """The file `reference` names, read as the specification `like` would
        (`resolution`). Returns `None` when the corpus holds no copy the
        rules allow — which is a gap in the corpus, not a defect in the
        document, and callers report it that way.
        """
        return self.resolution(reference, like=like)[0]

    def resolution(
        self, reference: str, *, like: ast.Specification
    ) -> tuple[Entry | None, CrossRelease | None]:
        """The file `reference` names when `like` cites it, and, when that
        file is outside `like`'s release, how the citation got there.

        In order: a reference its citers spell otherwise than the publisher
        (`CITED_AS`) is the publisher's document. An RFC, or a document
        outside 3GPP, is whatever copy the corpus holds. A specific
        reference (`CITED_VERSIONS`) is the version it names and no other.
        A 3GPP document's non-specific one is the newest copy in its own
        major version, and failing one, the cited document's final version
        when that ended in an earlier release (`FINAL_VERSIONS`); the
        corpus may lack the version of a release the document still had.
        A document outside 3GPP has no release, so its non-specific
        reference is the final version or nothing.
        """
        candidates = self._candidates(reference)
        if reference.startswith("RFC") or ast.is_external(reference):
            # An RFC number names one immutable document; there is no release
            # axis to match against. Nor is there for another publisher's
            # document: ETSI TS 283 034 V2.2.0 is no Release 2 of anything
            # 3GPP numbers. The corpus holds such a document only when someone
            # writes it by hand, and then the newest copy is the answer.
            return (candidates[0] if candidates else None), None
        citing = _reference(like)
        version = like.version
        external = _external(like)
        named = CITED_VERSIONS.get((citing, reference))
        if named is not None:
            entry = next((e for e in candidates if e.spec.version == named), None)
            if entry is None:
                return None, None
            same = (
                not external
                and version is not None
                and _major(version) == _major(named)
            )
            return entry, None if same else CrossRelease(
                citing, reference, named, SPECIFIC
            )
        if not external and version is None:
            # A version-less document (an RFC) citing a versioned one has no
            # release of its own to match, so the newest copy is the answer.
            return (candidates[0] if candidates else None), None
        if not external:
            assert version is not None
            wanted = _major(version)
            for entry in candidates:  # newest first
                # A version-less candidate has no major version to match;
                # only an RFC or an external document may be version-less,
                # and neither reaches this branch.
                if (
                    entry.spec.version is not None
                    and _major(entry.spec.version) == wanted
                ):
                    return entry, None
        final = FINAL_VERSIONS.get(reference)
        if final is None or (not external and _major(final) >= _major(version or "0")):
            # An ETSI version is no 3GPP release, so it says nothing about
            # which release a non-specific citation means; only a document
            # that ended means one version whatever the release. A 3GPP
            # citing document of the final version's release or earlier may
            # mean a version the corpus lacks.
            return None, None
        entry = next((e for e in candidates if e.spec.version == final), None)
        if entry is None:
            return None, None
        return entry, CrossRelease(citing, reference, final, NON_SPECIFIC)


def _reference(spec: ast.Specification) -> str:
    """`spec`'s reference, or its title where it names no supported
    document (a hand-authored vendor extension)."""
    try:
        return ast.spec_ref(spec.specification)
    except ast.SpecRefError:
        return spec.specification
