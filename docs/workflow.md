# Review and upgrade workflow

The corpus under `dad/` is derived output. One command rebuilds all of it
from the downloaded sources and the two edit layers:

```sh
uv run seanchai download      # the catalog into specifications/, PDFs included
uv run seanchai regenerate    # every committed specification, raw mirror included
git diff --stat dad           # what changed, if anything
```

`regenerate` prints one line per specification: `unchanged`, `changed`,
`replaced` (the manifest holds a newer version than the corpus did; the old
pair is removed), `new` (added with `--add`), or `failed` with the reason.
Warnings for declaration ranges that do not cover the parsed version print
under each specification without gating application. The extractor's warnings
print there too; they report unusual document structure and are worth a
glance on every rebuild.
`tests/test_real_sources.py` runs the same rebuild into a scratch directory
and fails on anything but `unchanged`.

## Adding a specification

1. `uv run seanchai regenerate --add TS29.273`. The document must be in the
   downloader's catalog (`src/seanchai/downloader/specs.toml`) and readable
   by the extractor; a `.doc` archive or a shape it rejects fails with the
   reason.
2. Lint the raw file: `uv run seanchai lint dad/raw/... --corpus dad`. Every
   error is either a source typo (input patch), a reading the extractor should
   not make undeclared (quirk), or wrong data (correction); see the table
   below.
3. Declare the fixes, regenerate again, and commit the raw and corrected pair
   with the edit files.

## Version upgrades

`seanchai download` follows 3GPP's newest version with a published ETSI PDF,
so a newer version shows up as a `replaced` line on the next regenerate. Diff
raw-vs-raw first: that is what changed in the *specification* with the
correction layer held still. A correction whose `expect` no longer matches
fails the specification's rebuild, which is the signal that a fix was adopted
upstream and the declaration should go. Then diff the corrected files.

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
