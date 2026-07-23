# TODO

Requirements from the design discussion, in no particular order. See README.md for
the overall architecture; this file is the working list of what has to exist.

This file is also the place for notes to future implementors: when you learn
something non-obvious while working (a source-document quirk, a workflow gotcha,
a convention that isn't visible in the code), record it here next to the
relevant item — see the "implementor notes" and "collected weirdness" blocks
below for the intended shape. Cheap to write now, expensive to rediscover later.

## `.dad` format

- Write a formal grammar for the format. The hand-made example in
  `files/ts_129329v180000p.dad` is the reference for look-and-feel. The linter
  should catch the kinds of mistakes hand transcription produces (mismatched
  header/rule names, inconsistent spacing, etc.).
- Directive comments (`; Key: value` headers, inline `; bold`-style markers) are
  part of the grammar with fixed positions; malformed directives are parse errors.
  `;;` introduces free-text comments the parser ignores.
- A file is a sequence of sections, each opened by a `; Type: X` header block
  (Message, Grouped AVP, Enumerated AVP, AVP Table, Reused AVPs, …) and separated by
  two blank lines; the parser dispatches on `Type:`.
- Keep the inline `; bold` marker as-is: it mirrors information present in the
  original document at the place where it's written, and inline is the wrong spot
  for origin references. Instead, a **Reused AVPs** section lists AVPs defined in
  another spec/RFC by name (names are unique within one specification's scope —
  they have to be, or the source documents themselves couldn't distinguish them),
  with the origin spec and any local overrides (e.g. the M-bit column of 3GPP
  "re-used AVPs" tables). Resolving an import yields the AVP's
  `(vendor-id, code)`, which disambiguates same-name AVPs across specs.
- Trivial AVP definitions use an **AVP Table** section mirroring each spec's own
  AVP table (whitespace-aligned columns, one AVP per row: name, code, section,
  type, flag columns). Rules: every cell is a single token, rows split on
  whitespace, `-` is the explicit empty-cell placeholder, column order is fixed
  by the grammar (the `;;` column-header line is cosmetic formatter output, never
  parsed). Canonical formatting uses at least 3 spaces between columns; column
  widths are computed from data cells only (minimum width 3) — the `;;` header
  line is excluded, so wide labels may overflow into the gaps. Per-row section references point at each AVP's own subsection; the
  semantics prose there is referenced, not copied. TS 29.230's one-big-table and
  RFC 6733 §4.5 serve as cross-check sources. See the AVP Table / Reused AVPs
  sections in the hand-made example.
- Inside enumerated AVP bodies, `; RESERVED = <n>` is a reserved-value directive
  (a grammar production, present in the AST — validators must treat assigning a
  reserved value as an error distinct from an unknown one). Decide range syntax
  (`; RESERVED = 34-99`) now, since specs reserve spans of values.

## Extractor

Implemented for 3GPP docx in `seanchai/extractor/tgpp_docx.py` (`extract()` +
`attach_pages()` PDF-outline pass), developed against TS 29.329 18.0.0
(`files/29329-i00.docx`, raw output in `files/29329-i00.raw.dad`) and diffed
against the hand-made `.dad` — remaining diffs are hand-file gaps, not extractor
bugs. Conventions learned: `Page:` is where the section starts per the PDF
bookmark outline (table sections get their parent section's page, which can be
one page before the table itself); AVPs listed in the reused table or in AVP
table NOTE references get no local definition even if their section reads like
one (DRMP). Source quirks handled: stray spaces inside rule names, bold applied
to bracket runs but not the name (only name runs are trusted), heading/rule name
mismatch (§6.1.8 "Push-Notifications-Answer") extracted with a warning.

Remaining:

- The source documents are human-written, so the extractor's strictness will
  eventually meet weirdness that neither code nor output-patches handle well
  (typos in numbers are fine to fix as `.dad` patches; structural oddities —
  a missing caption, a differently shaped table, a section that breaks the
  layout conventions — are not). Idea to keep in mind: a small per-spec
  override/instruction file the extractor reads (e.g. "treat table N as the
  AVP table", "ignore section X"). Don't build it speculatively — collect the
  actual weirdness from other documents here first, then design for it.
  Collected so far (all currently handled by generic leniency + warnings, none
  needed an override yet): heading/rule name mismatches (29.329 §6.1.8);
  rule names with spaces for hyphens (29.272 §7.3.196 "Monitoring Event
  Report"); AVP-table name cells line-wrapped losing a hyphen (29.272
  "MME-Location Information"); flags cells "M. V" and lowercase "v" (29.272);
  Diameter headers omitting the application id (29.272 VCSG commands →
  `application_id` is now optional in the AST); one command section holding two
  ABNFs for two application ids (29.272 IDR/DSR/RSR: S6a + S7a); empty clause
  cell (29.272 3GPP2-MEID → `AvpTableRow.section` now optional); merged table
  row duplicating cell text (29.272 Battery-Indicator M-bit); enum value/
  description styles inverted (29.229 §6.3.34); "x.y.z Name" headings without
  the " AVP" suffix (29.272); `<AVP header: 632, 10415>` comma separator
  (29.229). Also: 29.328 is a stage-2 data spec with no Diameter AVP table at
  all — "no AVP table found" is correct there, not a bug.
- Run the extractor over the other 3GPP Diameter specs (29.229, 29.328, 29.230's
  big table, …) — expect new document quirks; keep the acceptance loop
  "extract → format → parse → eyeball diff".
- Extend `download_diameter_specs.py` (or the extractor CLI) to fetch the docx
  zips from the 3GPP archive (`.../Specs/archive/<series>_series/<spec>/`,
  version encoded base-36: 18.0.0 → `i00`). Prefer `Specs/archive/` over the
  script's current `Specs/latest/Rel-N/` index: archive keeps every old
  version, which the raw-vs-raw diff workflow needs on version bumps.
- Implementor notes from the first three extractions:
  - Only 29.329 has a hand-verified reference `.dad`; the 29.229/29.272 raw
    outputs round-trip and were spot-checked but are otherwise unverified —
    the Wireshark-oracle cross-check is what makes them trustworthy at scale.
  - The `files/*.raw.dad` files were produced by ad-hoc scripts; once the CLI
    exists, regenerate them through it so the provenance is reproducible.
  - ETSI PDF filenames encode versions as two digits per component
    (18.1.0 → `v180100`); `etsi_pdf_url()` in the download script already does
    this correctly — don't hand-build these URLs.
  - Keep the docx and PDF versions matched exactly (i10 ↔ 18.01.00) or
    `attach_pages` will attach subtly wrong pages without any error.
  - TS 29.230's registry tables are a different shape from per-application AVP
    tables (no "AVP Flag rules" header) — the table-dispatch logic in
    `tgpp_docx.py` keys on that header and will need a separate path for it.
  - `seanchai/abnf_extractors/tgpp_pgf.py` is the obsolete PDF-based prototype,
    superseded by `seanchai/extractor/tgpp_docx.py` — delete it during the
    layout reorganization.
- Wire a `click` CLI entry point: docx + pdf in, `.dad` out, warnings to stderr.
- Add an RFC (plain text) extractor for the base protocol and IETF applications.
- The ETSI `Link:` URL is currently passed in by the caller; derive it (needs
  the ETSI edition suffix, e.g. `18.00.00_60`, which is not in the docx).

## Parser / formatter

- Python parser producing the shared AST; this is the public library surface that
  downstream generator/validator scripts build on.
- Canonical formatter: parse → pretty-print must be idempotent (stable diffs are
  what makes the patch-based review workflow survive extractor re-runs and spec
  version bumps). Parser is lenient about spacing; writer always emits the aligned
  canonical form.
- Formatter/linter should flag internal inconsistencies (header name vs. rule name,
  duplicate definitions, unresolved references).

## Tests

Scaffolding exists (`pytest` via `uv run pytest`, fixtures in `tests/conftest.py`,
two example tests in `tests/test_dad_format.py` showing the intended shape:
success tests build on the canonical example file, failure tests mutate it and
assert `DadParseError` with a message match). Tests worth writing:

- Round-trip: idempotence on a synthetic spec exercising every AST field the
  canonical file doesn't (no-vendor AVP header, `2*4`-style repetition
  qualifiers, RESERVED ranges, `Yes` in Encrypt, MUST-NOT M-bit override,
  missing `Page:`/`Link:`).
- Formatter alignment rules as unit tests: bold column = longest ABNF line + 1;
  enum `=` alignment including RESERVED and description padding; table column
  minimum width 3 and 3-space gaps; header labels excluded from widths.
- Parser error cases, one test each: unknown section `Type:`; duplicate
  directive; unexpected directive; trailing whitespace; mismatched ABNF
  brackets (`[ X }`); malformed Diameter/AVP header line; `Name:` directive vs.
  rule-name mismatch; message `Name:` without abbreviation; wrong table column
  count; bad flags cell (`X,V`); bad Encrypt cell; bad M-bit cell; inverted
  RESERVED range; malformed enum value line; content before first directive
  block; empty file.
- AST validation (no parser involved): field constraints reject bad AVP names,
  spec refs (`TS 29.336` with a space), section numbers, out-of-range codes;
  JSON dump/load round-trip preserves equality.
- Parser leniency: extra spaces between ABNF tokens and unaligned table columns
  parse to the same AST as the canonical form (once leniency is implemented —
  currently the parser is stricter than the design intends).

## Workflow & validation

- Commit raw extractor output per spec version; store reviewed corrections as
  diffs against it; corrected `.dad` files are the source of truth. Version upgrade
  = re-extract, diff raw-vs-raw, re-apply patch.
- Build patched `.dad` sets around the latest release with published PDFs (Rel-19
  currently); tooling itself must be version-agnostic.
- Cross-check extracted codes/vendors/types against Wireshark's Diameter
  `dictionary.xml` as an independent oracle in CI; optionally borrow its
  disambiguated AVP names for conflicting names across specs.
- First downstream consumers should be **validators** for existing hand-written
  dictionaries — they deliver CI value before any generator is adopted. Generators
  for implementations' native dictionary formats come after.

## Housekeeping

- Reorganize the folder/package layout (current structure is provisional).
