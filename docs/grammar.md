# The `.dad` grammar

The well-formed `.dad` file, precisely enough for a second implementation.
[dad-format.md](dad-format.md) gives the principles and the comment
placement rules. Canonical layout is the formatter's: the grammar accepts any
spacing the productions allow, and `seanchai format` writes one.

Notation is RFC 5234 ABNF. `SP` is one space and `NL` one line feed; a file
has no tabs, carriage returns or trailing spaces. A production ending in
`-text` is free text with the stated constraint.

## File

```abnf
file          = header *(2*NL section) NL
header        = spec-line NL [version-line NL] vendor-line [NL bases-line]
                [NL obsoletes-line] [NL link-line] [NL transcribed-line]
spec-line     = "; Specification: " inline-text
                ; a title naming a spec-ref's document: "3GPP TS 29.272",
                ; "RFC 6733", "ETSI ES 283 034", "Private ACME-HSS"
version-line  = "; Version: " version
vendor-line   = "; Vendor-ID: " 1*DIGIT    ; < 2^32; 0 is the IETF space
bases-line    = "; Bases: " spec-ref *(", " spec-ref)
obsoletes-line = "; Obsoletes: " spec-ref *(", " spec-ref)
spec-ref      = ("TS" 2DIGIT "." 3DIGIT) / ("RFC" 1*DIGIT) / external-ref
                ; "TS29.272", "RFC6733"
external-ref  = ("ETSI-" ("TS" / "ES") 3DIGIT "." 3DIGIT ["-" 1*DIGIT])
                                                          ; "ETSI-TS283.034"
              / ("3GPP2-" ALPHA "." ALPHA 4DIGIT ["-" 3DIGIT])
                                                          ; "3GPP2-X.S0057"
              / ("OMA" 1*("-" 1*(ALPHA / DIGIT / "_")))   ; "OMA-DDS-Charging_Data"
              / ("oneM2M-TS-" 4DIGIT)                     ; "oneM2M-TS-0004"
              / ("Private-" private-name)                 ; "Private-ACME-HSS"
private-name  = (ALPHA / DIGIT) *(ALPHA / DIGIT / "_" / "." / "-")
link-line     = "; Link: " URI          ; RFC 3986, must parse as an http(s) URL
transcribed-line = "; Transcribed: by hand from " URI   ; the rendering copied
version       = 1*DIGIT *("." 1*DIGIT)  ; "18.6.0"

section       = application-scope / message / grouped-avp
              / enumerated-avp / avp-table / reused-avps / registry
              / undefined-avp / value-table / information-elements
              / command-result-codes / interpreted-constraints
```

A `spec-ref` names a document without its version, as one token.

- 3GPP and IETF documents are their number.
- Other documents lead with the publisher and keep its numbering: ETSI's
  "TS 183 017" dotted like a 3GPP number, with its part ("TS 183 059-1");
  3GPP2's "X.S0057" without its revision letter but with its part
  ("X.S0013-014" is another document); OMA's name as printed; oneM2M's
  "TS-0004".
