"""Seanchaí: Diameter specifications as reviewable `.dad` files.

The package itself stays nearly empty on purpose. Importing `seanchai` should
not pull in docx, PDF and HTTP machinery, and the command-line interface is one
consumer of the library rather than its front door; it lives in `cli`. Only the
shared error base and the version are here.

- `seanchai.model`: the corpus resolved into objects a consumer uses, the place
  to start (docs/consumers.md);
- `seanchai.corpus`: a set of parsed `.dad` files, and the rules for resolving
  between them;
- `seanchai.dad`: the `.dad` AST, parser, canonical formatter and corrections;
- `seanchai.extractor`: 3GPP docx/PDF and RFC text to AST, the former with the
  `seanchai[extract]` extra;
- `seanchai.downloader`: fetches the source documents the corpus is built from,
  with that extra for whatever it has to open as docx or PDF.
"""

from importlib.metadata import version

from .errors import SeanchaiError

__all__ = ["SeanchaiError", "__version__"]

# Kept once, in this package's pyproject.
__version__ = version("seanchai")
