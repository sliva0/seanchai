"""Extractor: 3GPP .docx specification to `.dad` AST; also oneM2M TS-0004,
whose Diameter annex follows 3GPP's Word conventions.

`extract` walks the docx body (paragraphs and tables in document order,
grouped under numbered headings) into a `Specification`. `attach_pages` then
adds pages from the bookmark outline of the matching ETSI PDF.

Source text is normalized once, while building the section model, and input
patches (`extractor.sources`) are applied at that point, so patch counts are
exact and every later step sees patched text. Enumerated-AVP sections do not
print a vendor-id, so local AVPs take it from the grouped-AVP headers (3GPP:
10415). docs/extractor.md says which clause shapes become which blocks.

Modules: `_docx` reads the body into the section model of `_base`; `_collect`
classifies clauses with `_rules`, `_commands`, `_enums`, `_avp_tables` (over
`_tables`), `_origins` and `_registries`, then resolves and orders the blocks;
`_values` reads value tables; `_extract` runs it all and attaches pages;
`_quirks` holds the quirk names. Only `__all__` here is public.
"""

from ._base import ONEM2M_VENDOR, TGPP_VENDOR
from ._extract import attach_pages, extract, extract_with_comments, sources_file_name
from ._quirks import QUIRKS

__all__ = [
    "ONEM2M_VENDOR",
    "QUIRKS",
    "TGPP_VENDOR",
    "attach_pages",
    "extract",
    "extract_with_comments",
    "sources_file_name",
]
