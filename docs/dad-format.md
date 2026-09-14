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

| `; Type:`        | Holds                                                            |
|------------------|------------------------------------------------------------------|
| `Message`        | a command-code ABNF rule with its Diameter header                |
| `Grouped AVP`    | `Name ::= < AVP header: code vendor-id >` plus its body          |
| `Enumerated AVP` | the header rule plus named values and reserved ranges            |
| `AVP Table`      | the spec's own AVP table, one AVP per row                        |
| `Reused AVPs`    | AVPs defined elsewhere, mirroring "re-used Diameter AVPs" tables |

## Design intent

- **Directive comments are grammar.** A single `;` in a defined position is
  semantic (`; Key: value` headers, `; bold`, `; RESERVED`); a malformed one
  is a parse error. Free-text comments use `;;` and are discarded on parse.
- **The file states its own vendor-id.** `; Vendor-ID:` is the vendor space
  the document's own AVPs are defined in, and nothing else in the file
  supplies it: tables have no vendor column, and a clause header omits the
  vendor both for a genuine IETF-space AVP and when the document forgot. A
  hand-authored vendor extension states its own, and nothing else needs to
  learn about that vendor.
- **The file states what it builds on.** `; Bases:` lists the documents
  whose AVPs the file uses without citing them (`Session-Id`, `Origin-Host`,
  `* [ AVP ]` from RFC 6733). Extractors stamp `RFC6733` for everything but
  RFC 6733 itself; a document building on more (RFC 4072 on NASREQ) gets its
  entries from a `bases` correction.
- **`; bold` stays inline**, mirroring the source, where bold marks AVPs the
  specification defines or modifies.
- **A table declares its own columns.** `; Columns:` states which columns the
  source table had, in source order, so "the table had no such column" stays
  distinct from "the cell was empty". Only modelled columns are recorded;
  unmodelled prose columns are dropped, and an unmodelled machine-readable
  column is a reason to model it, not to carry it anonymously.
- **Table cells are single tokens**, `-` for empty.
- **Reused AVPs are listed by name.** Resolving a row against the origin's
  file yields the `(vendor-id, code)` that is the real identity.
- **The parser is strict; the formatter defines canonical form.** Hand edits
  are normalised by the formatter, not by the parser guessing.
- **Round-trip is exact and idempotent**: `format_spec(parse(text)) == text`
  for every canonical file, which is what makes re-extraction diffs stable.
- **A hand-authored file is a first-class input.** Someone with a proprietary
  extension or an uncovered specification can write a `.dad` file and have
  the parser, linter and consumers treat it like an extracted one. Nothing is
  built for that case yet, but a change that makes files easier to generate
  and harder to type is a change in the wrong direction.

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
