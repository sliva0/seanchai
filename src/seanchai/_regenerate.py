"""Rebuild the committed corpus from the downloaded sources.

Each corpus file is one extraction, page attachment and correction pass over a
document in `specifications/manifest.json`. `regenerate` redoes this for every
specification the corpus holds, so the corpus cannot drift from its sources
and edits. A transcription (`extractor.transcription`) has no manifest record
and is rebuilt from its own text.

The corpus decides which documents count: what is committed, plus whatever
`add` names that the catalog does not mark `out_of_scope`. The manifest
decides which version counts, so a superseded copy is replaced and reported.
The library returns a `Report`; `seanchai corpus regenerate` prints it.

A run changes nothing until it has rebuilt everything: the documents, the
removals of replaced copies, the corrections record and `expand_ranges`'
rewrites of the edit files are made in a scratch copy, and only a run with
no failure copies them over (`_Stage`). A failed run leaves the corpus and
the edits as they were.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from . import _correction_record, _ranges, linter
from ._versions import RangeWarning, VersionRange
from .corpus import CORPUS_FILE, TGPP2_RENDERING_RE, Corpus, CorpusError, Rules
from .dad import ast, corrections, formatter, interpretations, parser
from .dad.corrections import CorrectionError
from .dad.parser import DadParseError
from .downloader.catalog import SOURCES, load_catalog
from .errors import SeanchaiError
from .extractor import rfc_text, transcription
from .extractor.errors import ExtractionError
from .extractor.unclaimed import Baseline, Candidate, with_pages

if TYPE_CHECKING:
    from .diff import Diff

Status = Literal[
    "unchanged", "changed", "new", "failed", "not-in-manifest", "not-converted"
]


@dataclass
class Outcome:
    """What happened to one specification."""

    reference: str  # "TS29.388"
    status: Status
    version: str | None = None
    # The corrected file and its raw mirror, under the output directory.
    written: list[Path] = field(default_factory=list)
    # A superseded pair the manifest's version replaced, with its version.
    replaced: list[Path] = field(default_factory=list)
    replaced_version: str | None = None
    warnings: list[str] = field(default_factory=list)
    # With `expand_ranges`: each declaration range widened to `version`.
    expanded: list[str] = field(default_factory=list)
    error: str | None = None
    # The tables no reading claimed that resemble a definition
    # (`extractor.unclaimed`), and of them those the baseline does not list.
    unclaimed: list[Candidate] = field(default_factory=list)
    new_unclaimed: list[Candidate] = field(default_factory=list)
    # For a copy that replaced another: what changed for a stack
    # (`seanchai.diff`), or why it could not be told.
    diff: Diff | None = None
    # With `expand_ranges`: the interpretations another release reviewed
    # whose quotes this copy prints, applied and to be widened to it, by
    # citation (`corrections.offered`).
    adopted: list[str] = field(default_factory=list)


@dataclass
class Report:
    outcomes: list[Outcome]
    # The corrections record written, under the output directory; None with no
    # corrections directory, or when a failure left everything as it was.
    record: Path | None = None
    # The sources a partial download left out that this run needed, as
    # `seanchai corpus download --only` names them.
    missing_sources: tuple[str, ...] = ()
    # Whether the run's changes reached the output and the edit files: only a
    # run with no failure promotes anything.
    promoted: bool = False
    # Candidates the baseline lists for a rebuilt document that it no longer
    # prints unclaimed, by reference.
    stale_unclaimed: dict[str, list[Candidate]] = field(default_factory=dict)

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.status in ("failed", "not-in-manifest")]


@dataclass(frozen=True)
class _Source:
    """One manifest record the extractor can read."""

    reference: str
    document: Path
    pdf: Path | None
    link: str
    # "3gpp/rel-19" or "rfc": the corpus subdirectory the pair belongs in.
    tree: str
    # A legacy `.doc` the download did not convert (`--no-convert`);
    # `document` is the `.doc` itself, which the extractor cannot read.
    unconverted: bool = False
    # A hand transcription (`edits/transcriptions/`), named in the corpus by
    # `stem` rather than by its file.
    transcribed: bool = False
    stem: str | None = None


@dataclass(frozen=True)
class _Committed:
    corrected: Path
    raw: Path
    version: str | None


def regenerate(
    manifest: Path,
    corpus: Path,
    output: Path,
    *,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    interpretations_dir: Path | None = None,
    transcriptions_dir: Path | None = None,
    add: Sequence[str] = (),
    only: Sequence[str] = (),
    report: Callable[[Outcome], None] = lambda outcome: None,
    expand_ranges: bool = False,
    unclaimed: Path | None = None,
    acknowledge_unclaimed: bool = False,
    offer_cited: bool = False,
) -> Report:
    """Rebuild every committed specification (plus `add`) into `output`.

    `output` is normally `corpus` itself; the test suite passes an empty
    directory to check the committed corpus without touching it.

    `only` rebuilds those specifications instead of every committed one. With
    the manifest of an older version (`seanchai corpus download --spec
    --version`) and a scratch `output`, that re-extracts the older version for a
    raw-vs-raw diff.

    `expand_ranges` widens, in the edit files themselves, every declaration
    range a cleanly rebuilt specification's version falls outside
    (`seanchai._ranges`). The interpretations another release reviewed are
    offered to a copy of a release the corpus holds whole, and with
    `offer_cited` to a copy held only for citations too (`_Offering`).

    `transcriptions_dir` holds the hand transcriptions, each a source like a
    manifest record.

    `interpretations_dir` holds the documents' interpretations files
    (`dad.interpretations`), merged after their corrections.

    With `corrections_dir`, a run with no failure also rewrites `output`'s
    corrections record (`seanchai._correction_record`), the interpretations
    included.

    `unclaimed` is the baseline of unclaimed tables (`extractor.unclaimed`): a
    document printing one it does not list fails, and one it lists that the
    document no longer prints is reported stale. `acknowledge_unclaimed`
    rewrites the baseline's entries for the documents rebuilt instead.
    """
    try:
        sources = _sources(manifest)
    except ManifestError as error:
        # As any failure of a run: reported, with the corpus left alone.
        failed = Outcome(manifest.name, "failed", error=str(error))
        report(failed)
        return Report([failed])
    absent = _absent_sources(manifest)
    listed = sources | _transcriptions(transcriptions_dir)
    committed = _committed(corpus)
    # Acceptances are checked against the committed corpus's origins before
    # their ranges are widened; loaded once, and only then.
    books = Corpus.load([corpus]) if expand_ranges else None
    baseline = Baseline.load(unclaimed) if unclaimed is not None else None
    with _Stage(
        output,
        [sources_dir, corrections_dir, interpretations_dir] if expand_ranges else [],
    ) as stage:
        return _run(
            stage,
            listed,
            committed,
            absent,
            corpus,
            output,
            sources_dir=stage.edits(sources_dir),
            corrections_dir=stage.edits(corrections_dir),
            interpretations_dir=stage.edits(interpretations_dir),
            add=add,
            only=only,
            report=report,
            books=books,
            baseline=baseline,
            unclaimed=unclaimed if acknowledge_unclaimed else None,
            whole=_whole_releases(corpus),
            offer_cited=offer_cited,
        )


def _run(
    stage: _Stage,
    listed: dict[_Key, _Source],
    committed: dict[_Key, _Committed],
    absent: frozenset[str],
    corpus: Path,
    output: Path,
    *,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    interpretations_dir: Path | None,
    add: Sequence[str],
    only: Sequence[str],
    report: Callable[[Outcome], None],
    books: Corpus | None,
    baseline: Baseline | None,
    unclaimed: Path | None,
    whole: frozenset[int] | None = None,
    offer_cited: bool = False,
) -> Report:
    """`regenerate`'s run, building into `stage` and promoting it to `output`
    and the edit directories only when nothing failed. With `unclaimed`, the
    baseline is rewritten there for the documents rebuilt."""
    outcomes = []
    out_of_scope = load_catalog().out_of_scope() if add else {}
    for reference in add:
        if reference in out_of_scope:
            refused = Outcome(
                reference, "failed", error=f"out of scope: {out_of_scope[reference]}"
            )
            outcomes.append(refused)
            report(refused)
    readable = [reference for reference in add if reference not in out_of_scope]
    moves = {_followed(key, listed, committed): key for key in committed}
    selected = _selected(listed, committed, only, readable)
    if books is not None:
        # Newest first within a document, so that a run going back widens a
        # block release by release, each copy then the next one's neighbour.
        selected.sort(key=lambda key: (key[0], -(_release(key[1]) or 0)))
    for key in selected:
        outcome = _one(
            key[0],
            listed.get(key),
            committed.get(moves.get(key, key)),
            corpus,
            output,
            stage,
            sources_dir,
            corrections_dir,
            interpretations_dir,
            books,
            absent,
            _offering(key, [*listed, *committed], whole, offer_cited),
        )
        stage.unstaged(outcome)
        previous = committed.get(moves.get(key, key))
        if outcome.replaced and previous is not None:
            _diff(outcome, previous, corpus, output, stage)
        if baseline is not None and outcome.status not in ("failed",):
            outcome.new_unclaimed, _ = baseline.compare(
                outcome.reference, outcome.unclaimed
            )
            if outcome.new_unclaimed and unclaimed is None:
                outcome.status = "failed"
                outcome.error = (
                    f"{len(outcome.new_unclaimed)} table(s) no reading claims"
                    " and the baseline does not list; look them over, then"
                    " acknowledge them with --acknowledge-unclaimed"
                )
        outcomes.append(outcome)
        report(outcome)
    result = Report(
        outcomes,
        missing_sources=tuple(
            sorted(
                {
                    _source_of(outcome.reference)
                    for outcome in outcomes
                    if outcome.status == "not-in-manifest"
                }
                & absent
            )
        ),
    )
    rebuilt: dict[str, list[Candidate]] = {}
    for outcome in outcomes:
        if outcome.status in ("unchanged", "changed", "new"):
            rebuilt.setdefault(outcome.reference, []).extend(outcome.unclaimed)
    # A document one of whose copies was not rebuilt (a `.doc` left
    # unconverted) keeps its entries: its tables are not all read.
    for outcome in outcomes:
        if outcome.status == "not-converted":
            rebuilt.pop(outcome.reference, None)
    if baseline is not None:
        for reference, found in rebuilt.items():
            if stale := baseline.compare(reference, found)[1]:
                result.stale_unclaimed[reference] = stale
    if result.failed:
        return result
    if unclaimed is not None and baseline is not None:
        stage.write_file(unclaimed, baseline.updated(rebuilt).render())
        result.stale_unclaimed = {}
    record = None
    if corrections_dir is not None:
        try:
            record = _correction_record.write(
                stage.corpus, corrections_dir, interpretations_dir
            )
        except (CorrectionError, CorpusError, OSError) as error:
            failed = Outcome(
                _correction_record.RECORD_NAME,
                "failed",
                error=f"writing: {stage.unstaged_text(str(error))}",
            )
            outcomes.append(failed)
            report(failed)
            return result
    try:
        stage.promote()
    except OSError as error:
        failed = Outcome(output.name, "failed", error=f"promoting: {error}")
        outcomes.append(failed)
        report(failed)
        return result
    result.promoted = True
    if record is not None:
        result.record = output / record.relative_to(stage.corpus)
    return result


class ManifestError(SeanchaiError):
    """A `manifest.json` that is missing or is not what `seanchai corpus download`
    writes."""


# A corpus file's place: its reference and the corpus subdirectory it sits
# in, `("TS29.214", "3gpp/rel-19")`. The corpus holds one copy of a document
# per release tree, so TS 29.214 V7.12.0, which ETSI TS 183 017 cites as
# "Release 7", sits in `3gpp/rel-7` beside V19.3.0 in `3gpp/rel-19`.
_Key = tuple[str, str | None]


def _selected(
    listed: dict[_Key, _Source],
    committed: dict[_Key, _Committed],
    only: Sequence[str],
    add: Sequence[str],
) -> list[_Key]:
    """The copies a run rebuilds: every committed one, or with `only` those of
    the references it names that the manifest lists, and with `add` every listed
    copy of a reference not committed. A named reference neither listed nor
    committed is kept as `(reference, None)`, to be reported."""

    def of(reference: str, keys) -> list[_Key]:
        return [key for key in keys if key[0] == reference]

    if only:
        keys = []
        for reference in only:
            keys += (
                of(reference, listed) or of(reference, committed) or [(reference, None)]
            )
    else:
        keys = [_followed(key, listed, committed) for key in committed]
    for reference in add:
        keys += [key for key in of(reference, listed) if key not in committed] or (
            [] if of(reference, committed) else [(reference, None)]
        )
    return sorted(set(keys), key=lambda key: (key[0], key[1] or ""))


def _followed(
    key: _Key, listed: dict[_Key, _Source], committed: dict[_Key, _Committed]
) -> _Key:
    """Where a committed copy goes: its own place, unless the manifest no longer
    lists it and lists its document in one later release's tree, with nothing
    committed there. That is a release upgrade (TS 29.214 V18.4.0 in
    `3gpp/rel-18`, V19.3.0 in `3gpp/rel-19`), and `_one` is handed the old pair to
    take out. An older version's one-record manifest moves nothing."""
    if key in listed or (own := _release(key[1])) is None:
        return key
    later = [
        other
        for other in listed
        if other[0] == key[0]
        and other not in committed
        and (release := _release(other[1])) is not None
        and release > own
    ]
    return later[0] if len(later) == 1 else key


