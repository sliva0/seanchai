from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def canonical_dad_text() -> str:
    """The hand-made reference `.dad` file, which is canonically formatted."""
    return (EXAMPLES_DIR / "ts_129329v180000p.dad").read_text()
