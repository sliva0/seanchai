# Seanchaí

Seanchaí turns Diameter message ABNFs and AVP definitions from 3GPP
specifications and RFCs into one canonical, human- and machine-readable
format (`.dad`), and provides a parser and a resolved model over it so the
definitions can be converted into, or validated against, any Diameter
implementation's own dictionary format.

5G protocols ship OpenAPI; Diameter ships ABNF blocks and tables inside Word
documents and RFC text, which every implementation hand-transcribes into a
dictionary format of its own. Seanchaí does that transcription once, reviewed,
so that emitting *your* format, or checking an existing one against the
specifications, is a short script over a corpus rather than a project.

## Pipeline

1. **Extract** — source documents to raw `.dad`. 3GPP specs are read from their
   `.docx` (with page numbers attached from the matching ETSI PDF), RFCs from
   their plain text. See [docs/extractor.md](docs/extractor.md).
2. **Review** — three things are committed per specification: the raw
   extractor output, the corrections declared against it, and the corrected
   file the two produce. Every corrected line carries a `;;` note citing its
   declaration. See [docs/corrections.md](docs/corrections.md) and
   [docs/workflow.md](docs/workflow.md).
3. **Consume** — the parser turns `.dad` back into an AST, and `seanchai.model`
   resolves the corpus into messages whose members point at real AVP objects.
   See [docs/consumers.md](docs/consumers.md).

The one rule the pipeline rests on: **a `.dad` file records everything its
source document says about a definition**, including where the document is
redundant, self-contradictory or wrong. The extractor translates, it never
curates; the two declared edit layers (input patches for source typos,
corrections for wrong data) are the only edits, and both are reviewable. The
[linter](docs/linter.md) reports the contradictions, and the
[Wireshark oracle](docs/oracle.md) cross-checks values against an independent
reading of the same documents.

## Commands

```sh
seanchai download                       # fetch the catalog into specifications/
seanchai regenerate [--add SPECREF]     # rebuild dad/ from it
seanchai extract DOCX --pdf PDF --link URL [--corrections DIR] -o OUT.dad
seanchai extract-rfc RFC.txt --link URL [--corrections DIR] -o OUT.dad
seanchai correct RAW.dad --corrections DIR -o OUT.dad
seanchai lint [--corpus dad] FILE.dad...
seanchai crosscheck FILE.dad...         # against Wireshark's dictionary
```

## Repository layout

- `src/seanchai/` — `dad/` (AST, parser, formatter, corrections), `extractor/`,
  `downloader/`, `regenerate.py`, `linter.py`, `oracle.py`, `corpus.py`,
  `model.py`, `cli.py`.
- `dad/` — the committed corpus: `dad/3gpp/rel-18/`, `dad/rfc/`, and the raw
  mirror under `dad/raw/`. See [dad/README.md](dad/README.md).
- `edits/sources/<SpecRef>.toml` — input patches and quirks per source document.
- `edits/corrections/<SpecRef>.py` — corrections per specification.
- `integrations/` — consumer scripts over the model, runnable with `uv run`.
- `editors/` — `.dad` syntax highlighting for VS Code, Vim and Neovim.
- `specifications/` — downloaded sources (git-ignored).
- `docs/` — format ([dad-format](docs/dad-format.md), [grammar](docs/grammar.md)),
  pipeline ([extractor](docs/extractor.md), [corrections](docs/corrections.md),
  [downloader](docs/downloader.md)), checks ([linter](docs/linter.md),
  [oracle](docs/oracle.md)), [consumers](docs/consumers.md),
  [workflow](docs/workflow.md), [development](docs/development.md) and the
  [roadmap](docs/roadmap.md).

## Development

```sh
uv sync
uv run pytest -m "not sources"   # without the downloaded documents
uv run pytest                    # everything, needs `seanchai download`
uv run ruff check . && uv run ruff format .
uv run ty check && uv run basedpyright
```

See [docs/development.md](docs/development.md).