def _whole_releases(corpus: Path) -> frozenset[int] | None:
    """The 3GPP releases `corpus` holds whole, as its `corpus.toml` names
    them; None for a directory without one, where every copy counts."""
    path = corpus / CORPUS_FILE
    if not path.is_file():
        return None
    return frozenset(Rules.load(path).releases)


@dataclass(frozen=True)
class _Offering:
    """Whether a copy takes the interpretations another release reviewed
    (`corrections.offered`), and the releases of the document's other copies
    that do. A copy of a 3GPP release the corpus holds only for citations
    (TS 29.212's Release 11) takes none unless asked: its readings serve the
    documents citing it, and widening a block to it would claim it held
    there. A copy of no 3GPP release tree takes them, with no neighbours to
    keep a range clear of."""

    eligible: bool = True
    releases: frozenset[int] | None = None


def _offering(
    key: _Key,
    keys: Sequence[_Key],
    whole: frozenset[int] | None,
    offer_cited: bool,
) -> _Offering:
    def takes(release: int) -> bool:
        return whole is None or offer_cited or release in whole

    own = _release(key[1])
    if own is None:
        return _Offering()
    return _Offering(
        eligible=takes(own),
        releases=frozenset(
            release
            for other in keys
            if other[0] == key[0]
            and (release := _release(other[1])) is not None
            and release != own
            and takes(release)
        ),
    )


