# The `.dad` format

A plain-text format that stays as close as possible to the ABNF found in the
source documents, so a definition can be reviewed as a near-diff against the
spec. `examples/ts_129329v180000p.dad` is the hand-made reference file, based on
3GPP TS 29.329.

This document describes the format as it exists, and
[grammar.md](grammar.md) states it formally. Where the two disagree, the
grammar is the one to fix.

The format is **not stable and carries no compatibility promise** until the
project is finished and published. Change it whenever the work in hand needs
it, including in ways that invalidate every committed `.dad` file: those files
are extractor output, regenerated from the sources, and the hand-made reference
is a single file to re-edit. Weighing a format change against imagined existing
users is weighing it against nobody. The design intent below is what to
preserve; the spelling is not.

## Shape of a file

A file is a sequence of blocks separated by blank lines: the file header first,
then one block per section. Each section block starts with a `; Type: X`
directive.

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

## Section kinds

| `; Type:`        | Holds                                                            |
|------------------|------------------------------------------------------------------|
| `Message`        | a command-code ABNF rule with its Diameter header                |
| `Grouped AVP`    | `Name ::= < AVP header: code vendor-id >` plus its body          |
| `Enumerated AVP` | the header rule plus named values and reserved ranges            |
| `AVP Table`      | the spec's own AVP table, one AVP per row                        |
| `Reused AVPs`    | AVPs defined elsewhere, mirroring "re-used Diameter AVPs" tables |

Messages and grouped AVPs keep the spec's ABNF syntax verbatim: `<>`/`{}`/`[]`
qualifiers, `*` repetition, `::=`, `< Diameter Header: … >`. The two extensions
the raw ABNF lacks are enumerated AVPs with their named values, and the AVP
tables.

## Design intent

These are the decisions the format rests on. Preserve them when changing it.

- **Directive comments are grammar, not prose.** Lines and suffixes starting
  with a single `;` in defined positions are semantic, JSDoc-style: `; Key:
  value` header blocks above each definition (type, name, section, page) and at
  the top of the file (specification, version, link), plus inline markers such
  as `; bold`. A malformed directive is a parse error, never silently degraded
  to a comment. Free-text comments use `;;` and are discarded by the parser.
- **The file states its own vendor-id.** `; Vendor-ID:` is the vendor space this
  document's AVPs are defined in, and it has to be stated because nothing else
  in the file does: AVP tables have no vendor column, and a clause header omits
  the vendor both for a genuinely IETF-space AVP and when the document forgot.
  TS 29.229 gives code 621 to `Primary-Charging-Collection-Function-Name` while
  RFC 7683 gives 621 to `OC-Supported-Features`, and 29.229's table lists both.

  Extractors state it rather than deriving it: 3GPP documents are 10415, RFCs
  are 0. A hand-authored file states its own, which is the whole mechanism a
  vendor extension needs — nothing else has to learn about that vendor.
- **The file states what it builds on.** `; Bases:` is the comma-separated
  list of documents whose AVPs the file uses without citing them anywhere —
  RFC 6733's `Session-Id`, `Origin-Host` and the trailing `* [ AVP ]` appear
  in every Diameter application's ABNF and in no re-used table. Extractors
  stamp `RFC6733` for everything except RFC 6733 itself, so the line is
  optional rather than fabricated at the base of the tree; reference
  resolution reads it the way re-used rows' origins are read. A document
  that builds on more than the base protocol — RFC 4072's ABNFs use NASREQ's
  AVPs the way every ABNF uses `Session-Id` — gets its further entries from
  a `bases` correction targeting the file header, since the source text
  states the dependency nowhere an extractor can read. A hand-authored
  extension can state a different base, which is the same mechanism
  `; Vendor-ID:` gives vendors.
- **`; bold` stays inline** because it mirrors the source document: bold in
  3GPP ABNF marks AVPs defined or modified in that spec.
- **Table cells are single whitespace-separated tokens**, with `-` as the empty
  placeholder.
