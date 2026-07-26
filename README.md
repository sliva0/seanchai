# Seanchaí

Seanchaí turns Diameter message ABNFs and AVP definitions from 3GPP
specifications and RFCs into a single canonical, human- and machine-readable
format (`.dad`), and provides a parser for that format so the definitions can be
converted into, or validated against, any Diameter implementation's own
dictionary format.

## Motivation

5G's 3GPP protocols have OpenAPI and JSON Schema: a machine-readable
description of the wire format, published alongside the prose, that anyone can
generate code from. Diameter has nothing equivalent. Its definitions exist as
ABNF blocks and tables inside Word documents and RFC text, so every
implementation hand-transcribes them into a dictionary format of its own
invention — command ABNFs, grouped AVP rules and AVP tables, copied out of spec
PDFs. That work is slow, error-prone, and useful for exactly one implementation
at a time.

Seanchaí replaces it with one reviewed source of truth: transcribe (mostly
automatically) once, review once, then generate or verify every
implementation's dictionary from it. The intended end state is a Python library
you point at the `.dad` corpus and query — every message in a given
specification, every grouped AVP, every plain AVP — so that emitting
definitions *in your own format* is a short script rather than a transcription
project. That might be Python class definitions for a library like
[mensonen/diameter](https://github.com/mensonen/diameter), or a JSON schema
shaped like the 5G ones, or whatever a particular consumer already uses.
Seanchaí does not pick the output format; it makes the input to that choice
machine-readable and reviewed.

Generating a dictionary is only one of the two things that buys. If you have
already hand-written your format, you do not want it regenerated — you want to
know whether it is right. The same library and the same corpus let you write a
script that walks your existing dictionary and reports what disagrees with the
specifications: a wrong code, a stale type, a definition that changed two
releases ago. That costs nothing to adopt and does not ask you to move to
anyone else's format.

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
3. **Consumption** — the parser turns `.dad` files back into the AST, and a
   consumer model built from that AST lets downstream scripts emit an
   implementation's native dictionary format or validate an existing
   hand-written one against the spec. The parser is the half that exists
   today.

   The AST and the consumer model are deliberately different types. The AST
   mirrors a `.dad` file one-to-one, keeps references as unresolved strings,
   and must be able to represent a specification that contradicts itself —
   fidelity is its whole job. The consumer model is the resolved view: AVP
   references followed into real objects across files, identities and types
   attached, methods where they help. Making the AST convenient would make it
   less faithful, which is why the convenience lives one layer up.

Extraction is the stage that happens to be hardest, but it is not the only way
a `.dad` file can come to exist. The format is written, not just read: a vendor
with a proprietary Diameter extension, or anyone with a spec Seanchaí does not
cover, can hand-author a `.dad` file and have it slot into the same parser,
linter and consumers as an extracted one. That is a deliberate goal rather than
an accident of the design, though 3GPP and RFC sources come first in practice
— the near-term obligation is only to keep hand-authoring viable, not to build
anything specifically for it.

### The rule that holds the pipeline together

**A `.dad` file records everything its source document says about a
definition.** Specifications are redundant, occasionally self-contradictory and
sometimes plainly wrong; a `.dad` file records that faithfully rather than
tidying it up. The extractor translates, it does not curate — it never drops a
definition for being redundant, contradicted by another one, or not useful to
any consumer anyone has written yet.

The scope is definitions — names, codes, vendor-ids, types, flag rules, value
lists, ABNF bodies — not the specification's narrative. `.dad` has nowhere to
put a clause's paragraphs and nested bullet lists without mangling them, so it
does not try; `; Section:` points at the clause for anyone who wants to read
it. Inside that boundary, nothing is dropped for being inconvenient.

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
  AVP tables declare their own columns, so a table can carry the extra columns
  a given specification prints and an absent column stays distinct from an
  empty cell. See [docs/dad-format.md](docs/dad-format.md), and
  [docs/grammar.md](docs/grammar.md) for the formal grammar.
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

- A linter (duplicate definitions and duplicate `(vendor-id, code)` identities, local-vs-re-used conflicts,
  table-vs-definition consistency, and — once a base-protocol `.dad` exists —
  unresolved AVP references). The linter is where a source inconsistency gets
  reported, since the extractor's job is to record it rather than resolve it.
- Cross-checking extracted codes/vendors/types against Wireshark's Diameter
  `dictionary.xml` as an independent oracle.
- Extraction of the remaining 3GPP Diameter specs, and an RFC (plain-text)
  extractor for the base protocol and IETF applications.
- A consumer model over a parsed corpus, separate from the `.dad` AST, with
  cross-references resolved and a thin set of pre-built queries — every message
  in a spec, every grouped AVP, every plain AVP, look up an AVP by name or
  `(vendor-id, code)`. The AST stays public underneath for anything it does not
  cover.
- Downstream consumers in both directions: validating an existing hand-written
  dictionary against the corpus, and generating one in an implementation's
  native format. Validation comes first — it needs no opinion about output
  syntax.

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
