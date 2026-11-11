# Development

Setup, the checks to run before a push, the conventions and the repository
map are in [CONTRIBUTING.md](../CONTRIBUTING.md). This file holds the
procedures.

The repository is a uv workspace of the two packages published to PyPI:
`seanchai` at the root and `seanchai-corpus` at `packages/seanchai-corpus/`.
`uv sync` installs both from the working tree, so the installed corpus is the
committed one. The corpus package's module only says where its data is and
its version.

## Dependencies

- The library needs `pydantic` and `click`. `show`, `commands`, `dictionary`,
  `export`, `lint`, `format` and `corpus crosscheck` need nothing more.
- The `seanchai[extract]` extra adds `python-docx` (and `lxml`) and `pypdf`.
  The dev group installs it. Only `extractor/tgpp_docx/` and two validators
  in `downloader/core.py` import them. The catalog the export reads is its
  own module, `downloader/catalog.py`, so the export does not need the extra.
- Without the extra, `corpus extract`, `corpus regenerate` and a 3GPP,
  oneM2M or `transcribed` download stop with `MissingExtraError`.
  `corpus extract-rfc`, `corpus download --only rfc` and `--only wireshark`
  work without it.
- `seanchai corpus download` needs LibreOffice's `soffice` on PATH to convert
  legacy `.doc` files, unless run with `--no-convert`. The full `sources`
  tests fail on a `--no-convert` manifest, naming the unconverted documents.

The maintainers' commands are under `seanchai corpus`. Their defaults name
this repository's directories, so run them from its root.

## CI

