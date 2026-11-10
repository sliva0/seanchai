"""The Seanchaí corpus: `.dad` files, and where they are installed.

The package holds data and depends on nothing, the library included. `CORPUS_DIR`
is the directory `seanchai.corpus.Corpus.load` takes, the one holding the
corrected trees, the `raw/` mirror, `corpus.toml` (the corpus's format and
resolution rules), `holes.toml` and `corrections.json`.
"""

from importlib.metadata import version
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "dad"

# The date the corpus was regenerated, kept once, in this package's pyproject.
__version__ = version("seanchai-corpus")
