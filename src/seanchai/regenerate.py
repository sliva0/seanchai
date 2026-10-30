"""Rebuild the committed corpus from the downloaded sources.

`dad/` is derived output: every file in it is one extraction, one page
attachment and one correction pass over a document the downloader fetched.
This module does that for every specification the corpus holds, in one call,
driven by `specifications/manifest.json`, so that the corpus can never quietly
drift from what the sources and the edit layers would produce today.

Which documents count is decided by the corpus, not the manifest: the catalog
holds documents that define nothing the extractor reads (TS 29.201's XML
mapping, 29.228's IE tables, 29.230's registry), so a run rebuilds what is
committed plus whatever `add` names.
Which *version* counts is decided by the manifest: the downloader already
prefers the newest version with a published ETSI PDF, and a corpus that lags
it is exactly what this module exists to expose, so a superseded pair is
replaced and reported rather than kept.

The library returns a `Report`; `seanchai regenerate` prints it.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import ranges
from .dad import ast, corrections, formatter, parser
from .dad.corrections import CorrectionError
from .dad.parser import DadParseError
from .extractor import rfc_text, tgpp_docx
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
    """
    listed = _sources(manifest)
    committed = _committed(corpus)
    outcomes = []
    for reference in sorted(set(only or committed) | set(add)):
        outcome = _one(
            reference,
            listed.get(reference),
            committed.get(reference),
            corpus,
            output,
            sources_dir,
            corrections_dir,
            expand_ranges,
        )
        outcomes.append(outcome)
        report(outcome)
    return Report(outcomes)


def _one(
    reference: str,
    source: _Source | None,
    committed: _Committed | None,
    corpus: Path,
    output: Path,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    expand_ranges: bool,
) -> Outcome:
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
    if expand_ranges and spec.version is not None:
        try:
            _expand(outcome, spec, sources_dir, corrections_dir)
        except (CorrectionError, OSError, ValueError) as error:
            outcome.status = "failed"
            outcome.error = f"expanding ranges: {error}"
            return outcome

    stem = source.document.stem
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
) -> None:
    """Widen the stale ranges of a specification that just rebuilt cleanly.

    A clean rebuild is what makes this safe: every patch and quirk fired as
    declared and every correction's `expect` held, on this version.
    """
    assert spec.version is not None
    expansions = []
    if sources_dir is not None:
        path = sources_dir / f"{outcome.reference}.toml"
        expansions.append(ranges.expand_sources(path, spec.version))
    if corrections_dir is not None:
        expansions.append(
            ranges.expand_corrections(corrections_dir, spec.specification, spec.version)
        )
    outcome.expanded = [line for e in expansions for line in e.widened]
    remaining = [line for e in expansions for line in e.remaining]
    # The range warnings describe the files as they were; what is still out
    # of range after the rewrite is reported in their place.
    outcome.warnings = [
        warning for warning in outcome.warnings if not isinstance(warning, RangeWarning)
    ] + [f"not widened, widen it by hand: {line}" for line in remaining]


def _produce(
    source: _Source,
    sources_dir: Path | None,
    corrections_dir: Path | None,
    warnings: list[str],
) -> tuple[str, str, ast.Specification]:
    """The raw and corrected texts for one source, and the corrected tree."""
    comments = formatter.Comments()
    if source.document.suffix == ".txt":
        spec = rfc_text.extract(
            source.document,
            link=source.link,
            warnings=warnings,
            sources_dir=sources_dir,
        )
    else:
        spec, comments = tgpp_docx.extract_with_comments(
            source.document,
            link=source.link,
            warnings=warnings,
            sources_dir=sources_dir,
        )
        if source.pdf is not None:
            spec = tgpp_docx.attach_pages(spec, source.pdf, warnings=warnings)
    raw_text = formatter.format_spec(spec, comments)
    declared = corrections.load(corrections_dir, spec.specification)
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


def _sources(manifest_path: Path) -> dict[str, _Source]:
    """The manifest's records the extractor can read, by spec reference.

    A 3GPP record whose archive held a legacy `.doc` is readable through the
    `.docx` the downloader converted it to, listed under `conversions`. One
    whose `.doc` was extracted with no conversion (`--no-convert`) is listed
    as unconverted, so asking for it reports "not converted"; a record with
    no document at all (`--no-extract`) is left out, so asking for it reports
    "not in manifest" — which is what it is, as far as regeneration is
    concerned.
    """
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources: dict[str, _Source] = {}
    for record in manifest["artifacts"]:
        files = [root / name for name in record["files"]]
        if record["family"] == "IETF":
            texts = [f for f in files if f.suffix == ".txt"]
            if not texts:
                continue
            reference = ast.spec_ref(record["identifier"])
            sources[reference] = _Source(
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
            sources[reference] = _Source(
                reference,
                document,
                pdfs[0] if pdfs else None,
                record["pdf_url"],
                f"3gpp/{release.lower()}",
                unconverted,
            )
    return sources


def _committed(corpus: Path) -> dict[str, _Committed]:
    """Every corrected file in the corpus with its raw mirror, by reference."""
    committed: dict[str, _Committed] = {}
    for corrected in sorted(corpus.rglob("*.dad")):
        if (
            corrected.name.endswith(".raw.dad")
            or "raw" in corrected.relative_to(corpus).parts
        ):
            continue
        spec = parser.parse(corrected.read_text(encoding="utf-8"))
        reference = ast.spec_ref(spec.specification)
        raw = corpus / "raw" / corrected.relative_to(corpus).with_suffix(".raw.dad")
        committed[reference] = _Committed(corrected, raw, spec.version)
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
