# Review and upgrade workflow

## The loop

1. **Download** the source documents: `uv run seanchai download` fetches
   the curated catalog into the git-ignored `specifications/`. PDFs are on
   by default, and `--no-pdfs` is for catalog experiments only —
   [downloader.md](downloader.md) records what a PDF-less run breaks.
   Hand-fetched docx/PDF pairs live in `specifications/manual/`.
2. **Extract**: `uv run seanchai extract DOCX --pdf PDF --link URL -o OUT.dad`.
   Warnings go to stderr; read them, they are the extractor telling you the
   source document did something unusual. RFCs are one step shorter — the text
   is the RFC's only rendering, so there is no PDF:
   `uv run seanchai extract-rfc specifications/rfc/rfc6733.txt --link URL -o OUT.dad`.
3. **Eyeball** the diff against the spec. The acceptance loop is
   extract → format → parse → eyeball; the `.dad` format is designed to read as
   a near-diff of the source ABNF so this stays cheap.
4. **Lint** the raw output: `uv run seanchai lint RAW.dad`. What it reports is
   the list of things to correct. Once the corrected file is in the corpus,
   lint it again with `--corpus dad` — the cross-file rules check what the
   document says about *other* documents, which is a class of defect no amount
   of reading this one can find. See [linter](linter.md).
5. **Correct** it: declare each fix in `edits/corrections/<SpecRef>.py`, then
   re-extract with both layers at once:
   `uv run seanchai extract DOCX --pdf PDF --link URL --corrections edits/corrections -o dad/3gpp/rel-18/NAME.dad`.
   Every corrected line gets a `;;` note citing the declaration's `file:line`.
   See [corrections](corrections.md).
6. **Commit both files** into the corpus: the corrected one under the release
   it belongs to (`dad/3gpp/rel-18/29272-i60.dad`) and the raw one in the
   mirrored raw tree (`dad/raw/3gpp/rel-18/29272-i60.raw.dad`). The corrected
   one should lint clean; the raw one may not, and that is what it is for.
   See [dad/README.md](../dad/README.md).

## Version upgrades

Re-extract the new version and diff raw-vs-raw. That is what committing the
raw file buys: the diff shows what actually changed in the *specification*,
with the correction layer held still, instead of re-reviewing the file from
scratch. Then re-apply the corrections — a correction whose `expect` no longer
matches *fails*, so a fix the specification adopted upstream stops the run
instead of passing silently — and diff the corrected files too.

Three things this depends on, and which therefore must not regress:

- **Canonical formatting must be stable.** An unrelated edit must not reflow
  unrelated lines, or the diff drowns in noise.
- **The 3GPP archive, not the "latest" index.** `Specs/archive/<series>_series/`
  keeps every old version; `Specs/latest/Rel-N/` does not, and comparing
  against the old one needs it.
- **Corrections must keep failing loudly.** They are what makes a corrected
  corpus safe to commit: nothing else notices when a correction goes stale.

## Which layer fixes what

- **Input patches** (`edits/sources/<SpecRef>.toml`, `[[patch]]`) — typos in
  the source document that break extraction. See [extractor.md](extractor.md).
- **Quirks** (same file, `[[quirk]]`) — extractor readings too heuristic to
  run undeclared, enabled by name per document. See
  [extractor.md](extractor.md#quirks).
- **Extractor code** — exact-match structure that fails loudly on its own
  when a document deviates.
- **Corrections** (`edits/corrections/<SpecRef>.py`) — data that extracts and parses
  fine but is semantically wrong. See
  [corrections](corrections.md).

## Validation

Build patched `.dad` sets around the latest release with published PDFs
(Rel-18 today); the tooling itself stays version-agnostic. `seanchai
crosscheck` compares extracted values against Wireshark's dictionary — see
[oracle.md](oracle.md), including why its findings are leads to investigate
rather than verdicts. The first downstream dictionary validator exists —
see [consumers.md](consumers.md), whose Cx run also caught a silent
extraction truncation the review loop had missed.
