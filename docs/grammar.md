# The `.dad` grammar

A formal statement of the format. [dad-format.md](dad-format.md) explains what
the pieces are for and why they are shaped this way; this document says only
what is and is not a well-formed file, in enough detail to write a second
implementation without reading `src/seanchai/dad/parser.py`.

> **The grammar is not stable yet.** Until the project is finished and
> published, any part of it may change whenever the work in hand needs it —
> including in ways that invalidate every existing `.dad` file. There is no
> deprecation path, no format version and no compatibility promise, because
> there is nothing published to be compatible with. Committed files are
> regenerated when the format moves, which is exactly why the extractor and the
> formatter are the only things that produce them. Write tooling against this
> document by all means, but expect to follow it. A stable grammar is something
> to declare on publication, not before.

Two things this grammar deliberately does not cover, because they are not
syntax:

- **Semantic constraints carried by the AST.** A file can be grammatically
  perfect and still be rejected — an inverted `RESERVED` range, a flag in two
  flag columns at once, a row with a value under a column the table does not
  declare. These are listed under [Semantic constraints](#semantic-constraints)
  rather than encoded in the productions, because writing them into the grammar
  would make it unreadable without making it more precise.
- **Canonical layout.** Alignment, column widths and blank-line counts are the
  formatter's business ([formatter.py](../src/seanchai/dad/formatter.py)). The
  grammar accepts any spacing the productions allow; the formatter produces
  exactly one spelling of it. A file that parses is valid, but only a file the
  formatter would have written is canonical, and the review workflow assumes
  canonical files.

## Notation

ABNF as in RFC 5234, with `%x` for literal code points. Two conventions:

- `SP` is a single space (`%x20`), `NL` a single line feed (`%x0A`). The format
  is line-oriented and has no other whitespace: no tabs, no carriage returns,
  and no trailing spaces on any line.
- Productions ending in `-text` are free text with a shape constraint stated
  next to them, not full character classes.

## File

```abnf
file          = header 2*NL section *(2*NL section) NL
header        = spec-line NL [version-line NL] vendor-line [NL bases-line]
                [NL link-line]
spec-line     = "; Specification: " inline-text
version-line  = "; Version: " version
vendor-line   = "; Vendor-ID: " 1*DIGIT    ; < 2^32; 0 is the IETF space
bases-line    = "; Bases: " spec-ref *(", " spec-ref)
spec-ref      = ("TS" 2DIGIT "." 3DIGIT) / ("RFC" 1*DIGIT)   ; "RFC6733"
link-line     = "; Link: " URI          ; RFC 3986, must parse as an http(s) URL
version       = 1*DIGIT *("." 1*DIGIT)  ; "18.6.0"

section       = message / grouped-avp / enumerated-avp / avp-table / reused-avps
```

`; Vendor-ID:` is the vendor-id this document's own AVPs are defined in, and it
is required because nothing else in the file supplies it: AVP tables have no
vendor column, and a clause header omits the vendor both for a genuinely
IETF-space AVP and when the document forgot. An AVP the file merely re-uses
belongs to the origin's vendor space, which is that document's `; Vendor-ID:` to
state.

`; Version:` is present when the source document has a version axis, which a
3GPP specification does and an RFC does not: an RFC number names one immutable
document, so an RFC `.dad` carries no version line rather than a fabricated
one.

`; Bases:` names the documents this one builds on without citing them
anywhere — the base-protocol AVPs (`Session-Id`, `Origin-Host`, the trailing
`* [ AVP ]`) appear in every Diameter application's ABNF and in no re-used
table, because every application is assumed to have them. Entries use the same
single-token spelling re-used rows cite origins by. Extractors write
`; Bases: RFC6733` for every document except RFC 6733 itself, which is why the
line is optional: the base of the tree has nothing to put in it.

A file is a header block followed by one or more section blocks. Blocks are
separated by blank lines; a block is a run of consecutive non-blank lines. The
file ends with exactly one newline.

Free-text comments begin with `;;` and may appear anywhere: standing alone as
a whole line, or ending one — everything from the first `;;` on a line to the
end of the line is comment. They are discarded on parse and never written
back, so they do not survive a round-trip and must not carry meaning.

```abnf
comment       = ";;" *(%x20-10FFFF)
; a comment fills the rest of any line, or a whole line of its own
```

Two consequences keep this unambiguous. A line left empty by removing its
comment is skipped entirely — it does not separate blocks the way a genuinely
blank line does. And no inline value may contain `;;`: the AST rejects it,
because a value the formatter wrote out would come back different.

Anything else beginning with a single `;` in a defined position is a
**directive**, and directives are grammar: a malformed one is an error, never
degraded to a comment.

```abnf
directive     = "; " key ": " value NL
key           = ALPHA *(ALPHA / "-")
```

Within one block, a directive key may appear at most once, and all directives
precede the block's body lines. Their *order* is not significant — the parser
accepts a block's directives in any order — but the productions below are
written in the order the formatter emits, and only that order is canonical.

## Sections

Every section block opens with `; Type:`, which selects the production. The
`; Name:`, `; Section:`, `; Page:` directives are the block's own header;
`; Page:` is optional everywhere it appears and counts printed pages of the
ETSI PDF rendering from 1.

```abnf
source-ref    = "; Section: " section-number NL ["; Page: " 1*DIGIT NL]
section-number = 1*DIGIT *("." 1*DIGIT *(%x41-5A))   ; "6.3", "6.3.7A"
avp-name      = (ALPHA / DIGIT) *(ALPHA / DIGIT / "-" / "_")
```

The underscore is a source-fidelity extension to RFC 6733's `name-fmt`.
TS 29.109 consistently names `GBA_U-Awareness-Indicator` with one in its
heading, ABNF, AVP table and defining prose, so excluding it would make the
format unable to record a published AVP name.

### Message

```abnf
message       = "; Type: Message" NL
                "; Name: " avp-name ", " abbreviation NL
                source-ref
                message-rule NL
                *(avp-rule NL)
abbreviation  = 2*5(%x41-5A)
message-rule  = "<" avp-name "> ::= < Diameter Header: " header-items " >"
header-items  = command-code *(", " command-flag) [", " application-id]
command-code  = 1*DIGIT                 ; < 2^24
command-flag  = "REQ" / "PXY" / "ERR"
application-id = 1*DIGIT                ; < 2^32
```

The name in `; Name:` must equal the name in the rule. Command flags appear in
the order above, each at most once. The application id is optional *only*
because some source documents omit it (TS 29.272's VCSG commands print
`< Diameter Header: 8388638, REQ, PXY, >`).

### Grouped AVP

```abnf
grouped-avp   = "; Type: Grouped AVP" NL
                "; Name: " avp-name NL
                source-ref
                avp-header-rule NL
                *(avp-rule NL)
avp-header-rule = avp-name " ::= < AVP header: " code [SP vendor-id] " >"
code          = 1*DIGIT                 ; < 2^32
vendor-id     = 1*DIGIT                 ; < 2^32; absent for IETF-space AVPs
```

### AVP rule

The body line shared by messages and grouped AVPs.

```abnf
avp-rule      = *SP [occurrences *SP] bracket-open SP avp-name SP bracket-close
                [*SP "; bold"]
occurrences   = [1*DIGIT] "*" [1*DIGIT]
bracket-open  = "<" / "{" / "["
bracket-close = ">" / "}" / "]"
```

Brackets must match as a pair, and the pair carries the presence: `<>` fixed,
`{}` required, `[]` optional. An absent `occurrences` means exactly once; a
bare `*` means zero-or-more. `; bold` mirrors the source document, where bold
marks AVPs the specification defines or modifies.

### Enumerated AVP

```abnf
enumerated-avp = "; Type: Enumerated AVP" NL
                 "; Name: " avp-name NL
                 source-ref
                 enum-header-rule NL
                 *((enum-value / reserved) NL)
enum-header-rule = avp-name " ::= < Enumerated AVP header: " code
                   [SP vendor-id] " >"
enum-value    = *SP enum-name *SP "= " 1*DIGIT [1*SP "; " inline-text]
enum-name     = (ALPHA / DIGIT) *(ALPHA / DIGIT / "-" / "_")
reserved      = *SP "; RESERVED" *SP "= " 1*DIGIT ["-" 1*DIGIT]
```

`; RESERVED` is an inline directive rather than a block header, so it is the one
`; Key:` line that may appear in a body. A value the specification reserves is
distinct from one it merely leaves unassigned: a validator must reject a
dictionary that assigns a reserved value.

### AVP table

```abnf
avp-table     = "; Type: AVP Table" NL
                "; Section: " section-number NL
                ["; Table: " inline-text NL]
                ["; Page: " 1*DIGIT NL]
                "; Columns: " *SP columns NL
                1*(table-row NL)
columns       = column *(1*SP column)
column        = "Name" / "Code" / "Section" / "Type"
              / "Must" / "May" / "S.not" / "M.not" / "Encrypt"
table-row     = cell *(1*SP cell)
cell          = 1*(%x21-10FFFF)
```

`; Columns:` states which columns the source table had, in the source table's
order, and a row has exactly one cell per declared column, positionally
matched. A column the table does not declare is a column the source table did
not have, which is not the same as one whose cell is empty.

`; Table:` is present when the source table prints a label. RFC 6733 §4.5
introduces its table with prose and no "Table N" caption, so an RFC AVP table
has no label to record.

Only columns this format models can be named. A source column with no modelled
counterpart is dropped by the extractor rather than carried under its own
label — see [extractor.md](extractor.md#columns-the-format-does-not-model) for
which ones and why.

The cell vocabulary depends on the column:

```abnf
name-cell     = avp-name
code-cell     = 1*DIGIT / "-"
section-cell  = section-number / "-"
type-cell     = data-type / "-"
flags-cell    = avp-flag *("," [SP] avp-flag) / "-"
avp-flag      = "M" / "V" / "P"   ; P is RFC 3588's deprecated protected bit
encrypt-cell  = "Yes" / "No" / "-"
data-type     = "OctetString" / "Integer32" / "Integer64" / "Unsigned32"
              / "Unsigned64" / "Float32" / "Float64" / "Grouped"
              / "Address" / "Time" / "UTF8String" / "DiameterIdentity"
              / "DiameterURI" / "Enumerated" / "IPFilterRule"
```

`-` is the canonical empty cell for every column that permits one.
`data-type` is closed: the basic formats of RFC 6733 §4.2 and the common
derived formats of §4.3.1, and nothing else.

### Re-used AVPs

```abnf
reused-avps   = "; Type: Reused AVPs" NL
                "; Section: " section-number NL
                "; Table: " inline-text NL
                ["; Page: " 1*DIGIT NL]
                "; Columns: " *SP reused-columns NL
                1*(table-row NL)
reused-columns = reused-column *(1*SP reused-column)
reused-column = "Name" / "From" / "M-bit"
spec-ref      = ("TS" 2DIGIT "." 3DIGIT) / ("RFC" 1*DIGIT)
m-bit         = "MUST" / "MUST-NOT" / "-"
```

Rows follow the same `table-row` production as an AVP table's, with the cell
vocabulary selected by column: `avp-name` under Name, `spec-ref` under From,
`m-bit` under M-bit. Name and From are required; M-bit is not, because
TS 29.128, 29.173 and 29.336 print no such column.

## Text values

```abnf
inline-text   = VCHAR *(%x20-10FFFF) VCHAR / VCHAR
```

A single-line value that begins and ends with a non-space character. The
constraint exists to protect the round-trip rather than to police content: an
embedded newline would split the value across lines and, in a header, inject a
second directive; leading or trailing spaces would write a line the parser then
rejects for trailing whitespace. Anything a specification prints on one line
must survive, including values that look like directives.

## Semantic constraints

Checked after parsing, by the AST models. A file that violates one of these is
grammatically well-formed and still invalid.

- **Ranges are ordered.** `RESERVED first-last` requires `last >= first`;
  `min*max` requires `max >= min` when `max` is bounded.
- **Flag columns are disjoint.** A flag may appear in at most one of Must, May,
  S.not, M.not. A table asserting that a flag is both required and forbidden is
  a source or extraction error, not a state a consumer should resolve.
- **A table's rows agree with its columns.** Exactly one cell per declared
  column; no value for an undeclared column; a Name column is mandatory (Name
  and From, for a re-used table); no duplicate column.
- **Names match their rules.** `; Name:` must equal the name in the block's
  header rule.
- **Numeric ranges.** Command codes are 24-bit; codes, vendor ids (both the
  file's `; Vendor-ID:` and a header rule's), application ids and enum values are
  32-bit; page numbers are 32-bit and at least 1.
- **Tables are non-empty.** An AVP table or re-used table with no rows would
  mean the extractor found a caption and lost its contents.

## Extending the format

A source column this format does not model is dropped, not carried
anonymously. If one turns up holding *machine-readable* values — TS 29.212's
"Acc. Type" and "Applicability" are the standing examples — the answer is to
add a column to the relevant `column` production, with a name and a cell
grammar of its own, rather than to reintroduce a general escape hatch. An
anonymous column is only as useful as a consumer's guess about what it means,
and the extractor already warns about every unmodelled column that is not known
prose, so these do not pass unnoticed.

A new `; Type:` or a new directive key is a format change too, and the bar is
the same: a source document that cannot otherwise be recorded — not a consumer
that would find it convenient. Consumer convenience belongs in the consumer
model, which is a separate layer built from this one.
