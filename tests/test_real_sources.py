"""Regression pin of both extractors against the real source documents.

Every committed `.dad` file is re-extracted from the docx/PDF or RFC text that
produced it and compared byte-for-byte. This is the test that catches an
extractor change which is fine on the synthetic fixture and wrong on the real
documents.

The sources live under the git-ignored `specifications/` (fetched by
`seanchai download`; hand-fetched docx/PDF pairs under `specifications/manual/`).
A missing source is a failure, not a skip: a suite that silently skipped its
strongest check would look green for the wrong reason. Run
`pytest -m "not sources"` to leave these out deliberately.
"""

from pathlib import Path

import pytest

from seanchai.dad import corrections, formatter, parser
from seanchai.extractor import rfc_text, tgpp_docx

_ROOT = Path(__file__).parent.parent
_MANUAL = _ROOT / "specifications" / "manual"
_RFC_TEXTS = _ROOT / "specifications" / "rfc"
_SOURCES = _ROOT / "edits" / "sources"


def _cases():
    """One case per committed file, paired with the sources that produced it:
    the docx by file name, the PDF by the `; Link:` header the file carries.

    Both kinds are covered. `.raw.dad` pins the extractor alone; `.dad` pins
    the extractor plus the correction layer, which is also what re-checks that
    every `expect` still matches freshly extracted output.

    A file with no `; Link:` is pinned without pages: TS 29.388's docx is
    18.1.0 while ETSI publishes only an 18.0.0 PDF, and page numbers from the
    wrong version are worse than none, so that file carries neither.
    """
    committed = sorted((_ROOT / "dad").rglob("*.dad"))
    assert committed, "no committed .dad files found — this test would pass vacuously"
    for path in committed:
        spec = parser.parse(path.read_text(encoding="utf-8"))
        raw = path.name.endswith(".raw.dad")
        stem = path.name.removesuffix(".raw.dad" if raw else ".dad")
        link = str(spec.link) if spec.link is not None else None
        if path.parent.name == "rfc":
            # RFC files re-extract from the downloader's own text output —
            # `seanchai download` fetches rfc-editor.org renderings, so there
            # is nothing to hand-fetch.
            source = _RFC_TEXTS / f"{stem}.txt"
            pdf = None
        else:
            source = _MANUAL / f"{stem}.docx"
            pdf = _MANUAL / Path(link).name if link is not None else None
        yield pytest.param(path, source, pdf, link, raw, id=path.name)


@pytest.mark.sources
@pytest.mark.parametrize(("committed", "source", "pdf", "link", "raw"), list(_cases()))
def test_the_real_sources_still_produce_the_committed_output(
    committed, source, pdf, link, raw
):
    sources = [source] if pdf is None else [source, pdf]
    missing = [path.name for path in sources if not path.is_file()]
    assert not missing, (
        f"sources not present locally: {', '.join(missing)} — run `seanchai download`"
        ' or deselect with `pytest -m "not sources"`'
    )

    if source.suffix == ".txt":
        spec = rfc_text.extract(source, link=link, sources_dir=_SOURCES)
    else:
        spec = tgpp_docx.extract(source, link=link, sources_dir=_SOURCES)
    if pdf is not None:
        spec = tgpp_docx.attach_pages(spec, pdf)
    notes, standing, detached = {}, {}, {}
    if not raw:
        declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)
        if declared:
            spec, results = corrections.apply(spec, declared)
            notes, standing, detached = corrections.notes(results)

    # Byte-for-byte, not tree equality: the committed file is what a version
    # upgrade diffs against, so formatting is part of what must not drift.
    formatted = formatter.format_spec(spec, notes, standing, detached)
    assert formatted == committed.read_text(encoding="utf-8")
