# The `.dad` grammar

What is and is not a well-formed file, in enough detail to write a second
implementation. [dad-format.md](dad-format.md) explains why the pieces are
shaped this way. The grammar is not stable until publication; see the notice
there.

Not covered here: semantic constraints the AST enforces (listed at the end)
and canonical layout, which is the formatter's business — the grammar accepts
any spacing the productions allow, the formatter produces exactly one.

Notation is RFC 5234 ABNF. `SP` is one space, `NL` one line feed; the format
has no tabs, carriage returns or trailing spaces. Productions ending in
`-text` are free text with a stated shape constraint.

## File

```abnf
file          = header *(2*NL section) NL
header        = spec-line NL [version-line NL] vendor-line [NL bases-line]
                [NL link-line]
spec-line     = "; Specification: " inline-text
version-line  = "; Version: " version
vendor-line   = "; Vendor-ID: " 1*DIGIT    ; < 2^32; 0 is the IETF space
bases-line    = "; Bases: " spec-ref *(", " spec-ref)
spec-ref      = ("TS" 2*3DIGIT "." 3DIGIT) / ("RFC" 1*DIGIT)
                / (ALPHA "." ALPHA 4DIGIT)   ; "RFC6733", "TS29.272", "X.S0057"
link-line     = "; Link: " URI          ; RFC 3986, must parse as an http(s) URL
version       = 1*DIGIT *("." 1*DIGIT)  ; "18.6.0"

section       = message / grouped-avp / enumerated-avp / avp-table / reused-avps
```

`; Version:` is present when the source has a version axis (3GPP yes, RFC
no). `; Bases:` is optional only because RFC 6733, the base of the tree, has
nothing to put in it. A header-only file is legal: an RFC can allocate
command codes without defining an AVP and still be a corpus node.

Blocks are runs of consecutive non-blank lines separated by blank lines; the
file ends with exactly one newline.

```abnf
comment       = ";;" *(%x20-10FFFF)
; fills the rest of any line, or a whole line of its own; ignorable here
```

A line left empty by removing its comment is skipped, not a block separator.
No inline value may contain `;;`.

The grammar ignores comments, but a formatter that keeps them needs to know
where each belongs: a trailing comment to its line; a whole-line comment to
the next line of its block, or to the block's end after its last line; a run
of comment lines between blank lines to the section after it (to the end of
the file after the last section, to the start before the file header).
[dad-format.md](dad-format.md#comments) gives the canonical placement.

```abnf
directive     = "; " key ": " value NL
key           = ALPHA *(ALPHA / "-")
```

Within one block each key appears at most once and all directives precede
the body. Order is not significant to the parser; the order written below is
the canonical one.

## Sections

```abnf
source-ref    = "; Section: " section-number NL ["; Page: " 1*DIGIT NL]
section-number = (1*ALPHA / 1*DIGIT *ALPHA) *("." 1*DIGIT *ALPHA)
                ; "6.3", "6.3.7A", "5b.3.1", annex "E.6.3.6"
avp-name      = (ALPHA / DIGIT) *(ALPHA / DIGIT / "-" / "_")
```

`; Page:` counts printed pages of the ETSI PDF from 1. The underscore
extends RFC 6733's `name-fmt` for TS 29.109's `GBA_U-Awareness-Indicator`.

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

Flags appear in the order above, each at most once. The application id is
optional only because some documents omit it (TS 29.272's VCSG commands).

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

```abnf
avp-rule      = *SP [occurrences *SP] bracket-open SP avp-name SP bracket-close
                [*SP "; bold"]
occurrences   = [1*DIGIT] "*" [1*DIGIT]
bracket-open  = "<" / "{" / "["
bracket-close = ">" / "}" / "]"
```

Brackets match as a pair and carry the presence: `<>` fixed, `{}` required,
`[]` optional. No `occurrences` means exactly once; a bare `*` means
zero-or-more.

### Enumerated AVP

```abnf
enumerated-avp = "; Type: Enumerated AVP" NL
                 "; Name: " avp-name NL
                 source-ref
                 ["; Values: " inline-text NL]
                 enum-header-rule NL
                 *((enum-value / reserved) NL)
enum-header-rule = avp-name " ::= < Enumerated AVP header: " code
                   [SP vendor-id] " >"
enum-value    = *SP enum-name *SP "= " 1*DIGIT [1*SP "; " inline-text]
enum-name     = (ALPHA / DIGIT) *name-char *(SP 1*name-char)
name-char     = ALPHA / DIGIT / "-" / "_" / "(" / ")"
reserved      = *SP "; RESERVED" *SP "= " 1*DIGIT ["-" 1*DIGIT]
```

An enum name may contain single spaces, never leading, trailing or doubled,
and parentheses after its first character: TS 32.299 labels its values in
words (`PS to CS Transfer = 0`, `VAS4SMS Short Message Virtual Private
Network (VPN) = 7`). It cannot contain `=`, so the ` = ` before the digits
ends it.

`; Values:` says where the clause defines the values instead, in its own
words (`; Values: TS 32.422 [23] for Trace Depth`). With no values after
it, the section is complete as it stands: the document points elsewhere for
the list. Values may still follow, supplied by a correction.

`; RESERVED` is the one `; Key:` line that may appear in a body. A reserved
value is distinct from an unassigned one: a validator must reject a
dictionary that assigns it.

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

`; Columns:` states the columns the source table had, in source order; a row
has exactly one cell per column, positionally. `; Table:` is absent when the
source prints no caption (RFC tables).

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
              / "QoSFilterRule"
```

`data-type` is closed: RFC 6733 §4.2 and §4.3.1 plus RFC 3588's
`QoSFilterRule` used by RFC 4005.

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
m-bit         = "MUST" / "MUST-NOT" / "-"
; a From cell holds a spec-ref
```

Name and From are required; M-bit is not (TS 29.128, 29.173, 29.336 print no
such column).

## Text values

```abnf
inline-text   = VCHAR *(%x20-10FFFF) VCHAR / VCHAR
```

A single line beginning and ending with a non-space character, so the value
survives the round trip; anything a specification prints on one line must
survive, including values that look like directives.

## Semantic constraints

Checked by the AST after parsing:

- `RESERVED first-last` requires `last >= first`; `min*max` requires
  `max >= min` when bounded.
- A flag appears in at most one of Must, May, S.not, M.not.
- Exactly one cell per declared column; no value for an undeclared column;
  a Name column (Name and From for re-used tables) is mandatory; no duplicate
  column; tables are non-empty.
- `; Name:` equals the name in the block's header rule.
- Command codes are 24-bit; codes, vendor ids, application ids and enum
  values are 32-bit; page numbers are 32-bit and at least 1.

## Extending the format

A new column, `; Type:` or directive key is a format change, and the bar is a
source document that cannot otherwise be recorded — not a consumer that would
find it convenient. Consumer convenience belongs in the model.
