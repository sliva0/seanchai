# Plan: code quality pass

A review of the whole project (July 2026) turned up three categories worth
acting on: data-integrity bugs, a set of mechanical cleanups, and duplication
between the parser and the extractor. All seven sections are now done; this
file is kept as the record of what changed and why. Feature work is in
[roadmap.md](../roadmap.md).

Tests pass and all three tools are clean at every step; that is the acceptance
criterion for each one.

## Done

**Data-integrity bugs (§1).** `attach_pages` now reads the ETSI PDF's own cover
page and refuses a PDF whose specification *or* version differs from the
extracted docx — the case the downloader's fallback made reachable in normal
use — and reports how many sections the bookmark outline actually covered, with
an empty outline now an error. The `; bold` column is per-section, so one added
AVP can no longer reflow every marker in the file; `examples/*.dad` were
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

**Formatter dispatch (§4).** `functools.singledispatch` on the section type
replaced the dict of same-shaped callables, which also removed the `Any`
annotation the dict needed to type-check. The `bold_column` parameter is gone
rather than relocated: since §1.2 made the column per-section, `_abnf_body()`
derives it from the rules it is already formatting, so the three formatters
that opened with `del bold_column` no longer take an argument they ignore.
Dispatch is on the *exact* type — `singledispatch` alone walks the MRO, which
would format a `Message` subclass as a `Message` and drop its extra fields
silently — and an unregistered type raises instead of formatting nothing.
`formatter.format` is `format_spec`, so nothing shadows the builtin.

**Test gaps (§5).** Round-trip idempotency now runs over constructed ASTs
covering shapes the committed examples don't contain (no AVPs, every command
flag, unbounded and maximal occurrences, reserved-only enums). Extractor cases
that were documented but unpinned have fixtures: mixed bold in one ABNF line,
two ABNFs under one command heading, an AVP-table NOTE that names a defining
RFC, reserved notes interleaved by value rather than document order. Two code
fixes fell out: values reaching `int()` or a model field (a `; Page:` value, a
table `code` cell) escaped as bare `ValueError`s with no line, and an empty
table section crashed the formatter — tables now require at least one row,
since a table with none means the extractor found a caption and lost its
contents.

**Output corrections (§6).** `dad/corrections.py` implements the second patch
layer as designed: `Correction(target, field, expect, replace, reason)` over
five identity selectors, resolved and checked against the original tree before
anything is rebuilt, so a failure leaves no partially corrected file. Nodes are
rebuilt through validation rather than `model_copy(update=...)`. `seanchai
extract --corrections DIR` and `seanchai correct FILE --corrections DIR` expose
it; neither discovers the directory automatically, because loading one executes
its Python, and `correct` refuses to write over its input.
`corrections/TS29.272.py` is the first real correction set — the four VCSG
commands whose headers omit the application id clause 7.2.2 assigns them — and
a test re-applies every committed correction to the committed raw output, which
is the rot check the layer exists for.

**Downloader move (§7).** Now `src/seanchai/downloader/` behind `seanchai
download`, with `specs.toml` packaged alongside it (verified present in the
built wheel). The catalog is read on demand instead of at import, the module
raises `DownloadError` and reports progress through an injected callback
instead of printing and calling `SystemExit`, and `discover_3gpp_urls` takes
the specs it should look for rather than reading a module global — which let
the tests drop their `monkeypatch`ing of module state. Type checking found a
latent `None` dereference in the tests that the dynamically-loaded module had
been hiding.

**Tooling.** uv dev group with ruff, ty and basedpyright (`standard` mode);
ruff (`E`, `F`, `I`, `UP`, `B`, `SIM`, `RUF`) and pytest configured in
`pyproject.toml`; all three run clean. Policy in
[development.md](../development.md). Fixing the diagnostics surfaced a few genuine
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

## Not in this plan

- Parser leniency. An earlier design note called for it; the decision since is
  that the parser stays strict and the formatter defines canonical form. See
  [dad-format.md](../dad-format.md).
- CI. Deliberately not set up yet — run the tools locally.
