# TODO

Requirements from the design discussion, in no particular order. See README.md for
the overall architecture; this file is the working list of what has to exist.

## `.dad` format

- Write a formal grammar for the format. The hand-made example in
  `files/ts_129329v180000p.dad` is the reference for look-and-feel. The linter
  should catch the kinds of mistakes hand transcription produces (mismatched
  header/rule names, inconsistent spacing, etc.).
- Directive comments (`; Key: value` headers, inline `; bold`-style markers) are
  part of the grammar with fixed positions; malformed directives are parse errors.
  `;;` introduces free-text comments the parser ignores.
- Replace/augment the `; bold` marker with explicit parseable origin references:
  every AVP either is defined in the current spec or carries/inherits a reference to
  the spec/RFC it comes from. References must be resolvable to `(vendor-id, code)`
  to disambiguate same-name AVPs.
- Add a definition kind for plain (non-grouped, non-enumerated) AVPs: code, vendor,
  base data type, M/V flags. Sources: each spec's own AVP table for flags;
  TS 29.230 as the one-big-table source/cross-check for all 3GPP AVP names, codes
  and data types; RFC 6733 §4.5 for base-protocol AVPs.

## Extractor

- Switch 3GPP content extraction from PDF text to the .docx sources (docx is
  zip+XML: bold runs, tables, section structure are explicit — this removes most of
  the regex heuristics). Pipeline: docx → intermediate document model (sections,
  tables, styled runs) → `.dad` AST.
- Keep a minimal PDF pass that reads only the ETSI PDF bookmark outline
  (`pypdf` `reader.outline`, verified to work) to map section numbers → page
  numbers, so `.dad` headers can reference PDF pages.
- Add an RFC (plain text) extractor for the base protocol and IETF applications.
- Extractor and parser share the same `.dad` AST representation.

## Parser / formatter

- Python parser producing the shared AST; this is the public library surface that
  downstream generator/validator scripts build on.
- Canonical formatter: parse → pretty-print must be idempotent (stable diffs are
  what makes the patch-based review workflow survive extractor re-runs and spec
  version bumps). Parser is lenient about spacing; writer always emits the aligned
  canonical form.
- Formatter/linter should flag internal inconsistencies (header name vs. rule name,
  duplicate definitions, unresolved references).

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
