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

CI (`.forgejo/workflows/ci.yml`) runs the tests and ruff on every push, but
only the part that needs no source documents — the real-source tests skip
themselves when `specifications/` is absent, and the type checkers stay
local. Run all five commands before committing anyway.

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

- Every committed `.dad` file — the corpus under `dad/` and the hand-made
  reference in `examples/` — is round-trip-pinned **by glob**, so a newly
  committed file is covered automatically.
- The extractor and the CLI run end-to-end against a synthetic docx and a real
  PDF outline, both built in `tests/conftest.py` fixtures. Tests that need
  malformed input build a modified copy of the synthetic docx explicitly; the
  fixture itself is valid.
- The downloader is exercised against a local HTTP server fixture, including
  retry, caching, path-traversal rejection and the ETSI fallback path.
- The synthetic PDF fixtures carry a real cover title (`_write_cover` in
  `tests/conftest.py`), because `attach_pages` reads it to verify that the
  rendering matches the docx.
- Two thin seams are unit-tested directly rather than through a document:
  `tests/test_abnf.py` (the shared ABNF semantics, including that the parser
  and extractor dialects agree) and `tests/test_extract_phases.py` (the
  extractor's resolve phase).
- `tests/test_corrections.py` re-applies every committed correction module to
  the committed raw output, so a re-extraction that invalidates one fails here
  rather than in a review months later — and checks that the corrected file
  already holds every `replace`, so the committed pair cannot drift apart.
- `tests/test_real_sources.py` re-extracts every committed file from the real
  docx and its ETSI PDF and compares byte-for-byte: the raw files against the
  extractor alone, the corrected ones against both layers. It skips unless the
  sources are present under the git-ignored `specifications/` tree, so a
  fresh clone skips one case per committed file — but on a machine that has
  them, it is the test
  that catches an extractor change which is fine on the synthetic fixture and
  wrong on the documents the fixture was abstracted from.

When you add generic handling for a new source-document quirk, reproduce the
case in the synthetic docx fixture so the handling stays covered. The fixture
currently covers only a few of the cases collected in
[extractor.md](extractor.md).

## Conventions

- Python 3.14; the package is `src/seanchai/`.
- Comments explain *why*, especially where the code accommodates a specific
  real-world document quirk. Name the spec and clause that forced the code to
  look the way it does; that is what makes the next reader trust it instead of
  "simplifying" it back into a bug.
- Public functions carry docstrings; module docstrings explain the module's
  role in the pipeline.

## Working on these documents

`docs/` describes what exists, plus a small amount of scheduled work in
[roadmap.md](roadmap.md), plus explicitly labelled proposals. Completed review
rounds move to [history/](history/), which is a record and never a schedule.
Keeping those registers apart is the point of the split — a reader must be able
to tell "this is how it works" from "this is what we intend to do" without
checking the code.

Some decisions here are settled, and a review that reopens them costs more than
it returns. If you disagree, argue the decision on its merits; don't
reintroduce it as an incidental edit:

- **CI is a backstop, not the gate.** The Forgejo job runs what a bare
  container can (tests minus real sources, ruff); the full battery — both
  type checkers, the real-source re-extractions — runs locally before
  committing, and CI passing does not excuse skipping it.
- **Version ranges are advisory.** For input patches, quirks and corrections,
  a recorded range describes where a fix is known to be needed and sharpens
  the message. It never gates whether the fix is applied: gating means
  silently dropping a fix on the next release, the exact failure the
  accounting exists to catch.
- **Heuristic readings are opt-in per document.** An extractor behavior that
  could silently misread a document it was not written for — prose
  harvesting, tolerance of malformed input — runs only where a source
  declaration names it as a quirk; exact-match structure (header spellings,
  rule grammars) stays in code because unrecognized input fails loudly on
  its own. This *reverses* an earlier settled line ("recurring document
  conventions stay in extractor code"), deliberately: global leniencies
  accumulate, each collected case loosening the parser for every future
  document, and a code leniency has no per-document accounting — a quirk
  fails loudly when its document stops needing it. Do not migrate a
  leniency to a quirk in passing; do it when touching the behavior, with
  the real-source pins proving the output unchanged. And a quirk carries no
  parameters — the behavior it names lives in code.
- **Don't design ahead of collected cases.** The extractor has repeatedly not
  grown override files, structural-instruction formats or generalised table
  handling, because no real document has needed them yet. The same restraint
  applies to manifests, provenance schemas, format-version negotiation and
  public API contracts: write them down when a second consumer or a real
  failure asks for them, not before. A note in `roadmap.md` is the right size
  for a good idea whose time hasn't come.

  The corpus layout used to be on that list and no longer is:
  `dad/3gpp/rel-N/` and `dad/rfc/` for corrected files, with the raw mirror
  under `dad/raw/`, are settled and described in
  [dad/README.md](../dad/README.md).
- **Prose over process.** No status tables, dependency graphs, ticket IDs or
  acceptance-criteria blocks. This is a small repository; the docs should read
  like an experienced colleague explaining the system, which is also what makes
  the *why* survive.
- **Match the register.** Explanatory and specific, with real spec clauses and
  file references as evidence. Not a compliance checklist — sentences that
  start "must" three times a paragraph are a sign the content has drifted from
  describing this project to describing projects in general.
