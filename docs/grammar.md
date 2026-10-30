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

section       = application-scope / message / grouped-avp / enumerated-avp
              / avp-table / reused-avps / registry
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

### Application Scope

```abnf
application-scope = "; Type: Application Scope" NL
                    "; Name: " inline-text NL
                    source-ref
                    "; Application-ID: " application-id NL
                    "; Applies-To: " clause-wildcard *(", " clause-wildcard) NL
clause-wildcard   = section-number ".*"
```

An application id the document states outside its command headers:
`; Name:` is the document's name for the application ("Gx", "Diameter
Credit Control"), `; Section:` the clause stating the id, and `; Applies-To:`
the clauses whose commands it applies to. `5.*` is clause 5 and every
subclause under it (`5.6.2`, not `5a.1`); `5.1.*` does not cover `5.2.1`. A
bare `5`, which would name clause 5 alone, is reserved and does not parse.
The id applies to the commands whose headers print none; a header that
prints one keeps it. The block has no body.

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
optional only because some documents omit it (TS 29.272's VCSG commands);
an `application-scope` block records an id the document states elsewhere.

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
                [*SP "; bold"] [*SP "; strikethrough"]
occurrences   = [1*DIGIT] "*" [1*DIGIT]
bracket-open  = "<" / "{" / "["
bracket-close = ">" / "}" / "]"
```

Brackets match as a pair and carry the presence: `<>` fixed, `{}` required,
`[]` optional. No `occurrences` means exactly once; a bare `*` means
zero-or-more. A member the source both bolds and strikes carries both
markers, `; bold` first.

A member commented out (`;;      [ Acct-Session-Id ] ; strikethrough`) is a
comment like any other: no member, and attached to the member after it, or
to the body's end.

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
enum-name     = avp-name / quoted-name
quoted-name   = DQUOTE name-text DQUOTE
name-text     = name-char [*(name-char / SP) name-char]
name-char     = %x21 / %x23-5B / %x5D-7E / %x80-10FFFF / escaped
                ; neither SP, DQUOTE nor a bare "\"
escaped       = "\" (DQUOTE / "\")
reserved      = *SP "; RESERVED" *SP "= " 1*DIGIT ["-" 1*DIGIT]
```

A value name that is not an `avp-name` is quoted: TS 32.299 labels its
values in words (`"PS to CS Transfer" = 0`, `"VAS4SMS Short Message Virtual
Private Network (VPN)" = 7`). The quotes are not part of the name. Inside
them `\"` is a double quote and `\\` a backslash; nothing else is
escapable, so a backslash before any other character, or a trailing one
that would escape the closing quote, is no value line. RFC 4005 clause 7.3
labels a value `802 (includes all 802 media plus Ethernet "canonical
format")`, written `"802 (includes all 802 media plus Ethernet \"canonical
format\")" = 6`. A name cannot contain `;;`, which no value may. A quoted
`avp-name` (`"Yes" = 1`) parses as the same name, and the formatter writes
it bare and escapes exactly the two characters, so each name has one
spelling.

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
              / mark-column
mark-column   = "Acc-Type" / "Applicability" / "Reference-Points"
              / "ACR" / "ACA" / "CCR" / "CCA"
table-row     = cell *(1*SP cell)
cell          = 1*(quoted / %x21 / %x23-10FFFF)   ; spaces only inside quotes
quoted        = DQUOTE *(name-char / SP) DQUOTE
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
mark-cell     = mark *("," mark) / "-" / blank
mark          = plain-mark / quoted-name
plain-mark    = 1*(%x21 / %x23-2B / %x2D-3A / %x3C-5B / %x5D-10FFFF)
                ; no SP, ",", ";", DQUOTE or "\", and not "-" alone
blank         = DQUOTE DQUOTE
data-type     = "OctetString" / "Integer32" / "Integer64" / "Unsigned32"
              / "Unsigned64" / "Float32" / "Float64" / "Grouped"
              / "Address" / "Time" / "UTF8String" / "DiameterIdentity"
              / "DiameterURI" / "Enumerated" / "IPFilterRule"
              / "QoSFilterRule"
```

`data-type` is closed: RFC 6733 §4.2 and §4.3.1 plus RFC 3588's
`QoSFilterRule` used by RFC 4005.

A mark column holds what the document marks about where its row applies,
each mark in the document's spelling: the IP-CAN access types under
`Acc-Type` (`3GPP-EPS,Non-3GPP-EPS`, TS 29.212 and 29.215), functions and
supported features under `Applicability` (`Both,Rel8`), reference points
under `Reference-Points` (`Gi,Sgi`, TS 29.061), and TS 32.299's use mark per
command under `ACR`, `ACA`, `CCR` and `CCA` (`M`, `OM`, `OC`, `X`). The
vocabulary is the document's, so the grammar does not close it. A mark keeps
what the document prints beside it, a note reference mostly, and a mark
that is not a plain token is quoted with the rules of a quoted enum value
name ([Enumerated AVP](#enumerated-avp)): `"All (NOTE 5)"`, `"V2X Localized
User Plane"`. A quoted plain token parses as the same mark, and the
formatter writes it bare.

A mark cell tells three things apart. `-` is a dash the source printed,
which TS 32.299 clause 7.1.0 gives a meaning: "Those Diameter AVPs that are
not used are marked '-'". `""`, an empty quoted string no mark can be, is a
cell the source left blank. Anything else is the cell's marks.

### Re-used AVPs

```abnf
reused-avps   = "; Type: Reused AVPs" NL
                "; Section: " section-number NL
                "; Table: " inline-text NL
                ["; Page: " 1*DIGIT NL]
                "; Columns: " *SP reused-columns NL
                1*(table-row NL)
reused-columns = reused-column *(1*SP reused-column)
reused-column = "Name" / "From" / "M-bit" / "Code" / "Type" / mark-column
m-bit         = "MUST" / "MUST-NOT" / "-"
; a From cell holds a spec-ref; Code, Type and mark cells read as in an
; AVP table
```

Name and From are required; M-bit is not (TS 29.128, 29.173, 29.336 print no
such column). Code and Type are the citing table's own statement of what
the origin defines (TS 29.172 table 7.4.1-2, TS 32.299 tables 7.3.1-7.5.1).

### Registry

```abnf
registry      = "; Type: Registry" NL
                "; Registry: " registry-kind NL
                "; Section: " section-number NL
                "; Table: " inline-text NL
                ["; Page: " 1*DIGIT NL]
                "; Columns: " *SP registry-columns NL
                1*((table-row / registry-reserved) NL)
registry-kind = "Application IDs" / "Command Codes" / "AVP Codes"
              / "Result Codes"
registry-columns = registry-column *(1*SP registry-column)
registry-column = "Code" / "Name" / "Abbreviation" / "Type" / "Defined-In"
registry-reserved = "; RESERVED " 1*DIGIT ".." 1*DIGIT
                    [SP defined-in-cell] [SP quoted]
defined-in-cell = spec-ref *("," spec-ref) / "-"
registry-type-cell = data-type / quoted / "-"
; a Code cell is 1*DIGIT; Name and Abbreviation cells are a mark or "-"
```

A table allocating codes to the documents defining them, rather than
defining anything: TS 29.230 allocates application ids (table 4.1), command
codes (5.1/1–5.1/4), the 3GPP vendor's AVP codes (7.1) and its experimental
result codes (8.1.2–8.1.4). A row is one allocation, `Defined-In` the
documents it cites (`TS29.228,TS29.229` where table 4.1 prints "29.228 [1]
and 29.229 [2]"). A Name or Abbreviation cell is written as a mark is,
quoted where it is not a plain token (`"3GPP Cx/Px"`, `"Deprecated
value"`); in every registry column `-` is a blank cell, the Code column's
excepted, which has none. A Type cell is a `data-type`, or, quoted, a type
the closed set lacks, kept as printed: TS 29.230 table 7.1 types code 314
`"Integer"`. Bare, a Type cell is always a data type, so the quotes stay on
a plain token; a quoted data type parses as that type, and the formatter
writes it bare.

A `registry-reserved` line is a range the table reserves without
allocating, among the rows where the table prints it: the range, every
document its note names, and what it is reserved for, in the document's
words and always quoted (`; RESERVED 320..399 TS29.234 "TS 29.234"`, `;
RESERVED 256..299 "future use"`). Rows and reservations keep the table's
order, overlaps and all: TS 29.230 reserves 4703–4799 for TS 29.389 inside
4605–4799 for TS 29.388.

## Text values

```abnf
inline-text   = VCHAR *(%x20-10FFFF) VCHAR / VCHAR
```

A single line beginning and ending with a non-space character, so the value
survives the round trip; anything a specification prints on one line must
survive, including values that look like directives.

## Semantic constraints

Checked by the AST after parsing:

- `RESERVED first-last` and `RESERVED first..last` require `last >= first`;
  `min*max` requires `max >= min` when bounded.
- A flag appears in at most one of Must, May, S.not, M.not.
- Exactly one cell per declared column; no value for an undeclared column
  (a mark column's blank cell is no value);
  a Name column (Name and From for re-used tables, Code for registries) is
  mandatory; no duplicate column; tables are non-empty.
- `; Name:` equals the name in the block's header rule.
- `; Applies-To:` names a clause at most once.
- Command codes are 24-bit; codes, vendor ids, application ids and enum
  values are 32-bit; page numbers are 32-bit and at least 1.

## Extending the format

A new column, `; Type:` or directive key is a format change, and the bar is a
source document that cannot otherwise be recorded — not a consumer that would
find it convenient. Consumer convenience belongs in the model.
