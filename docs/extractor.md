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
the extractor threw away. The one exception is declared by clause and says so in
the file: an [exclusion](#exclusions).

## Source declarations

One TOML file per document, `edits/sources/<SpecRef>.toml`, with three block
kinds. Each requires a `reason`, carries a version range scoping it to a
release, and must fire as declared: a declaration that stops
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
a release so `--expand-ranges` widens them), else with none. A range with no
upper bound spans only its lower bound's release for this choice, and one with
no bounds spans none, since neither says a later release was reviewed; both
apply to every copy they cover. A declaration naming the new release alone,
written before the rest are widened, takes them all out of its reading. Write it
unranged until `--expand-ranges` has run. Corrections and acceptances are scoped
the same way, per module.

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
  naming them, named from the RFC by command code (TS 29.234, 29.061, 29.561).
- `access-type-headings`: `Event-Trigger AVP (All access types)` (TS
  29.212, 29.214).
- `spaced-rule-operator`: `:: =` (TS 32.299, 29.229, 29.234, oneM2M).
- `placeholder-codes`: a registry row whose code cell prints a placeholder,
  quoted as printed (TS 29.230 V19.3.0's `zz`, `xx1`, `xx2`).
- `spaced-heading-numbers`: a space before the heading's tab (TS 29.234,
  29.061; TS 32.299 V11.20.0 clauses 7.2.47, 7.2.54, 7.2.142 and 7.2.219A).
- `body-clause-headings`: a clause heading printed as a body paragraph (TS
  32.299 clause 7.2.135C).
