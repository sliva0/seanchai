# The `.dad` format

A plain-text format that stays as close as possible to the ABNF in the source
documents, so a definition reads as a near-diff against the spec.
[grammar.md](grammar.md) states it formally; where the two disagree, the
grammar is the one to fix.

The format is **not stable and carries no compatibility promise** until the
project is published. Change it whenever the work in hand needs it: committed
files are extractor output and get regenerated. The design intent below is
what to preserve; the spelling is not.

## Shape of a file

Blocks separated by blank lines: the file header, then one block per section,
each starting with `; Type:`.

```dad
; Specification: 3GPP TS 29.329
; Version: 18.0.0
; Vendor-ID: 10415
; Bases: RFC6733
; Link: https://www.etsi.org/deliver/...


; Type: Message
; Name: User-Data-Request, UDR
; Section: 6.1.1
; Page: 16
<User-Data-Request> ::= < Diameter Header: 306, REQ, PXY, 16777217 >
        < Session-Id >
        { Vendor-Specific-Application-Id }
      * [ Supported-Features ]                ; bold
```

| `; Type:`           | Holds                                                            |
|---------------------|------------------------------------------------------------------|
| `Application Scope` | an application id the document states in prose, and its clauses  |
| `Message`           | a command-code ABNF rule with its Diameter header                |
| `Grouped AVP`       | `Name ::= < AVP header: code vendor-id >` plus its body          |
| `Enumerated AVP`    | the header rule plus values and reserved ranges, or their source |
| `AVP Table`         | the spec's own AVP table, one AVP per row                        |
| `Reused AVPs`       | AVPs defined elsewhere, mirroring "re-used Diameter AVPs" tables |
| `Registry`          | codes a registry allocates, each to the documents defining it    |

## Design intent

