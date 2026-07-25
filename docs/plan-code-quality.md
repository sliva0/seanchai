# Plan: code quality pass

A review of the whole project (July 2026) turned up three categories worth
acting on: data-integrity bugs, a set of mechanical cleanups, and duplication
between the parser and the extractor. Sections 1–3 are done; what is left keeps
its original numbering. Feature work is in [roadmap.md](roadmap.md).

Tests pass and all three tools are clean at every step; that is the acceptance
criterion for each one.

## Done

**Data-integrity bugs (§1).** `attach_pages` now reads the ETSI PDF's own cover
page and refuses a PDF whose specification *or* version differs from the
extracted docx — the case the downloader's fallback made reachable in normal
use — and reports how many sections the bookmark outline actually covered, with
an empty outline now an error. `_bold_column` is per-section, so one added AVP
can no longer reflow every `; bold` marker in the file; `examples/*.dad` were
regenerated (only 29.229 changed). Input-patch count mismatches raise
`PatchError` instead of adding to a warning list that nothing acts on; version
ranges stay advisory.

**Shared ABNF semantics (§2).** `dad/abnf.py` now owns the meaning both the
parser and the extractor were implementing separately: bracket↔presence,
`min*max`↔occurrences, Diameter-header items, and the M/V flag vocabulary. Both
dialects' regexes use the same group names, so `abnf.avp_rule()` takes either
match; `tests/test_abnf.py` pins the two dialects to the same AST for the same
rule. Errors surface as `AbnfError` and each caller adds its own context (line
number or document section).

**`extract()` split (§3).** Now collect → resolve → assemble with `_Collected`
and `_Resolved` between them. Resolution — external-AVP skipping, code and
vendor-id lookup for enumerated AVPs — is unit-tested without building a docx
(`tests/test_extract_phases.py`). Tables are collected as lists and a second
AVP or re-used table is now an error naming the sections, replacing the
accumulator that silently kept the last one. Output for all three real specs is
byte-identical across the refactor.

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
