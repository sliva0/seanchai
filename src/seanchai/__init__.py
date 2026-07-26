"""Seanchaí: Diameter specifications as reviewable `.dad` files.

The package itself stays empty on purpose. Importing `seanchai` should not
pull in docx, PDF and HTTP machinery, and the command-line interface is one
consumer of the library rather than its front door — it lives in `cli`.

The library is in three subpackages:

- `seanchai.dad` — the `.dad` AST, parser, canonical formatter and corrections;
- `seanchai.extractor` — 3GPP docx/PDF to AST;
- `seanchai.downloader` — the specification corpus.
"""
