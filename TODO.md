# TODO

Open work, in no particular order. See README.md for the overall architecture.

This file is also the place for notes to future implementors: when you learn
something non-obvious while working (a source-document quirk, a workflow gotcha,
a convention that isn't visible in the code), record it here next to the
relevant item — see the "implementor notes" and "collected weirdness" blocks
below for the intended shape. Cheap to write now, expensive to rediscover later.

## Status

Implemented so far, so a fresh reader knows what already exists:

- `.dad` format: pydantic AST (`seanchai/dad/ast.py`), strict line-oriented
  parser (`parser.py`), canonical formatter (`formatter.py`). Round-trip is
  exact and idempotent; the hand-verified reference file is
  `examples/ts_129329v180000p.dad`. All section kinds are in: Message,
  Grouped AVP, Enumerated AVP (with `; RESERVED = n` / `= n-m` directives and
  per-value descriptions), AVP Table, Reused AVPs.
- 3GPP docx extractor (`seanchai/extractor/tgpp_docx.py`): `extract()` plus the
  `attach_pages()` ETSI-PDF-outline pass. Verified against the hand-made 29.329
  file; also produces `examples/29229-i10.raw.dad` and `examples/29272-i60.raw.dad`.
- Test scaffolding: `uv run pytest`, fixtures in `tests/conftest.py`, two
  shape-defining tests in `tests/test_dad_format.py`.
- Input patches: `patches/<SpecRef>.toml` find/replace fixes for source typos,
  applied to normalized text before parsing with exact application counting
  and known-version-range warnings (`seanchai/extractor/patches.py`).
- CLI: `uv run seanchai extract DOCX [--pdf PDF] [--link URL] [-o OUT]` —
  warnings go to stderr; the committed `examples/*.raw.dad` are regenerated
  through it. Downloader: `downloader/download_diameter_specs.py` (uv script)
  with the curated catalog split into `downloader/specs.toml`; downloads land
  in git-ignored `output/` (`output/manual/` holds hand-fetched docx/PDFs).

## `.dad` format

- Write a formal grammar document — currently the parser source is the spec.
  Design intent to preserve: directive comments are grammar with fixed
  positions (malformed = parse error), `;;` is ignorable free text, `; bold`
  stays inline because it mirrors the source document, table cells are single
  whitespace-separated tokens with `-` as the empty placeholder, column order
  fixed by the grammar, `;;` column headers cosmetic-only.
- Parser leniency: the design says "parser lenient about spacing, writer emits
  canonical form", but the parser is currently stricter than intended (exact
  single spaces in several places). Loosen it; the formatter defines canonical.
- Restrict `AvpTableRow.data_type` to the closed set of Diameter base/derived
  types (see `TODO(format)` in `ast.py`).
- Linter with cross-section checks: every AVP referenced in a message/grouped
  body resolves to a local definition, an AVP-table row, or a reused-AVPs
  entry; duplicate definitions; duplicate enum values; AVP-table row vs.
  grouped/enumerated definition consistency (code, type).

## Extractor

- Run the extractor over the remaining 3GPP Diameter specs — expect new
  document quirks; keep the acceptance loop "extract → format → parse →
  eyeball diff". 29.230's registry tables need their own path: they lack the
  "AVP Flag rules" header the table dispatch keys on.
- Extend `download_diameter_specs.py` (or the extractor CLI) to fetch the docx
  zips from the 3GPP archive (`.../Specs/archive/<series>_series/<spec>/`,
  version encoded base-36: 18.0.0 → `i00`). Prefer `Specs/archive/` over the
  script's current `Specs/latest/Rel-N/` index: archive keeps every old
  version, which the raw-vs-raw diff workflow needs on version bumps.
- Derive the ETSI `Link:` URL instead of taking it from the caller (needs the
  ETSI edition suffix, e.g. `18.00.00_60`, which is not in the docx — probably
  requires listing the ETSI deliver directory).
- Add an RFC (plain text) extractor for the base protocol and IETF
  applications. RFC AVP tables (RFC 6733 §4.5) will need plain-AVP rows like
  the 3GPP ones.
- Input patches (implemented — `seanchai/extractor/patches.py`, files in
  `patches/<SpecRef>.toml`, applied to the normalized paragraph/cell/title
  text while building the section model; a patch applying more or fewer times
  than `count` warns, including the `first_version`/`last_version` range so
  the message can say "needed on X..Y, currently parsing Z". The four
  collected typo cases in 29.272/29.329 are covered). The extractor is strict
  again: the old typo repair heuristics (flags-cell `.`/lowercase,
  space→hyphen name repairs) now raise `ExtractionError` and the typos are
  fixed by input patches instead — an unpatched 29.272 fails on
  "malformed flags cell 'M. V'". The synthetic fixture is valid by default;
  strict-error and pre-parse patching tests create malformed copies explicitly.
  Remaining:
  - Stretch goal: a CLI flag that auto-expands a patch's
    `first_version`/`last_version` range when a newer/older version is parsed
    and the patch still applied cleanly (needs comment-preserving TOML
    rewriting, e.g. tomlkit).
  - Division of labor stays: input patches = genuine typos; extractor code =
    recurring conventions that carry information (dual-application ABNFs,
    merged note rows, missing app ids); output `.dad` patches = semantic
    corrections. Structural damage (missing captions, split tables) has no
    collected case yet — revisit override-style instructions only if one
    appears.