def _release(tree: str | None) -> int | None:
    """The release of a corpus subdirectory, as `3gpp/rel-19` names it."""
    match = None if tree is None else re.fullmatch(r"3gpp/rel-(\d+)", tree)
    return None if match is None else int(match[1])


def _one(
    reference: str,
    source: _Source | None,
    committed: _Committed | None,
    corpus: Path,
    output: Path,
    stage: _Stage,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    interpretations_dir: Path | None,
    books: Corpus | None,
    absent: frozenset[str] = frozenset(),
    offering: _Offering | None = None,
) -> Outcome:
    if source is None and _source_of(reference) in absent:
        name = _source_of(reference)
        return Outcome(
            reference,
            "not-in-manifest",
            error=f"{name} is not downloaded"
            f" (`seanchai corpus download --only {name}`);"
            " the committed files were left alone",
        )
    if source is None:
        return Outcome(
            reference,
            "not-in-manifest",
            error="the manifest lists no readable source for it; the committed"
            " files were left alone",
        )
    if source.unconverted:
        # Not a failure: the download was asked to skip LibreOffice. The
        # sources test refuses it for a committed pair, so a manifest that
        # skipped conversions cannot pass it.
        return Outcome(
            reference,
            "not-converted",
            error=f"{source.document.name} was downloaded without conversion"
            " (`seanchai corpus download --no-convert`); the committed files were"
            " left alone",
        )
    outcome = Outcome(reference, "unchanged")
    try:
        raw_text, corrected_text, spec = _produce(
            source,
            sources_dir,
            corrections_dir,
            interpretations_dir,
            outcome.warnings,
            outcome.unclaimed,
            adopted=outcome.adopted if books is not None else None,
            offering=offering,
        )
    except (ExtractionError, CorrectionError, DadParseError, OSError) as error:
        outcome.status = "failed"
        outcome.error = str(error)
        return outcome
    outcome.version = spec.version
    if books is not None and spec.version is not None:
        try:
            _expand(
                outcome, spec, sources_dir, corrections_dir, interpretations_dir, books
            )
        except (CorrectionError, OSError, ValueError) as error:
            outcome.status = "failed"
            outcome.error = f"expanding ranges: {error}"
            return outcome

    stem = source.stem or source.document.stem
    corrected = Path(source.tree) / f"{stem}.dad"
    raw = Path("raw") / source.tree / f"{stem}.raw.dad"
    outcome.written = [output / corrected, output / raw]

    if committed is None:
        outcome.status = "new"
    elif committed.corrected.name != corrected.name:
        # A different version than the corpus holds: follow the manifest,
        # and take the old pair out of the output so the corpus never holds
        # two versions of one document.
        outcome.status = "new"
        outcome.replaced_version = committed.version
        for old in (committed.corrected, committed.raw):
            relative = old.relative_to(corpus)
            outcome.replaced.append(output / relative)
            stage.remove(relative)
    elif (
        _read(committed.corrected) != corrected_text or _read(committed.raw) != raw_text
    ):
        outcome.status = "changed"

    for path, text in ((corrected, corrected_text), (raw, raw_text)):
        stage.write(path, text)
    return outcome


