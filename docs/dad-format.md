# The `.dad` format

A plain-text format that stays close to the ABNF in the source documents,
so a definition reads as a near-diff against the specification.
[grammar.md](grammar.md) states it formally; where the two disagree, the
grammar is the one to fix.

## Shape of a file

Blocks separated by blank lines: the file header, then one block per
section, each starting with `; Type:`.

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
| `Reprinted AVP`     | another document's grouped rule, as this one prints it           |
| `Enumerated AVP`    | the header rule plus values and value ranges, or their source    |
| `AVP Table`         | the document's own AVP table, one AVP per row                    |
| `Reused AVPs`       | AVPs defined elsewhere, mirroring "re-used Diameter AVPs" tables |
| `Registry`          | codes a registry allocates, each to the documents defining it    |
| `Undefined AVP`     | a name the document uses that the corpus finds defined nowhere   |
| `Value Table`       | the names a document gives a numeric AVP's numbers: result codes, bits of a bit mask, features of a feature list |

## Design

- **Directive comments are grammar.** A single `;` in a defined position is
  semantic (`; Key: value` headers, `; bold`, `; strikethrough`,
  `; RESERVED`, `; VOID`, `; VENDOR-SPECIFIC`); a malformed one is a parse
  error.
  Free-text comments use `;;` and carry no data. Where they attach is still
  defined ([Comments](#comments)), so normalising a file keeps them.
- **The file states its own vendor-id.** `; Vendor-ID:` is the vendor space
  the document's own AVPs live in. Nothing else in the file supplies it: a
  clause header omits the vendor both for a genuine IETF-space AVP and when
  the document forgot, and a table has a vendor column only where the
  document prints one.
- **A table printing each row's vendor keeps it.** oneM2M TS-0004 table
  A.4-1 tabulates IETF, 3GPP and oneM2M AVPs side by side, each with its
  "AVP Vendor Id". The `Vendor-ID` column holds it, and the row's identity
  is that vendor and its code.
- **The file states what it builds on.** `; Bases:` lists the documents
  whose AVPs the file uses without citing them (`Session-Id`, `Origin-Host`,
  `* [ AVP ]` from RFC 6733). Extractors stamp `RFC6733` for everything but
  RFC 6733 itself; a document building on more (RFC 4072 on NASREQ, TS
  29.215's S9 on all of TS 29.212) gets its entries from a correction.
- **An application id stated in prose is a statement of its own.** TS
  29.212 prints its Gx commands with bare `272, REQ, PXY` headers and says
  in clause 5.1 that Gx's id is 16777238. An `Application Scope` block
  records that, citing clause 5.1, and applies it to the commands of clause
  5 (`; Applies-To: 5.*`). The headers stay as printed.
- **`; bold` and `; strikethrough` stay inline**, mirroring the source,
  where bold marks AVPs the document defines or modifies. A strike means
  what its document says it means. TS 32.299's legend (clauses 6.2.1.2,
  6.4.1.2) reads it as "not used by 3GPP", so its struck members are
  commented out, marker kept, where they stood.
- **A rule's elision stays where it stood.** TS 29.273, RFC 5778 and RFC 6738
  print `…` or `...` on a line of its own where a rule leaves out what it does
  not change. It names no
  member, so it is a `;;` comment there, as printed; the rule holds the members
  it prints and no more ([extractor.md](extractor.md#the-3gpp-docx-extractor)).
- **A table declares its own columns.** `; Columns:` states which columns
  the source table had, in source order, so "the table had no such column"
  stays distinct from "the cell was empty". Only modelled columns are
  recorded; prose columns are dropped.
- **Where a row applies is the document's marks.** TS 29.212's "Acc. Type"
  and "Applicability", TS 29.061's "Applicable Reference Points" and TS
  32.299's per-command "Used in" columns are mark columns (`Acc-Type`,
  `Applicability`, `Reference-Points`, `ACR` to `CCA`; OMA-DDS-Charging_Data
  table 11's `SI`, `CCR-MSCC` and `CCA-MSCC` beside them). A cell lists the
  marks the document prints, comma-separated, uninterpreted, each with
  what the document prints beside it (`"All (NOTE 5)"`). A printed dash is
  `-` and a blank cell `""`, since TS 32.299 gives the dash a meaning and
  the blank none.
- **Table cells are single tokens**, `-` for empty. In a mark column a mark
  that is not a plain token is quoted as an enum value name is.
- **Enum value names keep the document's spelling.** Most are identifiers
  (`DELIVERY_REPORT`), but TS 32.299 labels values in words, so a name that
  is not an identifier is quoted (`"PS to CS Transfer"`), with `\"` and
  `\\` for a double quote and a backslash inside.
- **A numeric AVP's named numbers are a table of their own.** A result code is
  a subclause heading (TS 29.229's `6.2.2.1 DIAMETER_ERROR_USER_UNKNOWN (5001)`)
  or a paragraph (RFC 6733's `DIAMETER_SUCCESS 2001`), a bit a row of a "Bit |
  Name | Description" table under an Unsigned32 clause, a feature a row of a
  "Feature bit | Feature | M/O | Description" table. None is an `Enumerated`, so
  one `Value Table` holds them: `; Kind:` says which, and each row is a name and
  a number, with a result code's own clause or a feature's M/O after it. The
  description is prose and is dropped. A plain Result-Code value is the IETF's;
  an experimental one lives in the file's `; Vendor-ID:`.
- **An enumeration defined elsewhere says where.** A clause that gives its
  values by reference (TS 29.272's `Trace-Depth`, "those defined in TS
  32.422 [23] for Trace Depth") prints `; Values:` with that citation. A
  corrected file keeps the citation and lists the cited document's values
  under it, each marked `;; supplied:`. Three stay citations alone, since
  their sources hold no flat list: TS 29.272's `Report-Interval`, RFC
  5777's `ICMP-Code` and TS 32.299's `API-Network-Service-Node`.
- **A range left to vendors is no reserved range.** TS 32.299's
  SM-Service-Type closes with "11 .. 99 Reserved for 3GPP defined SM
  services" and "100 .. 199 Vendor specific SM services". The first is
  `; RESERVED = 11-99`, a value no dictionary may assign; the second is
  `; VENDOR-SPECIFIC = 100-199 ; Vendor specific SM services`, values any
  dictionary may assign under a name of its own.
- **A withdrawn value is no reserved value.** TS 29.214's Specific-Action prints
  `Void (0)` and `Void (5)`: values the document once assigned and has
  withdrawn. They are `; VOID = 0` and `; VOID = 5`, which no dictionary may
  assign, distinct from `; RESERVED`, which was never assigned, and neither is a
  value named `Void`: the word replaces a label, it is none.
- **A registry allocates; it defines nothing.** TS 29.230 assigns each AVP
  code, command code and application id to the document defining it, so
  its tables are `Registry` blocks: a row is a code, the name the registry
  gives it and the documents it cites, and a reserved range is a
  `; RESERVED` line with the documents its note names and its purpose
  quoted as printed. Read as AVP definitions, the registry would become a
  second definer of every 3GPP AVP.
- **A copy names what it copies.** TS 29.109 follows MAR, BIR and GPR with "The
  content of Vendor-Specific-Application-ID according IETF RFC 6733 [33] is:"
  and that rule, glossing what its members hold there (`; 3GPP is 10415`,
  `; Omitted`). Each copy is a `Reprinted AVP` block with its clause, page and
  `; From: RFC6733`, its glosses `;;` comments on its members. It is no
  definition, which its type states: a reader of `Grouped AVP` blocks never
  meets it, the document defining the AVP is still the only one answering for
  it, and the three copies are no duplicates. A clause printing its own body
  for an AVP it re-uses, with no sentence saying it copies, stays a `Grouped
  AVP`, since that is a claim the linter weighs.
- **A name defined nowhere says so.** RFC 4004 clause 9.4 makes
  `MIP-HA-to-MN-SPI` a required member of `MIP-HA-to-MN-MSA`, and neither
  the RFC, its errata nor IANA gives it a code or a clause. An `Undefined
  AVP` block names each such name, cites the clause using it and keeps what
  the document says of it. Only a correction writes the block, citing what
  was searched (later versions, errata, the registry, Wireshark's
  dictionary); no extractor does. The block declares no type, code or
  flags: what a consumer does about the name is the consumer's choice
  ([consumers.md](consumers.md#undefined-names)).
- **What the corpus cannot complete is recorded beside it.** No `.dad`
  file says a name is a known hole, since a hole is the corpus's reading of
  several files together. The corpus's `holes.toml` lists each with its evidence
  ([consumers.md](consumers.md#known-holes)).
- **A file says less than its document only by a declared exclusion.** It is
  the only way to, always with a reason: a `[[exclude]]` in
  `edits/sources/<SpecRef>.toml` names a clause the document has not finished,
  which neither file holds, and both print a comment block after the header
  saying so, `;; excluded: clause 8 (Sh-ee), see TS29.329.toml`
  ([extractor.md](extractor.md#exclusions)).
- **Reused AVPs are listed by name.** Resolving a row against the origin's
  file yields the `(vendor-id, code)` that is the real identity.
- **An origin names its publisher, unless it is 3GPP or IETF.** Their
  documents are bare numbers (`TS29.272`, `RFC6733`); anything else leads
  with its publisher and keeps the publisher's numbering (`ETSI-TS283.034`,
  `ETSI-TS183.059-1`, `3GPP2-X.S0057`, `3GPP2-X.S0013-014`,
  `OMA-DDS-Charging_Data`, `oneM2M-TS-0004`).
- **A transcription says so.** A document no extractor reads is copied by
  hand from its rendering, and its header says which
  (`; Transcribed: by hand from <url>`). A transcription records what the
  document prints, in the shapes the extractors give the same constructs,
  and goes through the same pipeline: what the grammar cannot hold is an
  input patch and what the document prints wrong is a correction
  ([extractor.md](extractor.md#transcriptions)).
- **The parser is strict; the formatter defines canonical form.** Hand
  edits are normalised by `seanchai format`, not by the parser guessing.
- **Round-trip is exact and idempotent.** Parsing a canonical file with
  its comments and formatting it back gives the same text, which keeps
  re-extraction diffs stable. Every committed file is a fixed point of
  `seanchai format`.
- **A hand-authored file is a first-class input.** Someone with a
  proprietary extension can write a `.dad` file and have the parser, linter
  and consumers treat it like an extracted one.

## Comments

A `;;` comment is no data, but `seanchai format` keeps it, so where it
attaches is part of the format. Every line states one thing, named by its
`ast.TreePath`, and a comment attaches to a line through that path:

- A **trailing** comment stays on its line.
- A **whole-line** comment stays before the next line of its block, or at
  the block's end after its last line.
- A **block of comments**, comment lines with a blank line on both sides,
  stays a block of its own before the section that follows it, at the end
  of the file after the last section, or before the file header.

The formatter decides the rest: a whole-line comment is indented like the
body around it, `;;` is followed by one space, a comment block is spaced
like a section, and consecutive comment blocks merge. Every line the parser
accepts formats as exactly one line, so no comment can lose its line.

In the API, `parser.parse_with_comments(text)` returns the tree and a
`formatter.Comments` holding the three placements (`trailing`, `standing`,
`detached`), each keyed by path, and `formatter.format_spec(spec, comments)`
prints them back. The notes the corrections layer prints
([corrections.md](corrections.md#output)) are comments placed by the same
rules, so a corrected file formats to itself.

## AST

`src/seanchai/dad/ast.py` mirrors the file one-to-one in frozen pydantic
models. Its references are unresolved strings and it can represent a
document that contradicts itself; the resolved view is `seanchai.model`
([consumers.md](consumers.md)). Fields that are optional because the source
documents are inconsistent say so in their docstrings
(`Message.application_id`, `AvpTableRow.code`, `AvpTableRow.section`).

`dad/abnf.py` holds the semantics the parser and both extractors share:
bracket pair to presence, `min*max` to occurrence counts, Diameter-header
items, flag cells.

## The corpus

The corpus is the data of the `seanchai-corpus` package, at
`packages/seanchai-corpus/src/seanchai_corpus/dad/` in the repository:

```
dad/
  3gpp/rel-19/   one directory per 3GPP release; rel-6, rel-7 and rel-11
                 hold the older versions citing documents mean
  rfc/           RFCs have no release axis
  etsi/          ETSI documents transcribed by hand; versions are ETSI's
  3gpp2/         3GPP2 documents transcribed by hand
  oma/           OMA documents transcribed by hand
  onem2m/        oneM2M documents
  raw/           unedited extractor output, mirroring the trees above
  holes.toml     the record of known holes, hand-maintained
  corrections.json  each correction's reason, written by `seanchai regenerate`
```

The corrected trees are what tools and consumers read. `raw/` mirrors them
file for file and exists for diffing and rot-checking: a version upgrade can
diff raw against raw with the correction layer held still, corrections can
be re-checked without re-downloading, and the linter has something to fire
on.

Files are named as their publisher names them: `29272-j60` for TS 29.272
V19.6.0 (3GPP's archive naming), `rfc6733` for an RFC, `es283034-020200`
for ETSI ES 283 034 V2.2.0, `xs0057-0_v2.0` for 3GPP2 X.S0057 revision 0
V2.0, `xs0013-014-0_v1.0` for part 014 of its series, `ts-0004-v2_35_0` for
oneM2M TS-0004 V2.35.0, `dds-charging_data-v1_0-20110201-a` for
OMA-DDS-Charging_Data V1.0, approved 1 February 2011. RFC files carry no
`; Version:` header, since an RFC number names one immutable document.

Each document is committed twice:

- `29272-j60.dad`, the **corrected** file, the one to use.
- `raw/3gpp/rel-19/29272-j60.raw.dad`, what the document said, mistakes
  included. The `.raw.dad` suffix is what the corpus loader and tests key
  on.

Every line a correction touched carries a `;;` note citing the declaration
by module and id. A document with no corrections still gets both files,
byte-identical. Nothing here is edited by hand: `seanchai regenerate`
rebuilds the whole tree
([development.md](development.md#rebuilding-the-corpus)).
