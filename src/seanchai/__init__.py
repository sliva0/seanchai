"""Seanchaí: Diameter specifications as reviewable `.dad` files.

This package holds only the shared error base and the version, so importing
`seanchai` pulls in no docx, PDF or HTTP code. The command line lives in `cli`.

- `seanchai.model`: the corpus resolved into objects a consumer uses, the place
  to start (docs/consumers.md);
- `seanchai.corpus`: a set of parsed `.dad` files, and the rules for resolving
  between them;
- `seanchai.dictionary`: the JSON `seanchai dictionary` writes, as pydantic
  models, and its builder;
- `seanchai.export` and `seanchai.export_schema`: the JSON `seanchai export`
  writes for the static site, and its shape;
- `seanchai.dad`: the `.dad` AST, parser, canonical formatter, corrections and
  the ABNF syntax they share;
- `seanchai.linter`: the rules reporting what a file or the corpus contradicts;
- `seanchai.oracle`: the cross-check against Wireshark's Diameter dictionary;
- `seanchai.wireshark`: the Wireshark plugin validating Diameter traffic
  against the corpus;
- `seanchai.errors`: the error base, and the error naming a missing extra;
- `seanchai.extractor`: 3GPP docx/PDF and RFC text to AST, the former with the
  `seanchai[extract]` extra;
- `seanchai.downloader`: fetches the source documents the corpus is built from,
  with that extra for whatever it has to open as docx or PDF.

Semantic versioning covers the names in the `__all__` of this package and of
each module listed above (for `seanchai.downloader`, the package's own; for
`seanchai.extractor`, its modules'), the command line's commands, options and
exit statuses, the format versions of the two JSON outputs
(`dictionary.FORMAT_VERSION`, `export_schema.SCHEMA_VERSION`) and the corpus
formats the library reads (`corpus.FORMATS`). Modules whose names start with an
underscore, names outside an `__all__`, and the Python of `seanchai.cli` may
change in any release.
"""

from importlib.metadata import version

from .errors import SeanchaiError

__all__ = ["SeanchaiError", "__version__"]

# Kept once, in this package's pyproject.
__version__ = version("seanchai")
