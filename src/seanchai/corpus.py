"""A set of parsed `.dad` files, and the rules for resolving between them.

A single file names the documents it borrows from but not the versions:
`ReusedAvpRow.origin` is `TS29.272`, never `TS29.272 V18.6.0`. The rule this
module implements is the drafting rules' on references (3GPP TR 21.801
clauses 6.6.6.5.2-6.6.6.5.3, ETSI SR 001 262 clauses 12.3-12.4, and each
citing document's clause 2): **a specific reference means the version it
names; a non-specific one the latest version in the citing document's
release, the newest copy of that major**; and where the cited document
ended before that release, its final version. RFC numbers name immutable
documents and resolve to whatever the corpus holds, as does a document
outside 3GPP and IETF (ETSI, 3GPP2, OMA, oneM2M), whose versions are its
publisher's and share no release axis with the citing document's, unless
the citation names a 3GPP2 revision: then only that revision answers it, or
a held one an explicit entry lets stand in for it. A non-specific citation
whose release's last version the corpus does not hold resolves to nothing,
unless an entry records the evidence that a held copy of a later release
defines what the citing copy reaches the same way. Where the citation's own
version answers but leaves a field unstated, an entry lets a later release
state that field alone, with the same evidence. The reasoning, and what a
resolution across releases reports, is in
docs/consumers.md#resolution-across-releases and
docs/linter.md#resolving-an-origin.

The facts this needs are the corpus's, not the library's: the version a
specific reference names is in the citing document's references clause, not
in its `.dad` file, and a stand-in is a comparison of two copies. A corpus
directory records them in its `CORPUS_FILE` (`Rules`), beside its `.dad`
files, with the corpus's format (`FORMATS`), and may hold its record of known
holes too (`HOLE_RECORD`): what the corpus cannot complete, each with its
evidence, which the model builds strictly against
(docs/consumers.md#known-holes).
"""

from __future__ import annotations

import enum
import os
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from ._prose import collapse
from .dad import ast, parser
from .errors import SeanchaiError

__all__ = [
    "CORPUS_FILE",
    "FILLABLE",
    "FORMATS",
    "HOLE_RECORD",
    "Citation",
    "CitationRule",
    "Corpus",
    "CorpusError",
    "CorpusFormatError",
    "CorpusNotInstalledError",
    "CrossRelease",
    "Entry",
    "HoleRecord",
    "KnownHole",
    "Missing",
    "ReleaseFill",
    "ReleaseStandIn",
    "Rules",
    "StandIn",
    "installed_directory",
    "revision",
]


class CorpusError(SeanchaiError, ValueError):
    pass


class CorpusNotInstalledError(CorpusError):
    """No path was given and the `seanchai-corpus` package is not installed."""


# The corpus formats this library reads: the generation of the `.dad` grammar
# and of the corpus directory's layout and records a corpus's `CORPUS_FILE`
# states (docs/development.md#the-corpus-format).
FORMATS: tuple[int, ...] = (1,)


class CorpusFormatError(CorpusError):
    """A corpus states a format this library does not read: the library is
    older than the corpus, or the corpus older than any format it reads."""

    def __init__(self, path: Path, found: int) -> None:
        self.path = path
        self.found = found
        self.reads = FORMATS
        upgrade = "seanchai" if found > max(FORMATS) else "seanchai-corpus"
        reads = ", ".join(map(str, FORMATS))
        super().__init__(
            f"{path}: the corpus is format {found}, and seanchai {__version__}"
            f" reads format {reads}: upgrade {upgrade}"
        )


class Missing(enum.StrEnum):
    """What a hole leaves unstated (`model.Hole.missing`, `KnownHole.missing`):
    an `Avp` field, by its name, or the definition itself. `Avp.completed_by`
    and `ReleaseFill.fields` name fields the same way. Every serialized form
    (`to_dict`, the dictionary, the export, `holes.toml`, `corpus.toml`) writes
    the value."""

    VENDOR_ID = "vendor_id"
    CODE = "code"
    DATA_TYPE = "data_type"
    FLAG_RULES = "flag_rules"
    # A name nothing in the corpus defines, tabulates or can be followed to.
    DEFINITION = "definition"
    # A name an `Undefined AVP` block declares defined nowhere.
    UNDEFINED = "undefined"


@dataclass(frozen=True)
class StandIn:
    """A held revision answering a citation of one the corpus cannot hold,
    and the evidence that it cannot."""

    revision: str  # "0"
    version: str  # "2.0"
    evidence: str


