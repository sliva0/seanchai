"""Rebuild the committed corpus from the downloaded sources.

The corpus is derived output: every file in it is one extraction, one page
attachment and one correction pass over a document the downloader fetched.
This module does that for every specification the corpus holds, in one call,
driven by `specifications/manifest.json`, so that the corpus can never quietly
drift from what the sources and the edit layers would produce today.

A transcription — a document no extractor reads, copied by hand into
`edits/transcriptions/` — has no manifest record: the transcription is its
source, read through its input patches into the raw file, and it is
otherwise rebuilt like any other (`extractor.transcription`).

Which documents count is decided by the corpus, not the manifest: the catalog
holds documents that define nothing the extractor reads (TS 29.201's XML
mapping, 29.228's IE tables), marked `out_of_scope` there, so a run rebuilds
what is committed plus whatever `add` names and the catalog does not refuse.
Which *version* counts is decided by the manifest: the downloader already
prefers the newest version with a published ETSI PDF, and a corpus that lags
it is exactly what this module exists to expose, so a superseded pair is
replaced and reported rather than kept.

The library returns a `Report`; `seanchai regenerate` prints it.
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import correction_record, linter, ranges
from .corpus import TGPP2_RENDERING_RE, Corpus, CorpusError
from .dad import ast, corrections, formatter, parser
from .dad.corrections import CorrectionError
from .dad.parser import DadParseError
from .downloader.catalog import SOURCES, load_catalog
from .errors import SeanchaiError
from .extractor import rfc_text, transcription
from .extractor.errors import ExtractionError
from .versions import RangeWarning, VersionRange

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


@dataclass
class Report:
    outcomes: list[Outcome]
    # The corrections record written, under the output directory; None with no
    # corrections directory, or when a failure left the corpus part rebuilt.
    record: Path | None = None
    # The sources a partial download left out that this run needed, as
    # `seanchai download --only` names them.
    missing_sources: tuple[str, ...] = ()

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
    # "3gpp/rel-18" or "rfc": the corpus subdirectory the pair belongs in.
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
    transcriptions_dir: Path | None = None,
    add: Sequence[str] = (),
    only: Sequence[str] = (),
    report: Callable[[Outcome], None] = lambda outcome: None,
    expand_ranges: bool = False,
) -> Report:
    """Rebuild every committed specification (plus `add`) into `output`.

    `output` may be `corpus` itself, which is the normal run, or an empty
    directory, which is how the test suite checks that the committed corpus
    is what the sources produce without touching it.

    `only` rebuilds those specifications instead of every committed one. With
    the manifest of an older version (`seanchai download --spec --version`)
    and a scratch `output`, that re-extracts the older version for a
    raw-vs-raw diff against the corpus.

    `expand_ranges` widens, in the edit files themselves, every declaration
    range a successfully rebuilt specification's version falls outside; see
    `seanchai.ranges`.

    `transcriptions_dir` holds the hand transcriptions of documents no
    extractor reads, each a source like a manifest record.

    With `corrections_dir`, a run nothing failed in also rewrites `output`'s
    corrections record, over whatever corrected files `output` then holds
    (`seanchai.correction_record`).
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
    for key in _selected(listed, committed, only, readable):
        outcome = _one(
            key[0],
            listed.get(key),
            committed.get(key),
            corpus,
            output,
            sources_dir,
            corrections_dir,
            books,
            absent,
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
    if corrections_dir is not None and not result.failed:
        try:
            result.record = correction_record.write(output, corrections_dir)
        except (CorrectionError, CorpusError, OSError) as error:
            failed = Outcome(
                correction_record.RECORD_NAME, "failed", error=f"writing: {error}"
            )
            outcomes.append(failed)
            report(failed)
    return result


class ManifestError(SeanchaiError):
    """A `manifest.json` that is missing or is not what `seanchai download`
    writes."""


# A corpus file's place: its reference and the corpus subdirectory it sits
# in, `("TS29.214", "3gpp/rel-18")`. The corpus holds one copy of a document
# per release tree, so TS 29.214 V7.12.0, which ETSI TS 183 017 cites as
# "Release 7", sits in `3gpp/rel-7` beside V18.4.0 in `3gpp/rel-18`.
_Key = tuple[str, str | None]


def _selected(
    listed: dict[_Key, _Source],
    committed: dict[_Key, _Committed],
    only: Sequence[str],
    add: Sequence[str],
) -> list[_Key]:
    """The copies a run rebuilds: every committed one, or with `only` those
    of the references it names that the manifest lists (an older version's
    one-record manifest lists one release of a document the corpus may hold
    in two), and with `add` every listed copy of a reference not committed.
    A named reference neither lists nor commits is kept, as `(reference,
    None)`, to be reported."""

    def of(reference: str, keys) -> list[_Key]:
        return [key for key in keys if key[0] == reference]

    if only:
        keys = []
        for reference in only:
            keys += (
                of(reference, listed) or of(reference, committed) or [(reference, None)]
            )
    else:
        keys = list(committed)
    for reference in add:
        keys += [key for key in of(reference, listed) if key not in committed] or (
            [] if of(reference, committed) else [(reference, None)]
        )
    return sorted(set(keys), key=lambda key: (key[0], key[1] or ""))


def _one(
    reference: str,
    source: _Source | None,
    committed: _Committed | None,
    corpus: Path,
    output: Path,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    books: Corpus | None,
    absent: frozenset[str] = frozenset(),
) -> Outcome:
    if source is None and _source_of(reference) in absent:
        name = _source_of(reference)
        return Outcome(
            reference,
            "not-in-manifest",
            error=f"{name} is not downloaded (`seanchai download --only {name}`);"
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
            " (`seanchai download --no-convert`); the committed files were"
            " left alone",
        )
    outcome = Outcome(reference, "unchanged")
    try:
        raw_text, corrected_text, spec = _produce(
            source, sources_dir, corrections_dir, outcome.warnings
        )
    except (ExtractionError, CorrectionError, DadParseError, OSError) as error:
        outcome.status = "failed"
        outcome.error = str(error)
        return outcome
    outcome.version = spec.version
    if books is not None and spec.version is not None:
        try:
            _expand(outcome, spec, sources_dir, corrections_dir, books)
        except (CorrectionError, OSError, ValueError) as error:
            outcome.status = "failed"
            outcome.error = f"expanding ranges: {error}"
            return outcome

    stem = source.stem or source.document.stem
    corrected = output / source.tree / f"{stem}.dad"
    raw = output / "raw" / source.tree / f"{stem}.raw.dad"
    outcome.written = [corrected, raw]

    if committed is None:
        outcome.status = "new"
    elif committed.corrected.name != corrected.name:
        # A different version than the corpus holds: follow the manifest,
        # and take the old pair out of the output so the corpus never holds
        # two versions of one document.
        outcome.status = "new"
        outcome.replaced_version = committed.version
        for old in (committed.corrected, committed.raw):
            relocated = output / old.relative_to(corpus)
            outcome.replaced.append(relocated)
            relocated.unlink(missing_ok=True)
    elif (
        _read(committed.corrected) != corrected_text or _read(committed.raw) != raw_text
    ):
        outcome.status = "changed"

    for path, text in ((corrected, corrected_text), (raw, raw_text)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return outcome


def _expand(
    outcome: Outcome,
    spec: ast.Specification,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    books: Corpus,
) -> None:
    """Widen the stale ranges of a specification that just rebuilt cleanly.

    A clean rebuild is what makes this safe: every patch and quirk fired as
    declared and every correction's `expect` held, on this version. An
    acceptance changes nothing the rebuild checks, so the rebuilt file is
    linted against `books` with the module's acceptances, and only those
    that matched their finding are widened; the rest are reported stale.
    """
    assert spec.version is not None
    expansions = []
    if sources_dir is not None:
        path = sources_dir / f"{outcome.reference}.toml"
        expansions.append(ranges.expand_sources(path, spec.version))
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
            ranges.expand_corrections(
                corrections_dir, spec.specification, spec.version, accepted
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
    warnings: list[str],
) -> tuple[str, str, ast.Specification]:
    """The raw and corrected texts for one source, and the corrected tree."""
    comments = formatter.Comments()
    if source.transcribed:
        spec, comments = transcription.read(source.document, sources_dir, warnings)
    elif source.document.suffix == ".txt":
        spec = rfc_text.extract(
            source.document,
            link=source.link,
            warnings=warnings,
            sources_dir=sources_dir,
        )
    else:
        # Here, not at the top: importing this module asks for no extra.
        from .extractor import tgpp_docx

        spec, comments = tgpp_docx.extract_with_comments(
            source.document,
            link=source.link,
            warnings=warnings,
            sources_dir=sources_dir,
        )
        if source.pdf is not None:
            spec = tgpp_docx.attach_pages(spec, source.pdf, warnings=warnings)
    raw_text = formatter.format_spec(spec, comments)
    declared = corrections.in_release(
        corrections.load(corrections_dir, spec.specification), spec.version
    )
    for edit in declared:
        # `__post_init__` parsed the declared string; the annotation still
        # admits it, so parse again (a no-op) to satisfy the type.
        versions = VersionRange.parse(edit.versions)
        if warning := versions.warning(spec.version, f"correction {edit.cited}"):
            warnings.append(warning)
    if declared:
        spec, _, comments = corrections.apply_with_comments(spec, comments, declared)
        corrected_text = formatter.format_spec(spec, comments)
    else:
        corrected_text = raw_text
    return raw_text, corrected_text, spec


def _sources(manifest_path: Path) -> dict[_Key, _Source]:
    """The manifest's records the extractor can read, by spec reference.

    A 3GPP record whose archive held a legacy `.doc` is readable through the
    `.docx` the downloader converted it to, listed under `conversions`. One
    whose `.doc` was extracted with no conversion (`--no-convert`) is listed
    as unconverted, so asking for it reports "not converted"; a record with
    no document at all (`--no-extract`) is left out, so asking for it reports
    "not in manifest" — which is what it is, as far as regeneration is
    concerned.
    """
    try:
        return _read_sources(manifest_path)
    except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
        # JSON that is no manifest fails wherever the walk first trips on it.
        raise ManifestError(
            f"{manifest_path} is no download manifest"
            f" ({type(error).__name__}: {error}); run `seanchai download`"
        ) from error


def _source_of(reference: str) -> str:
    """The `seanchai download --only` source a document comes from. The hand
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
            # "3gpp/Rel-18/TS_29.388/29388-i10.docx" → "3gpp/rel-18".
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
    """Every hand transcription in `directory`, by the reference its file
    is named for, as a source, named as its publisher names the version:
    `ETSI-ES283.034.dad` is written to `etsi/es283034-020200.dad`, ETSI's
    code for V2.2.0, as a 3GPP pair is named for its archive, and
    `3GPP2-X.S0057.dad` to `3gpp2/xs0057-0_v2.0.dad`, 3GPP2's file name
    for revision 0 V2.0 less its date (`_tgpp2_stem`)."""
    found: dict[_Key, _Source] = {}
    for path in sorted(directory.glob("*.dad")) if directory is not None else ():
        text = path.read_text(encoding="utf-8")
        version = _VERSION_LINE_RE.search(text)
        if version is None:
            raise ValueError(f"{path}: a transcription states its '; Version:'")
        if match := _ETSI_STEM_RE.match(path.stem):
            code = "".join(f"{int(part):02d}" for part in version["value"].split("."))
            tree = "etsi"
            stem = f"{match['kind'].lower()}{match['series']}{match['number']}-{code}"
        elif match := _TGPP2_STEM_RE.match(path.stem):
            tree = "3gpp2"
            stem = _tgpp2_stem(path, text, match["number"], version["value"])
        else:
            raise ValueError(
                f"{path}: a transcription is named for an ETSI or 3GPP2 document"
                " (ETSI-ES283.034.dad, 3GPP2-X.S0057.dad)"
            )
        found[path.stem, tree] = _Source(
            path.stem, path, None, "", tree, transcribed=True, stem=stem
        )
    return found


def _tgpp2_stem(path: Path, text: str, number: str, version: str) -> str:
    """`xs0057-0_v2.0` for 3GPP2 X.S0057 V2.0, from the rendering's name,
    `X.S0057-0_v2.0_091215.pdf`. 3GPP2 numbers revisions of a document
    (X.S0057-0, -A, -B), each with its own versions; a spec-ref keeps no
    revision letter, so the rendering's name is the one place a
    transcription states it, and where `corpus.revision` reads it."""
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


_ETSI_STEM_RE = re.compile(
    r"^ETSI-(?P<kind>TS|ES)(?P<series>\d{3})\.(?P<number>\d{3})$"
)
_TGPP2_STEM_RE = re.compile(r"^3GPP2-(?P<number>[A-Z]\.[A-Z]\d{4})$")
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
    """One line per specification, as `seanchai regenerate` prints it."""
    version = f" {outcome.version}" if outcome.version else ""
    if outcome.status == "new" and outcome.replaced:
        return (
            f"replaced  {outcome.reference}{version} (was {outcome.replaced_version};"
            " following the manifest)"
        )
    if outcome.error:
        return f"{outcome.status:<9} {outcome.reference}: {outcome.error}"
    return f"{outcome.status:<9} {outcome.reference}{version}"
