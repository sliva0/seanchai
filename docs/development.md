# Development

Everything runs through [uv](https://docs.astral.sh/uv/); `uv sync` installs
the dev group.

The repository is a uv workspace of the two packages published to PyPI:

- `seanchai`, the library, at the root: `pyproject.toml` and `src/seanchai/`.
- `seanchai-corpus`, the data, at `packages/seanchai-corpus/`. The `.dad` files
  and the record of known holes sit under
  `src/seanchai_corpus/dad/`, inside the module, since the wheel ships what is
  in the module. The module itself only says where they are and their version.

`uv sync` installs both from the working tree, so in a checkout the installed
corpus is the committed one, and the tests live at the root for both.

```sh
uv run pytest -m "not sources"   # tests that need no downloaded documents
uv run pytest                    # all tests; needs `seanchai download` first
uv run ruff check .              # lint; findings get fixed, not suppressed
uv run ruff format .
uv run rumdl check .             # Markdown, line length only
uv run ty check
uv run basedpyright
```

`seanchai download` needs LibreOffice's `soffice` on PATH to convert the
catalog's legacy `.doc` files, unless run with `--no-convert`. The full
`sources` test needs the conversions and fails, naming them, on a
`--no-convert` manifest.

CI runs the tests without sources, ruff, rumdl and both type checkers, then
builds both packages and runs `tests/smoke_installed.py` over the wheels,
installed with their dependencies from the index. Run everything locally
before committing; CI is a backstop.

Type-checker suppressions are allowed in the narrowest form that works, with
the reason beside them. Where the two checkers disagree, use the
checker-specific form (`# pyright: ignore[...]`).

## Tests

- Tests marked `sources` run `seanchai regenerate` over the real documents
  under `specifications/` into a scratch directory and require every
  committed pair to come out unchanged. They fail, rather than skip, when
  the sources are absent or a legacy `.doc` is unconverted, so a green run
  without `-m "not sources"` means the strong check ran.
- Everything else runs on committed files and small synthetic fixtures
  (`tests/conftest.py`): every committed `.dad` round-trips, every committed
  correction re-applies to the committed raw output, the linter's findings
  over the corpus are pinned, and the corpus's `holes.toml` pins the known
  holes.
- `tests/test_packaging.py` builds both packages, pins what each distribution
  holds, and runs the wheels from a scratch environment with nothing of the
  repository importable. It needs `uv` and no network.
- `tests/test_python_diameter_generate.py` generates the python-diameter
  modules from the corpus, imports them in a fresh interpreter against the
  real library and round-trips a Cx UAR through the library's codec. The
  library is in the dev group for that reason.

When you add handling for a new source-document shape, the real-source pin
covers it; add a synthetic case only for a rejection path.

## Conventions

- Python 3.14; the package is `src/seanchai/`.
- Comments explain why. Where code accommodates a real document's quirk,
  name the specification and clause, so the next reader does not simplify
  it back into a bug.
- Public functions carry docstrings; module docstrings say the module's
  role.
- Docs describe what exists. No status tables, ticket IDs or acceptance
  criteria.
- TOML files keep to 80 columns, comments included. A long prose field (a
  `reason`, a `title`) is a multi-line basic string with no backslash
  continuations, and every reader collapses its whitespace to single spaces
  (`seanchai.prose`). An exact field (`find`, `replace`) cannot wrap, since
  its whitespace is significant, so it stays on one line; those are the
  only lines `tests/test_toml_files.py` lets run long.
- Markdown prose keeps to 80 columns, and `rumdl` holds it there. Tables,
  fenced code and a line that is one unbroken token or one link may run
  long. A long code span wraps at a space; it renders the same.

## Rebuilding the corpus

The corpus under `packages/seanchai-corpus/src/seanchai_corpus/dad/` is
derived output. One command rebuilds all of it
from the downloaded sources and the two edit layers:

```sh
uv run seanchai download      # the catalog into specifications/
uv run seanchai regenerate    # every committed document, raw mirror included
git diff --stat packages/seanchai-corpus   # what changed, if anything
```

`regenerate` prints one line per document: `unchanged`, `changed`,
`replaced` (the manifest holds a newer version; the old pair is removed),
`new` (added with `--add`), `not-converted` (a legacy `.doc` downloaded
with `--no-convert`; skipped, not a failure) or `failed` with the reason.
Under each document it prints the extractor's warnings and a warning for
every declaration whose version range does not cover the parsed version.
Transcriptions ([extractor.md](extractor.md#transcriptions)) have no
manifest record and are rebuilt from `edits/transcriptions/` alongside.

`regenerate` leaves the corpus's version alone; cutting a release sets it
([below](#releases)).

## Adding a document

1. `uv run seanchai regenerate --add TS29.305`. The document must be in the
   downloader's catalog (`src/seanchai/downloader/specs.toml`) and readable
   by the extractor; a shape it rejects fails with the reason.
2. Lint the raw file, under the corpus's `raw/`, with `uv run seanchai lint`,
   which reads the committed corpus for the cross-file rules. Every error is a
   source typo (input patch), a reading the extractor should not make
   undeclared (quirk) or wrong data (correction).
3. Declare the fixes, regenerate again, and commit the raw and corrected
   pair with the edit files. A hole the new document brings fails the
   default `Model.build` and `seanchai lint`: fix it, or record it in
   the corpus's `holes.toml` with its evidence
   ([consumers.md](consumers.md#known-holes)).

| Layer | Fixes | Where |
|---|---|---|
| transcriptions | documents no extractor reads, copied by hand as printed | `edits/transcriptions/<SpecRef>.dad` |
| input patches | typos in the source text that break extraction, and case-only misspellings of a name | `edits/sources/<SpecRef>.toml`, `[[patch]]` |
| quirks | readings too heuristic to run undeclared | same file, `[[quirk]]` |
| extractor code | exact-match structure that fails loudly on its own | `src/seanchai/extractor/` |
| corrections | data that parses fine but is wrong | `edits/corrections/<SpecRef>.py` |
| acceptances | linter notes a clause makes deliberate; no data changes | same file, `Accept` |

## Version upgrades

`seanchai download` follows 3GPP's newest version with a published ETSI PDF,
so a newer version shows up as `replaced` on the next regenerate. Diff
raw against raw first: that is what changed in the specification with the
correction layer held still. A correction whose `expect` no longer matches
fails the rebuild, which is the signal that a fix was adopted upstream and
the declaration should go. Then diff the corrected files.

When the extractor has changed since the old raw file was committed,
re-extract the old version with today's code, so the diff shows the
specification's changes and not the extractor's:

```sh
uv run seanchai download --spec TS29.272 --version 18.6.0
uv run seanchai regenerate --spec TS29.272 -o /tmp/old \
    --manifest specifications/versions/TS29.272/18.6.0/manifest.json
diff -u /tmp/old/raw/3gpp/rel-18/29272-i60.raw.dad \
    packages/seanchai-corpus/src/seanchai_corpus/dad/raw/3gpp/rel-18/29272-i70.raw.dad
```

`--spec` limits the rebuild to that document and `-o` keeps the older pair
out of the corpus. A document the corpus holds in two releases is two copies,
each rebuilt in its own tree.

Once the diffs are reviewed,

```sh
uv run seanchai regenerate --expand-ranges
```

widens the version ranges of every declaration that applied cleanly:
`first_version`/`last_version` in `edits/sources/<SpecRef>.toml` and the
`versions=` string literal in `edits/corrections/<SpecRef>.py`, printed as
`expanded:` under the document. Only the bound the version is past moves,
by replacing that value's text, so layout and comments stay as they were.
An `Accept` is widened only while it still matches its finding; otherwise
it is printed as `not widened, stale`. A literal outside the top-level
`CORRECTIONS` statements, inside a lambda, conditional or filtered
comprehension, split by comments, or built by an expression, is printed as
`not widened` for a person to handle.

## Releases

The two packages are released apart, each from a tag of its own:

| Package | Version | Tag |
|---|---|---|
| `seanchai` | semantic, `0.1.0` | `seanchai-v0.1.0` |
| `seanchai-corpus` | the date the corpus was regenerated, `2026.11.2` | `corpus-2026.11.2` |

Each version lives once, in its package's `pyproject.toml`, and `uv version`
sets it and the lockfile together. `tests/test_packaging.py` holds the corpus's
to a real date with no leading zeros, as PEP 440 normalizes them away. PyPI
takes a version once, so a second corpus release waits for the next date. The
`corpus` extra of the library names the oldest corpus it reads; raise it when
the library stops reading an older one.

To cut a corpus release, from a commit holding the regenerated corpus:

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

`.github/workflows/release.yml` runs only when started by hand. It builds both
packages, checks that a tag names the version it built, and runs the smoke test
over the wheels. It publishes only from a run on a package's tag with `publish`
naming that package, so a run anywhere else, or with the default `none`, is a
dry run. Publishing uses PyPI trusted publishing, so no token is stored: each
PyPI project trusts the repository `sliva0/senchai`, the workflow `release.yml`
and the environment `pypi`, which has to exist on GitHub.