def _diff(
    outcome: Outcome, previous: _Committed, corpus: Path, output: Path, stage: _Stage
) -> None:
    """What the copy replacing `previous` changes for a stack, read in the
    committed corpus; a warning where the corpus cannot be read so."""
    from . import diff as semantic
    from .model import HolePolicy, Model

    try:
        base = Corpus.load([corpus])
        new = stage.corpus / outcome.written[0].relative_to(output)
        outcome.diff = semantic.diff(
            Model.build(base, holes=HolePolicy.ANY),
            Model.build(semantic.overlay(base, [new]), holes=HolePolicy.ANY),
            documents=[outcome.reference],
        )
    except SeanchaiError as error:
        outcome.warnings.append(f"no diff against {previous.corrected.name}: {error}")


class _Stage:
    """A scratch copy of the output corpus, and of the edit directories a run
    rewrites, that a run changes in place of them; `promote` then copies what
    changed over the originals.

    Promotion writes every changed file beside its original under a hidden
    name first, and only once all are written renames them into place and
    removes what the run removed. A failure while writing removes the hidden
    files and changes nothing; the renames, within one directory, do not fail
    short of the disk going away.
    """

    def __init__(self, output: Path, edits: Sequence[Path | None]) -> None:
        self._output = output
        self._edits = [directory for directory in edits if directory is not None]
        self._scratch: tempfile.TemporaryDirectory[str] | None = None
        self.corpus = Path()
        self._copies: dict[Path, Path] = {}
        # Single files a run rewrites outside the directories: the baseline.
        self._files: dict[Path, bytes] = {}

    def __enter__(self) -> _Stage:
        self._scratch = tempfile.TemporaryDirectory(prefix="seanchai-regenerate-")
        root = Path(self._scratch.name)
        self.corpus = root / "corpus"
        if self._output.is_dir():
            shutil.copytree(self._output, self.corpus, ignore=_IGNORED)
        else:
            self.corpus.mkdir()
        for index, directory in enumerate(self._edits):
            copy = root / f"edits-{index}"
            shutil.copytree(directory, copy, ignore=_IGNORED)
            self._copies[directory] = copy
        return self

    def __exit__(self, *_: object) -> None:
        if self._scratch is not None:
            self._scratch.cleanup()

    def edits(self, directory: Path | None) -> Path | None:
        """The directory a run reads and rewrites in place of `directory`."""
        return None if directory is None else self._copies.get(directory, directory)

    def write(self, relative: Path, text: str) -> None:
        path = self.corpus / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_file(self, path: Path, text: str) -> None:
        """Stage `path`'s new text, for `promote` to write."""
        self._files[path] = text.encode("utf-8")

    def remove(self, relative: Path) -> None:
        path = self.corpus / relative
        path.unlink(missing_ok=True)
        # The last copy out of a release's tree takes the tree with it.
        if path.parent.is_dir() and not any(path.parent.iterdir()):
            path.parent.rmdir()

    def unstaged_text(self, text: str) -> str:
        """`text` naming the original directories in place of their copies."""
        for directory, copy in self._copies.items():
            text = text.replace(str(copy), str(directory))
        return text.replace(str(self.corpus), str(self._output))

    def unstaged(self, outcome: Outcome) -> None:
        """Name the original directories in `outcome`'s messages."""
        outcome.warnings = [self.unstaged_text(line) for line in outcome.warnings]
        outcome.expanded = [self.unstaged_text(line) for line in outcome.expanded]
        if outcome.error is not None:
            outcome.error = self.unstaged_text(outcome.error)

    def promote(self) -> None:
        """Copy every change over the originals, all or nothing."""
        writes: list[tuple[Path, Path]] = []
        removals: list[tuple[Path, Path]] = []
        for copy, original in [
            (self.corpus, self._output),
            *((copy, original) for original, copy in self._copies.items()),
        ]:
            staged = _files(copy)
            present = _files(original) if original.is_dir() else set()
            writes += [
                (copy / relative, original / relative)
                for relative in sorted(staged)
                if relative not in present
                or (copy / relative).read_bytes() != (original / relative).read_bytes()
            ]
            removals += [
                (original, original / relative) for relative in sorted(present - staged)
            ]
        hidden: list[tuple[Path, Path]] = []
        try:
            for source, target in writes:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.seanchai-staged")
                hidden.append((temporary, target))
                shutil.copyfile(source, temporary)
            for target, data in self._files.items():
                if target.is_file() and target.read_bytes() == data:
                    continue
                temporary = target.with_name(f".{target.name}.seanchai-staged")
                hidden.append((temporary, target))
                temporary.write_bytes(data)
        except OSError:
            for temporary, _ in hidden:
                temporary.unlink(missing_ok=True)
            raise
        for temporary, target in hidden:
            os.replace(temporary, target)
        for root, path in removals:
            path.unlink()
            parent = path.parent
            while parent != root and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent


