"""Download the 3GPP and IETF Diameter specification corpus.

3GPP publishes the latest version belonging to each release as a ZIP file.
Those ZIPs normally contain the editable DOC or DOCX specification source.
RFCs are downloaded as canonical plain text from the RFC Editor. Official
3GPP/ETSI PDF renditions can also be downloaded with ``--pdfs``.

The curated specification catalog lives in ``specs.toml`` next to this package;
the CLI downloads into the git-ignored ``specifications/`` directory by default.

This package is a library: it returns records and raises `DownloadError`, and
the `seanchai download` command owns the printing and the exit status. The
implementation lives in `core`; what is re-exported here is what the boundary
promises.
"""

from .core import (
    CATALOG_PATH,
    DownloadError,
    DownloadRecord,
    RfcSpec,
    ThreeGppSpec,
    download_corpus,
    load_catalog,
)

__all__ = [
    "CATALOG_PATH",
    "DownloadError",
    "DownloadRecord",
    "RfcSpec",
    "ThreeGppSpec",
    "download_corpus",
    "load_catalog",
]
