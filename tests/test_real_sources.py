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
    """
    committed = sorted((_ROOT / "dad").rglob("*.dad"))
    assert committed, "no committed .dad files found — this test would pass vacuously"
    for path in committed:
        spec = parser.parse(path.read_text(encoding="utf-8"))
        assert spec.link is not None, f"{path.name} has no ; Link: to find its PDF by"
        raw = path.name.endswith(".raw.dad")
        stem = path.name.removesuffix(".raw.dad" if raw else ".dad")
        docx = _MANUAL / f"{stem}.docx"
        pdf = _MANUAL / Path(str(spec.link)).name
        yield pytest.param(path, docx, pdf, str(spec.link), raw, id=path.name)


@pytest.mark.parametrize(("committed", "docx", "pdf", "link", "raw"), list(_cases()))
def test_the_real_sources_still_produce_the_committed_output(
    committed, docx, pdf, link, raw
):
    missing = [path.name for path in (docx, pdf) if not path.is_file()]
    if missing:
        pytest.skip(f"hand-fetched sources not present: {', '.join(missing)}")

    spec = tgpp_docx.extract(docx, link=link, patches_dir=_PATCHES)
    spec = tgpp_docx.attach_pages(spec, pdf)
    notes: dict[int, list[str]] = {}
    if not raw:
        declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)
        if declared:
            spec, results = corrections.apply(spec, declared)
            for result in results:
                notes.setdefault(result.node_id, []).append(
                    f"corrected: {result.correction.field}"
                    f" {result.old!r} -> {result.new!r} [{result.correction.origin}]"
                )

    # Byte-for-byte, not tree equality: the committed file is what a version
    # upgrade diffs against, so formatting is part of what must not drift.
    assert formatter.format_spec(spec, notes) == committed.read_text(encoding="utf-8")