Implementor notes:

- Only 29.329 has a hand-verified reference `.dad`; the 29.229/29.272 raw
  outputs round-trip and were spot-checked but are otherwise unverified — the
  Wireshark-oracle cross-check is what makes them trustworthy at scale.
- Conventions baked into the extractor: `Page:` is where the section starts
  per the PDF bookmark outline (table sections get their parent section's
  page, which can be one page before the table itself); AVPs listed in the
  reused table or in AVP-table NOTE references get no local definition even if
  their section reads like one (DRMP); enumerated AVPs take their code from
  the AVP table and the vendor-id from the spec's grouped-AVP headers.
- ETSI PDF filenames encode versions as two digits per component (18.1.0 →
  `v180100`); `etsi_pdf_url()` in the download script already does this
  correctly — don't hand-build these URLs.
- Keep the docx and PDF versions matched exactly (i10 ↔ 18.01.00) or
  `attach_pages` will attach subtly wrong pages without any error.
- 29.328 is a stage-2 data spec with no Diameter AVP table at all — "no AVP
  table found" is correct there, not a bug.

Collected source-document weirdness (all handled by generic leniency +
warnings so far; none needed an override yet):

- heading/rule name mismatches (29.329 §6.1.8 "Push-Notifications-Answer");
- rule names with spaces for hyphens (29.272 §7.3.196 "Monitoring Event
  Report");
- AVP-table name cells line-wrapped losing a hyphen (29.272 "MME-Location
  Information");
- flags cells "M. V" and lowercase "v" (29.272);
- Diameter headers omitting the application id (29.272 VCSG commands →
  `application_id` is optional in the AST);
- one command section holding two ABNFs for two application ids (29.272
  IDR/DSR/RSR: S6a + S7a);
- empty clause cell (29.272 3GPP2-MEID → `AvpTableRow.section` is optional);
- merged table row duplicating cell text (29.272 Battery-Indicator M-bit);
- enum value/description paragraph styles inverted (29.229 §6.3.34);
- "x.y.z Name" headings without the " AVP" suffix (29.272);
- `<AVP header: 632, 10415>` comma separator (29.229);
- bold applied to bracket runs but not the AVP name (only name runs are
  trusted for the `; bold` marker).

## Tests

The suite exists and is integration-leaning: committed `examples/*.dad` are
round-trip-pinned by glob (new committed files are covered automatically), the
extractor and CLI run end-to-end against a synthetic docx + real-outline PDF
built in `tests/conftest.py` fixtures, and the downloader is exercised against
a local HTTP server fixture. Still worth writing:

- Parser leniency: extra spaces between ABNF tokens and unaligned table columns
  parse to the same AST as the canonical form (once leniency is implemented).
- Optional regression pin against the real docx sources, skipped unless
  `output/manual/` is present (the docx/PDF binaries are git-ignored, so this
  can't run unconditionally).
- As new source-document weirdness gets generic handling in the extractor,
  reproduce each case in the synthetic docx fixture so the handling stays
  covered (the fixture currently covers only a few of the collected cases).

## Workflow & validation

- Commit raw extractor output per spec version; store reviewed corrections as
  diffs against it; corrected `.dad` files are the source of truth. Version
  upgrade = re-extract, diff raw-vs-raw, re-apply patch.
- Build patched `.dad` sets around the latest release with published PDFs
  (Rel-19 currently); tooling itself must be version-agnostic.
- Cross-check extracted codes/vendors/types against Wireshark's Diameter
  `dictionary.xml` as an independent oracle in CI; optionally borrow its
  disambiguated AVP names for conflicting names across specs.
- First downstream consumers should be **validators** for existing hand-written
  dictionaries — they deliver CI value before any generator is adopted.
  Generators for implementations' native dictionary formats come after.

## Housekeeping

- Fill in the `pyproject.toml` description (still the uv placeholder).
- Optional: split `downloader/download_diameter_specs.py` (~550 lines) into
  modules if it grows further; the catalog is already external in
  `specs.toml`. Review notes for whoever touches it next: 3GPP index pages are
  scraped with regexes over raw HTML (fine for the FTP listing format, but
  brittle if 3gpp.org changes markup); a failed download cancels remaining
  jobs but already-running ones finish; `manifest.json` records sha256/size
  per artifact — keep that when restructuring, the extractor pipeline can use
  it for change detection. Known wart: when a cached file fails the
  content-type check and the re-download also fails validation,
  `atomic_download` leaves the corrupt cached file in place instead of
  deleting it.
