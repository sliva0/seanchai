from pathlib import Path

import pytest

FILES_DIR = Path(__file__).parent.parent / "files"


@pytest.fixture
def canonical_dad_text() -> str:
    """The hand-made reference `.dad` file, which is canonically formatted."""
    return (FILES_DIR / "ts_129329v180000p.dad").read_text()
