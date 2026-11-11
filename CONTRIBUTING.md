# Contributing

## Setup

Run `uv sync`; uv installs Python and the dev group. The library supports
Python 3.12 and newer, which ruff and both type checkers target; development
runs on 3.14 (`.python-version`).

## Before every push

Run what CI runs, in the order `.github/workflows/ci.yml` runs it:

```sh
uv sync --locked
uv run pytest -m "not sources"
uv run --locked --isolated --python 3.12 pytest -m "not sources"
uv run ruff check .
uv run ruff format --check .
uv run rumdl check .
uv run ty check
uv run basedpyright
uv build --all-packages --no-sources
```

Every command must pass. Fix a failure; do not suppress it, and do not push
while any of them is red. CI then smoke-tests the built wheels
(`tests/smoke_installed.py`, `tests/smoke_extract.py`).

After a Markdown or TOML change, `uv run rumdl check .` and
`uv run pytest tests/test_docs.py tests/test_toml_files.py` are the quick
checks, but the full list is the rule. `uv run pytest` without `-m` also runs
the `sources` tests, which need `uv run seanchai corpus download`.

## Pins a change moves

- `tests/export.sha256`: review the export diff, then run
  `uv run pytest tests/test_export.py --update-export-pin`.
- The corpus's `corrections.json`: `uv run seanchai corpus regenerate`
  rewrites it. Commit it with the edits it records.
- The linter's findings over the corpus: `_RAW_ERRORS`, the note counts,
  `_STANDING_CORPUS_NOTES` and `_ACCEPTED_CORPUS_NOTES` in
  `tests/test_linter.py`. Edit them by hand after reading the failure.

[docs/development.md](docs/development.md) has the procedures.

## Conventions

- Markdown prose and TOML keep to 80 columns, comments included. Tables,
  fenced code and a line that is one unbroken token or link may run long.
- A long TOML prose field (`reason`, `title`) is a multi-line basic string
  with no backslash continuations; readers collapse its whitespace. An exact
  field (`find`, `replace`, `url`) stays on one line.
- Comments explain why. Code that handles a document's quirk cites the
  specification and clause.
- Public functions have docstrings; a module docstring states its role. A
  public module lists its API in `__all__`; a CLI-only module is underscored.
- Docs describe what exists: no status tables, ticket ids or acceptance
  criteria.
- A suppression takes the narrowest form that works, with the reason beside
  it. Where the type checkers disagree, use `# pyright: ignore[...]`.

## Repository map

| Path | Holds |
|---|---|
| `src/seanchai/` | the library and the `seanchai` command (`cli.py`) |
| `packages/seanchai-corpus/` | the corpus package; the `.dad` files are under `src/seanchai_corpus/dad/` |
| `edits/` | per-document `sources/` (input patches, quirks, exclusions), `corrections/` and `transcriptions/` |
| `tests/` | tests for both packages |
| `integrations/` | consumer scripts and staged Wireshark dictionary patches |
| `editors/` | `.dad` syntax highlighting for VS Code, Vim and Neovim |
| `specifications/` | downloaded sources, git-ignored |

Everything else is in [docs/](docs/): [development](docs/development.md),
[format](docs/dad-format.md), [grammar](docs/grammar.md),
[corrections](docs/corrections.md), [extractor](docs/extractor.md),
[linter](docs/linter.md), [downloader](docs/downloader.md),
[oracle](docs/oracle.md), [consumers](docs/consumers.md),
[website](docs/website.md).