_IGNORED = shutil.ignore_patterns("__pycache__", ".*.seanchai-staged")


def _files(directory: Path) -> set[Path]:
    """Every file under `directory`, relative to it, but caches."""
    return {
        path.relative_to(directory)
        for path in directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(directory).parts
        and not path.name.endswith(".seanchai-staged")
    }


def _expand(
    outcome: Outcome,
    spec: ast.Specification,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    interpretations_dir: Path | None,
    books: Corpus,
) -> None:
    """Widen the stale ranges of a specification that just rebuilt cleanly.

    The clean rebuild means every patch, quirk and correction `expect` held on
    this version. Acceptances are checked by linting the rebuilt file against
    `books`: only those that matched their finding are widened, and the rest are
    reported stale.
    """
    assert spec.version is not None
    expansions = []
    if sources_dir is not None:
        path = sources_dir / f"{outcome.reference}.toml"
        expansions.append(_ranges.expand_sources(path, spec.version))
    if corrections_dir is not None:
        acceptances = corrections.acceptances(
            corrections.in_release(
                corrections.load(corrections_dir, spec.specification), spec.version
            )
        )
        accepted = (
            {
                finding.accepted_by
                for finding in linter.lint_with_corpus(spec, books, acceptances)
                if finding.accepted_by is not None
            }
            if acceptances
            else set()
        )
        expansions.append(
            _ranges.expand_corrections(
                corrections_dir,
                spec.specification,
                spec.version,
                accepted,
            )
        )
    if interpretations_dir is not None:
        expansions.append(
            _ranges.expand_interpretations(
                interpretations_dir,
                spec.specification,
                spec.version,
                adopted=outcome.adopted,
            )
        )
    outcome.expanded = [line for e in expansions for line in e.widened]
    remaining = [line for e in expansions for line in e.remaining]
    stale = [line for e in expansions for line in e.stale]
    # The range warnings describe the files as they were; what is still out
    # of range after the rewrite is reported in their place.
    outcome.warnings = (
        [
            warning
            for warning in outcome.warnings
            if not isinstance(warning, RangeWarning)
        ]
        + [f"not widened, widen it by hand: {line}" for line in remaining]
        + [f"not widened, stale: {line}" for line in stale]
    )


