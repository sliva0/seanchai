"""Download the 3GPP and IETF Diameter specification corpus.

3GPP archive ZIPs hold a DOC or DOCX source; a legacy DOC is converted to DOCX
with headless LibreOffice. oneM2M specifications come as a ZIP at a catalogued
version and are converted the same way. RFCs come as plain text from the RFC
Editor, the ETSI PDF renditions alongside the 3GPP sources, and the PDFs the
hand transcriptions were copied from from ETSI, 3GPP2 and OMA.

The catalog is `specs.toml` next to this package, and the versions each
release the corpus holds whole is fetched at are `releases.toml` beside it.
The CLI downloads into the git-ignored `specifications/` directory by default.

This package returns records and raises `DownloadError`; `seanchai corpus
download` prints and sets the exit status. What is re-exported here is the
public boundary; `catalog` and `core` are the implementation. Only a 3GPP,
oneM2M or `transcribed` download needs the `seanchai[extract]` extra, to
validate what it fetched. See docs/downloader.md.
"""

from .catalog import (
    CATALOG_PATH,
    RELEASES_PATH,
    SOURCES,
    Catalog,
    DownloadError,
    OneM2MSpec,
    PinnedThreeGppSpec,
    Release,
    RfcSpec,
    ThreeGppSpec,
    TranscribedDocument,
    load_catalog,
)
from .core import Conversion, DownloadRecord, download_corpus, download_version

__all__ = [
    "CATALOG_PATH",
    "RELEASES_PATH",
    "SOURCES",
    "Catalog",
    "Conversion",
    "DownloadError",
    "DownloadRecord",
    "OneM2MSpec",
    "PinnedThreeGppSpec",
    "Release",
    "RfcSpec",
    "ThreeGppSpec",
    "TranscribedDocument",
    "download_corpus",
    "download_version",
    "load_catalog",
]
