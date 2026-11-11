"""The Seanchaí corpus: `.dad` files and where they are installed.

A data-only package with no dependencies. `CORPUS_DIR` is the directory to
pass to `seanchai.corpus.Corpus.load`. It holds the corrected trees, the
`raw/` mirror, `corpus.toml` (format and resolution rules), `holes.toml`,
`interfaces.toml` and `corrections.json`.
"""

from importlib.metadata import version
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "dad"

# The date the corpus was regenerated, kept once, in this package's pyproject.
__version__ = version("seanchai-corpus")
