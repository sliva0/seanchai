"""Every Python snippet a consumer reads runs as it stands."""

import re

import pytest
from conftest import _ROOT

_SNIPPET = re.compile(r"^```python\n(.*?)^```$", re.DOTALL | re.MULTILINE)
_DOCUMENTS = (
    "README.md",
    "docs/consumers.md",
    "packages/seanchai-corpus/README.md",
)


def _snippets() -> list[tuple[str, str]]:
    return [
        (f"{name}:{number}", snippet)
        for name in _DOCUMENTS
        for number, snippet in enumerate(
            _SNIPPET.findall((_ROOT / name).read_text("utf-8")), 1
        )
    ]


def test_the_documents_hold_snippets():
    assert {place.partition(":")[0] for place, _ in _snippets()} == set(_DOCUMENTS)


@pytest.mark.parametrize(
    ("place", "snippet"), _snippets(), ids=[place for place, _ in _snippets()]
)
def test_a_snippet_runs(place, snippet):
    exec(compile(snippet, place, "exec"), {})


@pytest.mark.parametrize("name", ["README.md", "packages/seanchai-corpus/README.md"])
def test_what_pypi_shows_links_nothing_relative(name):
    """PyPI renders a README away from the repository, so a relative link is
    dead there."""
    text = (_ROOT / name).read_text("utf-8")

    targets = re.findall(r"\]\(([^)]+)\)|^\[[^\]]+\]: (\S+)$", text, re.MULTILINE)

    assert targets
    for inline, reference in targets:
        assert (inline or reference).startswith("https://")
