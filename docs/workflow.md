# Review and upgrade workflow

## Adding or refreshing a specification

1. **Download**: `uv run seanchai download` fetches the catalog into the
   git-ignored `specifications/`. PDFs are on by default; `--no-pdfs` is for
   catalog experiments only (see [downloader.md](downloader.md)).
2. **Extract**: `uv run seanchai extract DOCX --pdf PDF --link URL -o OUT.dad`,
   or `uv run seanchai extract-rfc RFC.txt --link URL -o OUT.dad` (RFC text is
   the RFC's only rendering, so no PDF). Read the warnings on stderr: they are
   the extractor telling you the document did something unusual.
3. **Lint** the raw output: `uv run seanchai lint RAW.dad`. Once the file is in
   the corpus, `--corpus dad` adds the cross-file rules.
4. **Correct**: declare each fix in `edits/corrections/<SpecRef>.py`, then
   re-extract with `--corrections edits/corrections` writing to the corpus path.
5. **Commit both files**: the corrected one under its release
   (`dad/3gpp/rel-18/29272-i60.dad`) and the raw one under the mirror
   (`dad/raw/3gpp/rel-18/29272-i60.raw.dad`). The corrected one lints clean;
   the raw one need not.

## Version upgrades

Re-extract the new version and diff raw-vs-raw: that shows what changed in the
*specification* with the correction layer held still. Then re-apply the
corrections — one whose `expect` no longer matches fails, so a fix adopted
upstream stops the run instead of passing silently — and diff the corrected
files too.

This depends on three things that must not regress: canonical formatting is
stable (an unrelated edit must not reflow other lines), the downloader reads
the 3GPP *archive* which keeps old versions, and corrections keep failing
loudly.

## Which layer fixes what

| Layer | Fixes | Where |
|---|---|---|
| input patches | typos in the source text that break extraction | `edits/sources/<SpecRef>.toml`, `[[patch]]` |
| quirks | readings too heuristic to run undeclared | same file, `[[quirk]]` |
| extractor code | exact-match structure that fails loudly on its own | `src/seanchai/extractor/` |
| corrections | data that parses fine but is semantically wrong | `edits/corrections/<SpecRef>.py` |

See [extractor.md](extractor.md) for the first three and
[corrections.md](corrections.md) for the last.