- **Directive comments are grammar.** A single `;` in a defined position is
  semantic (`; Key: value` headers, `; bold`, `; strikethrough`,
  `; RESERVED`); a malformed one is a parse error. Free-text comments use
  `;;` and carry no data; where they attach is still defined (see
  [Comments](#comments)), so normalising a file keeps them.
- **The file states its own vendor-id.** `; Vendor-ID:` is the vendor space
  the document's own AVPs are defined in, and nothing else in the file
  supplies it: a clause header omits the vendor both for a genuine
  IETF-space AVP and when the document forgot, and a table has a vendor
  column only where its document prints one. A
  hand-authored vendor extension states its own, and nothing else needs to
  learn about that vendor.
- **A table printing each row's vendor keeps it.** oneM2M TS-0004 table
  A.4-1 tabulates IETF, 3GPP and oneM2M AVPs side by side, each with its
  "AVP Vendor Id"; the `Vendor-ID` column holds it, and the row's identity
  is that vendor and its code. Inferring it from the V flag would read the
  document's 45687 rows, which put V under Must-not, as IETF space.
- **The file states what it builds on.** `; Bases:` lists the documents
  whose AVPs the file uses without citing them (`Session-Id`, `Origin-Host`,
  `* [ AVP ]` from RFC 6733). Extractors stamp `RFC6733` for everything but
  RFC 6733 itself; a document building on more (RFC 4072 on NASREQ, TS
  29.215's S9 on all of 29.212's Gx and Gxx AVPs) gets its entries from a
  `bases` correction.
- **An application id stated in prose is a statement of its own.** TS
  29.212 prints its Gx commands with bare `272, REQ, PXY` headers and says
  in clause 5.1 that Gx's id is 16777238. An `Application Scope` block
  records that, citing clause 5.1, and applies it to the commands of clause
  5 (`; Applies-To: 5.*`); the headers stay as printed, so a header still
  says only what it says.
- **`; bold` and `; strikethrough` stay inline**, mirroring the source,
  where bold marks AVPs the specification defines or modifies. A strike
  means what its document says it means, so the marker records the fact
  and nothing more; where a document's legend gives it a meaning, the
  extractor reads that instead. TS 32.299's (clauses 6.2.1.2, 6.4.1.2) is
  "not used by 3GPP", so its struck members are commented out, marker
  kept, and stay visible where they stood without being members.
- **A table declares its own columns.** `; Columns:` states which columns the
  source table had, in source order, so "the table had no such column" stays
  distinct from "the cell was empty". Only modelled columns are recorded;
  unmodelled prose columns are dropped, and an unmodelled machine-readable
  column is a reason to model it, not to carry it anonymously.
- **Where a row applies is the document's marks.** TS 29.212's "Acc.
  Type" and "Applicability", TS 29.061's "Applicable Reference Points" and
  TS 32.299's per-command "Used in" columns are mark columns (`Acc-Type`,
  `Applicability`, `Reference-Points`, `ACR` to `CCA`): a cell lists the
  marks the document prints, comma-separated, without interpreting them,
  each with what the document prints beside it (`"All (NOTE 5)"`, whose
  note 5 excludes 3GPP-GPRS). What `Rel8` or `OC` means is the document's
  legend's, which the model documents per label. A dash the source prints
  is `-` and a blank cell `""`, since TS 32.299 gives the dash a meaning
  and the blank none.
- **Table cells are single tokens**, `-` for empty, except in a mark
  column, where a mark that is not a plain token is quoted as an enum value
  name is and `-` is the source's own dash.
- **Enum value names keep the document's spelling.** Most are identifiers
  (`DELIVERY_REPORT`), but TS 32.299 labels values in words, so a name is
  free text rather than a derived identifier no document prints, and one
  that is not an identifier is quoted (`"PS to CS Transfer"`,
  `"Virtual Private Network (VPN)"`), with `\"` and `\\` for a double quote
  and a backslash inside the quotes (RFC 4005's `802 (… "canonical
  format")`). Quoting only where needed keeps the identifiers reading as the
  ABNF does.
- **An enumeration defined elsewhere says where.** A clause that gives its
  values by reference (TS 29.272's `Trace-Depth`, "those defined in TS
  32.422 [23] for Trace Depth") prints `; Values:` with that citation and no
  values, which is distinct from a clause the extractor found nothing in.
- **A registry allocates; it defines nothing.** TS 29.230 assigns each AVP
  code, command code and application id to the document defining it, so its
  tables are `Registry` blocks rather than AVP tables: a row is a code, the
  name the registry gives it and the documents it cites, which may be
  several (`TS29.209,TS29.211,TS29.214` for codes 500–581), and a reserved
  range is a `; RESERVED` line with the documents its note names and its
  purpose quoted as printed. Read as AVP definitions, the table would make
  the registry a second definer of every 3GPP AVP and lose which document
  defines each.
- **Reused AVPs are listed by name.** Resolving a row against the origin's
  file yields the `(vendor-id, code)` that is the real identity.
- **An origin names its publisher, unless it is 3GPP or IETF.** The corpus
  is 3GPP's and IETF's, so their documents are bare numbers (`TS29.272`,
  `RFC6733`); anything else a document re-uses from leads with its
  publisher and keeps the publisher's own numbering (`ETSI-TS283.034`,
  `3GPP2-X.S0057`, `OMA-DDS-Charging_Data`, `oneM2M-TS-0004`). Without the
  prefix, ETSI's three-digit TISPAN series would read as a 3GPP number and
  OMA's names as nothing. No extractor reads these documents, so the corpus
  holds one only when someone writes it by hand, as ETSI ES 283 034 and TS
  183 017 are.
- **A transcription says so.** A document no extractor reads, because no
  Word or text source of it exists, is copied by hand from its rendering,
  and its header says which (`; Transcribed: by hand from <url>`, after
  `; Link:`), so a reader knows no extractor vouches for the reading. The
  extractor's rule binds the copyist: a transcription records what the
  document prints, in the shapes the extractors give the same constructs
  ([extractor.md](extractor.md#transcriptions)), and goes through the
  extractor's pipeline — transcription → input patches → raw →
  corrections → corrected — so what the grammar cannot hold is an input
  patch and what the document prints wrong a correction, never a silent
  fix.
- **The parser is strict; the formatter defines canonical form.** Hand edits
  are normalised by the formatter (`seanchai format`), not by the parser
  guessing.
- **Round-trip is exact and idempotent**: `format_spec(parse(text)) == text`
  for every canonical file, which is what makes re-extraction diffs stable;
  with comments kept, every committed file is a fixed point of
  `seanchai format`.
- **A hand-authored file is a first-class input.** Someone with a proprietary
  extension or an uncovered specification can write a `.dad` file and have
  the parser, linter and consumers treat it like an extracted one. Beyond
  `seanchai format` nothing is built for that case yet, but a change that
  makes files easier to generate and harder to type is a change in the wrong
  direction.

## Comments

A `;;` comment is no data, but `seanchai format` keeps it, so where it
attaches is part of the format. Every line states one thing, named by its
`ast.TreePath`: a directive line the field it states (`("sections", 3,
"source", "page")` for a `; Page:`), a header rule its section
(`("sections", 3)`), a body line its AVP rule, enum value or table row. A
comment attaches to a line through that path:

- A **trailing** comment stays on its line.
- A **whole-line** comment stays before the next line of its block. After a
  block's last line it stays at the block's end: after the last rule, value
  or row of a section, after the last line of the file header.
- A **block of comments** — comment lines with a blank line on both sides,
  such as a note between two sections — stays a block of its own before the
  section that follows it, at the end of the file after the last section,
  or before the file header when it opens the file.

The formatter decides the rest. A whole-line comment is indented like the
body around it (eight spaces among enum values, none elsewhere), `;;` is
followed by one space, a comment block is spaced from its neighbours like a
section, and consecutive comment blocks merge into one. Every line the
parser accepts formats as exactly one line, in its block, so no comment can
lose its line to the formatter merging or splitting lines; a directive line
the formatter moves into canonical order takes its comments with it.

In the API, `parser.parse_with_comments(text)` returns the tree and a
`formatter.Comments` holding the three placements — `trailing`, `standing`
(whole lines before a line, or at a block's end) and `detached` (blocks of
their own) — each keyed by path; `formatter.format_spec(spec, comments)`
prints them back.

The notes the corrections layer prints ([corrections.md](corrections.md#output))
are comments placed by the same rules — a trailing note on the line an edit
reached, a deletion's note standing where the deleted line stood, a deleted
section's note as a block where the section stood — so a corrected file
formats to itself.

## AST

`src/seanchai/dad/ast.py` mirrors the file one-to-one in frozen pydantic
models. Its references are unresolved strings and it can represent a
specification that contradicts itself; the resolved, convenient view is
`seanchai.model` ([consumers.md](consumers.md)), built from it. Fields that
are optional because the *source documents* are inconsistent say so in their
docstrings (`Message.application_id`, `AvpTableRow.code`,
`AvpTableRow.section`). Unfinished corners are marked `TODO(format)`.

`dad/abnf.py` holds the semantics the parser and both extractors share:
bracket pair to presence, `min*max` to occurrence counts, Diameter-header
items, M/V flag cells. The dialects' regexes stay in their own modules; a
change to what the syntax *means* is one edit.
