# The extractors

Two extractors produce the same `.dad` AST:

- `extractor/tgpp_docx/` reads 3GPP `.docx` specifications, and oneM2M's,
  which follow the same Word conventions. Page numbers come from the matching
  ETSI PDF.
- `extractor/rfc_text.py` reads RFC plain text.

Documents published only as PDF are [transcribed](#transcriptions) by hand.

## How extraction works

1. Load the document's [source declarations](#source-declarations) from
   `edits/sources/<SpecRef>.toml`.
2. Walk the document in order: a docx's paragraphs and tables under its
   numbered headings, or an RFC's lines with page furniture removed. Skip
   [excluded](#exclusions) clauses.
3. Apply input patches to the normalised text of each paragraph, cell and
   title.
4. Recognise definitions by their exact printed structure. Readings that could
   misfire on another document run only where a [quirk](#quirks) enables them.
5. For a docx, `attach_pages` adds `; Page:` from the PDF's bookmark outline,
   and refuses a PDF whose cover names another document or version.
6. Check that every declaration fired as declared, and write the raw file.
   Corrections in `edits/corrections/` then make the corrected file
   ([corrections.md](corrections.md)).

The docx package keeps one module per stage, each named with a leading
underscore. Its `__init__.py` lists what it offers.

## What a file records

A `.dad` file records everything the document says about a definition: names,
codes, vendor-ids, types, flag rules, value lists and ABNF bodies. Prose is out
of scope; `; Section:` points at the clause.

The extractor keeps a block another block contradicts, a block that looks
redundant, and a value that is wrong. The linter reports contradictions, and
the edit layers fix values while the unedited reading stays on disk. The only
thing left out is an [excluded](#exclusions) clause, and the file says so.

## Source declarations

Each document has one TOML file, `edits/sources/<SpecRef>.toml`, holding
`[[patch]]`, `[[quirk]]` and `[[exclude]]` blocks. Every block needs a `reason`
and may carry a version range. A block that does not fire as declared fails the
extraction.

`reason` is prose, and a multi-line string is collapsed to one line. Every
other field is exact, so `find` and `replace` stay on one line however long
([CONTRIBUTING.md](../CONTRIBUTING.md#conventions)).

### Input patches

A patch fixes a typo that breaks extraction, or a name misspelt only in case
against its defining clause.

```toml
[[patch]]
find = "M. V"
replace = "M, V"
exact = true               # match the whole text unit, not a substring
count = 1                  # must apply exactly this many times
section = "7.3"            # optional: only in this clause and those under it
reason = "flags cell typo in table 7.3.1/1"
first_version = "18.6.0"
last_version = "18.6.0"
```

`find` must be non-empty. A count mismatch raises `PatchError`. Bounds are
inclusive, an omitted bound is open, and trailing zero components are
equivalent. Corrections write the same range as one string (`"18.6.0"`,
`"18.0.0..18.2.0"`). RFCs have no version, so every declaration applies to
them.

### Releases

3GPP may change a document's template between releases, and with it every
quirk and typo. So each release's copy of a document gets its own
declarations. For a version, the extractor uses:

1. the declarations of the version's own release, if any range spans it;
2. otherwise those of the newest declared release below it;
3. otherwise none.

Within the chosen release a range is advisory. A version outside it still
applies the declaration, with a warning, and `seanchai corpus regenerate
--expand-ranges` widens the range.

When choosing the release, a range with no upper bound counts only for its
lower bound's release, and a range with no bounds does not count. Both still
apply to every copy they cover. A declaration ranged to a new release alone
takes the older release's declarations out of that release's reading, so write
it unranged until `--expand-ranges` has run.

Corrections and acceptances are scoped the same way, per module.

### Quirks

A quirk turns on, by name, a reading that could misfire on a document it was
not written for:

```toml
[[quirk]]
name = "prose-avp-codes"
reason = "the AVP tables print no Code column; each clause prints its code"
```

A quirk takes no parameters. An unknown name fails at load, and a quirk that
fires zero times fails. Readings of exact structure, such as header spellings
and rule grammars, need no quirk, because input they do not recognise fails on
its own. Closed vocabularies need none either: "Y"/"N" or a dash in an Encrypt
cell, and "Must"/"Must not" for the M bit.

The vocabularies are the `QUIRKS` mappings in `extractor/tgpp_docx/_quirks.py`
and `extractor/rfc_text.py`. The tables name one document that needs each
quirk; `grep -l '"<quirk>"' edits/sources/*.toml` lists them all.

#### Docx: structure and commands

| Quirk | Reads | Example |
|---|---|---|
| `prose-application-ids` | a sentence stating the application id the command headers omit ([below](#application-scopes)) | TS 29.212 |
| `message-headings` | a `Name message` heading over a rule spelled with the abbreviation, `<ACR> ::=` | TS 32.299 |
| `message-tables` | a command printed as a table ([below](#commands-printed-as-tables)) | TS 32.299 |
| `rfc-command-rules` | a rule no intro names, named by its command code from the RFC | TS 29.234 |
| `procedure-commands` | command names in a procedure clause's intro or step, or a heading such as `AAR Command` over `<AA-Request> ::=` | TS 29.273 |
| `command-reference-only` | a command clause holding only a pointer | TS 29.273 |
| `message-only` | commands and re-used AVPs with no local AVP table | TS 29.330 |
| `access-type-headings` | `Name AVP (All access types)` headings | TS 29.212 |
| `spaced-heading-numbers` | a space before the tab after a heading's number | TS 29.234 |
| `body-clause-headings` | a clause heading printed as a body paragraph | TS 32.299 |
| `list-numbered-headings` | clause numbers that exist only in Word's list numbering | oneM2M TS-0004 |
| `spaced-rule-operator` | `:: =` | TS 29.229 |
| `abnf-comments` | a member line's trailing `; comment`, dropped | TS 29.209 |
| `struck-rules-unused` | struck members, which the legend says are unused ([below](#abnf-bodies)) | TS 32.299 |
| `elided-members` | a body's lone `…` or `...` line, kept as a comment | TS 29.273 |
| `reprinted-avps` | a grouped rule under "The content of X according IETF RFC n [m] is:" ([below](#re-printed-rules)) | TS 29.109 |
| `prose-avp-origins` | "The X AVP is defined in" as a re-used row ([below](#avp-origins-in-prose)) | TS 29.329 |
| `bare-avp-citations` | with `prose-avp-origins`, "See 3GPP TS 29.229 [6] clause 6.3.56." as a whole clause | TS 29.329 |
| `trailing-result-codes` | a result code printed as the last sentence of the previous code's paragraph | TS 32.299 |
| `see-result-code-origins` | a result code's origin named with "see" alone ([below](#result-codes)) | TS 29.273 |

#### Docx: tables

| Quirk | Reads | Example |
|---|---|---|
| `physical-avp-columns` | an AVP table whose rows change grid spans, by physical cells | TS 32.299 |
| `physical-reused-columns` | the same for a re-used table | TS 29.273 |
| `independent-avp-tables` | AVP and re-used tables kept apart instead of paired | TS 29.273 |
| `vendor-avp-tables` | tables of other vendors' AVPs as re-used blocks | TS 32.299 |
| `refer-type-cells` | a `refer [n]` type cell as a re-used row citing reference n | TS 32.299 |
| `referred-type-sentences` | such a row's type from its clause's "is of type T" | TS 32.299 |
| `note-defined-in-rfc` | an AVP-table note naming a defining RFC as a re-used row | TS 29.229 |
| `wildcard-avp-row` | an `AVP` row with code `*`, kept as a comment | TS 32.299 |
| `vendor-id-sentence` | V under Must from "shall be set to 3GPP (10415)" for rows with blank flag cells | TS 29.389 |
| `dotted-flags` | a flags cell `M.V` | TS 29.212 |
| `type-short-forms` | `DiamIdent` and `DiamURI` | TS 32.299 |
| `unknown-type-tokens` | a type cell naming no Diameter type, kept quoted (`"Integer"`) | TS 29.230 |
| `reference-cells` | a Reference column: a bracketed clause as the row's section, a document as a re-used row | oneM2M TS-0004 |
| `document-clause-cells` | a clause cell naming another document as a re-used row ([below](#radius-attributes-as-avps)) | TS 29.561 |
| `origins-by-reference` | a From cell printing ETSI's document as 3GPP's, read through clause 2 | TS 29.212 |
| `clause-parenthetical` | a trailing parenthetical in a clause cell, `16.4.7 (see Note)`, dropped | TS 29.061 |
| `access-type-column` | an `Acc. Type` mark column ([below](#mark-columns)) | TS 29.212 |
| `applicability-column` | an `Applicability` mark column | TS 29.214 |
| `reference-points-column` | an `Applicable Reference Points` mark column | TS 29.061 |
| `command-columns` | `Used in` columns ACR, ACA, CCR, CCA as per-command marks | TS 32.299 |
| `worded-marks` | mark cells split at commas only | TS 29.468 |
| `registry-tables` | allocation tables as `Registry` blocks ([below](#the-registry)) | TS 29.230 |
| `reserved-range-notes` | "The AVP codes from a to b are reserved for P" as reserved ranges | TS 29.230 |
| `placeholder-codes` | a registry code cell printing a placeholder (`xx1`), kept quoted | TS 29.230 |

#### Docx: enumerated values

Each departure from `NAME (n)` needs its own quirk, and a line with two needs
both.

| Quirk | Reads | Example |
|---|---|---|
| `worded-enum-values` | `Device Trigger Request (1)` | TS 29.368 |
| `comma-enum-labels` | a worded label with a comma, kept quoted | TS 29.140 |
| `dashed-enum-values` | `- AUDIO (0)` | TS 29.272 |
| `hex-enum-values` | `OTHER (0xFFFFFFFF)` | TS 29.214 |
| `punctuated-enum-values` | a comma or full stop after the value | TS 29.338 |
| `described-enum-values` | `NO (0) The sending node …` | TS 29.109 |
| `label-after-enum-value` | `- (0) Private user identity.` | TS 29.109 |
| `run-on-enum-values` | several values in one paragraph | TS 29.229 |
| `value-first-enums` | `0 PS to CS Transfer` | TS 32.299 |
| `value-last-enums` | `MONETARY<tab>0` | TS 32.299 |
| `bracketed-enum-values` | `[0] called party` | TS 32.299 |
| `dotted-enum-values` | `0. SUBMISSION` | TS 32.299 |
| `list-numbered-enum-values` | numbers that exist only in Word's list numbering | TS 32.299 |
| `prose-enum-values` | `EVENT_RECORD (value 1)` in a sentence | oneM2M TS-0004 |
| `external-enum-values` | a clause saying where its values are defined, as `; Values:` | TS 29.212 |

#### RFC

| Quirk | Reads | Example |
|---|---|---|
| `prose-avp-codes` | codes from each clause's defining sentence, for tables with no Code column | RFC 7155 |
| `clause-avp-table` | the AVP index from defining sentences, for a document with no AVP table | RFC 4072 |
| `radius-attribute-table` | RADIUS attributes cited as AVPs: name, code and section | RFC 4590 |
| `radius-avp-codes` | table codes from RADIUS Type fields | RFC 5580 |
| `mixed-table-borders` | open flag header lines above boxed rows | RFC 5580 |
| `split-avp-tables` | a table of names and flags joined to the table of codes before it | RFC 4740 |
| `reused-avp-tables` | a table under a "Reused ... AVPs" clause as a `Reused AVPs` block | RFC 6736 |
| `note-avp-origins` | rows whose Defined cell cites "Note 1" as re-used rows | RFC 6738 |
| `prose-avp-origins` | "The X AVP is defined in" as a re-used row | RFC 8583 |
| `prose-cleared-flags` | M and V bits a clause says are cleared | RFC 6942 |
| `prose-catchall-row` | the "Rest of the AVPs" rows ending a table, ignored | RFC 5778 |
| `bare-name-continuation` | a wrapped name's continuation printed outside the box | RFC 4004 |
| `ragged-separator` | a horizontal rule with a stray space in it | RFC 8583 |
| `boxed-table-legend` | one-cell legend rows under a table, skipped | RFC 5866 |
| `type-short-forms` | `DiamIdent`, `IPFiltrRule`, RFC 4740's `U32` and the like | RFC 6733 |
| `parenthesized-enum-values` | `Name (n)` lines | RFC 6734 |
| `parenthesized-value-first` | `(0): QoS-Desired` | RFC 5777 |
| `bulleted-enum-values` | `o  NAME (n)` | RFC 4740 |
| `worded-enum-values` | value names of several words | RFC 4005 |
| `external-enum-values` | a clause saying where its values are listed, as `; Values:` | RFC 6733 |
| `cause-mapping-table` | values from a RADIUS-to-Diameter mapping table | RFC 4005 |
| `registry-enum-values` | values numbered only in the IANA section | RFC 5778 |
| `elided-members` | a body's lone `…` or `...` line, kept as a comment | RFC 5778 |

### Exclusions

An exclusion leaves a clause of a 3GPP docx unread, with every clause under it.
Declare one only when the document has not finished the clause and no reading
could state what it says. A clause that is wrong is read as printed and
corrected.

```toml
[[exclude]]
section = "8"              # the clause and every clause under it
name = "Sh-ee"             # what the file's note calls it
reason = "..."
first_version = "19.1.0"
```

The walk skips from the clause's heading to the next heading outside it,
numbered or not. A patch or correction written for the clause then fails, so
remove the clause's edits with it. Both files name what was left out, after
the header:

```dad
;; excluded: clause 8 (Sh-ee), see TS29.329.toml
```

An exclusion that leaves nothing out fails, and so does one declared for an
RFC or a transcription. TS 29.329 V19.1.0's clause 8 is excluded because it
names its application id `xx1` and gives its commands codes TS 29.230
allocates to others.

A range with no upper bound covers later versions too, and nothing warns when
one of them finishes the clause. A version upgrade re-reads the exclusions
([development.md](development.md#version-upgrades)).

## The 3GPP docx extractor

### What it recognises

| Printed | Block |
|---|---|
| `x.y.z Name (ABBR) Command` heading and `::= < Diameter Header: … >` | `Message` |
| `<answer-message> ::= < Diameter Header: code, ERR [PXY] >`, under any heading | `AnswerMessage` |
| `x.y.z Name AVP` heading and `::= < AVP header: … >` | `GroupedAvp` |
| `x.y.z Name AVP` heading, "is of type Enumerated", `Name (n)` items | `EnumeratedAvp` |
| a table headed "AVP Flag rules" | `AvpTable` |
| a "re-used Diameter AVPs" table | `ReusedAvps` |
| a "Bit, Name, Description" table | `bits` `ValueTable` |
| a "Feature bit, Feature, M/O, Description" table | `features` `ValueTable` |
| a clause titled "Result-Code AVP values" or similar | `result-codes` `ValueTable` |
| a sentence stating the application id | `ApplicationScope` |

Bold runs mark the document's own AVPs. A rule name may be bracketed and the
`::=` spaced. A message heading with no rule is not a definition. Any other
line naming `<answer-message>` fails. `w:smartTag` elements are unwrapped
first, because python-docx reads only a paragraph's direct runs.

### Application scopes

Under `prose-application-ids`, a sentence stating the application id becomes
an `ApplicationScope` for the interface clause it sits in (`; Applies-To: 5.*`
for TS 29.212 clause 5.1). If two sentences under one interface clause state
two applications, each applies to its own subclause. Six wordings are
recognised. The file lists the scopes before the commands.

### Enumerated values

Values are classified by content, not paragraph style.

- "Value n is reserved" is a reserved range.
- A range left to vendors or operators, with no `not`, `no`, `never` or
  `except` in its words, is a vendor-specific range described by those words.
  Any other range is reported.
- A value or range labelled `Void`, in any case, is a `; VOID` line.

An enumerated AVP takes its code from the AVP table and its vendor-id from the
document's grouped-AVP headers, or 10415 if there are none. Conflicting
vendors are an error.

### Bit and feature tables

The table belongs to the AVP its clause heads. "Bit | Description", with the
name as description, and "Event Type" or "Requirement" in place of "Name" read
the same way. A features table takes its application and Feature-List-ID from
its caption ("Features of Feature-List-ID 1 used in S6a/S6d") and belongs to
`Feature-List` unless the clause heads another AVP.

Columns are read by label. A full-width row is a note. A row naming no number
(`1-31 None`) is a `;;` comment. A table with no rows left warns and makes no
block. A features table's `void` row stays a row (`void = 18`).

### Result codes

In a result-code clause and its subclauses, each heading or line that is a
name with an underscore and a number is a code: `DIAMETER_X (5001)`,
`DIAMETER_X (5001):`, `DIAMETER_X 4010` or `4010 DIAMETER_X`. A clause naming
the Experimental-Result AVP holds experimental codes, whatever its title. In
one, "the following Result-Code AVP value defined in IETF RFC 8506" starts a
`Result-Code` table, until a line names the experimental codes again. A heading
with an unallocated number (`(56x1)`) is a `;;` comment.

A code is another document's only where its text says that document defines
it, either on the code's own line ("This error code is defined in 3GPP TS
29.229 [6]") or in the intro over the codes ("the following
Experimental-Result AVP values defined in 3GPP TS 29.273 [48] are
applicable:"). The row takes that document as its origin.

- A code whose own text names the document itself is local, even under an
  intro naming another.
- A code given two origins fails, and so does one whose text and intro
  disagree.
- A citation of a document no reading knows says nothing.

Under `see-result-code-origins`, two more shapes name an origin: a line that
is only "See 3GPP TS 29.229 [6] clause 6.2.2.11.", and a line ending "(see TS
29.229 [24])." A pointer to a procedure names no origin.

### AVP origins in prose

Under `prose-avp-origins`, a citation such as "The X AVP is defined in" becomes
a re-used row, in a block at the clause stating it, with no `; Table:`. The
local table's code, type and flags are kept, and a code the origin does not
give is a `reused-code-conflict`. A reference to an encoding or to value
meanings is no origin. An unnamed "this AVP" takes the clause's AVP; a clause
with several candidates fails.

### Mark columns

A mark column's cells become the row's marks. A cell is split at commas and
spaces, or at commas only under `worded-marks`. A parenthetical stays with the
mark before it. A dash means no marks and a blank cell means none were stated.

### ABNF bodies

ABNF is read line by line. A paragraph is split at its manual line breaks, and
bold and strikethrough belong to the line. Blank lines inside a body are
skipped when another member follows. A line holding several members is read as
several.

A body ends at a blank line, the next rule, a sentence, or a change of
paragraph style on a line with no ABNF. Any other line fails, naming its
section and text, and so does a member printed after the body ended. Fix a
typo with an input patch; add a reading with a quirk.

A struck member carries `; strikethrough` and a bold one `; bold`. A line only
partly struck fails. A struck member stays a member and warns, except under
`struck-rules-unused`, where the line is commented out:

```dad
<Accounting-Request> ::= < Diameter Header: 271, REQ, PXY >
        < Session-Id >
        ...
        [ Acct-Application-Id ]
;;      [ Vendor-Specific-Application-Id ] ; strikethrough
        [ User-Name ]
```

Under `elided-members`, a lone `…` line is kept the same way, as `;; …`.

### Tables

- A table needs a caption the extractor recognises, matched as a dotted label
  (`Table 7.3.1/1`, `Table 6.3.1-1`, `Table B.1.1`).
- Column labels are matched by a spelling map. "Comments", "Description" and
  "Comment" columns are dropped as prose. Any other unmodelled column, or a
  mark column whose quirk is not declared, warns.
- A row whose code cell is a NOTE reference gets no code. A header followed
  only by blank cells contributes nothing and warns.
- AVP and re-used tables are paired in document order, and counts that cannot
  pair are an error. An AVP table with no re-used table gets its own re-used
  block.
- A From cell's publisher prefix is optional for 3GPP and IETF. A bare clause
  number cites the document itself, and such a row is no re-use.
- A flag named twice (`M,M`) fails.

### Other conventions

- A command code is a number. Where a document prints a placeholder, an input
  patch supplies the code the document states elsewhere.
- `Page:` is where the section starts in the PDF's bookmark outline.
- An enumerated AVP listed as re-used, or referenced from an AVP-table NOTE,
  gets no local definition. A grouped AVP printed in full and also listed as
  re-used keeps its body, and the linter reports the conflict.
- `attach_pages` falls back to the PDF's Title metadata when the cover text
  does not read.

Other document shapes the code handles are explained in its comments.

### Commands printed as tables

Under `message-tables`, TS 32.299 V11.20.0 clause 6.4.5 prints a command as
`<Diameter Header: 258, PXY>` and its members, with a "Used in 3GPP" column read
as the strike. Clause 6.4.4 prints RAR as an `AVP`, `Category`, `Description`
table with no header. An input patch supplies the header, citing RFC 6733
clause 8.3.1, and the extraction fails without it. Category M reads as `{ }`,
OC as `[ ]`, and a dash as a struck member. Corrections supply the positions
and repetitions a category cannot state:

```dad
<Re-Auth-Request> ::= < Diameter Header: 258, REQ, PXY >
;; patched: the table prints no Diameter header, see TS32.299.toml
        < Session-Id > ;; corrected: (TS32.299.py#rel11-rar-session-id-position)
        { Origin-Host }
```

### Re-printed rules

Under `reprinted-avps`, TS 29.109 clauses 4.2, 5.2 and 5.4 print RFC 6733's
`Vendor-Specific-Application-Id` rule after a command. Each copy becomes a
`Reprinted AVP` block, with its glosses kept as `;;` comments:

```dad
; Type: Reprinted AVP
; Name: Vendor-Specific-Application-Id
; Section: 4.2
; Page: 15
; From: RFC6733
Vendor-Specific-Application-Id ::= < AVP header: 260 >
     1* [ Vendor-Id ] ;; 3GPP is 10415
     *1 { Auth-Application-Id } ;; 16777221
     *1 { Acct-Application-Id } ;; Omitted
```

A `Reprinted AVP` is not a definition: `Model.definition((0, 260))` answers
with RFC 6733's, and `Model.avps("TS29.109")` does not list it. The linter
holds each copy to the document it names
([linter.md](linter.md#cross-file-rules)). A grouped rule in a procedure clause
without the introducing sentence fails.

### RADIUS attributes as AVPs

TS 29.561 defines AVPs as RADIUS sub-attributes. Its clause 11.3 tables are not
read. Table 12.4-1 lists the AVPs, with a clause in `Section defined` for the
25 the document adds and a document for the 31 it takes from TS 29.061 and TS
29.229. Every row stays in the `AVP Table`, and `document-clause-cells` adds a
re-used row for each of the 31. Table 17.4-1 is read the same way.

### The registry

TS 29.230 allocates codes. Under `registry-tables`, these tables become
`Registry` blocks, read by physical cells: "Application identifier" (4.1),
"Command code value" (5.1/1 to 5.1/4), "AVP Code" (7.1) and "Experimental
Result Code" (8.1.2 to 8.1.4). A "Specified in" cell cites one or more
documents. A dash or a blank Data Type cell is no type. A row with no code
warns and is skipped.

Input patches fix broken cells and names that differ from the defining
clause's in case alone. Other misnamed rows are corrected
([linter.md](linter.md#standing-findings)).

### oneM2M TS-0004

The downloader fetches the Word original of V2.35.0 and converts it. Only
annex A, the Mch binding to Diameter accounting, holds definitions.

- The cover reads as `; Specification: oneM2M TS-0004` and `; Version:
  2.35.0`. No PDF exists, so there is no `; Page:`.
- `; Vendor-ID:` is 45687, from clause A.4.
- Table A.4-1 prints each row's vendor, read as `Vendor-ID`.
- Input patches and corrections supply the command names, the `Mch`
  application scope, the V flags and `M2M-Information`'s vendor.

## Out of scope

TS 29.228, 29.328, 29.213 and 29.305 hold procedures and IE mappings, with no
Diameter ABNF or AVP tables. TS 29.201 carries Rx over REST as an XML schema.
The catalog marks each `out_of_scope`, and `regenerate --add` refuses it with
that field's words. TS 32.296 prints unallocated codes and is not in the
catalog. Nothing in the corpus cites any of them.

## The RFC plain-text extractor

It reads the same definitions as the docx extractor. Every file states
`; Vendor-ID: 0`, with no `; Version:` and no `; Table:`.

- Page furniture is a footer line ending `[Page N]`, a form feed, and a running
  header found by position. `; Page:` numbers are the RFC's.
- A line whose name fragment sits at the Attribute Name column starts a row; a
  deeper line continues it. Each cell must be on one line.
- A header repeated after a page break continues the table; a header after
  prose starts another.
- Boxed and partly boxed tables are both read. A row starts where the table's
  first row does.
- Header labels are whole spellings, and an unrecognised header fails. Stacked
  labels (`MUST` over `NOT`) are read generically. Occurrence tables are not
  read.
- A definition anchors on a section title that is a bare name or `Name AVP`. A
  prose title counts only if the local table's row typing the AVP Grouped cites
  that clause.
- A body printed for another document's AVP is kept for the linter to compare.
- Bodies end as in the docx extractor. Blank lines a page break leaves inside a
  body are skipped.
- Enumerated values are read under a name-titled section when the local table
  types the name Enumerated. Value names are all-caps unless a quirk says
  otherwise.
- Result codes are read in a clause titled `Result-Code AVP`, `Result Code AVP
  Values`, `Extension to the Result-Code AVP Values` or `Additional Result-Code
  AVP Values`, or under one, in shapes such as `DIAMETER_SUCCESS 2001` and
  `RESOURCE_FAILURE (4014)`. Every code is `Result-Code`'s. Bit masks are not
  read.
- RFC 6733 section 7.2's `<answer-message>` becomes an `AnswerMessage`.
- Application scopes come from corrections, since no two RFCs word theirs
  alike. So do RFC 4590's Diameter types and flag rules
  ([corrections.md](corrections.md#operations)).

## Transcriptions

A document published only as PDF is copied by hand into
`edits/transcriptions/<SpecRef>.dad`, in `.dad` notation, with the header
`; Transcribed: by hand from <the PDF>`. The corpus holds transcriptions of
ETSI ES 283 026, 283 034 and 283 035; ETSI TS 183 017, 183 020, 183 033,
183 059-1 and 183 066; 3GPP2 X.S0013-006, -013 and -014 and X.S0057; and
OMA-DDS-Charging_Data.

A transcription goes through the same steps as an extraction:

1. The transcription copies what the document prints, misprints included.
2. Input patches in `edits/sources/<SpecRef>.toml` apply to its lines. A
   patch's `section` is the `; Section:` of the line's block. The patched text
   must parse, and is the raw file.
3. Corrections make the corrected file.

`tests/test_transcription.py` pins each raw file to its patched transcription.

Give each construct the shape the docx extractor gives it:

- commands and grouped AVPs as their ABNF prints them, bold members `; bold`,
  ABNF comments as trailing `;;` comments;
- the AVP table as an `AVP Table`, its NOTE rows as `;;` comments;
- an enumerated clause as an `Enumerated AVP`;
- a table of imported AVPs as `Reused AVPs` with Name, Code, From and Type, and
  any flag rules it restates in a `;;` comment above it;
- an application id stated in prose as an `Application Scope`.

Leave out clause prose, the defining sentence of a simple-typed AVP, result
codes, and informative annexes, unless an annex is the only definition of what
it prints.

A spec-ref keeps no 3GPP2 revision letter (X.S0057-0, -A, -B), so the
rendering's name in `; Transcribed:` states the revision. `regenerate` checks
it against the file's number and version, and `corpus.revision` reads it
([linter.md](linter.md#resolving-an-origin)). A part of a series is its own
document: ETSI's TS 183 059-1 is `ts18305901-020101`. A 3GPP2 page is the
number its footer prints.

## Strictness

Every extraction failure derives from `ExtractionError`, including
`PatchError`. Non-fatal problems go to a `warnings` list, which the CLI prints
to stderr even when a later stage fails. The docx and the PDF must be the same
document and version, because the downloader can fall back to an earlier ETSI
rendering.
