"""Extractor: 3GPP .docx specification → `.dad` AST; also oneM2M TS-0004,
whose Diameter annex follows 3GPP's Word conventions.

Pipeline stage one of two: this package walks the docx body (paragraphs and
tables in document order, grouped under numbered headings) and produces a
`Specification`. Pages are attached afterwards by `attach_pages`, which reads
only the bookmark outline of the matching ETSI PDF rendering.

All source text is normalized exactly once, while building the section model,
and input patches (see `extractor.sources`) are applied at that same point — so
patch application counting is exact, and every later parsing step sees
patched text.

What maps to what in a 3GPP Diameter spec docx:

- `x.y.z Name (ABBR) Command` headings with a `::= < Diameter Header: ... >`
  paragraph run → `Message`; per-run bold marks this-spec AVPs.
- `x.y.z Name AVP` headings with an `::= < AVP header: ... >` run → `GroupedAvp`.
- `x.y.z Name AVP` headings whose intro says "is of type Enumerated" with
  `B1`-style `ValueName (n)` items → `EnumeratedAvp`; `B2` items are value
  descriptions, `NO`-style "Value n is reserved" notes → reserved values,
  inserted in numeric order; behind `value-first-enums`, `a .. b` ranges
  reserved or left vendor-specific → reserved or vendor-specific values, a
  value labelled "Void" → a void value.
- The AVP-flags table (header "AVP Flag rules") → `AvpTable`; rows whose code
  cell is a NOTE reference get `code=None`, and note texts naming a defining
  RFC additionally produce `ReusedAvps` rows (the `note-defined-in-rfc`
  quirk).
- The "re-used Diameter AVPs" table → `ReusedAvps` rows with M-bit overrides.
- Columns marking where a row applies ("Acc. Type", "Applicability", "Used
  in", ...), in either table, → the row's marks, each behind its declared
  quirk.
- Behind `registry-tables`, TS 29.230's allocation tables → `Registry`, and
  behind `reserved-range-notes` their full-width notes → reserved ranges.

The vendor-id for locally defined AVPs is not printed by enumerated-AVP
sections, so it is taken from the spec's grouped-AVP headers (3GPP: 10415).

The stages, each a module of the package: `_docx` reads the body into the
section model of `_base`; `_collect` classifies its clauses, reading rules
(`_rules`), commands (`_commands`), enumerated values (`_enums`), AVP and
re-used tables (`_avp_tables`, over `_tables`), origins (`_origins`) and
registries (`_registries`), then resolves and orders the blocks; `_values`
reads the value tables; `_extract` runs it all and attaches pages; `_quirks`
holds the quirk vocabulary. Only `__all__` here is public.
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
