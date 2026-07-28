"""Optional regression pin of the extractor against the real source documents.

The rest of the suite runs on a synthetic docx, which is what keeps it fast and
committable. This module pins the other half: that the committed raw output is
still exactly what the real 3GPP docx and its ETSI PDF produce. It is the test
that catches an extractor change which is fine on the fixture and wrong on the
documents the fixture was abstracted from.

The sources are hand-fetched binaries under the git-ignored `output/manual/`
(see docs/workflow.md), so every test here skips when they are absent — which
is the normal state of a fresh clone, and of CI until there is one.
"""

from pathlib import Path

import pytest

from seanchai.dad import corrections, formatter, parser
from seanchai.extractor import tgpp_docx

_ROOT = Path(__file__).parent.parent
_MANUAL = _ROOT / "specifications" / "manual"
_PATCHES = _ROOT / "edits" / "patches"


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
        docx = _MANUAL / f"{stem}.docx"
        link = str(spec.link) if spec.link is not None else None
        pdf = _MANUAL / Path(link).name if link is not None else None
        yield pytest.param(path, docx, pdf, link, raw, id=path.name)


@pytest.mark.parametrize(("committed", "docx", "pdf", "link", "raw"), list(_cases()))
def test_the_real_sources_still_produce_the_committed_output(
    committed, docx, pdf, link, raw
):
    sources = [docx] if pdf is None else [docx, pdf]
    missing = [path.name for path in sources if not path.is_file()]
    if missing:
        pytest.skip(f"hand-fetched sources not present: {', '.join(missing)}")

    spec = tgpp_docx.extract(docx, link=link, patches_dir=_PATCHES)
    if pdf is not None:
        spec = tgpp_docx.attach_pages(spec, pdf)
    notes: dict[int, list[str]] = {}
    if not raw:
        declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)
        if declared:
            spec, results = corrections.apply(spec, declared)
            notes = corrections.notes(results)

    # Byte-for-byte, not tree equality: the committed file is what a version
    # upgrade diffs against, so formatting is part of what must not drift.
    assert formatter.format_spec(spec, notes) == committed.read_text(encoding="utf-8")
