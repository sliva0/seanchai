# Development

Everything runs through [uv](https://docs.astral.sh/uv/); the dev group is
installed by `uv sync`.

```sh
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run ty check        # type check — fast, alpha
uv run basedpyright    # type check — thorough, standard mode
```

There is no CI yet. Run the four commands before committing.

## How strictly to take the tools

- **ruff** is authoritative. Lint and format findings get fixed, not
  suppressed. Configuration lives in `pyproject.toml` (`E`, `F`, `I`, `UP`,
  `B`, `SIM`, `RUF`).
- **basedpyright** runs in `standard` mode, not `strict`. It is the more
  trustworthy of the two type checkers, but it is occasionally stricter than
  the value it delivers — particularly around third-party stubs (`pypdf`,
  `python-docx`) whose annotations don't match how the libraries actually
  behave.
- **ty** is alpha software. It is fast and useful as a first pass, but it will
  sometimes be wrong or unable to express a pattern that is obviously fine.

`# type: ignore` and `# pyright: ignore[rule]` comments are allowed, on two
conditions: prefer the narrowest form that works, and write down *why* next to
it. A suppression is a claim that the checker is wrong, so it should read like
one. What is not allowed is ignoring a diagnostic without looking at it — the
checkers have already caught real latent bugs here (an `Optional[int]` page
number used in arithmetic, a tuple width that the return type promised).

Note that the two checkers can disagree about the same line: ty may call a
suppression that basedpyright requires "unused". When that happens, use the
checker-specific form (`# pyright: ignore[...]`), which the other one does not
try to interpret.

## Tests

`uv run pytest`. The suite is integration-leaning by design:

- Committed `examples/*.dad` are round-trip-pinned **by glob**, so a newly
  committed file is covered automatically.
- The extractor and the CLI run end-to-end against a synthetic docx and a real
  PDF outline, both built in `tests/conftest.py` fixtures. Tests that need
  malformed input build a modified copy of the synthetic docx explicitly; the
  fixture itself is valid.
- The downloader is exercised against a local HTTP server fixture, including
  retry, caching, path-traversal rejection and the ETSI fallback path.

When you add generic handling for a new source-document quirk, reproduce the
case in the synthetic docx fixture so the handling stays covered. The fixture
currently covers only a few of the cases collected in
[extractor.md](extractor.md).

An optional regression pin against the real docx sources — skipped unless
`output/manual/` is present, since those binaries are git-ignored — is still
worth adding.

## Conventions

- Python 3.14; the package is `src/seanchai/`.
- Comments explain *why*, especially where the code accommodates a specific
  real-world document quirk. Name the spec and clause that forced the code to
  look the way it does; that is what makes the next reader trust it instead of
  "simplifying" it back into a bug.
- Public functions carry docstrings; module docstrings explain the module's
  role in the pipeline.
