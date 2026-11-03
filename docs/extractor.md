# The extractors

Two extractors produce the same `.dad` AST: `extractor/tgpp_docx.py` for
3GPP `.docx` specifications (page numbers attached from the matching ETSI
PDF) and for oneM2M's, which follow the same Word conventions, and
`extractor/rfc_text.py` for RFC plain text. Both read per-document
[source declarations](#source-declarations) from `edits/sources/`.

## What the extractor does not decide

**A `.dad` file records everything the source document says about a
definition.** The extractor translates, it does not curate: a definition is
never dropped for being redundant, contradicted by another one, or wrong.
The scope is definitions (names, codes, vendor-ids, types, flag rules,
value lists, ABNF bodies), not the document's prose; `; Section:` points at
the clause for anyone who wants that.

Three consequences:

- Do not drop a block because another contradicts it. An AVP defined
  locally and listed as re-used is a real inconsistency; the linter reports
  it.
- Do not drop a block because it looks redundant. A re-printed clause can
  change between versions.
- Do not normalise a value into what it should be. That is what the two
  declared edit layers are for, and they are separate so the unedited
  reading stays on disk.

A consumer can ignore anything the file carries; it can never recover what
the extractor threw away.

## Source declarations

One TOML file per document, `edits/sources/<SpecRef>.toml`, with two block
kinds. Both require a `reason`, carry a version range scoping them to a
release, and must fire exactly as declared: a declaration that stops
matching fails the extraction, because a silently dropped fix is the rot
the accounting exists to catch.

`reason` is prose; a long one is a multi-line string whose whitespace the
loader collapses. Everything else is exact. `find` and `replace` match and
write character for character, so they stay on one line however long
([development.md](development.md#conventions)).

### Input patches

Typos in the source that break extraction, or that misspell a name only in
case against the clause defining it, patched on the normalised paragraph,
cell and title text before parsing:

```toml
[[patch]]
find = "M. V"
replace = "M, V"
exact = true               # match the whole text unit, not a substring
count = 1                  # must apply exactly this many times
section = "7.3"            # optional: only inside this section (prefix)
reason = "flags cell typo in table 7.3.1/1"
first_version = "18.6.0"
last_version = "18.6.0"
```

`find` must be non-empty. A count mismatch raises `PatchError` naming the
version range. Bounds are inclusive, an omitted bound is open, and trailing
zero components are equivalent; corrections declare the same range as one
string (`"18.6.0"`, `"18.0.0..18.2.0"`). A version outside the range but in
its release warns during regeneration and never gates application. RFCs
have no version to compare.

### Releases

A release is where 3GPP may change a document's template, and with it
every quirk and typo, so a declaration speaks for the releases its range
spans. A document the corpus holds in several releases declares for each
copy, and no copy gets another's declarations. A version is read with the
declarations of its own release when any spans it, else with those of the
newest declared release below it (a release upgrade, each warning as within
a release so `--expand-ranges` widens them), else with none. Corrections
and acceptances are scoped the same way, per module.

### Quirks

A quirk enables, by name, a reading heuristic enough to misfire on a
document it was not written for:

```toml
[[quirk]]
name = "prose-avp-codes"
reason = "the AVP tables print no Code column; each clause prints its code"
```

What earns a behaviour a quirk is misfire risk: harvesting facts out of
prose would succeed silently on prose it was never meant to read.
Exact-match structure (header spellings, rule grammars) stays in code,
because unrecognised input fails loudly on its own. A quirk carries no
parameters. An unknown name fails at load, and a declared quirk that fires
zero times fails like a rotted patch.

The vocabulary, with the document that forced each:

**Docx, structure.**

- `prose-application-ids`: the clause stating the application id the
  command headers omit (TS 29.153, 29.154, 29.209, 29.210, 29.211, 29.212,
  29.214, 29.215, 29.217, 29.219, 29.234, 29.343, 29.368, 29.468).
- `message-headings`: an `x.y.z Name message` heading over a rule spelled
  with the abbreviation, `<ACR> ::=` (TS 32.299, oneM2M TS-0004).
- `rfc-command-rules`: RFC commands printed by rule alone under no intro
  naming them, named from the RFC by command code (TS 29.234).
- `access-type-headings`: `Event-Trigger AVP (All access types)` (TS
  29.212, 29.214).
- `spaced-rule-operator`: `:: =` (TS 32.299, 29.229, 29.234, oneM2M).
- `spaced-heading-numbers`: a space before the heading's tab (TS 29.234).
- `body-clause-headings`: a clause heading printed as a body paragraph (TS
  32.299 clause 7.2.135C).
- `struck-rules-unused`: TS 32.299's legend for struck members (below).
- `abnf-comments`: a member line's trailing `; comment` (TS 29.209, 29.214
  Release 7 and 11).
- `list-numbered-headings`: clause numbers that exist only in Word's list
  numbering (oneM2M TS-0004).
- `message-only`: commands and re-used rows, no local AVPs (TS 29.330,
  29.211).
- `command-reference-only`, `procedure-commands`: clauses holding only a
  pointer, and commands named in a procedure clause's intro (TS 29.273,
  29.234).
- `clause-parenthetical`: a trailing parenthetical in a clause cell,
  `16.4.7 (see Note)`, stripped as prose (TS 29.061).

**Docx, tables.**

- `physical-avp-columns`, `physical-reused-columns`: tables whose rows
  change grid spans, read by physical cells (TS 32.299 table 7.2.0.1; TS
  29.273, 29.368, 29.219).
- `independent-avp-tables`: no one-to-one pairing of AVP and re-used tables
  (TS 29.273, 29.215).
- `conflicting-avp-codes`: one name with two codes across tables, both kept
  (TS 29.273).
- `vendor-avp-tables`: tables of other vendors' AVPs read as re-used blocks
  (TS 32.299 tables 7.3.1 to 7.5.1).
- `refer-type-cells`, `referred-type-sentences`: a `refer [n]` type cell
  adds a re-used row citing reference n, and a clause typing such a row
  gives it its type (TS 32.299).
- `note-defined-in-rfc`: an AVP-table note naming a defining RFC becomes a
  re-used row (TS 29.229, 29.329).
- `wildcard-avp-row`: an `AVP` row with code `*` (TS 32.299).
- `vendor-id-sentence`: V from the clause's "shall be set to 3GPP (10415)"
  where the table prints no flags (TS 29.389).
- `dotted-flags`, `type-short-forms`, `unknown-type-tokens`: `M.` flag
  cells; `DiamIdent` and `DiamURI`; a Type cell naming no Diameter type,
  kept quoted (TS 29.230 and 29.234's `"Integer"`).
- `reference-cells`: a Reference column mixing clauses and documents
  (oneM2M).
- `origins-by-reference`: a From cell naming ETSI's document as 3GPP's,
  read through clause 2 (TS 29.212, 29.214).
- Mark columns, each naming the column's legend: `access-type-column`,
  `applicability-column`, `reference-points-column`, `command-columns`,
  and `worded-marks` for marks of several words split at commas only (TS
  29.061, 29.368, 29.468).
- `registry-tables`, `reserved-range-notes`: TS 29.230's allocation tables
  ([below](#the-registry-reading)).

**Docx, enumerated values.** Each departure from `NAME (n)` needs its own,
and a line needing two is read only with both: `worded-enum-values`
(`Device Trigger Request (1)`), `dashed-enum-values` (`- AUDIO (0)`),
`hex-enum-values` (`OTHER (0xFFFFFFFF)`), `punctuated-enum-values` (a comma
or full stop after the value), `described-enum-values` and
`label-after-enum-value` (TS 29.109's `NO (0) The sending node …` and
`- (0) Private user identity.`), `run-on-enum-values` (several values in one
paragraph), `comma-enum-labels` (a label with a comma, TS 29.140),
`value-first-enums` (`0 PS to CS Transfer`), `value-last-enums`
(`MONETARY<tab>0`, read only where a tab or run of spaces sets the number
off), `bracketed-enum-values` (`[0] called party`), `dotted-enum-values`
(`0. SUBMISSION`), `list-numbered-enum-values` (numbers in Word's list
numbering), `prose-enum-values` (`EVENT_RECORD (value 1)`, oneM2M) and
`external-enum-values` (a clause saying where its values are defined).

**RFC.** `prose-avp-codes` (RFC 7155), `clause-avp-table` (RFC 4072, 5447,
6734, 6942), `radius-attribute-table` (RFC 4590), `type-short-forms`,
`prose-catchall-row` (RFC 5778), `bare-name-continuation` (RFC 4004),
`ragged-separator` (RFC 8583), `parenthesized-enum-values` (RFC 6734,
7155), `parenthesized-value-first` (RFC 5777), `worded-enum-values`,
`external-enum-values`, `prose-cleared-flags` (RFC 6942),
`mixed-table-borders` and `radius-avp-codes` (RFC 5580),
`cause-mapping-table` (RFC 4005) and `registry-enum-values` (RFC 5778).

Not gated: the "Y"/"N" Encrypt spellings, a dashed Encrypt cell, and
"Must"/"Must not" M-bit short forms, closed vocabularies that cannot be
misread.

## The 3GPP docx extractor

Walks paragraphs and tables in document order under numbered headings:

- A sentence stating the application id the command headers omit becomes
  an `ApplicationScope` applying to the clause it sits in (`; Applies-To:
  5.*` for TS 29.212's clause 5.1). Five wordings are recognised; the file
  lists the scopes first, before the commands.
- `x.y.z Name (ABBR) Command` heading plus `::= < Diameter Header: … >`
  becomes a `Message`; per-run bold marks the document's own AVPs. Message
  headings without a rule (TS 32.299's pointers to RFC 6733) are not
  definitions.
- `x.y.z Name AVP` heading plus `::= < AVP header: … >` becomes a
  `GroupedAvp`. The rule name may be bracketed and the keyword spaced.
- `x.y.z Name AVP` heading whose intro says "is of type Enumerated", with
  `ValueName (n)` items, becomes an `EnumeratedAvp`. Values are classified
  by content, not paragraph style. "Value n is reserved" notes become
  reserved ranges. A range whose words leave it to vendors or operators,
  with no `not`, `no`, `never` or `except`, is a vendor-specific range
  keeping the words as its description; a range reserved with no such
  wording is a reserved range; any other range is reported. A clause that
  says where its values are defined instead of listing them gets that
  citation as `; Values:`, in the document's words.
- The table with the "AVP Flag rules" header becomes an `AvpTable`. A row
  whose code cell is a NOTE reference gets `code=None`. A table whose
  labelled header is followed only by blank cells contributes nothing and
  warns (TS 29.330 table 6.3.1-1).
- The "re-used Diameter AVPs" table becomes `ReusedAvps` with M-bit
  overrides, and the code and type where the table prints them.
- `prose-avp-origins` keeps definition citations ("The X AVP is defined in",
  "See ... for the definition of this AVP") as re-used rows beside the citing
  AVP table, like NOTE-derived origins. The local table's code, type and flag
  rules remain intact. References to encodings or value meanings do not
  establish an AVP's origin. An unnamed "this AVP" takes the clause's AVP: a
  clause with several candidates fails, and a sentence after another AVP's name
  is skipped. RFC 8583 uses the same quirk for "The SourceID AVP is defined in
  [RFC8581]"; its re-used block takes the citing table's section as its label
  when the table has no caption.
- `bare-avp-citations` adds TS 29.329's pointers, which say no "definition":
  "See 3GPP TS 29.229 [6] clause 6.3.56." where it is all a clause headed by
  the AVP holds, and "for further description of this AVP".
- Mark columns' cells become the row's marks. A cell is split at commas and
  spaces (at commas only under `worded-marks`); a parenthetical stays with
  the mark it follows. A printed dash is no marks and a blank cell is none
  at all, kept apart because TS 32.299 says what the dash means (clause
  7.1.0, "Those Diameter AVPs that are not used are marked '-'").

Conventions worth knowing:

- `Page:` is where the section starts in the PDF bookmark outline; a table
  inherits its section's page.
- An enumerated AVP listed as re-used, or referenced from an AVP-table NOTE,
  gets no local definition. Grouped AVPs are not treated that way: TS
  29.272 re-prints nine of TS 29.212's grouped AVPs in full and lists them
  as re-used; the bodies are kept and the linter reports the conflict. A
  row citing the document itself is no re-use.
- Enumerated AVPs take their code from the AVP table and their vendor-id
  from the document's grouped-AVP headers, or 10415 when there are none.
  Conflicting candidate vendors are an error.
- A flag named twice (`M,M`) fails rather than collapsing.
- Table captions are matched as a general dotted label (`Table 7.3.1/1`,
  `Table 6.3.1-1`, `Table B.1.1`); a table with no recognised caption is
  rejected.
- A From cell's publisher prefix is optional for 3GPP and IETF. A bare
  clause number cites the document itself. Another publisher's document is
  read with its publisher, as the cell or clause 2's entry prints it.
- Several AVP and re-used table pairs per document are paired in document
  order; counts that cannot pair are an error. Several AVP tables with no
  printed re-used table each get their own synthesised block.
- Column labels are matched by spelling map. "Comments", "Description" and
  "Comment" columns are dropped silently as prose; any other unmodelled
  column, or a mark column whose quirk the document does not declare, warns.
- The cover title is read from the cover table or a plain paragraph.
  `attach_pages` reads the PDF's own cover and refuses a different document
  or version, falling back to the PDF's Title metadata when the cover text
  does not read.

ABNF is read line by line: a paragraph is split at its manual line breaks,
and bold and strikethrough belong to the line. Blank lines inside a body are
skipped when another member follows; a line made entirely of several
members is read as several; any other line ends the body. A struck member
carries `; strikethrough`, as a bold one carries `; bold`, and a line only
partly struck fails. Without a legend the extractor reads, a struck member
stays a member and warns. Under `struck-rules-unused`, TS 32.299's own
legend ("not used by 3GPP") makes it no member, and the line is commented
out where it stood, marker kept:

```dad
<Accounting-Request> ::= < Diameter Header: 271, REQ, PXY >
        < Session-Id >
        ...
        [ Acct-Application-Id ]
;;      [ Vendor-Specific-Application-Id ] ; strikethrough
        [ User-Name ]
```

A PDF's text layer loses the strike, so the docx's run formatting is what
records it.

Real-document cases handled in code, kept as evidence in the code's
comments: heading and rule-name mismatches, Diameter headers omitting the
application id, two ABNFs under one command heading, empty clause cells,
merged rows duplicating cell text, headings without " AVP", an underscore in
a published name (`GBA_U-Awareness-Indicator`), the RFC 3588 `P` flag still
printed, parenthesised note references on name cells, one AVP printed with
two bodies, and "Void" as an enum value label. Everything patched is listed
with its reason in `edits/sources/`.

### Out of scope

TS 29.228, 29.328, 29.213 and 29.305 hold procedure and IE mappings, not
Diameter ABNF or AVP tables; TS 29.201 carries TS 29.214's Rx over REST as
an XML schema. The catalog marks each `out_of_scope`, and `regenerate --add`
refuses it in that field's words. TS 32.296's Re interface prints `xxx` command
codes and `TBD` AVP codes, never allocated, and it is not in the catalog.
Nothing in the corpus cites any of them.

### The registry reading

TS 29.230 is an allocation registry rather than a definer, read behind two
quirks of its own:

- `registry-tables`: a table whose first column is "Application
  identifier" (4.1), "Command code value" (5.1/1 to 5.1/4), "AVP Code"
  (7.1) or "Experimental Result Code" (8.1.2 to 8.1.4) becomes a
  `Registry` block, read by physical cells. A "Specified in" cell is one or
  more `29.229 [2]`, and the row cites each by its number. A Data Type
  cell's dash and blank are both no type. A row with no code warns and is
  not read.
- `reserved-range-notes`: a full-width note row becomes a reserved range
  per line reading "The AVP codes from a to b are reserved for P", P as
  printed, and every `TS n.n` it names the range's documents.

Table 7.1 types code 314 (Charging-Characteristics, TS 29.234) `"Integer"`,
kept quoted under `unknown-type-tokens`. No source settles the type: TS
29.234 clause 10.1.27 says "of type Integer" in every version, never with a
width, and implementations disagree (Wireshark and python-diameter
OctetString, freeDiameter Integer32). The row stays as printed and the
model reads it as a hole.

Input patches repair what fails these readings: broken reference cells, type
typos and names broken beside a hyphen, plus forty-seven respellings of
table 7.1's names to the defining clause's
([linter.md](linter.md#standing-findings)).

## oneM2M TS-0004

oneM2M TS-0004 binds the Mch reference point to Diameter accounting in its
annex A. The downloader fetches the Word original of the Release 2 line,
V2.35.0, and converts it. The document is on 3GPP's Word conventions, and
the 3GPP extractor reads it whole; nothing outside annex A is a definition
it recognises.

- The cover prints `oneM2M-TS-0004-V2.35.0`, read as `; Specification:
  oneM2M TS-0004` and `; Version: 2.35.0`. `; Vendor-ID:` is 45687, stated
  in clause A.4. No PDF of V2.35.0 exists, so there is no `; Page:`.
- Headings print no clause numbers (`list-numbered-headings`): the
  extractor replays Word's list numbering, level overrides and restarts
  included, so annex A's headings read A.1 to A.5.32 as the published PDF
  prints them.
- Clauses A.2.1 and A.2.2 head the commands "Accounting Request Command"
  over `<ACR> ::=`; input patches join the words to RFC 6733's names.
  Neither header prints an application id; clause A.5.2's
  "Acct-Application-Id shall contain the value of 3" is recorded by a
  correction as the `Mch` application scope.
- Table A.4-1 mixes vendors, each row printing its own "AVP Vendor Id",
  read into the `Vendor-ID` column. Its Reference column is read cell by
  cell: a bracketed clause is the row's Section, a document a re-used row.
  The table puts V under Must not for its own AVPs, which corrections move
  to Must citing RFC 6733 section 4.1.1.
- `M2M-Information`'s rule prints `< AVP Header: 1011>` with no vendor; a
  correction gives it 45687. `Protocol-Type`'s values are value first, with
  "100 .. 199 Operator and vendor specific protocol types" as a
  vendor-specific range.

## The RFC plain-text extractor

Same definitions, different carrier:

- **Page furniture.** Footer lines ending `[Page N]`, a form feed, then a
  running header recognised positionally, never by text. `; Page:` numbers
  are the RFC's own.
- **Wrapped rows.** A long name wraps (`Acct-` / `Interim-Interval`). A line
  whose name fragment sits at the Attribute Name column starts a row;
  anything deeper continues it; every cell must arrive on exactly one line.
- **More than one table.** A repeated header after a page break continues
  the table; a header after closing prose starts another.
- **Border styles.** RFC 6733 boxes only the flag columns; RFC 7683, 7944
  and 8581 to 8583 box the whole table.
- **Header labels are whole spellings**; an unrecognised header fails and
  earns an entry. Stacked flag labels (`MUST` over `NOT`) are read
  generically.
- **Tables without flag columns** (RFC 5777's IANA table) map onto the
  columns they have. **Clauses without tables** (RFC 4072, 5447) form the
  index behind `clause-avp-table`. RFC 4590's RADIUS attributes contribute
  Name, Code and Section behind `radius-attribute-table`, with no type
  fabricated; the Diameter types and flag rules RFC 4590 never states are
  its corrections' ([corrections.md](corrections.md#operations)).
- **Tables without a Code column** (RFC 7155): `prose-avp-codes` follows
  each row's Section cell to the defining sentence and completes the row.
- **Stated facts.** `; Vendor-ID: 0` always; no `; Version:` and no
  `; Table:`.
- **Definitions anchor on section titles.** A bare-name title or `Name AVP`
  is a candidate; a prose title is not. RFC 6733's base commands print no
  application id and the file records its absence; no RFC states its ids
  in a wording a second one shares, so their application scopes come from
  corrections.
- **Grouped AVPs** may write the rule name bracketed or bare. A body
  printed for another document's AVP is kept (RFC 8581 re-prints RFC 7683's
  `OC-OLR`) for the linter to compare.
- **Enumerated AVPs**: a value list under a name-titled section, when the
  local table types the name Enumerated. Both layouts are read (value alone
  with description below; description on the value's line) plus older
  `2 HMAC-SHA-1` forms. Value names are all-caps unless a quirk says
  otherwise, which keeps prose out. A clause that says where its values are
  listed gets that citation as `; Values:`.
- **Values printed outside a value list**, each behind its quirk: RFC
  4005's `Termination-Cause` values in a RADIUS-to-Diameter mapping table
  (`cause-mapping-table`), and RFC 5778's `MIP6-Auth-Mode` value numbered
  only in its IANA section (`registry-enum-values`).

## Transcriptions

ETSI ES 283 034 V2.2.0 and TS 183 017 V3.2.1, which 3GPP documents cite for
`Logical-Access-ID`, `Physical-Access-ID` and `Reservation-Priority`, and
3GPP2 X.S0057-0 V2.0, which TS 29.212 cites for `3GPP2-BSID`, are published
as PDF alone. No extractor reads them: each is copied by hand into
`edits/transcriptions/<SpecRef>.dad` in `.dad` notation, and its header
says so (`; Transcribed: by hand from <the PDF>`). The transcription stands
where the document does, and the pipeline is the extractor's:

    transcription → input patches → raw → corrections → corrected

The transcription copies what the document prints, misprints included, even
where the grammar cannot hold it. Input patches in
`edits/sources/<SpecRef>.toml` apply to its lines, a patch's `section` being
the `; Section:` of the line's block; the patched text must parse, and is
the raw file. Corrections make the corrected file from it.
`tests/test_transcription.py` pins each committed raw file to its patched
transcription.

A transcription gives each construct the shape the 3GPP extractor gives it:
commands and grouped AVPs as their ABNF prints them, bold members `; bold`,
ABNF comments as trailing `;;` comments; the AVP table as an `AVP Table`
with its NOTE rows as `;;` comments; an enumerated clause as an
`Enumerated AVP` named by its defining sentence; a table of imported AVPs
as `Reused AVPs` with Name, Code, From and Type, and flag rules the table
restates kept in a `;;` comment above it, since a re-used table has no
column for them; an application id stated in prose as an
`Application Scope`. Not transcribed: clause prose, the defining sentence
of a simple-typed AVP, result codes and informative annexes.

3GPP2 numbers revisions of a document (X.S0057-0, -A, -B), each with
versions of its own, and a spec-ref keeps no revision letter, so the
rendering's name in `; Transcribed:` is where a transcription states its
revision; `regenerate` checks it against the file's number and version,
and `corpus.revision` reads it for a citation naming a revision
([linter.md](linter.md#resolving-an-origin)). A 3GPP2 page is the number
its footer prints, after a front matter numbered in roman.

## Strictness

Everything that can fail an extraction derives from `ExtractionError`,
including `PatchError`. Non-fatal inconsistencies go to a `warnings` list
the CLI prints to stderr, also when a later stage fails. The docx and the
PDF must be the same document and version, which matters because the
downloader can fall back to an earlier ETSI rendering.