@dataclass(frozen=True)
class ReleaseStandIn:
    """A held copy of a later release answering a non-specific citation of
    the version the corpus does not hold, and the evidence that what the
    citing copy reaches is defined alike in both."""

    meant: str  # "11.12.0", the version the citation means
    version: str  # "19.1.0", the copy answering it
    evidence: str
    # The citing document names `meant`, where the corpus cannot pin it: TS 183
    # 033's V6.6.0 is no release's last, which is what the catalog pins.
    specific: bool = False


@dataclass(frozen=True)
class ReleaseFill:
    """Fields the version a citation means leaves unstated for named AVPs, which
    a held copy of a later release states, and the evidence that nothing the
    meant version or the citing document states disagrees."""

    meant: str  # "6.15.0", the version the citation means, which still answers it
    version: str  # "19.1.0", the copy stating the fields
    names: tuple[str, ...]
    fields: tuple[Missing, ...]  # of `FILLABLE`
    evidence: str


# A corpus directory's description of itself, beside its `.dad` files: its
# format and the facts resolution needs (`Rules`).
CORPUS_FILE = "corpus.toml"

# What `ReleaseFill.fields` may name. A code is never taken, since the later
# copy's has to agree.
FILLABLE = (Missing.DATA_TYPE, Missing.FLAG_RULES)

# Each table of `CORPUS_FILE`, by its key, with the fields an entry of it
# states: True for a required one. Every entry states its evidence.
_TABLES: dict[str, dict[str, bool]] = {
    "cited_as": {"cited": True, "document": True},
    "cited_version": {
        "citing": True,
        "citing_version": True,
        "cited": True,
        "version": True,
    },
    "latest_edition": {"citing": True, "citing_version": True, "cited": True},
    "final_version": {"document": True, "version": True},
    "cited_revision": {
        "citing": True,
        "citing_version": True,
        "cited": True,
        "revision": True,
    },
    "stand_in": {
        "citing": True,
        "citing_version": True,
        "cited": True,
        "revision": True,
        "version": True,
    },
    "release_stand_in": {
        "citing": True,
        "citing_version": True,
        "cited": True,
        "meant": True,
        "version": True,
        "specific": False,
    },
    "release_fill": {
        "citing": True,
        "citing_version": True,
        "cited": True,
        "meant": True,
        "version": True,
        "names": True,
        "fields": True,
    },
}
# A citation as the citing copy makes it, which a table read from a references
# clause is keyed by: citing reference, citing version and cited reference,
# ("TS29.212", "19.1.0", "3GPP2-X.S0057"). The version of a version-less
# citing document is "".
type Citation = tuple[str, str, str]

# The fields that are not text.
_LISTS = {"names", "fields"}
_FLAGS = {"specific"}


