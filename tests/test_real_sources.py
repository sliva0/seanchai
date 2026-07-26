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

from seanchai.dad import formatter, parser
from seanchai.extractor import tgpp_docx

_ROOT = Path(__file__).parent.parent
_MANUAL = _ROOT / "output" / "manual"
_PATCHES = _ROOT / "patches"


def _cases():
    """One case per committed raw file, paired with the sources that produced
    it: the docx by file name, the PDF by the `; Link:` header the file
    already carries."""
    for raw in sorted((_ROOT / "examples").glob("*.raw.dad")):
        spec = parser.parse(raw.read_text(encoding="utf-8"))
        assert spec.link is not None, f"{raw.name} has no ; Link: to find its PDF by"
        docx = _MANUAL / f"{raw.name.removesuffix('.raw.dad')}.docx"
        pdf = _MANUAL / Path(str(spec.link)).name
        yield pytest.param(raw, docx, pdf, str(spec.link), id=raw.name)


@pytest.mark.parametrize(("raw", "docx", "pdf", "link"), list(_cases()))
def test_the_real_sources_still_produce_the_committed_raw_output(raw, docx, pdf, link):
    missing = [path.name for path in (docx, pdf) if not path.is_file()]
    if missing:
        pytest.skip(f"hand-fetched sources not present: {', '.join(missing)}")

    spec = tgpp_docx.extract(docx, link=link, patches_dir=_PATCHES)
    spec = tgpp_docx.attach_pages(spec, pdf)

    # Byte-for-byte, not tree equality: the committed file is what a version
    # upgrade diffs against, so formatting is part of what must not drift.
    assert formatter.format_spec(spec) == raw.read_text(encoding="utf-8")
