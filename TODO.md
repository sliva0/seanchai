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
