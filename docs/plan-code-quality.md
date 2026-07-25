# Plan: code quality pass

A review of the whole project (July 2026) turned up three categories worth
acting on: two real correctness bugs, a set of mechanical cleanups, and
duplication between the parser and the extractor. This plan captures the
remaining work. Feature work is in [roadmap.md](roadmap.md).

Tests pass and all three tools are clean at every step; that is the acceptance
criterion for each one.

## Done

**Tooling.** uv dev group with ruff, ty and basedpyright (`standard` mode);
ruff (`E`, `F`, `I`, `UP`, `B`, `SIM`, `RUF`) and pytest configured in
`pyproject.toml`; all three run clean. Policy in
[development.md](development.md). Fixing the diagnostics surfaced a few genuine
issues: an `Optional[int]` PDF page number used in arithmetic, two functions
returning a wider tuple than their annotation promised, and `zip()` calls that
silently truncate.

**Mechanical cleanups.** Removed the unused `warnings` parameter from
`_extract_avp_table` and the dead `if avp_table is not None` branch; annotated
`extract(docx_path)` and `attach_pages(pdf_path)`; replaced the inline
section-number sort key with `_section_sort_key()` (which also removed a latent
`None` subscript); made `tables_section` narrow alongside `avp_table` so
`ReusedAvps.source` can no longer be built from `None`; deleted stale
`__pycache__` trees, including one for a package that no longer exists.

**Documentation.** README split into working-today and planned; `TODO.md`
replaced by this `docs/` directory.

## 1. Fix the data-integrity bugs

These corrupt data that then gets committed and reviewed as if it were correct,
so they come first.

**1.1 `attach_pages` silently attaches wrong pages on a source mismatch.**
Today it trusts the caller to pass a PDF of exactly the same specification and
version as the docx; if either differs, every `; Page:` directive is quietly
wrong. The ETSI PDF cover page carries `3GPP TS 29.272 V18.6.0`, in the same
form the extractor already parses from the docx cover table. Extract it,
compare **both** the spec number and the version, and raise on mismatch. Test
the wrong spec at the right version as well as the right spec at the wrong
version. Return a bookmark-coverage count too, so an outline that matched
nothing can't look like success. Then drop the corresponding warning from
[extractor.md](extractor.md).

The downloader falls back to an earlier ETSI PDF when the exact version isn't
published, which makes this reachable in normal use rather than only through
operator error — see [downloader.md](downloader.md).

**1.2 `_bold_column` is computed across the whole file.** One long AVP rule
anywhere in a specification reflows the `; bold` column of every rule in the
file. On a version bump that adds a single AVP, the raw-vs-raw diff — the core
of the review workflow — goes from three lines to the whole file. Make the
column per-section (or fix its width), regenerate the committed
`examples/*.dad`, and confirm the round-trip tests still pin exactly.

**1.3 Input-patch accounting is warning-only.** A patch that was required and
applied zero times still leaves `extract` exiting zero, so a corpus run can
lose a fix without anyone noticing. Make a count mismatch an extraction error.
Keep `first_version`/`last_version` advisory — they belong in the message, not
in a gate; a patch that stops applying because the version moved is the failure
mode this is meant to prevent.

## 2. De-duplicate the format semantics

The parser and the extractor independently implement the same `.dad` semantics:

- `_BRACKETS` — verbatim in both;
- the AVP-rule regex, in two dialects (canonical vs. lenient-about-source);
- the `min*max` → `(min_occurs, max_occurs)` conversion — verbatim in both;
- the Diameter-header item split, including the `items[-1].isdigit()`
  application-id heuristic — near-verbatim in both;
- the M/V flag vocabulary, encoded three times (`parser._flags`,
  `extractor._flags_cell`, `formatter._flags_cell`).

These are properties of the format, not of either consumer. Move them into a
new `dad/abnf.py`: brackets, the occurrence qualifier in both directions, the
Diameter-header item parse, and the flag-set/cell conversion. The two source
dialects stay separate where they genuinely differ (the extractor tolerates
spacing that the canonical format never emits), but the *semantics* are shared.

Add a test asserting that the parser and the extractor agree on the same rule
text — right now nothing pins the two implementations together, and a format
change needs two coordinated edits with no failing test if you forget one.

## 3. Split `extract()`

`extract()` is ~115 lines with ten accumulator locals, doing three phases at
once. Split it into collect → resolve → assemble with an explicit intermediate
result type. The win beyond readability is testability: the enum-resolution
step (skip AVPs that are external, error when a pending enum has no code in the
AVP table) becomes unit-testable without building a docx.

While in there, keep every matching table instead of the current
last-one-wins `avp_table`/reused accumulators, and reject unexpected
multiplicity with a source location. No collected spec has two AVP tables yet,
but the current code would drop one silently.

## 4. Tidy the formatter dispatch

Three of the five `_format_*` functions open with `del bold_column`, because the
dispatch table forces a uniform signature — and that same table is why the
dispatch needs an `Any` annotation to type-check. Replace it with
`functools.singledispatch`, or pass a small context object. Rename
`formatter.format` while there: it shadows the builtin, and every call site
already spells it `formatter.format(...)`, so `format_spec` costs nothing.

## 5. Close the test gaps

The suite is in good shape; these are the holes. All of them are cases the code
already claims to handle.

- **Idempotency over generated ASTs.** Today only the committed examples are
  round-trip-pinned. Add a test that constructs specs directly and asserts
  `format(parse(format(spec))) == format(spec)` — the invariant the whole review
  workflow rests on.
- **`_is_bold` mixed-bold rejection** — the `ExtractionError` is unreachable
  from the current fixture.
- **Multi-ABNF command sections** — one section, two application ids (the
  29.272 IDR/DSR/RSR case). A documented real convention with no fixture.
- **NOTE-derived reused rows** — the `note_rfcs` path that turns an AVP-table
  NOTE naming an RFC into a `ReusedAvps` row.
- **Enum ordering** — RESERVED ranges interleaved with values by numeric sort.
- **`patch_file_name`** — untested.
- **Parser integer paths** — `; Page: abc` and a non-numeric table `code` cell
  escape as a bare `ValueError` with no line number, straight past the
  `DadParseError` contract every other malformed input honours.

## 6. Implement output corrections

The pipeline is designed around two patch layers, and only the first exists.
Input patches fix source typos that break extraction; corrections fix data that
extracts and parses fine but is semantically wrong — a misprinted AVP code, a
clause reference pointing at the wrong section, an omitted application id.

The design is in [proposal-corrections.md](proposal-corrections.md): a
per-spec Python file holding a declarative list of `Correction` entries, each
naming its target by identity, the value it expects to find, and the
replacement. `expect` is checked, so a correction that the spec has fixed
upstream fails loudly instead of silently doing nothing.

This is the layer that turns "the extractor ran" into "the data is right", so it
gates the linter being useful (§ [roadmap](roadmap.md)) — `raw.dad` may fail the
linter, the corrected file must pass.

## 7. Move the downloader into the package

`downloader/download_diameter_specs.py` is a standalone stdlib-only uv script,
but the planned archive fetching means it and the extractor will need to share
version decoding and the manifest. Move it to `src/seanchai/downloader/` behind
a `seanchai download` command, keeping a thin script shim if the standalone
form is still wanted. See [downloader.md](downloader.md) for the notes and the
known wart to preserve or fix while restructuring.

## Not in this plan

- Parser leniency. An earlier design note called for it; the decision since is
  that the parser stays strict and the formatter defines canonical form. See
  [dad-format.md](dad-format.md).
- CI. Deliberately not set up yet — run the tools locally.
