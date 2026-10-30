# Development

Everything runs through [uv](https://docs.astral.sh/uv/); `uv sync` installs
the dev group.

```sh
uv run pytest -m "not sources"   # tests that need no downloaded documents
uv run pytest                    # all tests; needs `seanchai download` first
uv run ruff check .              # lint — findings get fixed, not suppressed
uv run ruff format .
uv run ty check                  # fast, alpha; may be wrong
uv run basedpyright              # standard mode; the more trustworthy one
```

`seanchai download` needs LibreOffice's `soffice` on PATH to convert the
catalog's legacy `.doc` archives, unless it is run with `--no-convert`. The
full sources test needs the conversions: TS 32.299, 29.154, 29.215, 29.217,
29.219, 29.343, 29.368 and 29.468 are read from them, and a `--no-convert`
manifest fails the test naming those eight.

CI runs the tests without sources plus ruff. Run everything locally before
committing anyway; CI is a backstop, not the gate.

Type-checker suppressions are allowed in the narrowest form that works, with
the reason written next to them. The two checkers sometimes disagree; use the
checker-specific form (`# pyright: ignore[...]`) when they do.

## Tests

- Tests marked `sources` run `seanchai regenerate` over the real documents
  under `specifications/` into a scratch directory and require every
  committed pair to come out unchanged, and load the pinned Wireshark
  dictionary. They *fail* when the sources are absent, or a committed
  specification's legacy `.doc` is unconverted, rather than skipping, so a
  green run without `-m "not sources"` means the strong check actually ran.
- Everything else runs on committed files and small synthetic fixtures
  (`tests/conftest.py`): every committed `.dad` round-trips by glob, every
  committed correction re-applies to the committed raw output, the linter's
  findings over the corpus are pinned, and the remaining tests cover error
  paths and shapes the corpus does not contain.
- `tests/test_python_diameter_generate.py` generates the python-diameter
  package from the committed corpus and imports it in a fresh interpreter
  against the real library, which is in the dev group for that reason.

When you add handling for a new source-document shape, the real-source pin
covers it; add a synthetic case only for a rejection path.

## Conventions

- Python 3.14; the package is `src/seanchai/`.
- Comments explain *why*. Where code accommodates a real document's quirk,
  name the spec and clause, so the next reader does not "simplify" it back
  into a bug.
- Public functions carry docstrings; module docstrings say the module's role.
- Docs describe what exists. Planned work goes in [roadmap.md](roadmap.md)
  as one short item; finished work leaves it. No status tables, ticket IDs
  or acceptance-criteria blocks.
