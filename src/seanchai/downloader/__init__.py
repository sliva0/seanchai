"""Download the 3GPP and IETF Diameter specification corpus.

3GPP keeps every version of a specification as a ZIP file in its archive.
Those ZIPs normally contain the editable DOC or DOCX specification source;
a legacy DOC is converted to DOCX with headless LibreOffice. oneM2M's
specifications come from its document library at a catalogued version, as
a ZIP holding a legacy DOC converted the same way.
RFCs are downloaded as canonical plain text from the RFC Editor, and the
official ETSI PDF renditions alongside the 3GPP sources. The PDFs the hand
transcriptions were copied from come from ETSI, 3GPP2 and OMA at the catalog's URLs.

The curated specification catalog lives in ``specs.toml`` next to this package;
the CLI downloads into the git-ignored ``specifications/`` directory by default.

This package is a library: it returns records and raises `DownloadError`, and
the `seanchai download` command owns the printing and the exit status. The
catalog lives in `catalog` and the implementation in `core`; what is re-exported
here is what the boundary promises. Only a 3GPP, oneM2M or `transcribed` download
needs the `seanchai[extract]` extra, to validate what it fetched.
"""

from .catalog import (
    CATALOG_PATH,
    RELEASE,
    SOURCES,
    Catalog,
    DownloadError,
    OneM2MSpec,
    PinnedThreeGppSpec,
    RfcSpec,
    ThreeGppSpec,
    TranscribedDocument,
    load_catalog,
)
from .core import Conversion, DownloadRecord, download_corpus, download_version

__all__ = [
    "CATALOG_PATH",
    "RELEASE",
    "SOURCES",
    "Catalog",
    "Conversion",
    "DownloadError",
    "DownloadRecord",
    "OneM2MSpec",
    "PinnedThreeGppSpec",
    "RfcSpec",
    "ThreeGppSpec",
    "TranscribedDocument",
    "download_corpus",
    "download_version",
    "load_catalog",
]
