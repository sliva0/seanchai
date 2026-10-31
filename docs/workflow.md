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
pair is removed), `new` (added with `--add`), `not-converted` (a legacy
`.doc` downloaded with `--no-convert`; skipped, its committed pair left
alone, and not a failure), or `failed` with the reason.
Warnings for declaration ranges that do not cover the parsed version print
under each specification without gating application. The extractor's warnings
print there too; they report unusual document structure and are worth a
glance on every rebuild.
A transcription, a document no extractor reads that a person copied into
`edits/transcriptions/` ([extractor.md](extractor.md#transcriptions)), has
no manifest record: it is read through its input patches in place of an
extraction and rebuilt like the rest, range warnings and `--expand-ranges`
included.
`tests/test_real_sources.py` runs the same rebuild into a scratch directory
and fails on anything but `unchanged`, `not-converted` included: it needs a
download that converted the legacy `.doc` archives.

## Adding a specification

1. `uv run seanchai regenerate --add TS29.305`. The document must be in the
   downloader's catalog (`src/seanchai/downloader/specs.toml`) and readable
   by the extractor; a shape it rejects fails with the reason. A legacy
   `.doc` archive is read through the `.docx` the downloader converted it to
   (see [downloader.md](downloader.md)); TS 32.299 and eight more are read
   this way.
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

The old raw file is in git. When the extractor has changed since it was
committed, re-extract the old version with today's code instead, so the diff
shows the specification's changes and not the extractor's:

```sh
uv run seanchai download --spec TS29.272 --version 18.6.0
uv run seanchai regenerate --spec TS29.272 -o /tmp/old \
    --manifest specifications/versions/TS29.272/18.6.0/manifest.json
diff -u /tmp/old/raw/3gpp/rel-18/29272-i60.raw.dad dad/raw/3gpp/rel-18/29272-i70.raw.dad
```

`--spec` limits the rebuild to that specification, so the rest of the corpus
is not reported missing from the one-record manifest, and `-o` keeps the
older pair out of `dad/`; it reports as `replaced` there. A document the
corpus holds in two releases (TS 32.299 in `rel-18` and, pinned, `rel-11`;
[downloader.md](downloader.md)) is two copies, each rebuilt in its own
tree: `--spec` rebuilds the ones the manifest lists, and `--add` adds every
listed copy not yet committed.

A rebuild that succeeds on the new version still warns about every
declaration whose range does not cover it. Once the diffs are reviewed,

```sh
uv run seanchai regenerate --expand-ranges
```

widens those ranges in place — `first_version`/`last_version` in
`edits/sources/<SpecRef>.toml`, the `versions=` string literal in
`edits/corrections/<SpecRef>.py` — and prints each as `expanded:` under its
specification. Only a specification that rebuilt cleanly is touched, since
that is what shows every patch and quirk fired as declared and every
`expect` held. An `Accept` is checked separately: the rebuilt file is
linted against the corpus, and an acceptance matching no finding is
printed as `not widened, stale` rather than widened. Only the bound the version is past moves, by replacing that
value's text: comments, block order and layout stay byte for byte, and a
corrections module keeps its source encoding and is loaded from a scratch
copy, required to declare the same edits, before it is replaced. A literal
is rewritten only inside the top-level `CORRECTIONS =` and `+=` statements
the loader applies, and outside lambdas, conditionals and filtered
comprehensions; a literal elsewhere, one split by comments, or a range
built by an expression is printed as `not widened` for a person. On the TS
29.272 18.6.0 → 18.7.0 upgrade it produces the hand-widened files byte for
byte.

This depends on three things that must not regress: canonical formatting is
stable (an unrelated edit must not reflow other lines), the downloader reads
the 3GPP *archive* which keeps old versions, and corrections keep failing
loudly.

## Which layer fixes what

| Layer | Fixes | Where |
|---|---|---|
| transcriptions | documents no extractor reads, copied by hand as printed | `edits/transcriptions/<SpecRef>.dad` |
| input patches | typos in the source text that break extraction, and case-only misspellings of a name | `edits/sources/<SpecRef>.toml`, `[[patch]]` |
| quirks | readings too heuristic to run undeclared | same file, `[[quirk]]` |
| extractor code | exact-match structure that fails loudly on its own | `src/seanchai/extractor/` |
| corrections | data that parses fine but is semantically wrong | `edits/corrections/<SpecRef>.py` |
| acceptances | linter notes a clause makes deliberate; no data changes | same file, `Accept` |

See [extractor.md](extractor.md) for the first three and
[corrections.md](corrections.md) for the last.