@dataclass(frozen=True)
class Rules:
    """A corpus's format and the facts resolving between its documents needs,
    each entry citing its evidence: what its `CORPUS_FILE` states, by hand,
    since `regenerate` writes `.dad` files only. Every key is a reference as a
    re-used row's From cell spells it. The empty `Rules()` is a corpus without
    the file: no format to hold it to, and no entries.

    A table read from a citing document's references clause is keyed by the
    citing copy, (citing reference, citing version, cited reference), and
    answers for that copy alone: a references clause changes between
    versions, and the corpus may hold several copies of one document.

    - `cited_as`: a document its citers number otherwise than its publisher,
      the cited reference to the publisher's (ETSI-TS283.034 is ETSI's
      ES 283 034), which answers a raw file's From cell.
    - `cited_versions`: the version a specific reference names, by citing
      copy and cited reference, read from that copy's references clause.
    - `latest_editions`: the evidence, by citing copy and cited reference,
      that a document outside 3GPP means the latest edition by a
      non-specific one.
    - `final_versions`: a document's final version, by reference.
    - `cited_revisions`: the 3GPP2 revision a citation names, by citing copy
      and cited reference; `stand_ins`, keyed the same, a held revision
      answering one of them.
    - `release_stand_ins`: by citing copy and cited reference, a later
      release's copy answering for the version a citation means;
      `release_fills`, keyed the same, one stating fields of named AVPs the
      meant version leaves unstated.
    """

    path: Path | None = None
    format: int | None = None
    cited_as: Mapping[str, str] = field(default_factory=dict)
    cited_versions: Mapping[Citation, str] = field(default_factory=dict)
    latest_editions: Mapping[Citation, str] = field(default_factory=dict)
    final_versions: Mapping[str, str] = field(default_factory=dict)
    cited_revisions: Mapping[Citation, str] = field(default_factory=dict)
    stand_ins: Mapping[Citation, StandIn] = field(default_factory=dict)
    release_stand_ins: Mapping[Citation, ReleaseStandIn] = field(default_factory=dict)
    release_fills: Mapping[Citation, ReleaseFill] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Rules:
        """Read `path`, refusing a format this library does not read with
        `CorpusFormatError`, before anything else of it, and with `CorpusError`
        an unknown table or field, a missing or empty one, an entry stated
        twice, and a stand-in for a revision no citation names. Whether the
        documents it names are held is `check`'s."""
        data = _read_toml(path)
        found = data.get("format")
        if not isinstance(found, int) or isinstance(found, bool):
            raise CorpusError(
                f"{path}: states no corpus format: a top-level `format = 1`"
            )
        if found not in FORMATS:
            raise CorpusFormatError(path, found)
        unknown = set(data) - {"format", *_TABLES}
        if unknown:
            raise CorpusError(
                f"{path}: {', '.join(sorted(unknown))}: not a table of a corpus"
                f" file, which holds format and [[{']], [['.join(_TABLES)}]]"
            )
        tables = {name: _entries(path, data, name) for name in _TABLES}

        def keyed[K, V](
            name: str, key: Callable[[dict[str, Any]], K], value: Callable[..., V]
        ) -> dict[K, V]:
            out: dict[K, V] = {}
            for entry in tables[name]:
                each = key(entry)
                if each in out:
                    shown = (
                        " ".join(map(str, each)) if isinstance(each, tuple) else each
                    )
                    raise CorpusError(f"{path}: [[{name}]] {shown} is stated twice")
                out[each] = value(entry)
            return out

        def triple(entry: dict[str, Any]) -> Citation:
            return entry["citing"], entry["citing_version"], entry["cited"]

        rules = cls(
            path=path,
            format=found,
            cited_as=keyed("cited_as", lambda e: e["cited"], lambda e: e["document"]),
            cited_versions=keyed("cited_version", triple, lambda e: e["version"]),
            latest_editions=keyed("latest_edition", triple, lambda e: e["evidence"]),
            final_versions=keyed(
                "final_version", lambda e: e["document"], lambda e: e["version"]
            ),
            cited_revisions=keyed("cited_revision", triple, lambda e: e["revision"]),
            stand_ins=keyed(
                "stand_in",
                triple,
                lambda e: StandIn(e["revision"], e["version"], e["evidence"]),
            ),
            release_stand_ins=keyed(
                "release_stand_in",
                triple,
                lambda e: ReleaseStandIn(
                    e["meant"], e["version"], e["evidence"], e.get("specific", False)
                ),
            ),
            release_fills=keyed(
                "release_fill",
                triple,
                lambda e: ReleaseFill(
                    e["meant"],
                    e["version"],
                    tuple(e["names"]),
                    tuple(map(Missing, e["fields"])),
                    e["evidence"],
                ),
            ),
        )
        for key in rules.stand_ins:
            if key not in rules.cited_revisions:
                raise CorpusError(
                    f"{path}: [[stand_in]] {' '.join(key)}: no [[cited_revision]]"
                    " of that citing copy names the revision it stands in for"
                )
        return rules

    def check(self, books: Corpus) -> None:
        """Refuse with `CorpusError` an entry naming a document or a copy
        `books` lacks, which would answer no citation: the rules describe the
        corpus beside them, raw mirror alike."""

        def held(
            reference: str, version: str | None = None, letter: str | None = None
        ) -> bool:
            return any(
                (version is None or entry.spec.version == version)
                and (letter is None or revision(entry.spec) == letter)
                for entry in books._candidates(reference)
            )

        def lacks(table: str, what: str) -> CorpusError:
            return CorpusError(
                f"{self.path}: [[{table}]] names {what}, which the corpus lacks"
            )

        for cited, document in self.cited_as.items():
            if books._by_reference.get(cited):
                raise CorpusError(
                    f"{self.path}: [[cited_as]] {cited} is a document the corpus"
                    " holds, not a misnaming"
                )
            if not held(document):
                raise lacks("cited_as", document)
        for document, version in self.final_versions.items():
            if not held(document, version):
                raise lacks("final_version", f"{document} V{version}")
        tables: tuple[tuple[str, Mapping[Citation, object]], ...] = (
            ("cited_version", self.cited_versions),
            ("latest_edition", self.latest_editions),
            ("cited_revision", self.cited_revisions),
            ("stand_in", self.stand_ins),
            ("release_stand_in", self.release_stand_ins),
            ("release_fill", self.release_fills),
        )
        for table, entries in tables:
            for (citing, citing_version, cited), entry in entries.items():
                # Exact, a version-less copy's being "": no entry is a wildcard.
                if not any(
                    (each.spec.version or "") == citing_version
                    for each in books._candidates(citing)
                ):
                    shown = f" V{citing_version}" if citing_version else ""
                    raise lacks(table, f"{citing}{shown}")
                if isinstance(entry, StandIn):
                    if not held(cited, entry.version, entry.revision):
                        raise lacks(
                            table,
                            f"{cited} revision {entry.revision} V{entry.version}",
                        )
                    continue
                versions: list[str | None] = [None]
                if isinstance(entry, ReleaseStandIn):
                    versions = [entry.version]
                elif isinstance(entry, ReleaseFill):
                    versions = [entry.meant, entry.version]
                elif table == "cited_version":
                    assert isinstance(entry, str)
                    versions = [entry]
                for version in versions:
                    if not held(cited, version):
                        raise lacks(
                            table, cited if version is None else f"{cited} V{version}"
                        )