- A private or vendor document, which no publisher numbers, is `Private-`
  and a name of its author's, its title `Private ACME-HSS`. Its
  `; Vendor-ID:` is its own vendor's, and other files cite it by the
  reference: a From cell `Private-ACME-HSS`. It follows no publisher's
  releases, so what it cites without a version means the newest copy held,
  as for an RFC ([consumers.md](consumers.md#without-python)).
- Each document has one spelling, since resolution compares references
  exactly. A raw file keeps a citing document's misnaming (3GPP cites ETSI ES
  283 034 as `ETSI-TS283.034`); the corpus maps each listed misnaming
  ([linter.md](linter.md#resolving-an-origin)), and a correction writes
  `ETSI-ES283.034` in the corrected file. A citation's revision is recorded
  beside the corpus.

`; Version:` is present when the source has versions (3GPP, not RFCs).
`; Bases:` is absent only in RFC 6733, the base of the tree. `; Obsoletes:`
lists the documents the header says this one obsoletes, held by the corpus
or not: RFC 7155's "Obsoletes: 4005" is `; Obsoletes: RFC4005`. What an
obsoleted document defines stays its own reading; the model says which
documents obsolete it ([consumers.md](consumers.md#the-model)). `; Transcribed:`
marks a file copied by hand for a document no extractor reads (ETSI's, 3GPP2's
and OMA's exist only as PDF) and names the rendering
([extractor.md](extractor.md#transcriptions)). A header-only file is legal: an
RFC can allocate command codes without defining an AVP.

A block is a run of non-blank lines; blocks are separated by blank lines.
The file ends with exactly one newline.

```abnf
comment       = ";;" *(%x20-10FFFF)
; fills the rest of any line, or a whole line of its own; ignorable here
```

A line left empty by removing its comment is skipped, not a block separator.
No inline value may contain `;;`. Where a comment attaches is in
[dad-format.md](dad-format.md#comments).

```abnf
directive     = "; " key ": " value NL
key           = ALPHA *(ALPHA / "-")
```

Within a block each key appears at most once, and all directives precede the
body. The parser accepts any order; the order below is canonical.

## Sections

```abnf
source-ref    = "; Section: " section-number NL ["; Page: " 1*DIGIT NL]
section-number = (1*ALPHA / 1*DIGIT *ALPHA) *("." 1*DIGIT *ALPHA)
                ; "6.3", "6.3.7A", "5b.3.1", annex "E.6.3.6"
avp-name      = (ALPHA / DIGIT) *(ALPHA / DIGIT / "-" / "_")
```

`; Page:` counts the ETSI PDF's pages from 1. For a 3GPP2 PDF it is the
number the footer prints, after roman-numbered front matter (3GPP2 X.S0057's
page 61 is the PDF's 71st). The underscore in `avp-name` extends RFC 6733's
`name-fmt` for TS 29.109's `GBA_U-Awareness-Indicator`.

### Application Scope

```abnf
application-scope = "; Type: Application Scope" NL
                    "; Name: " inline-text NL
                    source-ref
                    "; Application-ID: " application-id NL
                    "; Applies-To: " clause-wildcard *(", " clause-wildcard) NL
clause-wildcard   = section-number ".*"
```

An application id the document states outside its command headers. TS 29.212
prints its Gx commands with bare `272, REQ, PXY` headers and says in clause
5.1 that Gx's id is 16777238; the block has `; Name: Gx`, `; Section: 5.1`
and `; Applies-To: 5.*`.

- `5.*` is clause 5 and every subclause under it (`5.6.2`, not `5a.1`);
  `5.1.*` does not cover `5.2.1`. A bare `5` is reserved and does not parse.
- The id applies to commands whose headers print none; a printed id is kept.
- The block has no body.

### Message

```abnf
message       = "; Type: Message" NL
                "; Name: " avp-name ", " abbreviation NL
                source-ref
                message-rule NL
                *(avp-rule NL)
abbreviation  = 2*6(%x41-5A)
message-rule  = "<" avp-name "> ::= < Diameter Header: " header-items " >"
header-items  = command-code *(", " command-flag) [", " application-id]
command-code  = 1*DIGIT                 ; < 2^24
command-flag  = "REQ" / "PXY" / "ERR"
application-id = 1*DIGIT                ; < 2^32
```

Flags appear in the order above, each at most once. The application id is
optional because some documents omit it (TS 29.272's VCSG commands).

### Answer Message

```abnf
answer-message = "; Type: Answer Message" NL
                 source-ref
                 "<answer-message> ::= < Diameter Header: code, ERR [, PXY] >" NL
                 *(avp-rule NL)
```

RFC 6733 section 7.2's format for an answer with the E bit set, in place of
its command's. The rule line is kept as printed (TS 29.229 clause 7.3.1
writes `ERR [PXY]`). The block has no `; Name:`. TS 29.229 and 3GPP2
X.S0013-006 clause 7.3.1 print their own, adding
`[ Supported-Applications ]`; a document printing none takes its bases'
([consumers.md](consumers.md#the-model)).

### Grouped AVP

```abnf
grouped-avp   = "; Type: Grouped AVP" NL
                "; Name: " avp-name NL
                source-ref
                ["; Reprints: " spec-ref NL]
                avp-header-rule NL
                *(avp-rule NL)
avp-header-rule = avp-name " ::= < AVP header: " code [SP vendor-id] " >"
code          = 1*DIGIT                 ; < 2^32
vendor-id     = 1*DIGIT                 ; < 2^32; absent for IETF-space AVPs
```

`; Reprints:` marks another document's grouped AVP, printed under a sentence
naming that document. Such a block defines nothing, so a file can hold
several of one name: TS 29.109 prints RFC 6733's
`Vendor-Specific-Application-Id` in clauses 4.2, 5.2 and 5.4, each block
`; Reprints: RFC6733`. What the document glosses about a member is a
trailing comment (`*1 { Auth-Application-Id } ;; 16777221`). A clause
printing its own body for a re-used AVP without such a sentence has no
`; Reprints:`, and the linter compares it with the origin.

### AVP rule

```abnf
avp-rule      = *SP [occurrences *SP] bracket-open SP avp-name SP bracket-close
                [*SP "; bold"] [*SP "; strikethrough"]
occurrences   = [1*DIGIT] "*" [1*DIGIT]
bracket-open  = "<" / "{" / "["
bracket-close = ">" / "}" / "]"
```

- Brackets match as a pair: `<>` fixed, `{}` required, `[]` optional.
- No `occurrences` means exactly once; a bare `*` means zero or more.
- `; bold` and `; strikethrough` mirror the source. A member both bold and
  struck carries both, `; bold` first.
- A member commented out is a comment, attached to the member after it or to
  the body's end. TS 32.299 (clauses 6.2.1.2, 6.4.1.2) defines a strike as
  "not used by 3GPP", so its struck members are commented out with the marker
  kept: `;;      [ Acct-Session-Id ] ; strikethrough`.
- An elision (`…` or `...` on its own line, in TS 29.273, RFC 5778 and RFC
  6738) is a `;;` comment where it stood. The rule holds only the members it
  prints ([extractor.md](extractor.md#the-3gpp-docx-extractor)).

### Enumerated AVP

```abnf
enumerated-avp = "; Type: Enumerated AVP" NL
                 "; Name: " avp-name NL
                 source-ref
                 ["; Values: " inline-text NL]
                 enum-header-rule NL
                 *((enum-value / reserved / void / vendor-specific) NL)
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
void          = *SP "; VOID" *SP "= " 1*DIGIT ["-" 1*DIGIT]
vendor-specific = *SP "; VENDOR-SPECIFIC" *SP "= " 1*DIGIT ["-" 1*DIGIT]
                  [1*SP "; " inline-text]
```

A value name keeps the document's spelling. One that is not an `avp-name` is
quoted: TS 32.299's `"PS to CS Transfer" = 0`.

- The quotes are not part of the name. Inside them only `\"` and `\\` are
  escapes; a backslash before anything else, or one escaping the closing
  quote, makes the line no value. RFC 4005 clause 7.3's label is written
  `"802 (includes all 802 media plus Ethernet \"canonical format\")" = 6`.
- A name cannot contain `;;`.
- A quoted `avp-name` (`"Yes" = 1`) is the same name. The formatter writes it
  bare and escapes exactly the two characters, so each name has one spelling.

`; Values:` is the clause's own words for where its values are defined
(`; Values: TS 32.422 [23] for Trace Depth`). With no values after it the
section is complete as printed. A correction may supply values under it. TS
29.272's `Report-Interval`, RFC 5777's `ICMP-Code` and TS 32.299's
`API-Network-Service-Node` stay citations only, since their sources hold no
flat list.

`; RESERVED`, `; VOID` and `; VENDOR-SPECIFIC` are the only directives
allowed in a body.

- A reserved value was never assigned, and a validator must reject a
  dictionary that assigns it.
- A void value was assigned and withdrawn; the document prints "Void" where
  its label was (TS 29.214 clause 5.3.13's `Void (0)` is `; VOID = 0`). It is
  no value named `Void`. A validator treats it as reserved.
- A vendor-specific range is left to vendors or operators, so a dictionary
  may assign its values under names of its own, and a validator must accept
  them. The document's description follows as a value's does: `; VENDOR-SPECIFIC
  = 100-199 ; Vendor specific SM services` (TS 32.299 clause 7.2.213).

### AVP table

```abnf
avp-table     = "; Type: AVP Table" NL
                "; Section: " section-number NL
                ["; Table: " inline-text NL]
                ["; Page: " 1*DIGIT NL]
                "; Columns: " *SP columns NL
                1*(table-row NL)
columns       = column *(1*SP column)
column        = "Name" / "Vendor-ID" / "Code" / "Section" / "Type"
              / "Must" / "May" / "S.not" / "M.not" / "Encrypt"
              / mark-column
mark-column   = (ALPHA / DIGIT) *(ALPHA / DIGIT / "_" / "." / "-")
                ; any other name but a structural column of either table
table-row     = cell *(1*SP cell)
cell          = 1*(quoted / %x21 / %x23-10FFFF)   ; spaces only inside quotes
quoted        = DQUOTE *(name-char / SP) DQUOTE
```

`; Columns:` lists the modelled columns the source table had, in source
order, so a missing column differs from an empty cell; prose columns are
dropped. A row has one cell per column. `; Table:` is absent when the source
prints no caption (RFC tables).

```abnf
name-cell     = avp-name
vendor-cell   = 1*DIGIT / "-"           ; < 2^32; 0 is the IETF space
code-cell     = 1*DIGIT / "-"
section-cell  = section-number / "-"
type-cell     = data-type / quoted / "-"
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

`data-type` is closed: RFC 6733 §4.2 and §4.3.1, plus RFC 3588's
`QoSFilterRule`, which RFC 4005 uses. A type outside it is quoted as printed
(TS 29.234 table 10.1.1 types code 314 `"Integer"`), and the model treats the
row as untyped. A quoted data type parses as that type.

A Vendor-ID cell is the row's vendor, overriding its V flag, for a table
that tabulates several vendors: oneM2M TS-0004 table A.4-1 has IETF rows 0,
`Node-Id` 10415 and its own AVPs 45687. Without the column, or with `-`, the
vendor comes from `; Vendor-ID:` and the V flag
([linter.md](linter.md#vendor-spaces)).

A mark column holds the document's marks for where a row applies, in its
spelling, comma-separated and uninterpreted. The set is open: a column that
is not one of the structural columns above, nor a re-used table's, is a mark
column, named by the label its document prints, written as one token. A
document with a column of its own needs an extractor reading, not a format
change. The corpus holds:

| Column | Source |
|---|---|
| `Acc-Type` | IP-CAN access types, TS 29.212 and 29.215 (`3GPP-EPS,Non-3GPP-EPS`) |
| `Applicability` | functions and features, TS 29.212 (`Both,Rel8`) |
| `Reference-Points` | TS 29.061 (`Gi,Sgi`) |
| `ACR`, `ACA`, `CCR`, `CCA` | TS 32.299's use per command (`M`, `OM`, `OC`, `X`) |
| `SI`, `CCR-MSCC`, `CCA-MSCC` | OMA-DDS-Charging_Data table 11 |

A column named as one of the file's commands abbreviates, as `ACR`, marks
that command's use of the AVP (`member-marked-unused` in
[linter.md](linter.md#single-file-rules)).

A mark keeps what the document prints beside it, mostly a note reference. A
mark that is not a `plain-mark` is quoted as an enum value name is
(`"All (NOTE 5)"`); a quoted plain mark parses as the same mark and is
written bare. In a mark cell `-` is a printed dash, which TS 32.299 clause
7.1.0 defines as "not used", and `""` is a blank cell.

### Re-used AVPs

```abnf
reused-avps   = "; Type: Reused AVPs" NL
                "; Section: " section-number NL
                ["; Table: " inline-text NL]
                ["; Page: " 1*DIGIT NL]
                "; Columns: " *SP reused-columns NL
                1*(table-row NL)
reused-columns = reused-column *(1*SP reused-column)
reused-column = "Name" / "From" / "M-bit" / "Code" / "Type" / mark-column
m-bit         = "MUST" / "MUST-NOT" / "-"
; a From cell holds a spec-ref; Code, Type and mark cells read as in an
; AVP table
```

- Name and From are required. M-bit is optional (TS 29.128, 29.173 and
  29.336 print none). Code and Type are the citing table's statement of what
  the origin defines (TS 29.172 table 7.4.1-2).
- A From cell may name any `spec-ref`: TS 29.212 re-uses `3GPP2-BSID` from
  `3GPP2-X.S0057`.
- A row an AVP table's NOTE or cell derives is in a block under that table's
  label: TS 29.329's NOTE on table 6.3.1 sends four AVPs to RFCs.
- A block with no `; Table:` holds the origins one clause's prose states, and
  `; Section:` is that clause. TS 29.329 clause 6.3.9 says of Server-Name
  "See 3GPP TS 29.229 [6]", so a block at 6.3.9 has Name and From columns. A
  clause stating it again gets its own block.
- Flag rules a table restates for imported AVPs "in the context of the
  present document" (ETSI ES 283 034 tables 11–13) have no column; the
  transcriptions keep them in a `;;` comment above the table.

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
; a Code cell is 1*DIGIT / quoted; Name and Abbreviation cells are a mark or "-"
```

A table allocating codes to the documents that define them. TS 29.230
allocates application ids (table 4.1), command codes (5.1/1–5.1/4), the 3GPP
vendor's AVP codes (7.1) and its experimental result codes (8.1.2–8.1.4).
Read as definitions, it would define every 3GPP AVP a second time.

- A row is one allocation. `Defined-In` lists the documents it cites
  (`TS29.228,TS29.229` for "29.228 [1] and 29.229 [2]").
- Name and Abbreviation cells are written as marks (`"3GPP Cx/Px"`).
- `-` is a blank cell in every column but Code. A Code cell printing a
  placeholder is quoted: TS 29.230 V19.3.0 table 4.1 allocates Sh-ee `"zz"`.
- A Type cell is a `data-type` or a quoted type as printed (table 7.1's
  `"Integer"`). A bare Type cell is always a data type, so a quoted plain
  token keeps its quotes; a quoted data type parses as that type and is
  written bare.
- A `registry-reserved` line is a range the table reserves without
  allocating, where the table prints it, with the documents its note names
  and its purpose, quoted (`; RESERVED 320..399 TS29.234 "TS 29.234"`).
  Rows and reservations keep the table's order and overlaps: TS 29.230
  reserves 4703–4799 for TS 29.389 inside 4605–4799 for TS 29.388.

### Undefined AVP

```abnf
undefined-avp = "; Type: Undefined AVP" NL
                "; Name: " avp-name NL
                source-ref
                ["; Note: " inline-text NL]
```

A name the document uses as a member of a message or grouped body that
nothing in the corpus defines: no clause, row or base, and no later version,
erratum or sibling document. RFC 4004 clause 9.4 requires `MIP-HA-to-MN-SPI`
in `MIP-HA-to-MN-MSA`, and neither the RFC, its errata nor IANA defines it.

- Only a correction writes the block, citing what was searched; extractors
  never do.
- `; Section:` is the first clause, in file order, whose ABNF names it.
- `; Note:` quotes what the document says of the name, prefixed by the
  clause where that is not `; Section:` (`; Note: A.4.1 "the SCEF shall send
  an Event-Configuration-Request (ECR) command ..."`). Without it the
  document says nothing beyond the ABNF.
- The block has no body, type, code or flags; what to do about the name is
  the consumer's choice ([consumers.md](consumers.md#undefined-names)). A
  name with a stated type but no code is a table row, not this block.

### Value Table

```abnf
value-table   = "; Type: Value Table" NL
                "; AVP: " avp-name NL
                "; Kind: " value-kind NL
                ["; Feature-List-ID: " 1*DIGIT NL]
                ["; Application: " inline-text NL]
                "; Section: " section-number NL
                ["; Table: " inline-text NL]
                ["; Page: " 1*DIGIT NL]
                1*(value-row NL)
value-kind    = "result-codes" / "bits" / "features" / "values"
value-row     = enum-name *SP "= " 1*DIGIT [1*SP "; " value-tail]
value-tail    = section-number [1*SP "from " spec-ref] / "from " spec-ref / mark
                ; a result code's own clause and the document defining it,
                ; a feature's M/O mark
```

The names a document gives a numeric AVP's numbers when the AVP is not
`Enumerated`:

```dad
; Type: Value Table
; AVP: Experimental-Result-Code
; Kind: result-codes
; Section: 6.2
; Page: 17
DIAMETER_FIRST_REGISTRATION = 2001 ; 6.2.1.1


; Type: Value Table
; AVP: ULR-Flags
; Kind: bits
; Section: 7.3.7
; Table: 7.3.7/1
; Page: 40
Single-Registration-Indication = 0


; Type: Value Table
; AVP: Feature-List
; Kind: features
; Feature-List-ID: 1
; Application: S6a/S6d
; Section: 7.3.10.1
; Table: 7.3.10/1
; Page: 44
ODB-all-APN = 0 ; O


; Type: Value Table
; AVP: TWAN-S2a-Failure-Cause
; Kind: values
; Section: 5.2.3.31
; Table: 5.2.3.30/1
; Page: 80
"Insufficient resources" = 26
"Unknown APN"            = 27
```

- `result-codes` are values of the named AVP, from subclause headings (TS
  29.229's `6.2.2.1 DIAMETER_ERROR_USER_UNKNOWN (5001)`) or paragraphs (RFC
  6733's `DIAMETER_SUCCESS 2001`). The tail is the row's subclause when it
  differs from `; Section:`, and `from` the defining document when the clause
  names one: `DIAMETER_ERROR_USER_UNKNOWN = 5001 ; 7.4.3.2 from TS29.229`, or
  `; from RFC8506` in the block's own clause. A `Result-Code` value is in the
  IETF space; an `Experimental-Result-Code` value is in the file's
  `; Vendor-ID:`.
- `bits` number a bit mask's bits, least significant first, with no tail.
- `features` number one feature list's bits. `; Application:` and
  `; Feature-List-ID:` appear only here, each where the caption gives it.
  The tail is the M/O cell, absent when blank or when the table has no such
  column.
- `values` name the values of an integer AVP that is no `Enumerated`, as a
  table in its clause prints them (TS 29.272 table 7.3.190-1's
  Group-Service-Id, TS 29.273 table 5.2.3.30/1's TWAN-S2a-Failure-Cause),
  with no tail. The table need not hold every value the AVP takes: TS
  29.272 leaves Group-Service-Id above 1000 to the home operator.

Names are written as enum value names and marks as table marks; `-` is no
mark. Descriptions are dropped. A row printing no name and number pair (TS
29.172's "1-31 None", or `DIAMETER_ERROR_ALREADY_BANNED (56x2)`) is a `;;`
comment where it stood.

### Information Elements

```abnf
information-elements = "; Type: Information Elements" NL
                       ["; Command: " avp-name NL]
                       ["; Application-ID: " application-id NL]
                       ["; Command-Section: " section-number NL]
                       ["; From: " spec-ref NL]
                       ["; AVP: " avp-name NL]
                       "; Section: " section-number NL
                       ["; Table: " inline-text NL]
                       ["; Page: " 1*DIGIT NL]
                       (named-elements / avp-elements)
named-elements = "; Columns: Name" 1*SP "AVP" 1*SP "Cat" NL
                 1*(element-row NL)
avp-elements  = "; Columns: AVP" 1*SP "Cat" NL
                1*(avp-element-row NL)
element-row   = *(4SP) name-cell 1*SP mapping-cell 1*SP category-cell
avp-element-row = *(4SP) mapping-cell 1*SP category-cell
                ; a mapping cell naming an AVP or quoted, not "-"
name-cell     = mark                    ; the element as printed
mapping-cell  = avp-name *("," avp-name) / avp-name 1*("/" avp-name)
              / quoted / "-"
category-cell = "M" / "C" / "O" / "OM" / "OC" / "-" / DQUOTE DQUOTE
```

A stage-3 document's table of one command's information elements,
"Information element name | Mapping to Diameter AVP | Cat. | Description"
(TS 29.272 table 5.2.1.1.1/1, Update Location Request):

```dad
; Type: Information Elements
; Command: Update-Location-Request
; Section: 5.2.1.1.1
; Table: 5.2.1.1.1/1
; Page: 18
; Columns: Name                            AVP                  Cat
IMSI                                       User-Name            M
"Supported Features (See TS 29.229 [9])"   Supported-Features   O
```

- A row is an element: its name as printed, quoted as a mark is; the AVPs
  its mapping cell names, without what it prints after a name ("User-Name
  (See IETF RFC 6733 [61])"); and its category, the Cat. cell. The
  Description cell is prose and stays in the document, where `; Section:`,
  `; Table:` and `; Page:` find it. A full-width NOTE row is no element.
- AVPs joined by `,` are carried together ("Destination-Host,
  Destination-Realm"); joined by `/` the row offers one of them, as the
  document's "/" or "or" does ("Result-Code / Experimental-Result"). A
  mapping cell naming no AVP is quoted as printed (TS 29.273's "EAP
  payload"); `-` is a blank cell.
- `; Command:` is the command the rows describe, which a procedure clause's
  sentence names ("This procedure is mapped to the commands
  Update-Location-Request/Answer (ULR/ULA) ..."). It is absent where the
  document does not name it in a way the extractor reads, and a correction
  supplies it.
- The command is the file's own where it prints one of that name, compared
  without regard to case; else the one of the document `; From:` names,
  which the sentence says specifies it ("specified in TS 29.229 [5]", TS
  29.228); else the first `; Bases:` document printing it.
- `; Application-ID:` chooses among the applications the file prints the
  command for: TS 29.272 prints Insert-Subscriber-Data-Request for S6a and
  for S7a.
- `; Command-Section:` chooses among the blocks of a document printing the
  command more than once under the one application, by the clause of the
  block: TS 29.273 prints Diameter-EAP-Request for SWa (clause 4.2.2.1.1),
  STa (5.2.2.1.1) and SWd (6.2.2.1.1.1), each with a body of its own, all in
  STa's application.
- `; AVP:` names a grouped AVP of the command whose members the rows
  describe instead (TS 29.228 table 6.3.2, SIP-Auth-Data-Item in
  Multimedia-Auth-Request).
- `; Table:` is absent where the table prints no caption (TS 29.234 V11.2.0
  clause 8.3.2's first).
- A category cell is the Cat. cell as printed, `""` a blank one. M, C and O
  are a stage-3 document's mandatory, conditional and optional. TS 32.299's
  message tables use TS 32.240's categories, as their clauses 6.2.1.2 and
  6.4.1.2 say: M and C, OM and OC, operator provisionable mandatory and
  conditional ("all operator provisionable parameters (Oc and Om)", clause
  7.1.12), and `-`, a printed dash, the row's description "Not used in
  3GPP" or "Not used in CCR".

TS 32.299 prints each command's AVPs as a table in the clause printing its
ABNF, "AVP | Category | Description", with no element name: `; Columns: AVP
Cat`, whose rows are the AVP cell and the category. Every row of a block
names its element, or none does. A row is set off four spaces a level under
the row above it, a member of the grouped AVP that row maps, as the table
sets it off a tab a level (TS 32.299 table 6.2.2.1):

```dad
; Type: Information Elements
; Command: Accounting-Request
; Section: 6.2.2
; Table: 6.2.2.1
; Page: 58
; Columns: AVP                   Cat
Session-Id                       M
Acct-Application-Id              OM
Vendor-Specific-Application-Id   -
    Vendor-Id                    -
User-Name                        OC
Proxy-Info                       OC
    Proxy-Host                   M
    Proxy-State                  M
AVP                              OC
```

- A row's depth is as printed. A row set more than one level under the row
  above is the document's misprint, which the raw file keeps and the linter
  reports (`element-misplaced`); a row with rows under it maps one AVP, or
  they are under no AVP.
- The `AVP` row is the body's `* [ AVP ]`.
- `; Command:` is the command whose ABNF the table's clause prints.

### Command Result Codes

```abnf
command-result-codes = "; Type: Command Result Codes" NL
                       ["; Command: " avp-name NL]
                       ["; Application-ID: " application-id NL]
                       ["; Command-Section: " section-number NL]
                       ["; From: " spec-ref NL]
                       "; Section: " section-number NL
                       ["; Table: " inline-text NL]
                       ["; Page: " 1*DIGIT NL]
                       1*(enum-name NL)    ; a code's name as printed
```

A procedure's table of the result codes its answer may carry, each under a
condition, "Result-Code AVP value | Condition" (TS 29.228 table 6.2.2.1.1,
"User information update response valid result codes"):

```dad
; Type: Command Result Codes
; Command: Push-Profile-Answer
; From: TS29.229
; Section: 6.2.2.1
; Table: 6.2.2.1.1
; Page: 36
DIAMETER_SUCCESS
DIAMETER_ERROR_NOT_SUPPORTED_USER_DATA
DIAMETER_ERROR_USER_UNKNOWN
DIAMETER_ERROR_TOO_MUCH_DATA
DIAMETER_UNABLE_TO_COMPLY
```

- A row is a code's name as printed, written as an enum value's name. The
  Condition cell is prose and stays in the document. The table prints no
  number, which the document defining the code gives, often another (TS
  29.229 defines Cx's `DIAMETER_ERROR_TOO_MUCH_DATA`), so the block is no
  Value Table, whose rows name numbers. Result-Code's and
  Experimental-Result-Code's codes stand together, as the table lists them.
- `; Command:`, `; Application-ID:`, `; Command-Section:` and `; From:`
  find the command as an Information Elements block's do
  ([above](#information-elements)): the answer of the procedure whose
  information-element tables stand in the clause above or beside the
  table's.
- No table says it lists every code an answer may carry, and none lists the
  protocol errors an agent returns.

### Interpreted Constraints

```abnf
interpreted-constraints = "; Type: Interpreted Constraints" NL
                          "; AVP: " avp-name NL
                          ["; Command: " avp-name NL
                           ["; Application-ID: " application-id NL]
                           ["; Command-Section: " section-number NL]
                           ["; Request-Section: " section-number NL]]
                          ["; Within: " avp-name NL]
                          "; Section: " section-number NL
                          ["; Table: " inline-text NL]
                          ["; Page: " 1*DIGIT NL]
                          "; Versions: " versions NL
                          1*reading
versions      = version-bound [".." version-bound]
version-bound = version / "*"
reading       = 1*(quote-line NL) 1*(rule-line NL)
quote-line    = DQUOTE 1*(name-char / SP) DQUOTE   ; as inline-text, escaped
rule-line     = 4SP rule
rule          = length / range / exclude / encoding / predicate / default
              / bits / members / "unique" / values / equals / "absent"
              / "text-only"
length        = "length " bounds SP ("octets" / "digits" / "characters")
range         = "range " bounds
exclude       = "exclude " integer *(", " integer)
bounds        = bound [".." bound]               ; one bound: exactly it
bound         = integer / "*"                    ; "*": open
integer       = ["-"] 1*DIGIT
encoding      = "encoding " codec
              / "encoding element " spec-ref [SP section-number]
                [SP DQUOTE name-text DQUOTE]
codec         = "e164-tbcd" / "plmn-id" / "plmn-id-prefix" / "digits"
              / "labels" / "apn" / "plmn-domain" / "epc-plmn-domain"
              / "ip-address" / "time-zone" / "mac-address"
              / "ip-filter" / "ip-filter-out"
predicate     = predicate-kind SP conditions
predicate-kind = "present-if" / "absent-if" / "requires" / "excludes"
conditions    = conjunction *(" or " conjunction)
conjunction   = condition *(" and " condition)
condition     = ["not "] path [" = " (value-ref / rooted) / " bit " value-ref]
path          = [root "/"] avp-name *("/" avp-name)
rooted        = root "/" avp-name *("/" avp-name)
root          = "request"
value-ref     = integer / enum-name
default       = "default " value-ref
bits          = "bits " ("at-most-one" / "at-least-one") 2*(SP 1*DIGIT)
              / "bits " ("set" / "clear" / "only") 1*(SP 1*DIGIT)
members       = "members " ("at-least-one" / "only") 1*(SP avp-name)
values        = "values " integer *(", " integer) " if " conditions
equals        = "equals " path
```

What a clause states in prose about one AVP's value or presence, as a person
read it: the sentences read, verbatim, each followed by the rules read from
them (TS 29.272 clauses 7.3.35 and 5.2.2.2.1):

```dad
; Type: Interpreted Constraints
; AVP: Context-Identifier
; Within: APN-Configuration
; Section: 7.3.35
; Page: 128
; Versions: 19.6.0
"The Context-Identifier in the APN-Configuration AVP shall identify that APN configuration, and it shall not have a value of zero."
    exclude 0


; Type: Interpreted Constraints
; AVP: Context-Identifier
; Command: Delete-Subscriber-Data-Request
; Application-ID: 16777251
; Section: 5.2.2.2.1
; Table: 5.2.2.2.1/1
; Page: 43
; Versions: 19.6.0
"This element shall be present only if the \"PDN subscription contexts Withdrawal\" bit or the \"PDP context withdrawal\" bit is set in the DSR-Flags."
    requires DSR-Flags bit "PDN subscription contexts Withdrawal" or DSR-Flags bit "PDP contexts Withdrawal"
```

- The block is interpreted: no document prints it as structure, no extractor
  writes it, and a person writes it in the document's interpretations file
  ([below](#interpretations-files)), so only a corrected file of the corpus
  holds one. It stands in clause order after the last block of its clause or
  one before it, beside the clause it reads.
- `; AVP:` is the AVP the rules constrain. `; Command:`, with
  `; Application-ID:` where the file prints the command for several
  applications and `; Command-Section:`, the clause of the command's block,
  where it prints the command more than once for one application or for
  none (TS 29.273's Diameter-EAP-Request for STa and SWd, as an Information
  Elements block chooses), or `; Within:`, a grouped AVP, scopes them to the
  AVP as a member there; a predicate's conditions are its siblings. With
  neither, the rules hold wherever the document reads the AVP.
- A path names an AVP from the scope through the grouped AVPs before it,
  one name a level: `MIP6-Agent-Info/MIP-Home-Agent-Host` is the
  MIP-Home-Agent-Host of the block's command's MIP6-Agent-Info, as the
  document reading the grouped AVP prints its body. With no scope a path
  starts at the block's own AVP. Of the AVPs a path names, any one meeting
  a condition does.
- In a block scoped to an answer, a name after `request/` is a member of
  the request the answer answers: the same command code with the R bit,
  under the same application, printed at `; Request-Section:` where the
  file prints that request more than once there (TS 29.273's Diameter-EAP-
  Request for STa and SWd); otherwise the one print is meant, and the
  directive is not written.
- A quote is one or more sentences of the clause, or an information
  element's description where `; Table:` names its table, as printed once
  whitespace is collapsed; `\"` and `\\` are its escapes. `; Versions:` is
  the range of the document's versions the quotes were checked against.
- `length` counts the payload's octets, the digits an encoding carries, or a
  text's characters. `range` and `exclude` bound an integer value.
- `encoding` names the layout, one of a closed set of codecs
  ([consumers.md](consumers.md#interpreted-constraints) gives each one's
  clause). `element` is another document's information element carried
  whole, with the clause and name the clause gives.
- A predicate ties the AVP's presence to conditions on its siblings, `or`
  joining alternatives and `and` the conditions of one, which binds
  tighter, with no parentheses: `present-if Result-Code = DIAMETER_SUCCESS
  and TWAN-Connection-Mode bit MC-MODE`; `not` before a condition says it
  does not hold: `present-if` (present when one holds), `absent-if`
  (absent when one holds), `requires` (one holds when it is present) and
  `excludes` (none holds when it is present). A condition is a sibling's
  presence, or the request's member's, its value, a number or a name its
  values or result codes give it, or the value of a member of the request
  (`Result-Code = request/Result-Code`, octet for octet), or a bit, by
  number or by its bit table's name. Of the request's members of a name,
  any one meeting it does. A name is spelt as its table spells it, quoted
  where it is no `avp-name` (`Event-Trigger =
  "H(E)NB_LOCAL_IP_ADDRESS_CHANGE"`) or is digits only, which would read as
  a number (TS 29.272's Report-Amount `"16"`, its value 4); one beginning
  with a digit is bare (`3GPP_PS_DATA_OFF_CHANGE`).
- `default` is what the AVP is read as when absent, a number or a name its
  values give. `bits` is a rule on the AVP's own bits, numbered as its bit
  table numbers them, bit 0 the least significant, an OctetString's octets
  read as one big-endian number: at most one of them set, at least one,
  each set, each clear, or none but them set.
- `members` is a rule on the members a grouped AVP holds: at least one of
  them present (one name: it is present), or none but them.
- `unique` says no two of the grouped AVPs `; Within:` names, in one body,
  hold the AVP with the same value; it needs `; Within:`.
- `values` restricts the AVP's integer value to those listed when one of
  the conditions holds, conditions as a predicate's.
- `equals` says the AVP holds the value, octet for octet, of the one the
  path names wherever both are present: `equals request/User-Name`, an
  answer echoing the request's.
- `absent` says the AVP is never present in the scope: a member of the
  command, or of the grouped AVP, or with no scope anywhere the document
  reads it. A grouped AVP's members are in its scope, not its command's:
  TS 29.273's SWx commands carry no Session-Timeout, which their
  Non-3GPP-User-Data does.
- A block scoped to a command or grouped AVP names one of its members, or
  an AVP its `* [ AVP ]` admits: clause 5.2.4 of TS 29.273 forbids
  Auth-Session-State in STa commands that do not print it.
- `text-only` is a rule the quote states that no kind expresses: one
  depending on an earlier message, a feature, the node or the subscriber,
  or on more than the kinds can say. It is a reading's only rule.

### Interpretations files

```abnf
interpretations = interprets-line *(2*NL interpretation) NL
interprets-line = "; Interprets: " inline-text   ; as spec-line's title
interpretation  = "; Type: Interpreted Constraints" NL
                  "; Id: " id NL
                  ; then interpreted-constraints's lines after its
                  ; ; Type:, without ; Page:
id              = 1*(LOWER / DIGIT) *("-" 1*(LOWER / DIGIT))
LOWER           = %x61-7A
```

A `.dadx` file, `edits/interpretations/TS29.272.dadx`, holds what a person
read in one document's prose, merged into its corrected copies as the corpus
is rebuilt ([constraints.md](constraints.md#the-interpretations-file)). It is
no document: the corpus loaders read `*.dad` and refuse it by name.

```dad
; Interprets: 3GPP TS 29.272
;; Read in clause order.


; Type: Interpreted Constraints
; Id: ue-usage-type-range
; AVP: UE-Usage-Type
; Section: 7.3.202
; Versions: 18.7.0..19.6.0
"The allowed values of UE-Usage-Type shall be in the range of 0 to 255."
    range 0..255
```

- `; Interprets:` names the document as its files' `; Specification:` does,
  and the file is named by its spec-ref.
- `; Id:` is unique in the file; the corrected file's `;; interpreted:` note
  cites the block by it.
- No block has a `; Page:`, which is read from each copy's source.
- Each block's `; Section:` sorts at or after the one above it
  (`ast.section_sort_key`): the blocks follow the document's clause order.
- Comments follow the `.dad` rules and stay in the file.

## Text values

```abnf
inline-text   = VCHAR *(%x20-10FFFF) VCHAR / VCHAR
```

One line that begins and ends with a non-space character, so it survives the
round trip, including text that looks like a directive.

## Semantic constraints

Checked by the AST after parsing:

- `RESERVED first-last`, `RESERVED first..last` and
  `VENDOR-SPECIFIC first-last` require `last >= first`; a bounded `min*max`
  requires `max >= min`.
- A flag appears in at most one of Must, May, S.not and M.not.
- A row has exactly one cell per declared column and no value for an
  undeclared one (a mark column's blank cell is no value). The name column
  is required (Name and From for re-used tables, Code for registries).
  Columns are not repeated, and tables are not empty.
- `; Name:` equals the name in the block's header rule.
- `; Applies-To:` names a clause at most once.
- An Undefined AVP block's `; Name:` is not `AVP`.
- A Value Table has at least one row. A clause or origin in a row requires
  `result-codes`; a mark, `; Application:` and `; Feature-List-ID:` require
  `features`.
- An Interpreted Constraints block's bounds are ordered and an `exclude`
  names a value once; `; Application-ID:` needs `; Command:`, which excludes
  `; Within:`; a condition tests a value or a bit, not both; only `element`
  takes a document, and it needs one; a `bits` rule names a bit once, and
  two or more for `at-most-one` and `at-least-one`; a `members` rule names a
  member once, a `values` rule a value once; `unique` needs `; Within:`; a
  rule reading the request needs `; Command:`, and `; Request-Section:` a
  rule reading the request; a value read from another AVP starts at a root;
  `not` is said once of a condition.
- Command codes are 24-bit. Codes, vendor ids, application ids, enum values,
  value-table numbers and Feature-List-IDs are 32-bit. Page numbers are 32-bit
  and at least 1.
