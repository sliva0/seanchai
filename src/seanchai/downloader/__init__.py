"""Download the 3GPP and IETF Diameter specification corpus.

3GPP keeps every version of a specification as a ZIP file in its archive.
Those ZIPs normally contain the editable DOC or DOCX specification source;
a legacy DOC is converted to DOCX with headless LibreOffice. oneM2M's
specifications come from its document library at a catalogued version, as
a ZIP holding a legacy DOC converted the same way.
RFCs are downloaded as canonical plain text from the RFC Editor, and the
official ETSI PDF renditions alongside the 3GPP sources.

The curated specification catalog lives in ``specs.toml`` next to this package;
the CLI downloads into the git-ignored ``specifications/`` directory by default.

This package is a library: it returns records and raises `DownloadError`, and
the `seanchai download` command owns the printing and the exit status. The
implementation lives in `core`; what is re-exported here is what the boundary
promises.
"""

from .core import (
    CATALOG_PATH,
    Catalog,
    Conversion,
    DownloadError,
    DownloadRecord,
    OneM2MSpec,
    RfcSpec,
    ThreeGppSpec,
    download_corpus,
    download_version,
    load_catalog,
)

__all__ = [
    "CATALOG_PATH",
    "Catalog",
    "Conversion",
    "DownloadError",
    "DownloadRecord",
    "OneM2MSpec",
    "RfcSpec",
    "ThreeGppSpec",
    "download_corpus",
    "download_version",
    "load_catalog",
]