- `struck-rules-unused`: TS 32.299's legend for struck members (below).
- `message-tables`: a command printed as a table, `<Diameter Header: 258,
  PXY>` and then its members, with a "Used in 3GPP" column read as the strike
  (TS 32.299 V11.20.0 clause 6.4.5), or as an `AVP`, `Category`, `Description`
  table and no rule (clause 6.4.4, [below](#commands-printed-by-category)). A
  caption naming the command over any other table fails.
- `abnf-comments`: a member line's trailing `; comment` (TS 29.209, 29.061,
  29.109, 29.214).
- `reprinted-avps`: a grouped rule in a procedure clause, under "The content of
  X according IETF RFC n [m] is:" (TS 29.109, [below](#re-printed-rules)).
- `elided-members`: a body's lone `…` or `...` line (TS 29.273, below).
- `list-numbered-headings`: clause numbers that exist only in Word's list
  numbering (oneM2M TS-0004).
- `message-only`: commands and re-used rows, no local AVPs (TS 29.330,
  29.211).
- `command-reference-only`, `procedure-commands`: clauses holding only a
  pointer, and commands named in a procedure clause's intro (TS 29.273,
  29.234), under a heading no other reading names them by (TS 29.061's
  `AAR Command` over `<AA-Request> ::=`), or in a procedure step's sentence
  (TS 29.109's "a Bootstrapping-Info-Request message (BIR)").
- `clause-parenthetical`: a trailing parenthetical in a clause cell,
  `16.4.7 (see Note)`, stripped as prose (TS 29.061, 29.561).
- `trailing-result-codes`: a result code printed as the last sentence of the
  paragraph describing the code before it (TS 32.299 V11.20.0 clause 7.1.11).
- `see-result-code-origins`: a result code's clause naming the document
  defining it with "see" alone (TS 29.273, 29.329;
  [below](#the-3gpp-docx-extractor)).

**Docx, tables.**

- `physical-avp-columns`, `physical-reused-columns`: tables whose rows
  change grid spans, read by physical cells (TS 32.299 table 7.2.0.1; TS
  29.273, 29.368, 29.219).
- `independent-avp-tables`: no one-to-one pairing of AVP and re-used tables
  (TS 29.273, 29.215).
- `vendor-avp-tables`: tables of other vendors' AVPs read as re-used blocks
  (TS 32.299 tables 7.3.1 to 7.5.1).
- `refer-type-cells`, `referred-type-sentences`: a `refer [n]` type cell
  adds a re-used row citing reference n, and a clause typing such a row
  gives it its type (TS 32.299).
- `note-defined-in-rfc`: an AVP-table note naming a defining RFC becomes a
  re-used row (TS 29.229, 29.329).
- `wildcard-avp-row`: an `AVP` row with code `*`, the `* [ AVP ]` wildcard,
  which defines no AVP and stays a `;;` comment where it stood (TS 32.299
  tables 7.1 and 7.1.0.1).
- `vendor-id-sentence`: V from the clause's "shall be set to 3GPP (10415)"
  where the table prints no flags (TS 29.389).
- `dotted-flags`, `type-short-forms`, `unknown-type-tokens`: `M.` flag
  cells; `DiamIdent` and `DiamURI`; a Type cell naming no Diameter type,
  kept quoted (TS 29.230 and 29.234's `"Integer"`).
- `reference-cells`: a Reference column mixing clauses and documents
  (oneM2M).
- `document-clause-cells`: a clause column whose cell may name another document,
  `3GPP TS 29.061 [5]`, read as a re-used row citing it (TS 29.561 table 12.4-1,
  [below](#radius-attributes-as-avps)).
- `origins-by-reference`: a From cell naming ETSI's document as 3GPP's,
  read through clause 2 (TS 29.212, 29.214).
- Mark columns, each naming the column's legend: `access-type-column`,
  `applicability-column`, `reference-points-column`, `command-columns`,
  and `worded-marks` for marks of several words split at commas only (TS
  29.061, 29.368, 29.468, 29.561).
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
5779, 6734, 6942, 7075), `radius-attribute-table` (RFC 4590),
`type-short-forms`, `prose-catchall-row` (RFC 5778), `bare-name-continuation`
(RFC 4004), `ragged-separator` (RFC 8583), `parenthesized-enum-values` (RFC
6734, 6736, 7155), `parenthesized-value-first` (RFC 5777),
`bulleted-enum-values` (RFC 4740), `worded-enum-values`,
`external-enum-values`, `prose-cleared-flags` (RFC 6942),
`mixed-table-borders` and `radius-avp-codes` (RFC 5580),
`cause-mapping-table` (RFC 4005), `registry-enum-values` (RFC 5778),
`boxed-table-legend` (RFC 5866), `split-avp-tables` (RFC 4740),
`reused-avp-tables` (RFC 6736), `note-avp-origins` (RFC 6738),
`prose-avp-origins` (RFC 5779, 8583) and `elided-members` (RFC 5778, 6738).

Not gated: the "Y"/"N" Encrypt spellings, a dashed Encrypt cell, and
"Must"/"Must not" M-bit short forms, closed vocabularies that cannot be
misread.

### Exclusions

An exclusion leaves a clause of a 3GPP docx unread, with everything under it,
when the document has not finished it and no reading could state what it says:

```toml
[[exclude]]
section = "8"              # the clause and every clause under it
name = "Sh-ee"             # what the file's note calls it
reason = "..."
first_version = "19.1.0"
```

It belongs to the input-patch layer: the walk over the document stops at the
heading, so nothing in the clause reaches a reading, a patch's accounting or
either file. A patch or correction written for the clause fails once it is
excluded, so a clause's edits go with it. The exclusion ends at the next
heading outside it, numbered or not (TS 29.329's clause 8 ends at "Annex A
(informative):").

The raw and corrected files both say so, in a comment block after the header:

```dad
;; excluded: clause 8 (Sh-ee), see TS29.329.toml
```

An exclusion that leaves nothing out fails like a rotted patch, and so does one
declared for an RFC or a transcription, whose readings do not ask. Nothing but
the document being unfinished earns one: a clause that is wrong is read as
printed and corrected. TS 29.329 V19.1.0's clause 8 names its application id
`xx1`, "allocated by IANA"; gives its commands 310 and 311, which TS 29.230
allocates to others; and lists `DIAMETER_INVALID_AVP_VALUE` at 5004 as an
experimental result code, which is TS 29.229's.

A range with no upper bound holds for later versions too, and no warning says
that one of them has finished the clause. A version upgrade re-reads the
document's exclusions against its clauses, as it does its references clause
for the corpus's entries keyed by it (`corpus.toml`,
[development.md](development.md#version-upgrades)), and removes one the new
version settles.

## The 3GPP docx extractor

Walks paragraphs and tables in document order under numbered headings. A
`w:smartTag` prints as the runs inside it, so the walk unwraps them first:
python-docx reads a paragraph's direct runs alone, and through it TS 29.338
clause 5.3.2.6's heading loses its `(ALA)` and TS 29.214's clause cells come out
blank.

- A sentence stating the application id the command headers omit becomes
  an `ApplicationScope` applying to the interface clause it sits in (`;
  Applies-To: 5.*` for TS 29.212's clause 5.1). Where another sentence under
  the same interface clause states another application, each applies to its
  own clause: TS 29.210 V6.7.0's 6.1 states Gx's id and 6.2 Gx over Gy's, so
  Gx's is `6.1.*`, and one of them at the interface clause itself fails. Six
  wordings are recognised; the file lists the scopes first, before the
  commands.
- `x.y.z Name (ABBR) Command` heading plus `::= < Diameter Header: … >`
  becomes a `Message`; per-run bold marks the document's own AVPs. Message
  headings without a rule (TS 32.299's pointers to RFC 6733) are not
  definitions.
- An `<answer-message> ::= < Diameter Header: code, ERR [PXY] >` paragraph run
  becomes an `AnswerMessage`, whatever its heading: TS 29.229 clause 7.3.1's,
  the format of a Cx or Dx answer with the E bit set. A line naming
  `<answer-message>` in any other shape fails. The file places it among the
  commands, in document order.
- `x.y.z Name AVP` heading plus `::= < AVP header: … >` becomes a
  `GroupedAvp`. The rule name may be bracketed and the keyword spaced.
- `x.y.z Name AVP` heading whose intro says "is of type Enumerated", with
  `ValueName (n)` items, becomes an `EnumeratedAvp`. Values are classified
  by content, not paragraph style. "Value n is reserved" notes become
  reserved ranges. A range whose words leave it to vendors or operators,
  with no `not`, `no`, `never` or `except`, is a vendor-specific range
  keeping the words as its description; a range reserved with no such
  wording is a reserved range; any other range is reported. A value or range
  labelled `Void`, in any case, is a `; VOID` line (TS 29.214 clause 5.3.13's
  `Void (0)`, in all three copies). A clause that
  says where its values are defined instead of listing them gets that
  citation as `; Values:`, in the document's words.
- A feature table's `void` row stays a row (`void = 18`, TS 29.212 tables
  5.4.1.1 and 5a.4.1.1, in both copies): `; VOID` is an enumeration's line, a
  `Value Table` holds names and numbers, and the row's blank M/O cell is what
  tells it apart. No other value table prints the word.
- The table with the "AVP Flag rules" header becomes an `AvpTable`. A row
  whose code cell is a NOTE reference gets `code=None`. A table whose
  labelled header is followed only by blank cells contributes nothing and
  warns (TS 29.330 table 6.3.1-1).
- The "re-used Diameter AVPs" table becomes `ReusedAvps` with M-bit
  overrides, and the code and type where the table prints them.
- `prose-avp-origins` keeps definition citations ("The X AVP is defined in",
  "See ... for the definition of this AVP") as re-used rows, each in a block at
  the clause stating it, with no `; Table:` since no table prints it, and in
  each clause stating it. A NOTE-derived origin is the AVP table's and stands
  under its label, apart from any re-used table the document prints beside it.
  The local table's code, type and flag rules remain intact, and a code the
  origin does not give is `reused-code-conflict`. References to encodings or
  value meanings do not establish an AVP's origin. An unnamed "this AVP" takes
  the clause's AVP: a clause with several candidates fails, and a sentence
  after another AVP's name is skipped. RFC 8583 uses the same quirk for "The
  SourceID AVP is defined in [RFC8581]", in a block at its clause 7.4. TS
  29.283 does not declare it: its one citation, clause 7.3.21's
  Sequence-Number "defined in the 3GPP TS 29.329", names TS 29.329's AVP 716
  for one table 7.3.1-1 gives 4512, which TS 29.230 allocates to TS 29.283,
  and read it would be a `reused-code-conflict`.
- `bare-avp-citations` adds TS 29.329's pointers, which say no "definition":
  "See 3GPP TS 29.229 [6] clause 6.3.56." where it is all a clause headed by
  the AVP holds, and "for further description of this AVP".
- A "Bit | Name | Description" table, or "Bit | Description" whose description
  is the name (TS 29.272 clause 7.3.31, `UTRAN Not Allowed`), or "Event Type"
  and "Requirement" for the name (TS 29.172), becomes a `bits` `ValueTable` for
  the AVP its clause heads. A "Feature bit | Feature | M/O | Description" table
  becomes a `features` one, its application and Feature-List-ID from the caption
  ("Features of Feature-List-ID 1 used in S6a/S6d", the application's noun
  dropped where the caption prints one, "used on the Sy interface"), its AVP the
  `Feature-List` unless the clause heads another. A table is read positionally
  by its labels, note references aside. A full-width row is a note, and prose. A
  row naming no number (`1-31 None`, `1+n Congestion level 1+n`) is a `;;`
  comment where it stood. A table with nothing else warns and is no block (TS
  29.153 clause 5.4.2, TS 29.283 clause 7.3.16).
- A clause titled "Result-Code AVP values", "Rx specific
  Experimental-Result-Code AVP values" or the like, and everything under it,
  becomes a `result-codes` `ValueTable`: each subclause heading or line of its
  own that is a name with an underscore and a number, `DIAMETER_X (5001)`,
  `DIAMETER_X (5001):`, `DIAMETER_X 4010` or `4010 DIAMETER_X`. The row's clause
  is the subclause it sits in. A clause naming the Experimental-Result AVP
  anywhere holds experimental codes, whatever its title says (TS 29.229 clause
  6.2), and in such a clause "the following Result-Code AVP value defined in
  IETF RFC 8506" starts a `Result-Code` table of its own, until a line names the
  experimental ones again (TS 29.212 clause 5.5.3). A heading whose number is
  unallocated (TS 29.345 clause 6.4.3.15, `(56x1)`) is a `;;` comment.
  Exact-match structure: neither reading is behind a quirk.
- A code is another document's where its text says that document defines it,
  and only then: the code's own text ("This error code is defined in 3GPP TS
  29.229 [6]", TS 29.283 clause 7.4.3.2; "This value is defined in TS 29.229
  [204]" on the line after TS 32.299 clause 7.1.8A's code), or the intro over
  the codes it lists ("the following Experimental-Result AVP values defined in
  3GPP TS 29.273 [48] are applicable:", TS 29.212 clause 5.5.3, until "the
  following specific Gx Experimental-Result-Codes values are defined:"). The row
  takes it as its origin. "The Result-Code AVP values defined in Diameter Base
  IETF RFC 6733 [61] are applicable" names no code, and a document's own number
  is no origin: a code whose own text names the document itself, or says it "is
  defined in the present document", is local even under an intro naming
  another. A code its own text says two documents define fails, and so does one
  whose text names another document than its intro does; a citation naming no
  document a reading knows says nothing either way. A code's clause saying only
  "See 3GPP TS 29.229 [6] clause 6.2.2.11." (TS 29.329) or ending "(see TS
  29.229 [24])." (TS 29.273 clauses 10.3.2 to 10.3.5) is read so only behind
  `see-result-code-origins`, and only in those two shapes, a line that is the
  pointer alone or a parenthetical naming the document alone that ends the
  line: "For retry handling see TS 29.229 [6] clause 5." points at a procedure,
  and names no origin.
- Mark columns' cells become the row's marks. A cell is split at commas and
  spaces (at commas only under `worded-marks`); a parenthetical stays with
  the mark it follows. A printed dash is no marks and a blank cell is none
  at all, kept apart because TS 32.299 says what the dash means (clause
  7.1.0, "Those Diameter AVPs that are not used are marked '-'").

Conventions worth knowing:

- A command code is a number. TS 29.109 clause 5.4 prints `xxx` for GBA push's
  code and `xxxxxxxx` for its id, and states both in clauses 6.0 and 6.1, so
  input patches print them in the rule, citing those clauses and TS 29.230.
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
and bold and strikethrough belong to the line. A run holding only a repetition
says neither, since TS 29.561 clause 12.6.3 prints a plain `0*16 ` before a bold
member. Blank lines inside a body are skipped when another member follows, and a
line made entirely of several members is read as several.

A body ends at a blank line, the next rule, a sentence, or a change of paragraph
style on a line with no ABNF in it. A sentence counts because prose follows a
body directly and in its own style in dozens of clauses (TS 29.336's "The
following combinations are allowed:"). Any other line fails, naming its section
and text, and so does a member printed after the body ended and before the next
rule: `[ OC-OLR ] ]` once ended TS 29.273's Multimedia-Auth-Answer there and
took the members after it out of the file. A typo is an input patch, and a
reading a quirk.

A struck member carries `; strikethrough`, as a bold one carries `; bold`, and a
line only partly struck fails. Without a legend the extractor reads, a struck
member stays a member and warns. Under `struck-rules-unused`, TS 32.299's own
legend ("not used by 3GPP") makes it no member, and the line is commented out
where it stood, marker kept:

```dad
<Accounting-Request> ::= < Diameter Header: 271, REQ, PXY >
        < Session-Id >
        ...
        [ Acct-Application-Id ]
;;      [ Vendor-Specific-Application-Id ] ; strikethrough
        [ User-Name ]
```

Under `elided-members`, a `…` or `...` on a line of its own is kept the same
way. TS 29.273 prints one in 47 commands, between members and before `*[ AVP ]`,
where a rule leaves out what it does not change. It is no member, and the file
says where the document said it, as printed:

```dad
<Diameter-EAP-Answer> ::= < Diameter Header: 268, PXY, 16777250 >
        < Session-Id >
        [ MPS-Priority ]
;; …
      * [ AVP ]
```

A PDF's text layer loses the strike, so the docx's run formatting is what
records it.

### Commands printed by category

TS 32.299 V11.20.0 clause 6.4.4 prints RAR as table 6.4.4, a row per member with
its category and a description, and no ABNF. The document states no command code
for it, nor flags: clause 6.4.1.1 says only that RAR/RAA "are used according to"
RFC 3588 [401]. TS 29.230 has no row for RFC 6733's 258 either, allocating
3GPP's commands alone. So an input patch supplies the header line, citing RFC
6733 clause 8.3.1, and the extractor fails without it, rather than pass over a
command the document prints. The file says so under the header, naming the
declarations whose patch says where the header comes from. Clause 6.4.1.2's
symbols read M as `{ }` and OC as `[ ]`; a dash, "Not used in 3GPP", reads as a
strike, the member commented out; a row a tab sets off is the grouped AVP's
above it, kept as a comment and no member.

The category says neither a fixed position nor a repetition, which RFC 6733's
rule states and V19.0.0's clause 6.4.4 prints. Those are corrections
(`rel11-rar-session-id-position`, `rel11-rar-repeats-*`), so the file shows both
the reading and the edit:

```dad
<Re-Auth-Request> ::= < Diameter Header: 258, REQ, PXY >
;; patched: the table prints no Diameter header, see TS32.299.toml
        < Session-Id > ;; corrected: (TS32.299.py#rel11-rar-session-id-position)
        { Origin-Host }
```

The application id stays out of the header, as for the clause's other commands:
the `Ro` scope clause 7.1.6 states applies to clause 6.4.

### Re-printed rules

TS 29.109 clauses 4.2, 5.2 and 5.4 follow MAR, BIR and GPR with "The content of
Vendor-Specific-Application-ID according IETF RFC 6733 [33] is:" and that rule,
differing only in what they gloss (the application id, `xxxxxxxx` in 5.4). The
document says of them only what RFC 6733 says, and the file still records it,
in one `Reprinted AVP` block per copy:

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

A `Grouped AVP` with a directive would have had every reader of definitions
filter it out; a type of its own keeps it out of them by default, so
`Model.definition((0, 260))` still answers RFC 6733, `Model.avps("TS29.109")`
does not list it, and three blocks of one name are no duplicates. The linter
holds a copy to the document it names
([linter.md](linter.md#cross-file-rules)). The glosses stay, as `;;` comments on
their members, since they are all that tells one copy from another; a command's
glosses in the same clauses are still dropped under `abnf-comments`.

A grouped rule in a procedure clause with no such sentence fails, naming its
clause, as one under a document not declaring the quirk does.

Real-document cases handled in code, kept as evidence in the code's
comments: heading and rule-name mismatches, Diameter headers omitting the
application id, two ABNFs under one command heading, empty clause cells,
merged rows duplicating cell text, headings without " AVP", an underscore in
a published name (`GBA_U-Awareness-Indicator`), the RFC 3588 `P` flag still
printed, parenthesised note references on name cells, and one AVP printed with
two bodies. Everything patched is listed with its reason in `edits/sources/`.

### RADIUS attributes as AVPs

TS 29.561 defines its AVPs as RADIUS vendor-specific sub-attributes. Clause 11.3
tabulates them, with octet layouts and prose, in tables no reading here
recognises (`Attr #`, `Sub-attr #`, `Octets`), so those stay unread. What makes
them AVPs is table 12.4-1, whose caption says "re-used" and whose rows say which
are: `Section defined` is `11.3.1` for the 25 this document adds, and a document
for the 31 it takes from TS 29.061 and TS 29.229. Every row stays in the `AVP
Table` as printed, and `document-clause-cells` adds a re-used row for each of
the 31, so `Model.definition` answers those from their origin. Table 17.4-1 adds
`3GPP-S-NSSAI` the same way, from clause 16.3.1.

Sub-attribute 117, `3GPP-Supported-Features`, has no row: it is RADIUS's, and
Diameter uses `Supported-Features`. Tables 12.4-1 and 17.4-1 give codes 135 and
200, which TS 29.230 V19.3.0 allocates to no document by name, inside the 1 to
255 it reserves for TS 29.061, 29.561 and 29.234.

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
typos and names broken beside a hyphen, plus twenty-one respellings of table
7.1's names that differ from the defining clause's in case alone. A name the
registry prints otherwise, parseable as printed, stays in the raw file and is
corrected to the defining clause's: twenty-six of table 7.1's (`NAF-Hostname`
for TS 29.109's `NAF-Id`, code 402) and one of table 8.1.4's
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
  and 8581 to 8583 box the whole table, and RFC 4740 and two of RFC 6736's
  tables every column of it, where a wrapped name's continuation is the line
  with its other cells blank. A row starts where the table's first row does,
  which RFC 5866 and 6736 print one column left of the header's label.
- **Headers naming no caption.** RFC 4740 captions its tables below them and
  RFC 6736 stacks "AVP", "Flag", "rules", so a boxed `Attribute Name` followed
  by `MUST` or `AVP` opens a table as "AVP Flag" does. Occurrence tables are
  not read.
- **Codes and flags apart.** RFC 4740 prints name, code, clause and type in
  table 2 and the same names with flags in table 3. `split-avp-tables` joins
  them into one table, and fails when their names differ. A table of names and
  flags without the quirk is an error.
- **Tables of re-used AVPs.** RFC 6736's clauses 8.1 and 8.3 to 8.6 tabulate
  "the AVPs reused from" a document. `reused-avp-tables` reads each as a
  `Reused AVPs` block citing it, keeping the printed code and type for the
  linter to compare; the block has no column for the flags. `note-avp-origins`
  does the same for rows RFC 6738's table sends to "Note 1". A document without
  it drops such a row, as RFC 5778 does.
- **The error answer.** RFC 6733 section 7.2's `<answer-message>` sits under
  "Error Bit", which names no definition; its rule line anchors it, as the docx
  extractor's does, and it becomes an `AnswerMessage` among the commands.
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
  is a candidate; a prose title is not, unless the local table's row typing the
  name Grouped cites that clause (RFC 5777's `QoS-Capability`, under "QoS
  Capability Indication"). RFC 6733's base commands print no
  application id and the file records its absence; no RFC states its ids
  in a wording a second one shares, so their application scopes come from
  corrections.
- **Grouped AVPs** may write the rule name bracketed or bare. A body
  printed for another document's AVP is kept (RFC 8581 re-prints RFC 7683's
  `OC-OLR`) for the linter to compare.
- **A body ends at a blank line, the next rule or a sentence.** Blank lines
  a page break leaves inside a body are skipped when another member follows.
  Any other line fails, naming its section and text, and so does a member
  printed after the body ended and before the next rule. A typo is an input
  patch, a reading a quirk. Under `elided-members` a `…` or `...` on a line of
  its own stays a `;;` comment where it stood: RFC 5778 prints them in DER and
  DEA, and RFC 6738 in IKESKR and IKESKA, leaving out what the rule does not
  change.
- **Enumerated AVPs**: a value list under a name-titled section, when the
  local table types the name Enumerated. Both layouts are read (value alone
  with description below; description on the value's line) plus older
  `2 HMAC-SHA-1` forms. Value names are all-caps unless a quirk says
  otherwise, which keeps prose out. A clause that says where its values are
  listed gets that citation as `; Values:`.
- **Result codes**: a line of a clause titled `Result-Code AVP`, `Result Code
  AVP Values`, `Extension to the Result-Code AVP Values` or `Additional
  Result-Code AVP Values`, or its subclauses, that is a name with an underscore
  and a number: `DIAMETER_SUCCESS 2001` (RFC 6733, 4004, 4006, 8506), `o
  DIAMETER_X 2003` (RFC 4740), `RESOURCE_FAILURE (4014)` (RFC 6736, 6942),
  `DIAMETER_X (Status Code 2009)` (RFC 5778). RFC 7075 clause 3.4 gives its code
  a clause of its own, headed `DIAMETER_X Protocol Error Code`. An RFC's are all
  `Result-Code`'s. Its bit masks are prose (RFC 7683's `OC-Feature-Vector`, RFC
  5778's `MIP6-Feature-Vector`), and no table reads them.
- **Values printed outside a value list**, each behind its quirk: RFC
  4005's `Termination-Cause` values in a RADIUS-to-Diameter mapping table
  (`cause-mapping-table`), and RFC 5778's `MIP6-Auth-Mode` value numbered
  only in its IANA section (`registry-enum-values`).

## Transcriptions

ETSI ES 283 034 V2.2.0 and TS 183 017 V3.2.1, which 3GPP documents cite for
`Logical-Access-ID`, `Physical-Access-ID` and `Reservation-Priority`, and
3GPP2 X.S0057-0 V2.0, which TS 29.212 cites for `3GPP2-BSID`, are published
as PDF alone. So are the documents behind the rest of the AVPs Wireshark's
dictionary holds in ETSI's and 3GPP2's vendor spaces: ETSI TS 183 033 V1.2.0,
the last version printing its AVPs, V1.3.0 and V2.0.0 pointing at TS 129 433
instead; ES 283 035 V2.5.1; ES 283 026 V1.6.0; TS 183 066 V2.1.1, with the two
documents it imports from, TS 183 020 V1.1.1 and TS 183 059-1 V2.1.1; and 3GPP2
X.S0013-013-0 and X.S0013-014-0 V1.0, with X.S0013-006-B V1.0, the revision of
the Cx document published with them, which X.S0013-014 cites by no revision.
OMA-DDS-Charging_Data V1.0, approved 1 February 2011, which TS 32.299 cites for
thirteen AVPs in each copy the corpus holds, is published the same way. No
extractor reads them: each is copied
by hand into `edits/transcriptions/<SpecRef>.dad` in `.dad` notation, and its
header
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
of a simple-typed AVP, result codes and informative annexes, unless an annex
is the only definition of what it prints (TS 183 033's Annex ZA, whose 21 AVPs
no other document defines).

3GPP2 numbers revisions of a document (X.S0057-0, -A, -B), each with
versions of its own, and a spec-ref keeps no revision letter, so the
rendering's name in `; Transcribed:` is where a transcription states its
revision; `regenerate` checks it against the file's number and version,
and `corpus.revision` reads it for a citation naming a revision
([linter.md](linter.md#resolving-an-origin)). A part of a series is a document
of its own, which a spec-ref keeps: X.S0013-013 and X.S0013-014 are two, and
ETSI's TS 183 059-1 is `ts18305901-020101`, as ETSI runs its digits. A 3GPP2
page is the number its footer prints, after a front matter numbered in roman.

OMA-DDS-Charging_Data's table 11 tabulates IETF and 3GPP AVPs side by side with
a Reference column, which becomes as TS 32.299's `refer [nnn]` does: a clause in
the row's Section cell, a document a row of a `Reused AVPs` block of the same
label. Its clause 6.2 lists Charging Data Elements and table 10 maps each to an
AVP, so a value list there is an `Enumerated AVP` under the AVP table 10 names,
where table 11 types that AVP Enumerated. The other two, under a Grouped and an
Unsigned32 AVP, are comments.

## Strictness

Everything that can fail an extraction derives from `ExtractionError`,
including `PatchError`. Non-fatal inconsistencies go to a `warnings` list
the CLI prints to stderr, also when a later stage fails. The docx and the
PDF must be the same document and version, which matters because the
downloader can fall back to an earlier ETSI rendering.
