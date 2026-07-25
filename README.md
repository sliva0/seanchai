# Seanchaí

Seanchaí turns Diameter message ABNFs and AVP definitions from 3GPP
specifications and RFCs into a single canonical, human- and machine-readable
format (`.dad`), and provides a parser for that format so the definitions can be
converted into, or validated against, any Diameter implementation's own
dictionary format.

## Motivation

Diameter implementations each maintain their own hand-transcribed dictionary of
command ABNFs, grouped AVP rules, and AVP tables, copied out of spec PDFs.
Hand transcription is slow and error-prone, and useful for exactly one
implementation at a time. Seanchaí replaces that with one reviewed source of
truth: transcribe (mostly automatically) once, review once, then generate or
verify every implementation's dictionary from it.

## Architecture

The pipeline has three stages:

1. **Extraction** — source documents to raw `.dad` files. 3GPP specs are parsed
   from their **.docx** sources (3GPP publishes Word as the authoritative
   format; bold runs, tables and section structure are explicit there), going
   docx → intermediate document model → `.dad` AST. A separate pass reads the
   bookmark outline of the matching ETSI **PDF** to attach page numbers.
2. **Review** — raw extractor output is committed per spec version; corrections
   are kept alongside it, and the corrected `.dad` files are the source of
   truth. A version upgrade is re-extract, diff raw-vs-raw, re-apply the
   corrections — not a re-review from scratch.
3. **Consumption** — the parser turns `.dad` files back into the AST, and
   downstream scripts emit an implementation's native dictionary format or
   validate an existing hand-written one against the spec.

## Status

### Working today

- **The `.dad` format**: pydantic AST, strict line-oriented parser, canonical
  formatter. Round-trip is exact and idempotent. All five section kinds are
  implemented (Message, Grouped AVP, Enumerated AVP, AVP Table, Reused AVPs).
  See [docs/dad-format.md](docs/dad-format.md).
- **3GPP docx extractor**, plus the ETSI-PDF page-attachment pass and
  per-spec input patches for source typos. See
  [docs/extractor.md](docs/extractor.md).
- **CLI**: `uv run seanchai extract DOCX [--pdf PDF] [--link URL] [-o OUT]`.
- **Downloader**: `downloader/download_diameter_specs.py` with the curated
  catalog in `downloader/specs.toml`.
- **Extracted specs**: TS 29.329 (hand-verified reference), TS 29.229 and
  TS 29.272 (raw, round-tripped and spot-checked).

### Planned

- A formal `.dad` grammar document, and a cross-section linter (unresolved AVP
  references, duplicate definitions, table-vs-definition consistency).
- The second patch layer: corrections for data that parses fine but is
  semantically wrong, designed in
  [docs/proposal-corrections.md](docs/proposal-corrections.md).
- Cross-checking extracted codes/vendors/types against Wireshark's Diameter
  `dictionary.xml` as an independent oracle.
- Extraction of the remaining 3GPP Diameter specs, and an RFC (plain-text)
  extractor for the base protocol and IETF applications.
- Downstream consumers: validators for existing hand-written dictionaries
  first, generators for native dictionary formats after.

Open work is tracked in [docs/roadmap.md](docs/roadmap.md); the current
code-quality work is planned in
[docs/plan-code-quality.md](docs/plan-code-quality.md).

## Repository layout

- `src/seanchai/` — the `dad` package (AST, parser, canonical formatter), the
  `extractor` package, and the `seanchai` CLI.
- `downloader/` — `download_diameter_specs.py` plus `specs.toml`, the curated
  catalog of 3GPP specs and RFCs to fetch.
- `patches/` — per-spec input patches (`<SpecRef>.toml`) for source typos that
  would break extraction.
- `output/` — downloaded source documents (git-ignored; recreate with the
  downloader).
- `examples/` — committed `.dad` files: the hand-made reference and raw
  extractor outputs.
- `tests/` — pytest suite.
- `docs/` — format, extractor, workflow, development and roadmap documents.

## Development

```sh
uv sync                # install, including the dev group
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run ty check        # type check (fast, alpha)
uv run basedpyright    # type check (thorough, standard mode)
```

See [docs/development.md](docs/development.md) for how strictly to take each of
these.
