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
document's, unless the citation names a 3GPP2 revision (`CITED_REVISIONS`):
then only that revision answers it, or a held one an explicit entry lets
stand in for it (`STAND_INS`). A non-specific citation whose release's
last version the corpus does not hold resolves to nothing, unless an entry
in `RELEASE_STAND_INS` records the evidence that a held copy of a later
release defines what the citing copy reaches the same way. The reasoning,
and what a resolution across releases reports, is in
docs/consumers.md#resolution-across-releases and
docs/linter.md#resolving-an-origin.

A directory holding a corpus may hold its record of known holes too
(`HOLE_RECORD`): what the corpus cannot complete, each with its evidence,
which the model builds strictly against (docs/consumers.md#known-holes).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dad import ast, parser
from .prose import collapse


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

# The revision a citation of a 3GPP2 document names, by (citing, cited)
# reference, read from the citing document's references clause. 3GPP2
# numbers revisions of a document (X.S0057-0, -A, -B) as 3GPP numbers
# releases, each with versions of its own, and a spec-ref keeps no revision
# letter, so the revision a reference names is recorded here, as
# `CITED_VERSIONS` records versions. It is a specific reference: that
# revision answers it and no other, unless `STAND_INS` says one does.
CITED_REVISIONS: dict[tuple[str, str], str] = {
    # TS 29.212 V18.2.0 clause 2, [24] 3GPP2 X.S0057-B: "E-UTRAN - eHRPD
    # Connectivity and Interworking: Core Network Aspects".
    ("TS29.212", "3GPP2-X.S0057"): "B",
}


@dataclass(frozen=True)
class StandIn:
    """A held revision answering a citation of one the corpus cannot hold,
    and the evidence that it cannot."""

    revision: str  # "0"
    version: str  # "2.0"
    evidence: str


# Citations of a revision (`CITED_REVISIONS`) that a held copy of another
# revision answers, by (citing, cited) reference. One entry per citation,
# each with the evidence the cited revision is out of reach; a citation
# without one resolves to nothing while the corpus lacks its revision.
STAND_INS: dict[tuple[str, str], StandIn] = {
    ("TS29.212", "3GPP2-X.S0057"): StandIn(
        "0",
        "2.0",
        "3GPP2's library publishes X.S0057-0 v1.0 and v2.0 only (checked"
        " 2026-10-30 at http://www.3gpp2.org/Public_html/Specs/index.cfm,"
        " X series)",
    ),
}


@dataclass(frozen=True)
class ReleaseStandIn:
    """A held copy of a later release answering a non-specific citation of
    the version the corpus does not hold, and the evidence that what the
    citing copy reaches is defined alike in both."""

    meant: str  # "11.12.0", the version the citation means
    version: str  # "18.1.0", the copy answering it
    evidence: str


# Non-specific citations from an older copy (TS 32.299 V11.20.0, which
# oneM2M TS-0004 [31] names) that mean their release's last version of a
# document the corpus holds only at a later release, by (citing reference,
# citing version, cited reference). One entry per citation, each with the
# evidence that the cited version and the held copy define alike everything
# the citing copy re-uses from it, members its grouped AVPs reach in the
# cited document included: code, vendor, type, every table row's flag
# rules, grouped bodies and enumerated values. A citation without one
# resolves to nothing while the corpus lacks its version. Where the two
# versions differ the meant version is pinned instead (TS 29.212 V11.19.0,
# TS 29.214 V11.16.0, TS 29.061 V6.15.0, src/seanchai/downloader/specs.toml).
def _compared(date: str, release: int) -> str:
    return (
        f"compared {date} with the Release {release} copy extracted from the 3GPP"
        f" archive, whose listing holds no later Release {release} version"
    )


_REL11 = _compared("2026-10-31", 11)
RELEASE_STAND_INS: dict[tuple[str, str, str], ReleaseStandIn] = {
    # TS 32.299 V11.20.0 clause 2 [207].
    ("TS32.299", "11.20.0", "TS29.061"): ReleaseStandIn(
        "11.12.0",
        "18.1.0",
        "V11.12.0 tabulates the 22 AVPs TS 32.299 V11.20.0 re-uses from it"
        " that either version tabulates with V18.1.0's codes, types and flag"
        " rules on every row (3GPP-IMSI, 3GPP-MS-TimeZone, 3GPP-RAT-Type and"
        " 3GPP-User-Location-Info on both of their rows), and prints"
        " CN-IP-Multicast-Distribution's, MBMS-2G-3G-Indicator's and"
        " MBMS-Service-Type's values as V18.1.0 does; neither tabulates"
        " 3GPP-Session-Stop-Indicator, whose code-only row is V18.1.0's"
        " correction; " + _REL11,
    ),
    # [229].
    ("TS32.299", "11.20.0", "TS29.173"): ReleaseStandIn(
        "11.1.0",
        "18.0.0",
        "V11.1.0 tabulates MME-Name (2402) and MME-Realm (2408) with"
        " V18.0.0's types and flag rules; " + _REL11,
    ),
    # [204].
    ("TS32.299", "11.20.0", "TS29.229"): ReleaseStandIn(
        "11.5.0",
        "18.1.0",
        "V11.5.0 tabulates Server-Capabilities, Mandatory-Capability,"
        " Optional-Capability, Server-Name, Session-Priority and User-Data"
        " with V18.1.0's codes, types and flag rules, and prints"
        " Server-Capabilities' body and Session-Priority's values as V18.1.0"
        " does; " + _REL11,
    ),
    # [219], [230].
    ("TS32.299", "11.20.0", "TS29.272"): ReleaseStandIn(
        "11.14.0",
        "18.7.0",
        "V11.14.0 tabulates CSG-Id, MME-Number-for-MT-SMS, Terminal-Information"
        " and its members IMEI, 3GPP2-MEID and Software-Version with V18.7.0's"
        " codes, types and flag rules, and prints Terminal-Information's body"
        " as V18.7.0 does; " + _REL11,
    ),
    # [237].
    ("TS32.299", "11.20.0", "TS29.273"): ReleaseStandIn(
        "11.11.0",
        "18.6.0",
        "V11.11.0 tabulates SSID (1524) on both of V18.6.0's rows with its"
        " type and flag rules; " + _REL11,
    ),
    # [221].
    ("TS32.299", "11.20.0", "TS29.329"): ReleaseStandIn(
        "11.7.0",
        "18.0.0",
        "V11.7.0 tabulates MSISDN (701) with V18.0.0's type and flag rules; " + _REL11,
    ),
    # TS 29.210 V6.7.0 clause 2 [16].
    ("TS29.210", "6.7.0", "TS29.229"): ReleaseStandIn(
        "6.11.0",
        "18.1.0",
        "V6.11.0 table 6.3.1 tabulates Charging-Information (618) and its members"
        " Primary-Event-Charging-Function-Name, Secondary-Event-Charging-Function-"
        "Name, Primary-Charging-Collection-Function-Name and Secondary-Charging-"
        "Collection-Function-Name (619-622) with the codes, types and flag rules"
        " of V18.1.0's table 6.3.0.1, and clause 6.3.19 prints Charging-"
        "Information's body as V18.1.0 does; " + _compared("2026-11-01", 6),
    ),
    # TS 29.234 V11.2.0 clause 2 [6].
    ("TS29.234", "11.2.0", "TS29.229"): ReleaseStandIn(
        "11.5.0",
        "18.1.0",
        "V11.5.0 table 6.3.1 tabulates the 14 AVPs TS 29.234 V11.2.0 re-uses from"
        " it, and Deregistration-Reason's members Reason-Code and Reason-Info, with"
        " the codes, types and flag rules of V18.1.0's table 6.3.0.1, and prints"
        " Deregistration-Reason's body and Server-Assignment-Type's and"
        " Reason-Code's values as V18.1.0 does. V18.1.0's SIP-Digest-Authenticate,"
        " a member of SIP-Auth-Data-Item, adds Alternate-Digest-Algorithm and"
        " Alternate-Digest-HA1 to V11.5.0's, which TS 29.234 does not reach: its"
        " clause 10.1.4 prints a SIP-Auth-Data-Item body of its own, without that"
        " member; " + _compared("2026-11-01", 11),
    ),
}

# 3GPP2's name for a rendering, "X.S0057-0_v2.0_091215.pdf": number,
# revision, version and publication date.
TGPP2_RENDERING_RE = re.compile(
    r"^(?P<number>[A-Z]\.[A-Z]\d{4})-(?P<revision>[0-9A-Z])"
    r"_v(?P<version>\d+\.\d+)_\d{6}\.pdf$"
)

# `CrossRelease.rule`'s values: the drafting rule a resolution followed, or
# `STAND_IN`, the table entry that let another revision (`STAND_INS`) or a
# later release's copy (`RELEASE_STAND_INS`) answer.
SPECIFIC = "specific"
NON_SPECIFIC = "non-specific"
STAND_IN = "stand-in"


@dataclass(frozen=True)
class CrossRelease:
    """A citation resolved outside the citing document's release, and the
    rule that allowed it: `SPECIFIC`, the version the citing document's
    references name (`CITED_VERSIONS`), or `NON_SPECIFIC`, the cited
    document's final version (`FINAL_VERSIONS`). A document outside 3GPP
    has no release, so each of its 3GPP citations that resolves is one.
    `STAND_IN` is a held copy answering a citation of one the corpus cannot
    hold: a 3GPP2 revision for another, a revision being 3GPP2's release
    (`STAND_INS`), or a later release's copy for the version a non-specific
    reference means (`RELEASE_STAND_INS`, `meant` set)."""

    citing: str  # "TS32.299"
    cited: str  # "TS29.140"
    version: str  # "7.0.0", the copy resolved to
    rule: str
    # For `STAND_IN`, a 3GPP2 revision being 3GPP2's release: the revision
    # the reference names ("B") and the one resolved to ("0").
    cited_revision: str | None = None
    revision: str | None = None
    # For a `RELEASE_STAND_INS` entry, the version the non-specific
    # reference means ("11.12.0"), which the corpus does not hold.
    meant: str | None = None

    def __str__(self) -> str:
        if self.rule == STAND_IN and self.meant is not None:
            return (
                f"{self.citing} cites {self.cited} non-specifically, meaning"
                f" V{self.meant}, which the corpus lacks: V{self.version} stands"
                " in (corpus.RELEASE_STAND_INS)"
            )
        if self.rule == STAND_IN:
            return (
                f"{self.citing} cites {self.cited} revision {self.cited_revision},"
                f" which the corpus lacks: revision {self.revision}"
                f" V{self.version} stands in (corpus.STAND_INS)"
            )
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
    missing: tuple[str, ...]
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
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise CorpusError(f"{path}: {error}") from error
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
        return KnownHole(document, name, tuple(missing), collapse(reason))


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

    def __init__(
        self, entries: Iterable[Entry], record: HoleRecord | None = None
    ) -> None:
        # None for a corpus with no record: a partial or foreign one, or raw.
        self.record = record
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

        A directory in `paths` holding `HOLE_RECORD` directly gives the corpus
        its record, so a consumer loading `dad/` gets it with no argument; a
        file list or a subdirectory has none, since a record describes the
        whole corpus it sits beside, and neither has a raw corpus, which the
        record does not describe. Two directories holding one are refused.
        """
        paths = list(paths)
        records = [
            path / HOLE_RECORD
            for path in paths
            if not raw and path.is_dir() and (path / HOLE_RECORD).is_file()
        ]
        if len(records) > 1:
            raise CorpusError(
                f"two hole records in one corpus: {', '.join(map(str, records))}"
            )
        entries = []
        for path in cls._files(paths):
            if path.name.endswith(".raw.dad") != raw:
                continue
            try:
                spec = parser.parse(path.read_text(encoding="utf-8"))
            except ValueError as error:  # DadParseError and pydantic alike
                raise CorpusError(f"{path}: {error}") from error
            entries.append(Entry(path=path, spec=spec))
        return cls(entries, HoleRecord.load(records[0]) if records else None)

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
        (`CITED_AS`) is the publisher's document. A citation naming a 3GPP2
        revision (`CITED_REVISIONS`) is a copy of that revision, or failing
        one, the copy an explicit `STAND_INS` entry names, or nothing. An
        RFC, or another document outside 3GPP, is whatever copy the corpus
        holds. A specific
        reference (`CITED_VERSIONS`) is the version it names and no other.
        A 3GPP document's non-specific one is the newest copy in its own
        major version, and failing one, the cited document's final version
        when that ended in an earlier release (`FINAL_VERSIONS`), or the
        later release's copy a `RELEASE_STAND_INS` entry names; the corpus
        may lack the version of a release the document still had.
        A document outside 3GPP has no release, so its non-specific
        reference is the final version or nothing.
        """
        candidates = self._candidates(reference)
        citing = _reference(like)
        cited_revision = CITED_REVISIONS.get((citing, reference))
        if cited_revision is not None:
            return self._revision(citing, reference, cited_revision, candidates)
        if reference.startswith("RFC") or ast.is_external(reference):
            # An RFC number names one immutable document; there is no release
            # axis to match against. Nor is there for another publisher's
            # document: ETSI TS 283 034 V2.2.0 is no Release 2 of anything
            # 3GPP numbers. The corpus holds such a document only when someone
            # writes it by hand, and then the newest copy is the answer.
            return (candidates[0] if candidates else None), None
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
            stand_in = RELEASE_STAND_INS.get((citing, version, reference))
            if stand_in is not None:
                entry = next(
                    (e for e in candidates if e.spec.version == stand_in.version),
                    None,
                )
                if entry is None:
                    return None, None
                return entry, CrossRelease(
                    citing,
                    reference,
                    stand_in.version,
                    STAND_IN,
                    meant=stand_in.meant,
                )
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

    @staticmethod
    def _revision(
        citing: str, reference: str, cited: str, candidates: list[Entry]
    ) -> tuple[Entry | None, CrossRelease | None]:
        """A citation of revision `cited`: its newest copy, or the copy a
        `STAND_INS` entry lets stand in for it, reported as such."""
        entry = next((e for e in candidates if revision(e.spec) == cited), None)
        if entry is not None:
            return entry, None
        stand_in = STAND_INS.get((citing, reference))
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
            STAND_IN,
            cited_revision=cited,
            revision=stand_in.revision,
        )


def _reference(spec: ast.Specification) -> str:
    """`spec`'s reference, or its title where it names no supported
    document (a hand-authored vendor extension)."""
    try:
        return ast.spec_ref(spec.specification)
    except ast.SpecRefError:
        return spec.specification