def _produce(
    source: _Source,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    interpretations_dir: Path | None,
    warnings: list[str],
    unclaimed: list[Candidate] | None = None,
    adopted: list[str] | None = None,
    offering: _Offering | None = None,
) -> tuple[str, str, ast.Specification]:
    """The raw and corrected texts for one source, and the corrected tree;
    `unclaimed` receives the tables no reading claimed.

    The interpretations another release reviewed whose ranges do not span
    the copy's release are offered to it, as `offering` allows
    (`corrections.offered`). With `adopted`, each whose quotes the copy
    prints is applied and its citation added to `adopted`, for its range to
    be widened, and each it does not print is reported as not carried.
    Without it those whose quotes the copy prints are only counted."""
    comments = formatter.Comments()
    found: list[Candidate] = []
    if source.transcribed:
        spec, comments = transcription.read(source.document, sources_dir, warnings)
    elif source.document.suffix == ".txt":
        spec, comments = rfc_text.extract_with_comments(
            source.document,
            link=source.link,
            warnings=warnings,
            sources_dir=sources_dir,
            unclaimed=found,
        )
    else:
        # Here, not at the top: importing this module asks for no extra.
        from .extractor import tgpp_docx

        spec, comments = tgpp_docx.extract_with_comments(
            source.document,
            link=source.link,
            warnings=warnings,
            sources_dir=sources_dir,
            unclaimed=found,
        )
        if source.pdf is not None:
            spec = tgpp_docx.attach_pages(spec, source.pdf, warnings=warnings)
            if found:
                found = with_pages(found, tgpp_docx.clause_pages(source.pdf))
    if unclaimed is not None:
        unclaimed.extend(found)
    raw_text = formatter.format_spec(spec, comments)
    # The interpretations after the corrections: a block is placed in the
    # corrected tree, and its names are looked up there.
    module = [
        *corrections.load(corrections_dir, spec.specification),
        *interpretations.load(interpretations_dir, spec.specification),
    ]
    declared = corrections.in_release(module, spec.version)
    for edit in declared:
        # `__post_init__` parsed the declared string; the annotation still
        # admits it, so parse again (a no-op) to satisfy the type.
        versions = VersionRange.parse(edit.versions)
        if warning := versions.warning(spec.version, f"correction {edit.cited}"):
            warnings.append(warning)
    offering = offering or _Offering()
    offered = (
        corrections.offered(module, spec.version, offering.releases)
        if offering.eligible
        else []
    )
    interpreted = [
        edit for edit in declared if isinstance(edit, corrections.Interpretation)
    ]
    if interpreted or offered:
        texts, pages = _clauses(source, sources_dir, [*interpreted, *offered])
        interpretations.check_quotes(interpreted, texts)
        if adopted is None:
            # Counted, not carried: one the copy does not print stays out of
            # it without a word, as a reviewed release's would.
            if printed := _held(offered, texts, []):
                warnings.append(
                    f"{len(printed)} interpretation(s) another release reviewed,"
                    " whose quotes this copy prints, are not applied to it;"
                    " --expand-ranges carries them"
                )
            offered = []
        trying = {id(edit) for edit in _held(offered, texts, warnings)}
        chosen = {id(edit) for edit in declared} | trying
        # In module order, each interpretation on its clause's page here.
        placed = [
            (
                interpretations.paged(edit, pages)
                if isinstance(edit, corrections.Interpretation)
                else edit,
                id(edit) in trying,
            )
            for edit in module
            if id(edit) in chosen
        ]
        declared = [edit for edit, _ in placed]
        held = [
            edit
            for edit, tried in placed
            if tried and isinstance(edit, corrections.Interpretation)
        ]
    else:
        held: list[corrections.Interpretation] = []
    if declared:
        try:
            spec, _, comments = corrections.apply_with_comments(
                spec, comments, declared
            )
        except CorrectionError:
            if not held:
                raise
            declared = _applicable(spec, comments, declared, held, warnings)
            spec, _, comments = corrections.apply_with_comments(
                spec, comments, declared
            )
        corrected_text = formatter.format_spec(spec, comments)
    else:
        corrected_text = raw_text
    if adopted is not None:
        adopted.extend(
            edit.cited for edit in declared if any(edit is each for each in held)
        )
    return raw_text, corrected_text, spec


def _clauses(
    source: _Source,
    sources_dir: Path | None,
    interpreted: Sequence[corrections.Interpretation],
) -> tuple[dict[str, list[str]], dict[str, int] | None]:
    """The text of each clause interpreted constraints are held to, and each
    clause's page in this copy, from the PDF's outline or the RFC's pages."""
    if source.transcribed:
        raise CorrectionError(
            f"{interpreted[0].at()}: interpreted constraints are checked"
            " against a 3GPP docx or an RFC's text, and a transcription is"
            " neither"
        )
    if source.document.suffix == ".txt":
        texts, pages = rfc_text.clause_texts(source.document, sources_dir)
        return {key: list(value) for key, value in texts.items()}, dict(pages)
    from .extractor import tgpp_docx

    texts = tgpp_docx.clause_texts(source.document, sources_dir)
    pages = None if source.pdf is None else dict(tgpp_docx.clause_pages(source.pdf))
    return {key: list(value) for key, value in texts.items()}, pages


def _held(
    offered: Sequence[corrections.Interpretation],
    texts: dict[str, list[str]],
    warnings: list[str],
) -> list[corrections.Interpretation]:
    """Of the interpretations `offered`, those whose every quote the copy
    prints in its clause (`interpretations.check_quotes`); the rest are reported as
    not carried, with what the clause lacks."""
    held = []
    for edit in offered:
        try:
            interpretations.check_quotes([edit], texts)
        except CorrectionError as error:
            warnings.append(f"not carried: {error}")
            continue
        held.append(edit)
    return held