def _read_toml(path: Path) -> dict[str, Any]:
    """`path` parsed, refusing with `CorpusError` a file that cannot be read,
    is not UTF-8 or is not TOML."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CorpusError(f"{path}: {error}") from error


def _entries(path: Path, data: dict[str, Any], table: str) -> list[dict[str, Any]]:
    """`table`'s entries in `data`, each checked against `_TABLES` and its
    evidence collapsed (`seanchai._prose`)."""
    entries = data.get(table, [])
    if not isinstance(entries, list):
        raise CorpusError(f"{path}: {table} must be [[{table}]] tables")
    fields = {**_TABLES[table], "evidence": True}
    required = {name for name, needed in fields.items() if needed}
    checked = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not required <= set(entry)
            or not set(entry) <= set(fields)
        ):
            raise CorpusError(
                f"{path}: a [[{table}]] states {', '.join(sorted(required))}"
                + (
                    f" and may state {', '.join(sorted(set(fields) - required))}"
                    if set(fields) - required
                    else ""
                )
                + f"; this one is {entry!r}"
            )
        for name, value in entry.items():
            if name in _FLAGS:
                good = isinstance(value, bool)
                kind = "true or false"
            elif name in _LISTS:
                good = (
                    isinstance(value, list)
                    and bool(value)
                    and all(isinstance(v, str) and v.strip() for v in value)
                    and len(set(value)) == len(value)
                    and (name != "fields" or set(value) <= set(FILLABLE))
                )
                kind = "a non-empty list of distinct names" + (
                    f" of {', '.join(FILLABLE)}" if name == "fields" else ""
                )
            elif name == "citing_version":
                # "" is the version of a citing document that has none, an RFC.
                good = isinstance(value, str) and (not value or bool(value.strip()))
                kind = 'a version, or "" for a document without one'
            else:
                good = isinstance(value, str) and bool(value.strip())
                kind = "non-empty text"
            if not good:
                raise CorpusError(
                    f"{path}: a [[{table}]]'s {name} must be {kind}, not {value!r}"
                )
        checked.append({**entry, "evidence": collapse(entry["evidence"])})
    return checked


# 3GPP2's name for a rendering, "X.S0057-0_v2.0_091215.pdf": number, part
# where the document has parts ("X.S0013-014-0_v1.0_080224.pdf"), revision,
# version and publication date.
TGPP2_RENDERING_RE = re.compile(
    r"^(?P<number>[A-Z]\.[A-Z]\d{4}(?:-\d{3})?)-(?P<revision>[0-9A-Z])"
    r"_v(?P<version>\d+\.\d+)_\d{6}\.pdf$"
)


class CitationRule(enum.StrEnum):
    """`CrossRelease.rule`: the drafting rule a resolution followed, or
    `STAND_IN`, the `Rules` entry that let another revision (`stand_in`) or a
    later release's copy (`release_stand_in`) answer, or `LATER_RELEASE`, the
    one that let a later release's copy state a field the answer leaves
    unstated (`release_fill`). The dictionary and the export write the
    value."""

    SPECIFIC = "specific"
    NON_SPECIFIC = "non-specific"
    LATEST_EDITION = "latest-edition"
    STAND_IN = "stand-in"
    LATER_RELEASE = "later-release"


@dataclass(frozen=True)
class CrossRelease:
    """A citation resolved outside the citing document's release, and the
    rule that allowed it (`CitationRule`), by an entry of the corpus's
    `Rules`: `SPECIFIC`, the version the citing document's references name
    (`cited_version`),
    `NON_SPECIFIC`, the cited document's final version (`final_version`), or
    `LATEST_EDITION`, the newest copy, where the citing document's clause 2
    says a non-specific reference means it (`latest_edition`). A document
    outside 3GPP has no release, so each of its 3GPP citations that resolves
    is one. `STAND_IN` is a held copy answering a citation of one the corpus
    cannot hold: a 3GPP2 revision for another, a revision being 3GPP2's
    release (`stand_in`), or a later release's copy for the version a
    reference means (`release_stand_in`, `meant` set). `LATER_RELEASE` is a
    later release's copy stating a field of the version the reference means,
    which the corpus holds and which answers for the rest (`release_fill`,
    `meant` set); `Avp.completed_by` names the fields."""

    citing: str  # "TS32.299"
    cited: str  # "TS29.140"
    version: str  # "7.0.0", the copy resolved to
    rule: CitationRule
    # For `STAND_IN`, a 3GPP2 revision being 3GPP2's release: the revision
    # the reference names ("B") and the one resolved to ("0").
    cited_revision: str | None = None
    revision: str | None = None
    # For a `release_stand_in` entry, the version the reference means
    # ("11.12.0"), which the corpus does not hold, and whether the citing
    # document names it. For a `release_fill` entry, the version it means, which
    # the corpus holds.
    meant: str | None = None
    specific: bool = False

    def __str__(self) -> str:
        if self.rule is CitationRule.LATER_RELEASE:
            return (
                f"{self.citing} cites {self.cited} non-specifically, meaning"
                f" V{self.meant}, which leaves a field unstated: V{self.version}"
                " states it (corpus.toml, release_fill)"
            )
        if self.rule is CitationRule.STAND_IN and self.meant is not None:
            how = "naming" if self.specific else "non-specifically, meaning"
            return (
                f"{self.citing} cites {self.cited} {how}"
                f" V{self.meant}, which the corpus lacks: V{self.version} stands"
                " in (corpus.toml, release_stand_in)"
            )
        if self.rule is CitationRule.STAND_IN:
            return (
                f"{self.citing} cites {self.cited} revision {self.cited_revision},"
                f" which the corpus lacks: revision {self.revision}"
                f" V{self.version} stands in (corpus.toml, stand_in)"
            )
        if self.rule is CitationRule.SPECIFIC:
            why = f"the reference names V{self.version} (corpus.toml, cited_version)"
        elif self.rule is CitationRule.LATEST_EDITION:
            why = (
                f"the reference is non-specific and V{self.version} is the latest"
                " edition the corpus holds (corpus.toml, latest_edition)"
            )
        else:
            why = (
                f"the reference is non-specific and V{self.version} is the"
                " document's final version (corpus.toml, final_version)"
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


def revision(spec: ast.Specification) -> str | None:
    """The 3GPP2 revision `spec` is a copy of, which its spec-ref does not
    keep: the one its rendering's name states (`X.S0057-0_v2.0_091215.pdf`
    is revision 0), or None for a document of no such naming."""
    for url in (spec.transcribed, spec.link):
        name = str(url).rsplit("/", 1)[-1] if url is not None else ""
        if match := TGPP2_RENDERING_RE.match(name):
            return match["revision"]
    return None


def _external(spec: ast.Specification) -> bool:
    """Whether `spec` is another publisher's document. A title naming no
    supported document (a hand-authored vendor extension) is not."""
    try:
        return ast.is_external(ast.spec_ref(spec.specification))
    except ast.SpecRefError:
        return False


# A corpus directory's record of known holes, beside its `.dad` files.
HOLE_RECORD = "holes.toml"


@dataclass(frozen=True)
class KnownHole:
    """A hole the record lists: what `model.Hole` will say of it, and why it
    stands."""

    # `Hole.document`: "TS29.234", or "TS29.061 V6.15.0" for an older copy.
    document: str
    name: str
    # `Hole.missing`, compared exactly.
    missing: tuple[Missing, ...]
    # The evidence, as a correction's reason states it: spec version and
    # clause, and what was searched.
    reason: str


@dataclass(frozen=True)
class HoleRecord:
    """A corpus's known holes, hand-maintained: `regenerate` writes `.dad`
    files only, and nothing but the model and the linter reads this."""

    path: Path
    holes: tuple[KnownHole, ...]

    @classmethod
    def load(cls, path: Path) -> HoleRecord:
        """Read `path`, refusing what the model could not hold a build to: an
        unknown key, a missing or empty field, a hole listed twice."""
        data = _read_toml(path)
        tables = data.get("hole", [])
        if set(data) - {"hole"} or not isinstance(tables, list):
            raise CorpusError(f"{path}: only [[hole]] tables belong in a hole record")
        holes = tuple(cls._entry(path, entry) for entry in tables)
        seen: set[tuple[str, str]] = set()
        for hole in holes:
            key = (hole.document, hole.name)
            if key in seen:
                raise CorpusError(
                    f"{path}: {hole.document} {hole.name} is listed twice"
                )
            seen.add(key)
        return cls(path, holes)

    @staticmethod
    def _entry(path: Path, entry: Any) -> KnownHole:
        fields = {"document", "name", "missing", "reason"}
        if not isinstance(entry, dict) or set(entry) != fields:
            raise CorpusError(
                f"{path}: a [[hole]] states exactly {', '.join(sorted(fields))};"
                f" this one is {entry!r}"
            )
        document, name, missing, reason = (
            entry["document"],
            entry["name"],
            entry["missing"],
            entry["reason"],
        )
        texts = [
            document,
            name,
            reason,
            *(missing if isinstance(missing, list) else []),
        ]
        if (
            not isinstance(missing, list)
            or not missing
            or not all(isinstance(text, str) and text.strip() for text in texts)
        ):
            raise CorpusError(
                f"{path}: {document} {name}: document, name and reason must be"
                " non-empty text, and missing a non-empty list of it"
            )
        unknown = sorted(set(missing) - set(Missing))
        if unknown:
            raise CorpusError(
                f"{path}: {document} {name}: missing holds {', '.join(unknown)},"
                f" which is not one of {', '.join(Missing)}"
            )
        return KnownHole(document, name, tuple(map(Missing, missing)), collapse(reason))


def installed_directory() -> Path:
    """The directory the `seanchai-corpus` package put the corpus in.

    The package is an optional dependency (`seanchai[corpus]`), so it is looked
    for only when asked for. Inside this repository it is the workspace copy.
    """
    return _installed_package().CORPUS_DIR


def _installed_package() -> Any:
    try:
        import seanchai_corpus
    except ModuleNotFoundError as error:
        raise CorpusNotInstalledError(
            "the seanchai-corpus package is not installed: install it"
            """ (`pip install "seanchai[corpus]"`) or name a corpus directory"""
        ) from error
    return seanchai_corpus


@dataclass(frozen=True)
class Entry:
    """One parsed file and where it came from."""

    path: Path
    spec: ast.Specification

    @property
    def reference(self) -> str:
        """`TS29.272` — the spelling a re-used row uses."""
        return ast.spec_ref(self.spec.specification)


# What one copy of a document is: its reference, its version and, for a 3GPP2
# document, the revision its spec-ref does not keep.
type _CopyKey = tuple[str, str | None, str | None]


class Corpus:
    """Parsed `.dad` files, indexed by the reference re-used rows cite.

    A file named twice counts once. Two files claiming one reference, version
    and revision raise `CorpusError`. `version` is the installed package's
    version when `installed` loaded it, and None for any other corpus, which
    has no one version to name. `rules` is what resolution reads, the empty
    `Rules()` by default.

    `load` and `installed` are the checked ways in. Constructed directly, from
    entries a caller parsed, a corpus checks only the copies it is given: it
    reads no `CORPUS_FILE`, so no format is held, and takes `rules` and
    `record` as they are, without checking that what they name is held. A
    `model.Model` built over it still holds the build to `record`.
    """

    def __init__(
        self,
        entries: Iterable[Entry],
        record: HoleRecord | None = None,
        version: str | None = None,
        rules: Rules | None = None,
    ) -> None:
        # None for a corpus with no record: a partial or foreign one, or raw.
        self.record = record
        self.version = version
        self.rules = Rules() if rules is None else rules
        self._by_reference: dict[str, list[Entry]] = {}
        # A file reached twice is one copy; two files claiming one copy would
        # leave `newest` and `resolve` to the order they were named in.
        claimed: dict[_CopyKey, Path] = {}
        for entry in entries:
            key = (entry.reference, entry.spec.version, revision(entry.spec))
            first = claimed.get(key)
            if first is None:
                claimed[key] = entry.path
                self._by_reference.setdefault(entry.reference, []).append(entry)
            elif first.resolve() != entry.path.resolve():
                version = "" if entry.spec.version is None else f" {entry.spec.version}"
                raise CorpusError(
                    f"{first} and {entry.path} are both"
                    f" {entry.reference}{version}; give one copy"
                )
        for candidates in self._by_reference.values():
            candidates.sort(key=lambda e: _version_key(e.spec.version), reverse=True)

    @classmethod
    def load(
        cls,
        paths: str | os.PathLike[str] | Iterable[str | os.PathLike[str]],
        *,
        raw: bool = False,
    ) -> Corpus:
        """Parse every `.dad` file in `paths`, one path or several, recursing
        into directories. A path that does not exist, or that is no path,
        raises `CorpusError`, as a file that does not parse does.

        Raw files are skipped by default. A corpus mixing raw and corrected
        copies of one specification would hold two versions of the same
        document that disagree on purpose, and resolution would pick between
        them by version number — which they share.

        A directory in `paths` holding `HOLE_RECORD` directly gives the corpus
        its record, so a consumer loading the corpus gets it with no argument; a
        file list or a subdirectory has none, since a record describes the
        whole corpus it sits beside, and neither has a raw corpus, which the
        record does not describe. Two directories holding one are refused; one
        directory named twice is one directory.

        `CORPUS_FILE` is found the same way and gives the corpus its `rules`,
        raw corpus included, whose From cells need them most: it is read before
        any `.dad` file, so a format this library does not read raises
        `CorpusFormatError` rather than a parse error, and checked against the
        files once they are read. A corpus without one, a file list or a
        subdirectory, has the empty `Rules()`: no format to hold it to, and no
        entries, so a citation they would answer resolves to nothing.
        """
        unique: dict[Path, Path] = {}
        for path in _as_paths(paths):
            if not path.exists():
                raise CorpusError(f"{path}: no such file or directory")
            unique.setdefault(path.resolve(), path)
        given = list(unique.values())
        records = [
            path / HOLE_RECORD
            for path in given
            if not raw and path.is_dir() and (path / HOLE_RECORD).is_file()
        ]
        if len(records) > 1:
            raise CorpusError(
                f"two hole records in one corpus: {', '.join(map(str, records))}"
            )
        described = [
            path / CORPUS_FILE
            for path in given
            if path.is_dir() and (path / CORPUS_FILE).is_file()
        ]
        if len(described) > 1:
            raise CorpusError(
                f"two corpus files in one corpus: {', '.join(map(str, described))}"
            )
        rules = Rules.load(described[0]) if described else Rules()
        entries = []
        for path in cls._files(given):
            if path.name.endswith(".raw.dad") != raw:
                continue
            try:
                spec = parser.parse(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:  # DadParseError, pydantic alike
                raise CorpusError(f"{path}: {error}") from error
            entries.append(Entry(path=path, spec=spec))
        books = cls(
            entries, HoleRecord.load(records[0]) if records else None, rules=rules
        )
        rules.check(books)
        return books

    @classmethod
    def installed(cls, *, raw: bool = False) -> Corpus:
        """Load the corpus the `seanchai-corpus` package installed, record and
        rules and all, as `load` loads a directory. `CorpusNotInstalledError`
        without it, and `CorpusFormatError` for a corpus of a format this
        library does not read.
        """
        package = _installed_package()
        books = cls.load([package.CORPUS_DIR], raw=raw)
        books.version = package.__version__
        return books

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
        """The copies `reference` names, newest first, through `cited_as`."""
        return self._by_reference.get(self.rules.cited_as.get(reference, reference), [])

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

        Every entry of `rules` keyed by the citing document answers for the
        copy of it `like` is, by its version, and for no other copy. In order:
        a reference its citers spell otherwise than the publisher (`cited_as`)
        is the publisher's document.
        A citation naming a 3GPP2 revision (`cited_revisions`) is a copy of
        that revision, or failing one, the copy an explicit `stand_ins` entry
        names, or nothing. An RFC, or another document outside 3GPP, is
        whatever copy the corpus holds. A specific reference
        (`cited_versions`) is the version it names and no other. A 3GPP
        document's non-specific one is the newest copy in its own major
        version, and failing one, the cited document's final version when
        that ended in an earlier release (`final_versions`), or the later
        release's copy a `release_stand_ins` entry names; the corpus may lack
        the version of a release the document still had. A document outside
        3GPP has no release, so its non-specific reference is the newest copy
        where its references clause says so (`latest_editions`), the final
        version, or nothing, and a version it names that the corpus lacks is
        answered only by a `release_stand_ins` entry.
        """
        candidates = self._candidates(reference)
        citing = _reference(like)
        rules = self.rules
        key = (citing, like.version or "", reference)
        cited_revision = rules.cited_revisions.get(key)
        if cited_revision is not None:
            return self._revision(key, cited_revision, candidates)
        if reference.startswith("RFC") or ast.is_external(reference):
            # An RFC number names one immutable document; there is no release
            # axis to match against. Nor is there for another publisher's
            # document: ETSI TS 283 034 V2.2.0 is no Release 2 of anything
            # 3GPP numbers. The corpus holds such a document only when someone
            # writes it by hand, and then the newest copy is the answer.
            return (candidates[0] if candidates else None), None
        version = like.version
        external = _external(like)
        named = rules.cited_versions.get(key)
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
                citing, reference, named, CitationRule.SPECIFIC
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
        if key in rules.release_stand_ins:
            return self._release_stand_in(key, candidates)
        if external and key in rules.latest_editions and candidates:
            newest = candidates[0]
            return newest, CrossRelease(
                citing,
                reference,
                newest.spec.version or "",
                CitationRule.LATEST_EDITION,
            )
        final = rules.final_versions.get(reference)
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
        return entry, CrossRelease(citing, reference, final, CitationRule.NON_SPECIFIC)

    def release_fill(
        self, reference: str, *, like: ast.Specification
    ) -> tuple[Entry, ReleaseFill, CrossRelease] | None:
        """The `release_fills` entry for `like` citing `reference`, with the later
        copy it names and the crossing it reports, or None without an entry or
        that copy. `resolution` still answers the citation."""
        citing = _reference(like)
        fill = self.rules.release_fills.get((citing, like.version or "", reference))
        if fill is None:
            return None
        entry = next(
            (e for e in self._candidates(reference) if e.spec.version == fill.version),
            None,
        )
        if entry is None:
            return None
        return (
            entry,
            fill,
            CrossRelease(
                citing,
                reference,
                fill.version,
                CitationRule.LATER_RELEASE,
                meant=fill.meant,
            ),
        )

    def _release_stand_in(
        self, key: Citation, candidates: list[Entry]
    ) -> tuple[Entry | None, CrossRelease | None]:
        """The copy a `release_stand_ins` entry names, or nothing."""
        citing, _, reference = key
        stand_in = self.rules.release_stand_ins.get(key)
        if stand_in is None:
            return None, None
        entry = next(
            (e for e in candidates if e.spec.version == stand_in.version), None
        )
        if entry is None:
            return None, None
        return entry, CrossRelease(
            citing,
            reference,
            stand_in.version,
            CitationRule.STAND_IN,
            meant=stand_in.meant,
            specific=stand_in.specific,
        )

    def _revision(
        self, key: Citation, cited: str, candidates: list[Entry]
    ) -> tuple[Entry | None, CrossRelease | None]:
        """A citation of revision `cited`: its newest copy, or the copy a
        `stand_ins` entry lets stand in for it, reported as such."""
        citing, _, reference = key
        entry = next((e for e in candidates if revision(e.spec) == cited), None)
        if entry is not None:
            return entry, None
        stand_in = self.rules.stand_ins.get(key)
        if stand_in is None:
            return None, None
        entry = next(
            (
                e
                for e in candidates
                if revision(e.spec) == stand_in.revision
                and e.spec.version == stand_in.version
            ),
            None,
        )
        if entry is None:
            return None, None
        return entry, CrossRelease(
            citing,
            reference,
            stand_in.version,
            CitationRule.STAND_IN,
            cited_revision=cited,
            revision=stand_in.revision,
        )


def _as_paths(paths: Any) -> list[Path]:
    """What `Corpus.load` was given, as a list: a lone string is one path, not
    an iterable of characters."""
    if isinstance(paths, str | os.PathLike):
        paths = [paths]
    try:
        return [Path(path) for path in paths]
    except TypeError as error:
        raise CorpusError(
            f"Corpus.load takes a path or a list of paths, not {paths!r}"
        ) from error


def _reference(spec: ast.Specification) -> str:
    """`spec`'s reference, or its title where it names no supported
    document (a hand-authored vendor extension)."""
    try:
        return ast.spec_ref(spec.specification)
    except ast.SpecRefError:
        return spec.specification
