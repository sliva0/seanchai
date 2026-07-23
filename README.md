# Seanchaí

Seanchaí extracts Diameter message ABNFs and AVP definitions from 3GPP
specifications and RFCs into a single canonical, human- and machine-readable format
(`.dad`), and provides a parser for that format so the definitions can be converted
into, or validated against, any Diameter implementation's own dictionary format.

## Motivation

Diameter implementations each maintain their own hand-transcribed dictionary of
command ABNFs, grouped AVP rules, and AVP tables, copied out of spec PDFs.
Hand transcription is slow and error-prone, and useful for exactly one
implementation at a time. Seanchaí replaces that with one reviewed source of truth:
transcribe (mostly automatically) once, review once, then generate or verify every
implementation's dictionary from it.

## Architecture

The pipeline has three stages:

1. **Extraction.** The extractor parses source documents into raw `.dad` files.
   For 3GPP specs, content is parsed from the **.docx** sources (3GPP publishes
   Word as the authoritative format; bold runs, tables and section structure are
   explicit there), going docx → intermediate document model (sections, tables,
   styled runs) → `.dad` AST. A small separate pass reads only the bookmark
   outline of the matching ETSI **PDF** (`pypdf`'s `reader.outline`) to attach PDF
   page numbers to sections. RFCs are extracted from their plain-text form.
2. **Review.** Raw extractor output is committed per spec version. Reviewed
   corrections are kept as diffs against it, and the corrected `.dad` files are the
   source of truth. Upgrading to a new spec release means re-extract, diff
   raw-vs-raw, re-apply the correction patch — not re-reviewing from scratch.
   Extracted data is also cross-checked against independent sources such as
   Wireshark's Diameter dictionary.
3. **Consumption.** A Python parser turns `.dad` files into an AST (shared with the
   extractor). Downstream users write short scripts on top of it: generators that
   emit an implementation's native dictionary format, or validators that check an
   existing hand-written dictionary against the spec.

## The `.dad` format

A plain-text format that stays as close as possible to the ABNF found in the source
documents, so a definition can be reviewed as a near-diff against the spec. See
`examples/ts_129329v180000p.dad` for a hand-made example based on 3GPP TS 29.329.

Key properties:

- Message and grouped-AVP rules keep the spec's ABNF syntax
  (`<>`/`{}`/`[]`/`*` qualifiers, `::=`, `< Diameter Header: … >`).
- Extended with definition kinds the raw ABNF lacks: enumerated AVPs with their
  named values, and AVP tables mirroring each spec's own AVP table — one AVP per
  whitespace-aligned row with code, section, base data type and flag (M/V)
  information.
- A file is a sequence of sections, each starting with a `; Type: X` header block
  and separated by two blank lines.
- **Directive comments**: lines/suffixes starting with `;` in defined positions are
  semantic, JSDoc-style — `; Key: value` header blocks above each definition
  (type, name, section, page) and at the top of the file (spec, version, link), plus
  inline markers such as `; bold` (bold in 3GPP ABNF marks AVPs defined/modified in
  that spec). These are grammar productions, not free text: a malformed directive is
  a parse error, never silently degraded to a comment. Free-text comments use `;;`.
- **Reused AVPs**: AVPs defined in another spec/RFC are listed by name in a
  dedicated section, mirroring the "re-used AVPs" tables of 3GPP specs (names are
  unique within one specification's scope); resolving such a reference yields the
  AVP's `(vendor-id, code)` — the true identity key — which disambiguates AVPs
  sharing a name across specs.
- A canonical formatter accompanies the parser: parse → pretty-print is idempotent,
  so hand edits get normalized and the patch-based review workflow keeps stable
  diffs across extractor re-runs.

## Repository layout

- `src/seanchai/` — the `dad` package (AST, parser, canonical formatter), the
  `extractor` package, and the `seanchai` CLI.
- `downloader/` — `download_diameter_specs.py` plus `specs.toml`, the curated
  catalog of 3GPP specs and RFCs to fetch.
- `output/` — downloaded source documents (git-ignored; recreate with the
  downloader).
- `examples/` — committed `.dad` files: the hand-made reference and raw
  extractor outputs.
- `tests/` — pytest suite (`uv run pytest`).