def _applicable(
    spec: ast.Specification,
    comments: formatter.Comments,
    declared: list[corrections.Declaration],
    held: list[corrections.Interpretation],
    warnings: list[str],
) -> list[corrections.Declaration]:
    """`declared` without the offered interpretations the copy's corrected
    file cannot take, each tried alone with the copy's own declarations,
    reported as not carried."""
    own = [edit for edit in declared if not any(edit is each for each in held)]
    refused = []
    for edit in held:
        try:
            corrections.apply_with_comments(spec, comments, [*own, edit])
        except CorrectionError as error:
            warnings.append(f"not carried: {edit.cited}: {error}")
            refused.append(edit)
    return [edit for edit in declared if not any(edit is each for each in refused)]


def _sources(manifest_path: Path) -> dict[_Key, _Source]:
    """The manifest's records the extractor can read, by spec reference.

    A legacy `.doc` record is read through its converted `.docx`
    (`conversions`). One extracted without conversion (`--no-convert`) is listed
    as unconverted, so asking for it reports "not converted". A record with no
    document (`--no-extract`) is left out and reports "not in manifest".
    """
    try:
        return _read_sources(manifest_path)
    except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
        # JSON that is no manifest fails wherever the walk first trips on it.
        raise ManifestError(
            f"{manifest_path} is no download manifest"
            f" ({type(error).__name__}: {error}); run `seanchai corpus download`"
        ) from error


def _source_of(reference: str) -> str:
    """The `seanchai corpus download --only` source a document comes from. The hand
    transcriptions come from none, and are always listed."""
    if reference.startswith("RFC"):
        return "rfc"
    return "onem2m" if reference.startswith("oneM2M") else "3gpp"