`.github/workflows/ci.yml` runs the commands listed in
[CONTRIBUTING.md](../CONTRIBUTING.md#before-every-push). The same workflow
runs on GitHub and on Forgejo, which reads `.github/workflows/` while
`.forgejo/workflows/` does not exist. A Forgejo instance needs:

- A runner with the label `node22` on an image with node in it, such as
  `node22:docker://docker.io/library/node:22-bookworm`. `runs-on` picks that
  label when `github.server_url` is not GitHub's.
- `DEFAULT_ACTIONS_URL` under `[actions]` reaching every action the workflow
  names. The default, `https://data.forgejo.org`, mirrors them.
- Optionally `cache.enabled: true` in the runner's config, to keep the cache
  between runs. Without it each run starts cold.

## Tests

- Tests marked `sources` run `seanchai corpus regenerate` over the documents
  in `specifications/` into a scratch directory and require every committed
  pair to come out unchanged. They fail, not skip, when sources are missing
  or a `.doc` is unconverted, so a green `uv run pytest` means they ran.
- The other tests use committed files and small fixtures
  (`tests/conftest.py`). Every committed `.dad` file round-trips, every
  correction re-applies to the raw output, and the linter's findings over the
  corpus are pinned. `holes.toml` pins the known holes, `corpus.toml` may
  name only copies the corpus holds and versions the catalog pins, and
  `corrections.json` must match `edits/corrections/`.
- Two offline pins check extractor output. RFC 5778, 6942 and 7944, copied
  into `tests/fixtures/rfc/`, must rebuild to their committed pair; the
  `sources` tests hold the copies to the downloads, so after a download
  changes one, copy it over. The synthetic document's whole raw output is
  `tests/fixtures/tgpp_docx/synthetic.raw.dad`: after a deliberate extractor
  change, replace it with the new output and review the diff.
- `tests/test_export.py` runs `seanchai export` over the corpus in
  subprocesses, outside the repository and under two hash seeds that must
  agree byte for byte. `tests/export.sha256` pins a digest per file and leaves
  out the two versions in `index.json`, so a release does not move it. A
  failure names the changed files.
- `tests/test_packaging.py` builds both packages, pins what each holds, and
  runs the wheels from scratch environments, with and without the `extract`
  extra. It needs `uv` and no network.
- `tests/test_python_diameter_generate.py` generates python-diameter modules
  from the corpus and round-trips a Cx UAR through the real library, which is
  why the dev group holds it. `tests/test_python_diameter_validate.py` runs
  the validator against a fake library tree.
- `tests/test_wireshark_validator.py` runs the Wireshark validator's
  `core.lua` under each of `lua5.1` to `lua5.4` and the generated plugin
  under `tshark`. Interpreters not on PATH are skipped.

Support for a new source-document shape is covered by the `sources` tests.
Add a synthetic test only for a rejection path.

## Rebuilding the corpus

The corpus in `packages/seanchai-corpus/src/seanchai_corpus/dad/` is derived
from the downloaded sources and the edit layers.

1. `uv run seanchai corpus download` fetches the catalog into
   `specifications/`.
2. `uv run seanchai corpus regenerate` rebuilds every document, the raw
   mirror and `corrections.json`.
3. `git diff --stat packages/seanchai-corpus` shows what changed.
4. If the export changed, review it and run
   `uv run pytest tests/test_export.py --update-export-pin`.
5. Commit `corrections.json` with the edits it records. Changing a
   correction, even only its reason, without regenerating fails `uv run pytest`.

`regenerate` prints one line per document:

| Status | Meaning |
|---|---|
| `unchanged`, `changed` | rebuilt |
| `replaced` | the manifest holds a newer version; the old pair is removed |
| `new` | added with `--add` |
| `not-converted` | a legacy `.doc` downloaded with `--no-convert`; skipped |
| `not-in-manifest` | the manifest lacks the document; the run fails |
| `failed` | with the reason |

Under each document it prints the extractor's warnings and a warning for each
declaration whose version range does not cover the parsed version.
Transcriptions are rebuilt from `edits/transcriptions/`. `corrections.json` is
written only when nothing failed.

`regenerate` writes `.dad` files and `corrections.json` only. It does not set
the corpus's version ([Releases](#releases)) and does not touch `corpus.toml`,
`holes.toml` or `interfaces.toml`, which are edited by hand.

## Adding a document

`<SpecRef>` is the document's reference, such as `TS29.272` or `RFC6733`.

1. Add a `[[tgpp]]` or `[[rfc]]` entry to `src/seanchai/downloader/specs.toml`
   with its number, title and, unless the default covers it, a `reason`. Run
   `uv run seanchai corpus download`.
2. Run `uv run seanchai corpus regenerate --add <SpecRef>`. A shape the
   extractor rejects fails with the reason. An entry marked `out_of_scope` is
   refused ([extractor.md](extractor.md#out-of-scope)).
3. Run `uv run seanchai lint` on the new file under the corpus's `raw/`. Each
   error is a source typo (input patch), a reading the extractor should not
   make undeclared (quirk) or wrong data (correction); see
   [corrections.md](corrections.md).
4. Declare the fixes in `edits/` and run `uv run seanchai corpus regenerate`
   again. A hole the document brings fails `Model.build` and `seanchai lint`:
   fix it or record it in `holes.toml`
   ([corrections.md](corrections.md#the-record-of-known-holes)).
5. If the document cites others across releases, add the `corpus.toml` entry
   its references clause needs, with `citing_version` and evidence
   ([consumers.md](consumers.md#resolution-across-releases)).
6. Give the document its entry in `interfaces.toml`: the Diameter interfaces
   or reference points it specifies, or for an RFC its application, read from
   its scope clause and table of contents. See below.
7. Review the export diff and run
   `uv run pytest tests/test_export.py --update-export-pin`.
8. Run `uv run pytest`. Update the linter pins in `tests/test_linter.py` only
   after reading what each failure says.
9. Commit the raw and corrected files, the edit files, the catalog entry,
   `corrections.json`, any `corpus.toml` entry, the `interfaces.toml` entry
   and `tests/export.sha256`.

An `interfaces.toml` entry lists names as the specification spells them,
comma-separated in a TOML list: the Diameter ones, not every interface the
document mentions. Key it by reference under `[references]`, or by file stem
under `[documents]` where one edition's names differ from the others' (TS
29.212's St is not in its Release 11 edition, `29212-bj0`). A document with
none gets an empty list, so that it reads as decided; a document with no entry
fails `tests/test_corpus.py`. The export writes the names as each document's
`interfaces` in `index.json`.

## Version upgrades

`seanchai corpus download` follows 3GPP's newest version that has a published
ETSI PDF, so a new version appears as `replaced` on the next `regenerate`.

1. Diff the old raw file against the new raw file. This shows the
   specification's changes with the corrections held still.
2. A correction whose `expect` no longer matches fails the rebuild. That
   usually means upstream fixed the error: delete the declaration.
3. Diff the corrected files.
4. Re-read the new copy's references clause for every `corpus.toml` entry
   keyed by the document (`cited_version`, `latest_edition`,
   `cited_revision`, `stand_in`, `release_stand_in`, `release_fill`). Move
   `citing_version` to the new version where the clause says the same;
   otherwise update the entry and its evidence, or remove it if it is no
   longer needed. An entry left at a version the corpus no longer holds fails
   every load of the corpus. A document held in two releases has an entry per
   copy.
5. Re-read each excluded clause; remove the `[[exclude]]` if the new version
   finishes it ([extractor.md](extractor.md#exclusions)).
6. Run `uv run seanchai corpus regenerate --expand-ranges` to widen the
   version ranges of every declaration that applied cleanly.

If the extractor changed since the old raw file was committed, re-extract the
old version with the current code before diffing:

```sh
uv run seanchai corpus download --spec TS29.272 --version 19.5.0
uv run seanchai corpus regenerate --spec TS29.272 -o /tmp/old \
    --manifest specifications/versions/TS29.272/19.5.0/manifest.json
diff -u /tmp/old/raw/3gpp/rel-19/29272-j50.raw.dad \
    packages/seanchai-corpus/src/seanchai_corpus/dad/raw/3gpp/rel-19/29272-j60.raw.dad
```

`-o` keeps the old pair out of the corpus.

`--expand-ranges` rewrites `first_version`/`last_version` in
`edits/sources/<SpecRef>.toml` and the `versions=` string literal in
`edits/corrections/<SpecRef>.py`, moving only the bound the version passed and
keeping layout and comments. It prints each change as `expanded:`. An `Accept`
is widened only while it still matches its finding, and is otherwise printed as
`not widened, stale:`. A literal it cannot rewrite (outside the top-level
`CORRECTIONS` statements, in a lambda, conditional or filtered comprehension,
split by comments, or computed) is printed as `not widened, widen it by hand:`.

### A new release

A new 3GPP release upgrades every document at once.

1. Set `RELEASE` in `src/seanchai/downloader/catalog.py` and run
   `uv run seanchai corpus download`.
2. Run `uv run seanchai corpus regenerate`. Each copy moves into the new tree
   as `replaced`; the old pairs and empty trees are removed. Each document is
   read with the declarations of the release below it
   ([extractor.md](extractor.md#releases)).
3. A `find` or `expect` that now fails is usually a fix upstream adopted:
   remove it. A new shape needs an extractor change or a new declaration.
4. Do steps 4 and 5 of the version upgrade for every document. Also redo each
   `release_stand_in` and `release_fill` comparison against the new copy and
   move its `version` to it. Where the citing and cited copies differ for what
   the citing copy uses, pin the older version it means. Commit the
   `corpus.toml` changes with the corpus, since `regenerate` cannot write
   `corrections.json` while an entry names a missing copy.
5. Re-read every `Supply`'s cited clause: a non-specific reference moves to
   the cited document's latest version (TS 29.272's TS 32.422 gained values
   in Release 19).
6. Run `uv run seanchai corpus regenerate --expand-ranges` once the corpus
   holds the new copies, since acceptances are checked against them.

Moving a document's version this way is a corpus release only; the library
does not change.

## Releases

The two packages are released separately, each from its own tag:

| Package | Version | Tag |
|---|---|---|
| `seanchai` | semantic, `0.1.0` | `seanchai-v0.1.0` |
| `seanchai-corpus` | the date the corpus was regenerated, `2026.11.11` | `corpus-2026.11.11` |

Each version is set once, in the package's `pyproject.toml`, by `uv version`,
which updates the lockfile too. `tests/test_packaging.py` requires the corpus
version to be a real date without leading zeros, since PEP 440 drops them.
PyPI accepts a version once, so a second corpus release waits for the next
day.

The library's `corpus` extra names the oldest corpus it reads: the first
release of the oldest format in `corpus.FORMATS`. Raise it when the library
stops reading a format ([The corpus format](#the-corpus-format)).

To release the corpus from a commit holding the regenerated corpus:

```sh
version=$(date +%Y.%-m.%-d)
uv version --package seanchai-corpus "$version"
git commit -am "release corpus $version"
git tag "corpus-$version"
git push github main "corpus-$version"
gh workflow run release.yml --ref "corpus-$version" -f publish=seanchai-corpus
```

A library release is the same with `uv version --package seanchai 0.2.0`, the
tag `seanchai-v0.2.0` and `-f publish=seanchai`.

`.github/workflows/release.yml` runs only when started by hand; on Forgejo its
jobs are skipped. It runs the tests without sources, builds both packages,
checks that the tag names the built version, and smoke-tests the wheels. It
publishes only when run on a package's tag with `publish` naming that
package, through PyPI trusted publishing: each PyPI project trusts the
repository `sliva0/seanchai`, the workflow `release.yml` and a GitHub
environment, `pypi` for `seanchai` and `pypi-corpus` for `seanchai-corpus`.
Both environments must exist. They differ because PyPI accepts one pending
publisher per repository, workflow and environment.

To try a release without publishing, run it anywhere but a tag, or with the
default `publish=none`. The built distributions are kept as artifacts of the
run:

```sh
gh workflow run release.yml --ref main
```

The first release of each package needs a pending trusted publisher on PyPI,
added under "Publishing" in the account with the names above. Publish
`seanchai-corpus` first, since the library's `corpus` extra cannot install
until it exists.

## The corpus format

`corpus.toml` states the format, `format = 1`, and `corpus.FORMATS` lists the
formats the library reads. Loading another format raises
`corpus.CorpusFormatError` before any `.dad` file is parsed, naming both
numbers and the package to upgrade. A directory without `corpus.toml` has no
format check and no resolution rules, and is loaded as it parses; a
`holes.toml` beside its files is still read
([consumers.md](consumers.md#known-holes)).

Bump the number when a library that reads the old format would misread or
refuse the corpus:

- a change to the `.dad` grammar the parser does not accept, such as a new
  block type;
- a change to the directory layout (the trees, the raw mirror, the records);
- a change to the schema of `corpus.toml`, `holes.toml` or
  `corrections.json`.

A new document, version, `corpus.toml`, `holes.toml` or `interfaces.toml`
entry, or correction is not a format change. Nor is a new file beside them,
which an older library does not read: `interfaces.toml` is a file of its own
because `Rules.load` refuses a table of `corpus.toml` it does not know, so a
table there would have needed a format bump.

To bump it:

1. Release the library with the new number in `FORMATS`, beside the old one
   if possible.
2. Release the corpus stating the new number.
3. Raise the `corpus` extra's lower bound only when the old number leaves
   `FORMATS`.

The extra has no upper bound. A date-versioned corpus cannot know which
release will change the format, and the format check already makes an older
library fail at load with a message to upgrade `seanchai`. Consumers who want
neither pin both packages
([consumers.md](consumers.md#installing-the-corpus)).
