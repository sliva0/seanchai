# The `.dad` format

A `.dad` file records the Diameter definitions of one document version in
plain text close to the document's own ABNF, so a file reads as a near-diff
against the specification. This page describes the format's principles, the
comment rules, the AST and the corpus layout.
[grammar.md](grammar.md) defines each block precisely; where the two
disagree, fix the grammar.

## Shape of a file

A file is a header block followed by one block per section, separated by
blank lines. Each section starts with `; Type:`.

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
| `Answer Message`    | the format an answer with the E bit set takes (RFC 6733 7.2)     |
| `Grouped AVP`       | `Name ::= < AVP header: code vendor-id >` plus its body          |
| `Reprinted AVP`     | another document's grouped rule, as this one prints it           |
| `Enumerated AVP`    | the header rule plus values and value ranges, or their source    |
| `AVP Table`         | the document's own AVP table, one AVP per row                    |
| `Reused AVPs`       | AVPs defined elsewhere, mirroring "re-used Diameter AVPs" tables |
| `Registry`          | codes a registry allocates, each to the documents defining it    |
| `Undefined AVP`     | a name the document uses that the corpus finds defined nowhere   |
| `Value Table`       | the names a document gives a numeric AVP's numbers: result codes, bits of a bit mask, features of a feature list |

## Design

- A file records everything the document states about its definitions, as
  printed. Fixes go in the declared edit layers
  ([corrections.md](corrections.md)), and the unedited reading is kept as the
  raw file.
- A file leaves out part of its document only through a declared
  `[[exclude]]`, which both files announce in a comment block after the
  header: `;; excluded: clause 8 (Sh-ee), see TS29.329.toml`
  ([extractor.md](extractor.md#exclusions)).
- A single `;` in a defined position is a directive and part of the grammar
  (`; Key: value`, `; bold`, `; strikethrough`, `; RESERVED`, `; VOID`,
  `; VENDOR-SPECIFIC`). A malformed one is a parse error. Free text uses `;;`
  and carries no data.
- `; Vendor-ID:` states the vendor space of the document's own AVPs. Nothing
  else supplies it: a clause header omits the vendor both for an IETF AVP and
  when the document forgot it.
- `; Bases:` lists the documents whose AVPs the file uses without citing
  them, such as `Session-Id` from RFC 6733. Extractors write `RFC6733` for
  every document but RFC 6733; further bases (RFC 4072 on NASREQ) come from a
  correction.
- Re-used AVPs are listed by name. Resolving the row against the origin's
  file gives the real identity, `(vendor-id, code)`. A result code whose
  clause says another document defines it names that document the same way,
  and that document answers for it.
- A name defined nowhere gets an `Undefined AVP` block; a name the corpus
  cannot complete is recorded in `holes.toml`, since that is a reading of
  several files together ([consumers.md](consumers.md#known-holes)).
- The parser is strict; `seanchai format` defines the canonical form.
  Parsing a canonical file with its comments and formatting it back gives the
  same text, and every committed file is a fixed point of `seanchai format`.
- A hand-written file, for a proprietary extension say, is read by the
  parser, linter and model like an extracted one.
- A new column, `; Type:` or directive key is a format change. It needs a
  source document that cannot otherwise be recorded; consumer convenience
  belongs in the model.

## Comments

`seanchai format` keeps `;;` comments, so where a comment attaches is part of
the format. Every line is named by an `ast.TreePath`, and a comment attaches
to a line through that path:

- A trailing comment stays on its line.
- A whole-line comment stays before the next line of its block, or at the
  block's end after its last line.
- A comment block, comment lines with a blank line on both sides, stays
  before the section that follows it, at the end of the file after the last
  section, or before the file header.

The formatter indents a whole-line comment like the body around it, puts one
space after `;;`, spaces a comment block like a section and merges
consecutive comment blocks. Every line the parser accepts formats as exactly
one line, so no comment loses its line.

`parser.parse_with_comments(text)` returns the tree and a
`formatter.Comments` holding the three placements (`trailing`, `standing`,
`detached`), each keyed by path. `formatter.format_spec(spec, comments)`
prints them back. The notes the corrections layer writes
([corrections.md](corrections.md#output)) follow the same rules.

## AST

`src/seanchai/dad/ast.py` mirrors the file one-to-one in frozen pydantic
models. References are unresolved strings, and a self-contradicting document
is representable; the resolved view is `seanchai.model`
([consumers.md](consumers.md)). Fields that are optional because documents
are inconsistent say so in their docstrings (`Message.application_id`,
`AvpTableRow.code`, `AvpTableRow.section`).

`dad/abnf.py` holds what the parser and the extractors share: bracket pair
to presence, `min*max` to occurrence counts, Diameter-header items and flag
cells.

## The corpus

The corpus is the data of the `seanchai-corpus` package, at
`packages/seanchai-corpus/src/seanchai_corpus/dad/`:

| Path | Holds |
|---|---|
| `3gpp/rel-19/` | one directory per 3GPP release; `rel-6`, `rel-7` and `rel-11` hold older versions that citing documents mean |
| `rfc/` | RFCs, which have no release |
| `etsi/`, `3gpp2/`, `oma/` | documents transcribed by hand |
| `onem2m/` | oneM2M documents |
| `raw/` | unedited output, mirroring the trees above |
| `corpus.toml` | the format and resolution rules, edited by hand |
| `holes.toml` | the record of known holes, edited by hand |
| `corrections.json` | the corrections record, written by `seanchai corpus regenerate` |

Each document is committed twice:

- `29272-j60.dad`, the corrected file, which tools and consumers read;
- `raw/3gpp/rel-19/29272-j60.raw.dad`, what the document says, mistakes
  included. The loader and tests key on the `.raw.dad` suffix.

The raw mirror lets a version upgrade diff raw against raw, lets corrections
be re-checked without downloading, and gives the linter the documents' own
errors to fire on. A document without corrections has two identical files.
Every line a correction touched carries a `;;` note citing it.

Files are named as their publishers name them:

| File | Document |
|---|---|
| `29272-j60` | TS 29.272 V19.6.0 (3GPP's archive naming) |
| `rfc6733` | RFC 6733 |
| `es283034-020200` | ETSI ES 283 034 V2.2.0 |
| `xs0057-0_v2.0` | 3GPP2 X.S0057 revision 0 V2.0 |
| `xs0013-014-0_v1.0` | part 014 of 3GPP2 X.S0013 |
| `ts-0004-v2_35_0` | oneM2M TS-0004 V2.35.0 |
| `dds-charging_data-v1_0-20110201-a` | OMA-DDS-Charging_Data V1.0, approved 1 February 2011 |

Nothing here is edited by hand except `corpus.toml` and `holes.toml`;
`seanchai corpus regenerate` rebuilds the rest
([development.md](development.md#rebuilding-the-corpus)).
