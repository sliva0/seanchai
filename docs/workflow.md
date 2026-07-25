# Review and upgrade workflow

## The loop

1. **Download** the source documents: `downloader/download_diameter_specs.py`
   fetches the curated catalog in `downloader/specs.toml` into the git-ignored
   `output/`. Hand-fetched docx/PDF pairs live in `output/manual/`.
2. **Extract**: `uv run seanchai extract DOCX --pdf PDF --link URL -o OUT.dad`.
   Warnings go to stderr; read them, they are the extractor telling you the
   source document did something unusual.
3. **Eyeball** the diff against the spec. The acceptance loop is
   extract → format → parse → eyeball; the `.dad` format is designed to read as
   a near-diff of the source ABNF so this stays cheap.
4. **Commit the raw output** per spec version (`examples/29272-i60.raw.dad`).
5. **Correct** it. Reviewed corrections are kept as diffs against the raw
   output; the corrected `.dad` file is the source of truth.

## Version upgrades

Re-extract the new version, diff raw-vs-raw, re-apply the correction patch.
That is the whole point of committing raw output: an upgrade reviews only what
actually changed in the specification, instead of re-reviewing the file from
scratch.

Two things this depends on, and which therefore must not regress:

- **Canonical formatting must be stable.** An unrelated edit must not reflow
  unrelated lines, or the raw-vs-raw diff drowns in noise.
- **The 3GPP archive, not the "latest" index.** `Specs/archive/<series>_series/`
  keeps every old version; `Specs/latest/Rel-N/` does not, and the raw-vs-raw
  diff needs the old one.

## Which layer fixes what

- **Input patches** (`patches/<SpecRef>.toml`) — genuine typos in the source
  document. See [extractor.md](extractor.md).
- **Extractor code** — recurring conventions that carry information.
- **Output `.dad` patches** — semantic corrections to extracted data.

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
