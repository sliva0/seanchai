# Review and upgrade workflow

## The loop

1. **Download** the source documents: `uv run seanchai download` fetches the
   curated catalog into the git-ignored `output/`. Hand-fetched docx/PDF pairs
   live in `output/manual/`.
2. **Extract**: `uv run seanchai extract DOCX --pdf PDF --link URL -o OUT.dad`.
   Warnings go to stderr; read them, they are the extractor telling you the
   source document did something unusual.
3. **Eyeball** the diff against the spec. The acceptance loop is
   extract → format → parse → eyeball; the `.dad` format is designed to read as
   a near-diff of the source ABNF so this stays cheap.
4. **Commit the raw output** per spec version (`examples/29272-i60.raw.dad`).
5. **Correct** it: declare each fix in `corrections/<SpecRef>.py` and run
   `uv run seanchai correct RAW.dad --corrections corrections -o OUT.dad`.
   The source of truth is the committed pair — raw file plus correction module.
   The corrected file is generated output: never hand-edited, or the
   corrections can no longer be re-applied to the next version. Where corrected
   files should live is part of the still-undecided corpus layout, so none are
   committed yet. See [corrections](corrections.md).

## Version upgrades

Re-extract the new version, diff raw-vs-raw, re-apply the corrections. That is
the whole point of committing raw output: an upgrade reviews only what actually
changed in the specification, instead of re-reviewing the file from scratch.

Two things this depends on, and which therefore must not regress:

- **Canonical formatting must be stable.** An unrelated edit must not reflow
  unrelated lines, or the raw-vs-raw diff drowns in noise.
- **The 3GPP archive, not the "latest" index.** `Specs/archive/<series>_series/`
  keeps every old version; `Specs/latest/Rel-N/` does not, and the raw-vs-raw
  diff needs the old one.

## Which layer fixes what

- **Input patches** (`patches/<SpecRef>.toml`) — typos in the source document
  that break extraction. See [extractor.md](extractor.md).
- **Extractor code** — recurring conventions that carry information.
- **Corrections** (`corrections/<SpecRef>.py`) — data that extracts and parses
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
