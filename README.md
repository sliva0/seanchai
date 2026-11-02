# Seanchaí

Seanchaí extracts Diameter command ABNFs and AVP definitions from 3GPP
specifications, RFCs and a few other documents into one plain-text format,
`.dad`, and gives you a parser and a resolved model over the result. From
there, generating your implementation's dictionary format, or checking an
existing dictionary against the specifications, is a short script.

5G protocols ship OpenAPI. Diameter ships ABNF blocks and tables inside Word
documents and RFC text, and every implementation transcribes them by hand.
Seanchaí does that transcription once, with every edit declared and reviewed.

## How it works

1. **Extract.** Source documents become raw `.dad` files. 3GPP specifications
   are read from their `.docx` (legacy `.doc` files are converted with
   LibreOffice), with page numbers from the matching ETSI PDF; RFCs are read
   from their plain text. See [docs/extractor.md](docs/extractor.md).
2. **Correct.** Three things are committed per document: the raw output, the
   corrections declared against it, and the corrected file they produce.
   Every corrected line carries a `;;` note naming its correction. See
   [docs/corrections.md](docs/corrections.md).
3. **Consume.** The parser turns `.dad` back into an AST, and `seanchai.model`
   resolves the corpus into messages whose members point at real AVP
   objects. See [docs/consumers.md](docs/consumers.md).

The rule everything rests on: **a `.dad` file records everything its source
document says about a definition**, including where the document is
redundant, self-contradictory or wrong. The extractor translates and never
curates. The only edits are the two declared layers, input patches for
source typos and corrections for wrong data, and both are reviewable. The
[linter](docs/linter.md) reports the contradictions, and the
[Wireshark oracle](docs/oracle.md) cross-checks values against an
independent reading of the same documents.

## Commands

```sh
seanchai download                       # fetch the catalog into specifications/
seanchai download --no-convert          # without LibreOffice; legacy .doc unread
seanchai download --spec SPECREF --version X.Y.Z   # one older version, for diffs
seanchai regenerate [--add SPECREF]     # rebuild the corpus from the downloads
seanchai regenerate --expand-ranges     # also widen stale declaration ranges
seanchai extract DOCX --pdf PDF --link URL [--corrections DIR] -o OUT.dad
seanchai extract-rfc RFC.txt --link URL [--corrections DIR] -o OUT.dad
seanchai correct RAW.dad --corrections DIR -o OUT.dad
seanchai format [--check] FILE.dad...   # canonical form, ;; comments kept
seanchai lint [--corpus DIR | --no-corpus] [--show-accepted] FILE.dad...
seanchai crosscheck [FILE.dad | DIR]... # against Wireshark's dictionary
```

## Repository layout

- `src/seanchai/`: `dad/` (AST, parser, formatter, corrections),
  `extractor/`, `downloader/`, `regenerate.py`, `ranges.py`, `linter.py`,
  `oracle.py`, `corpus.py`, `model.py`, `cli.py`.
- `packages/seanchai-corpus/`: the corpus package. Its
  `src/seanchai_corpus/dad/` holds the committed corpus, one directory per 3GPP
  release plus `rfc/`, `etsi/`, `3gpp2/` and `onem2m/`, a raw mirror under
  `raw/`, and the record of known holes
  ([docs/dad-format.md](docs/dad-format.md#the-corpus)).
- `edits/sources/<SpecRef>.toml`: input patches and quirks per document.
- `edits/corrections/<SpecRef>.py`: corrections per document.
- `edits/transcriptions/<SpecRef>.dad`: documents no extractor reads, copied
  by hand (ETSI ES 283 034, TS 183 017, 3GPP2 X.S0057).
- `integrations/`: consumer scripts over the model, and staged Wireshark
  dictionary patches.
- `editors/`: `.dad` syntax highlighting for VS Code, Vim and Neovim.
- `specifications/`: downloaded sources, git-ignored.
- `docs/`: [dad-format](docs/dad-format.md), [grammar](docs/grammar.md),
  [extractor](docs/extractor.md), [corrections](docs/corrections.md),
  [downloader](docs/downloader.md), [linter](docs/linter.md),
  [oracle](docs/oracle.md), [consumers](docs/consumers.md),
  [development](docs/development.md).

## Development

```sh
uv sync
uv run pytest -m "not sources"   # without the downloaded documents
uv run pytest                    # everything; needs `seanchai download`
uv run ruff check . && uv run ruff format .
uv run rumdl check .
uv run ty check && uv run basedpyright
```

See [docs/development.md](docs/development.md).
