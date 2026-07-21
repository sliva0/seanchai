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
`files/ts_129329v180000p.dad` for a hand-made example based on 3GPP TS 29.329.

Key properties:

- Message and grouped-AVP rules keep the spec's ABNF syntax
  (`<>`/`{}`/`[]`/`*` qualifiers, `::=`, `< Diameter Header: … >`).
- Extended with definition kinds the raw ABNF lacks: enumerated AVPs with their
  named values, and plain (non-grouped) AVPs with code, vendor, base data type and
  flag (M/V) information.
- **Directive comments**: lines/suffixes starting with `;` in defined positions are
  semantic, JSDoc-style — `; Key: value` header blocks above each definition
  (type, name, section, page) and at the top of the file (spec, version, link), plus
  inline markers such as `; bold` (bold in 3GPP ABNF marks AVPs defined/modified in
  that spec). These are grammar productions, not free text: a malformed directive is
  a parse error, never silently degraded to a comment. Free-text comments use `;;`.
- **Cross-references**: AVPs imported from other specs carry a parseable origin
  reference (spec/RFC identifier), which also disambiguates AVPs sharing a name but
  differing in `(vendor-id, code)` — the true identity key.
- A canonical formatter accompanies the parser: parse → pretty-print is idempotent,
  so hand edits get normalized and the patch-based review workflow keeps stable
  diffs across extractor re-runs.

## Repository layout

- `src/` — extractor and (eventually) parser/formatter packages.
- `specifications/` — source documents, fetched by `download_diameter_specs.py`
  (3GPP releases and RFCs that need conversion).
- `files/` — examples and scratch material, including the hand-made `.dad` example.
