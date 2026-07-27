# Review and upgrade workflow

## The loop

1. **Download** the source documents: `uv run seanchai download` fetches the
   curated catalog into the git-ignored `specifications/`. Hand-fetched
   docx/PDF pairs live in `specifications/manual/`.
2. **Extract**: `uv run seanchai extract DOCX --pdf PDF --link URL -o OUT.dad`.
   Warnings go to stderr; read them, they are the extractor telling you the
   source document did something unusual.
3. **Eyeball** the diff against the spec. The acceptance loop is
   extract → format → parse → eyeball; the `.dad` format is designed to read as
   a near-diff of the source ABNF so this stays cheap.
4. **Lint** the raw output: `uv run seanchai lint RAW.dad`. What it reports is
   the list of things to correct. See [linter](linter.md).
5. **Correct** it: declare each fix in `edits/corrections/<SpecRef>.py`, then
   re-extract with both layers at once:
   `uv run seanchai extract DOCX --pdf PDF --link URL --corrections edits/corrections -o dad/3gpp/rel-18/NAME.dad`.
   Every corrected line gets a `;;` note citing the declaration's `file:line`.
   See [corrections](corrections.md).
6. **Commit both files** into the corpus, under the release they belong to:
   `dad/3gpp/rel-18/29272-i60.raw.dad` and `29272-i60.dad`. The corrected one
   should lint clean; the raw one may not, and that is what it is for.
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

- **Input patches** (`edits/patches/<SpecRef>.toml`) — typos in the source document
  that break extraction. See [extractor.md](extractor.md).
- **Extractor code** — recurring conventions that carry information.
- **Corrections** (`edits/corrections/<SpecRef>.py`) — data that extracts and parses
  fine but is semantically wrong. See
  [corrections](corrections.md).

## Validation

- Build patched `.dad` sets around the latest release with published PDFs
  (Rel-19 at the time of writing). The tooling itself stays version-agnostic.
- Cross-check extracted codes, vendor-ids and types against Wireshark's
  Diameter `dictionary.xml` as an independent oracle. Wireshark's disambiguated
  names for AVPs that clash across specs may be worth borrowing too. *(Planned.)*
- The first downstream consumers should be **validators** for existing
  hand-written dictionaries — they deliver value before any generator is
  adopted. Generators for implementations' native dictionary formats come
  after. *(Planned.)*
