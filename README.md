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
2. **Review** — the durable pair is what gets committed: raw extractor output
   per spec version, plus the corrections declared against it. The corrected
   `.dad` file is generated from those two and is what downstream consumes. A
   version upgrade is re-extract, diff raw-vs-raw, re-apply the corrections —
   not a re-review from scratch.
3. **Consumption** — the parser turns `.dad` files back into the AST, and
   downstream scripts emit an implementation's native dictionary format or
   validate an existing hand-written one against the spec.

### The rule that holds the pipeline together

**A `.dad` file records everything its source document says.** Specifications
are redundant, occasionally self-contradictory and sometimes plainly wrong; a
`.dad` file records that faithfully rather than tidying it up. The extractor
translates, it does not curate — it never drops a block for being redundant,
contradicted by another block, or not useful to any consumer anyone has written
yet.

The only edits are the two declared patch layers, and both exist to keep that
property rather than to weaken it. Input patches fix honest typos in the source
*text*, so that a document with a flags cell reading `M. V` can be read at all.
Corrections fix data that parses fine but is wrong, and they produce a
*separate* file — the committed raw one still says what the document said.
Every edit is declared, reasoned and reviewable, and none of them are the
extractor quietly deciding what a specification meant to say.

Interpreting the result — resolving references, choosing between a local
definition and a re-used row, filtering to what one implementation needs — is
the consumer's job. A consumer can ignore anything the file carries; it can
never recover what the extractor threw away.

## Status

### Working today

- **The `.dad` format**: pydantic AST, strict line-oriented parser, canonical
  formatter. Round-trip is exact and idempotent. All five section kinds are
  implemented (Message, Grouped AVP, Enumerated AVP, AVP Table, Reused AVPs).
  See [docs/dad-format.md](docs/dad-format.md).
- **3GPP docx extractor**, plus the ETSI-PDF page-attachment pass and
  per-spec input patches for source typos. See
  [docs/extractor.md](docs/extractor.md).
- **Corrections**: the second patch layer, for data that parses fine but is
  semantically wrong. See
  [docs/corrections.md](docs/corrections.md).
- **CLI**: `seanchai extract` (docx → `.dad`), `seanchai correct` (raw `.dad` →
  corrected), `seanchai download` (fetch the corpus).
- **Downloader**: `uv run seanchai download`, with the curated catalog in
  `src/seanchai/downloader/specs.toml`.
- **Extracted specs**: TS 29.329 (hand-verified reference), TS 29.229 and
  TS 29.272 (raw, round-tripped and spot-checked).

### Planned

- A formal `.dad` grammar document, and a linter (duplicate definitions and
  duplicate `(vendor-id, code)` identities, local-vs-re-used conflicts,
  table-vs-definition consistency, and — once a base-protocol `.dad` exists —
  unresolved AVP references). The linter is where a source inconsistency gets
  reported, since the extractor's job is to record it rather than resolve it.
- Cross-checking extracted codes/vendors/types against Wireshark's Diameter
  `dictionary.xml` as an independent oracle.
- Extraction of the remaining 3GPP Diameter specs, and an RFC (plain-text)
  extractor for the base protocol and IETF applications.
- Downstream consumers: validators for existing hand-written dictionaries
  first, generators for native dictionary formats after.

Open work is tracked in [docs/roadmap.md](docs/roadmap.md). Completed review
rounds and the reasoning behind them are kept in
[docs/history/](docs/history/).

## Repository layout

- `src/seanchai/` — the `dad` package (AST, parser, formatter, corrections),
  the `extractor` and `downloader` packages, and the `seanchai` CLI.
- `patches/` — per-spec input patches (`<SpecRef>.toml`) for source typos that
  would break extraction.
- `corrections/` — per-spec correction modules (`<SpecRef>.py`) for extracted
  data that is semantically wrong.
- `output/` — downloaded source documents (git-ignored; recreate with the
  downloader).
- `examples/` — committed `.dad` files: the hand-made reference and raw
  extractor outputs.
- `tests/` — pytest suite.
- `docs/` — format, extractor, workflow, development and roadmap documents,
  plus `docs/history/` for completed review rounds.

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