def _absent_sources(manifest_path: Path) -> frozenset[str]:
    """What a partial download left out of the manifest. One with no `sources`
    predates partial downloads, and holds the whole catalog."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return frozenset(SOURCES) - frozenset(manifest.get("sources", SOURCES))


def _read_sources(manifest_path: Path) -> dict[_Key, _Source]:
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources: dict[_Key, _Source] = {}
    for record in manifest["artifacts"]:
        files = [root / name for name in record["files"]]
        if record["family"] == "IETF":
            texts = [f for f in files if f.suffix == ".txt"]
            if not texts:
                continue
            reference = ast.spec_ref(record["identifier"])
            sources[reference, "rfc"] = _Source(
                reference, texts[0], None, record["url"], "rfc"
            )
        elif record["family"] == "3GPP":
            # (archived file, readable document): normally the same `.docx`;
            # for a legacy `.doc` (TS 32.299, 29.368), the downloader's
            # conversion.
            documents = [(f, f) for f in files if f.suffix == ".docx"] or [
                (root / conversion["source"], root / conversion["file"])
                for conversion in record.get("conversions") or ()
            ]
            legacy = [(f, f) for f in files if f.suffix == ".doc"]
            unconverted = not documents and bool(legacy)
            documents = documents or legacy
            if not documents or not record.get("pdf_url"):
                continue
            archived, document = documents[0]
            try:
                reference = ast.spec_ref(record["identifier"])
            except ast.SpecRefError:
                # A `.dad` file names a TS or an RFC. A catalogued TR is
                # guidance with no definitions of its own (TR 29.909, dropped
                # from the catalog, proposed AVPs with codes left as "XXX")
                # and has no reference a corpus file could carry.
                continue
            pdfs = [f for f in files if f.suffix == ".pdf"]
            # "3gpp/Rel-19/TS_29.388/29388-j10.docx" → "3gpp/rel-19".
            release = Path(record["files"][files.index(archived)]).parts[1]
            tree = f"3gpp/{release.lower()}"
            sources[reference, tree] = _Source(
                reference,
                document,
                pdfs[0] if pdfs else None,
                record["pdf_url"],
                tree,
                unconverted,
            )
        elif record["family"] == "oneM2M":
            # Always a legacy `.doc`, read through its conversion; no PDF
            # rendering of the same version exists, so no pages, and the
            # link is oneM2M's download.
            converted = [
                root / conversion["file"]
                for conversion in record.get("conversions") or ()
            ]
            legacy = [f for f in files if f.suffix == ".doc"]
            if not converted and not legacy:
                continue
            reference = ast.spec_ref(record["identifier"])
            # "oneM2M TS-0004" V2.35.0 → "ts-0004-v2_35_0", the name oneM2M
            # gives its file, less the title: "TS-0004-Service_Layer_Core_
            # Protocol-V2_35_0(cl).doc".
            version = record["source_version"].replace(".", "_")
            sources[reference, "onem2m"] = _Source(
                reference,
                converted[0] if converted else legacy[0],
                None,
                record["url"],
                "onem2m",
                unconverted=not converted,
                stem=f"{reference.removeprefix('oneM2M-').lower()}-v{version}",
            )
    return sources


def _transcriptions(directory: Path | None) -> dict[_Key, _Source]:
    """Every hand transcription in `directory` as a source, by the reference its
    file is named for, written under its publisher's name for the version:
    `ETSI-ES283.034.dad` to `etsi/es283034-020200.dad` (ETSI's code for V2.2.0),
    `3GPP2-X.S0057.dad` to `3gpp2/xs0057-0_v2.0.dad` (`_tgpp2_stem`)."""
    found: dict[_Key, _Source] = {}
    for path in sorted(directory.glob("*.dad")) if directory is not None else ():
        text = path.read_text(encoding="utf-8")
        version = _VERSION_LINE_RE.search(text)
        if version is None:
            raise ValueError(f"{path}: a transcription states its '; Version:'")
        if match := _ETSI_STEM_RE.match(path.stem):
            code = "".join(f"{int(part):02d}" for part in version["value"].split("."))
            tree = "etsi"
            # A part keeps ETSI's own run of digits: ts_18305901v020101p.pdf.
            part = f"{int(match['part']):02d}" if match["part"] else ""
            number = f"{match['series']}{match['number']}{part}"
            stem = f"{match['kind'].lower()}{number}-{code}"
        elif match := _TGPP2_STEM_RE.match(path.stem):
            tree = "3gpp2"
            stem = _tgpp2_stem(path, text, match["number"], version["value"])
        elif path.stem.startswith("OMA-"):
            tree = "oma"
            stem = _oma_stem(path, text, version["value"])
        else:
            raise ValueError(
                f"{path}: a transcription is named for an ETSI, 3GPP2 or OMA"
                " document (ETSI-ES283.034.dad, 3GPP2-X.S0057.dad,"
                " OMA-DDS-Charging_Data.dad)"
            )
        found[path.stem, tree] = _Source(
            path.stem, path, None, "", tree, transcribed=True, stem=stem
        )
    return found


def _tgpp2_stem(path: Path, text: str, number: str, version: str) -> str:
    """`xs0057-0_v2.0` for 3GPP2 X.S0057 V2.0, from the rendering's name,
    `X.S0057-0_v2.0_091215.pdf`. A spec-ref has no revision letter (X.S0057-0,
    -A, -B), so this stem is where a transcription states it and where
    `corpus.revision` reads it."""
    transcribed = _TRANSCRIBED_LINE_RE.search(text)
    rendering = (
        TGPP2_RENDERING_RE.match(transcribed["value"].rsplit("/", 1)[-1])
        if transcribed is not None
        else None
    )
    if (
        rendering is None
        or rendering["number"] != number
        or rendering["version"] != version
    ):
        raise ValueError(
            f"{path}: a 3GPP2 transcription is transcribed from 3GPP2's"
            f" rendering of its number and version, {number}-<revision>"
            f"_v{version}_<date>.pdf"
        )
    return f"{number.replace('.', '')}-{rendering['revision']}_v{version}".lower()


def _oma_stem(path: Path, text: str, version: str) -> str:
    """`dds-charging_data-v1_0-20110201-a` for OMA-DDS-Charging_Data V1.0, from
    the rendering's name, `OMA-DDS-Charging_Data-V1_0-20110201-A.pdf`, less the
    publisher. The name holds the approval date and status the version does not."""
    transcribed = _TRANSCRIBED_LINE_RE.search(text)
    name = transcribed["value"].rsplit("/", 1)[-1] if transcribed is not None else ""
    expected = f"{path.stem}-V{version.replace('.', '_')}-"
    if not (name.startswith(expected) and name.endswith(".pdf")):
        raise ValueError(
            f"{path}: an OMA transcription is transcribed from OMA's rendering of"
            f" its name and version, {expected}<date>-<status>.pdf"
        )
    return name.removeprefix("OMA-").removesuffix(".pdf").lower()


_ETSI_STEM_RE = re.compile(
    r"^ETSI-(?P<kind>TS|ES)(?P<series>\d{3})\.(?P<number>\d{3})(?:-(?P<part>\d+))?$"
)
_TGPP2_STEM_RE = re.compile(r"^3GPP2-(?P<number>[A-Z]\.[A-Z]\d{4}(?:-\d{3})?)$")
_VERSION_LINE_RE = re.compile(r"^; Version: (?P<value>[0-9.]+)$", re.MULTILINE)
_TRANSCRIBED_LINE_RE = re.compile(
    r"^; Transcribed: by hand from (?P<value>\S+)$", re.MULTILINE
)


def _committed(corpus: Path) -> dict[_Key, _Committed]:
    """Every corrected file in the corpus with its raw mirror, by reference
    and tree."""
    committed: dict[_Key, _Committed] = {}
    for corrected in sorted(corpus.rglob("*.dad")):
        if (
            corrected.name.endswith(".raw.dad")
            or "raw" in corrected.relative_to(corpus).parts
        ):
            continue
        spec = parser.parse(corrected.read_text(encoding="utf-8"))
        reference = ast.spec_ref(spec.specification)
        raw = corpus / "raw" / corrected.relative_to(corpus).with_suffix(".raw.dad")
        tree = corrected.parent.relative_to(corpus).as_posix()
        committed[reference, tree] = _Committed(corrected, raw, spec.version)
    return committed


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def describe(outcome: Outcome) -> str:
    """One line per specification, as `seanchai corpus regenerate` prints it."""
    version = f" {outcome.version}" if outcome.version else ""
    if outcome.status == "new" and outcome.replaced:
        return (
            f"replaced  {outcome.reference}{version} (was {outcome.replaced_version};"
            " following the manifest)"
        )
    if outcome.error:
        return f"{outcome.status:<9} {outcome.reference}: {outcome.error}"
    return f"{outcome.status:<9} {outcome.reference}{version}"