- **A table declares its own columns.** `; Columns:` is a directive, not a
  cosmetic label line, and it states which columns the source table had, in the
  source table's order. Tables do not all have the same ones: TS 29.273's AVP
  table has no Encrypt column, RFC 6733 §4.5 has neither MAY nor SHOULD NOT nor
  Encrypt, and TS 29.128, 29.173 and 29.336 print re-used tables with no M-bit
  column. Declaring them is what keeps "the table had no such column" distinct
  from "the cell was empty", which were the same `False` before.

- **Only modelled columns are recorded; the rest are dropped.** Every source
  column without a modelled counterpart so far has been prose — "Comments",
  "Description", "Comment" — holding a sentence or a whole paragraph about how
  an AVP is used. `.dad` carries definitions, not narrative, and `; Section:`
  already points at the clause that holds the prose undamaged, so quoting it
  into a table cell bought nothing a reader could not get better from the
  specification. That was tried and removed.

  This is a statement about what has turned up, not a rule that unmodelled
  means unimportant. A source column carrying *machine-readable* values is a
  reason to add a modelled column for it, named, with a cell grammar of its
  own. TS 29.212's "Acc. Type" (`3GPP-EPS`, `3GPP-GPRS`, `All`) and
  "Applicability" (`CC`/`PC`/`Both` plus feature names) are the standing
  candidates, and TS 29.172's re-used table prints AVP Code and Value Type
  columns. The extractor warns about every unmodelled column that is not one of
  the known prose labels, which is how such a case gets noticed rather than
  quietly lost.
- **Reused AVPs are listed by name.** Names are unique within one
  specification's scope; resolving a row against the origin spec's `.dad`
  yields the AVP's `(vendor-id, code)` — the true identity key, which
  disambiguates AVPs sharing a name across specs.
- **The parser is strict and the formatter defines canonical form.** An earlier
  design note called for a lenient parser; that idea was dropped. Hand edits are
  normalised by running the formatter, not by the parser guessing intent.
  Strictness is what keeps re-extraction diffs meaningful.
- **A hand-authored file is a first-class input.** The format is written as
  well as read: someone with a proprietary Diameter extension, or a
  specification Seanchaí has no extractor for, should be able to write a `.dad`
  file directly and have the parser, linter and consumers treat it like an
  extracted one. Nothing is being built for that case yet — 3GPP and RFC
  sources come first — but it is why the format has to stay writable by hand,
  which in turn is why it looks like the source ABNF instead of like a
  serialisation format. A change that makes files easier to generate and harder
  to type is a change in the wrong direction.
- **Round-trip is exact and idempotent.** `format_spec(parse(text)) == text` for
  every canonical file, which is what makes the patch-based review workflow
  produce stable diffs across extractor re-runs.

## AST and shared semantics

`src/seanchai/dad/ast.py` mirrors the file structure one-to-one. All nodes are
frozen pydantic models: extractor output and hand patches are exactly the kind
of data worth validating eagerly, and `model_dump_json()` gives downstream
generator and validator scripts a serialized form for free.

The AST is not the type a schema generator should ultimately want to consume,
and it should not be bent into one. Its references are unresolved strings
because that is what the file holds, and it has to be able to represent a
specification that contradicts itself. The resolved, cross-referenced view with
convenience methods is a separate consumer model built *from* the AST — see
[roadmap.md](roadmap.md). Requests to make these nodes friendlier to generators
usually belong to that layer instead.

Fields that are optional because the *source documents* are inconsistent are
marked as such in the model docstrings — `Message.application_id` (some TS
29.272 headers omit it), `AvpTableRow.code` (definition deferred to another
spec), `AvpTableRow.section` (no local clause).

Corners of the format that are not final are marked `TODO(format)` in the AST.

`dad/abnf.py` holds the semantics that both the parser and the source
extractors need: which bracket pair is which presence, how `min*max` maps to
occurrence counts, how Diameter-header items split into command code, flags and
application id, and how M/V flag cells are spelled. The two read different
*dialects* — canonical `.dad` text versus whatever Word produced — so their
regexes stay in their own modules, but a change to what the syntax means is one
edit, and `tests/test_abnf.py` pins the dialects to the same result.
