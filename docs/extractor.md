# The extractors

Two extractors produce the same `.dad` AST: `extractor/tgpp_docx.py` for 3GPP
`.docx` specifications (page numbers attached from the matching ETSI PDF),
and for oneM2M's on the same Word conventions ([below](#onem2m-ts-0004)),
and `extractor/rfc_text.py` for RFC plain text. Both read per-document
[source declarations](#source-declarations) from `edits/sources/`.

## What the extractor does not decide

**A `.dad` file records everything the source document says about a
definition.** The extractor translates, it does not curate: a definition is
never dropped for being redundant, contradicted by another one, or wrong.
The scope is *definitions* — names, codes, vendor-ids, types, flag rules,
value lists, ABNF bodies — not the document's prose; `; Section:` points at
the clause for anyone who wants that.

Three consequences, each tempting to get wrong the same way:

- Do not drop a block because another contradicts it. An AVP defined locally
  *and* listed as re-used is a real inconsistency; report it in the linter.
- Do not drop a block because it looks redundant. A re-printed clause can
  change between versions.
- Do not normalize a value into what it "should" be. That is what the two
  declared edit layers are for, and they are separate so the unedited reading
  stays on disk.

Interpreting the result is the consumer's job. A consumer can ignore anything
the file carries; it can never recover what the extractor threw away.

## Source declarations

One TOML file per document, `edits/sources/<SpecRef>.toml`, with two block
kinds. Both require a `reason`, carry an advisory version range, and must
fire exactly as declared — a declaration that stops matching fails the
extraction, because a silently dropped fix is the rot the accounting exists
to catch.

### Input patches

Typos in the source that break extraction, or that misspell a name only in
case against the clause defining it, patched on the normalized paragraph,
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

`find` must be non-empty (`str.replace("")` inserts between every character
and still "applies" the declared number of times). A count mismatch raises
`PatchError` naming the version range. The bounds are inclusive, an omitted
bound is open, and trailing zero components are equivalent; corrections
declare the same range as one string (`"18.6.0"`, `"18.0.0..18.2.0"`). A
version outside the range warns under its specification during regeneration
and never gates application. RFCs have no version to compare.

### Quirks

A quirk enables, by name, a reading heuristic enough to misfire on a document
it was not written for:

```toml
[[quirk]]
name = "prose-avp-codes"
reason = "the AVP tables print no Code column; each clause prints its code"
```

What earns a behavior a quirk is misfire *risk*: harvesting facts out of
prose would succeed silently on prose it was never meant to read. Exact-match
structure (header spellings, rule grammars) stays in code because
unrecognized input fails loudly on its own. A quirk carries no parameters;
the behavior lives in code. An unknown name fails at load with the vocabulary;
a declared quirk that fires zero times fails like a rotted patch.

Vocabulary, RFC extractor: `prose-avp-codes` (RFC 7155), `clause-avp-table`
(RFC 4072, 5447), `radius-attribute-table` (RFC 4590), `type-short-forms`
(RFC 6733, 4004, 4005, 4006), `prose-catchall-row` (RFC 5778),
`bare-name-continuation` (RFC 4004), `ragged-separator` (RFC 8583).
The declared vocabulary, with the document that forced each:

- Docx: `prose-application-ids` (29.154, 29.212, 29.214, 29.215, 29.217,
  29.219, 29.343, 29.368, 29.468: the clause stating the application id the
  command headers omit); `access-type-headings` (29.212, 29.214: `Event-Trigger
  AVP (All access types)`); the mark columns, each declaration naming the
  column's legend: `access-type-column` (29.212, 29.215),
  `applicability-column` (29.061, 29.154, 29.212, 29.214, 29.215, 29.217,
  29.219, 29.368, 29.468), `reference-points-column` (29.061) and
  `command-columns` (32.299), and `worded-marks` (29.061, 29.368, 29.468:
  marks of several words, separated by commas only);
  `note-defined-in-rfc` (29.229, 29.329: AVP-table
  notes naming a defining RFC become re-used rows); `dotted-flags` (29.061, 29.212);
  `vendor-id-sentence` (29.389: the V bit its table leaves blank, from the
  clause's sentence);
  `clause-parenthetical` (29.061); `message-only` (29.330 §6.3.1: commands
  and re-used rows, no local AVPs); and five from TS 29.273:
  `command-reference-only` (clauses holding only a pointer),
  `procedure-commands` (8.2.2.1–4 name commands in their intros),
  `physical-reused-columns` (table 8.2.3.0/2 changes grid spans; also
  29.368 table 6.5.1.1 and 29.219 table 5.4, whose header and data rows
  merge a sliver grid column into different labels),
  `independent-avp-tables` (no one-to-one table pairing; also 29.215,
  whose clause 5.4.0 states S9's re-use in prose),
  `conflicting-avp-codes` (table 8.2.3.0/1 contradicts 5.2.3.24; both rows
  kept, no enum code derived from them). TS 29.230 declares
  `registry-tables`, `unknown-type-tokens` and `reserved-range-notes`
  (below). TS 32.299 declares fourteen:
  `message-headings` (6.2.2–6.4.5 head commands "Accounting-Request
  message" over `<ACR> ::=`), `spaced-rule-operator` (`:: =` in clause 7.2;
  also 29.229's four grouped rules), `struck-rules-unused`,
  `physical-avp-columns` (table 7.2.0.1), `refer-type-cells`,
  `referred-type-sentences` (7.2.50, 7.2.69, 7.2.191), `type-short-forms` (`DiamIdent`, `DiamURI` in table 7.1.0.1),
  `wildcard-avp-row` (7.1.0.1's `AVP` row with code `*`),
  `value-first-enums`, `body-clause-headings` (7.2.135C), `dotted-flags`,
  `external-enum-values` (7.2.238, 7.2.20eA; also 29.061, 29.212
  and 29.272), `vendor-avp-tables` (tables 7.3.1, 7.4.1, 7.5.1) and
  `command-columns`.
  Enumerated value lines that depart from `NAME (n)` each need their own:
  `worded-enum-values` (29.368 6.4.6's `Device Trigger Request (1)`; also
  29.109, 29.172, 29.214), `dashed-enum-values` (a list dash printed as
  text, `- AUDIO (0)`: 29.109, 29.214, 29.272, 29.338), `hex-enum-values`
  (29.214 5.3.19's `OTHER (0xFFFFFFFF)`), `punctuated-enum-values` (a list's
  comma or full stop after the value: 29.109, 29.338),
  `described-enum-values` and `label-after-enum-value` (29.109: `NO (0) The
  sending node is not GBA_U aware`, `- (0) Private user identity.`) and
  `run-on-enum-values` (29.229 6.3.58, two values in one paragraph);
  29.061 and 29.212 declare `worded-enum-values` too. TS 29.212 and 29.214
  declare `origins-by-reference` (a From cell naming ETSI's document as
  3GPP's, read through clause 2). oneM2M TS-0004 declares
  `list-numbered-headings`, `reference-cells` and `prose-enum-values` of its
  own ([below](#onem2m-ts-0004)), with `message-headings`,
  `spaced-rule-operator`, `command-columns`, `type-short-forms`,
  `value-first-enums` and `external-enum-values`.
- RFC: `clause-avp-table` (6734, 6942: no table; Name/Code/Type from the
  defining clauses); `parenthesized-enum-values` (6734 §3.1.1, mixed-case
  `rRK (1)`; 7155 §4.4.1, `Login (1)`); `worded-enum-values` (4005 §5.5 and
  7155 §4.3.5, `CHAP with MD5       5`; 4005 §6.1, and with the previous
  one 7155 §4.4.1, `Callback Login`; 4005's informational lists, `2   ISDN
  Sync`); `parenthesized-value-first` (5777
  §5.4, `(0): QoS-Desired`); `external-enum-values` (4005, 5777, 5778, 6733,
  7155: where an enumerated clause says its values are listed);
  `prose-cleared-flags` (6942 §8.1–8.2 state the M and V bits
  cleared); `mixed-table-borders` and `radius-avp-codes` (5580 §6: header
  boxes only the flags, codes come from the RADIUS Type fields in §4);
  `cause-mapping-table` (4005 §9.3.5: Termination-Cause's values only in a
  RADIUS-to-Diameter mapping table); `registry-enum-values` (5778 §6.20
  names `MIP6-Auth-Mode`'s value, only the IANA section §9.5 numbers it).

Not gated: the "Y"/"N" Encrypt spellings and TS 29.338's "Must"/"Must not"
M-bit short forms, closed vocabularies that cannot be misread.

## The 3GPP docx extractor

Walks paragraphs and tables in document order under numbered headings:

- Behind `prose-application-ids`, a sentence stating the application id the
  command headers omit → `ApplicationScope`, applying to the interface
  clause the sentence sits in (`; Applies-To: 5.*` for TS 29.212's 5.1). Two wordings: "the Application-ID for the Gx
  Application in the present release is 16777238" (TS 29.212 clauses 5.1,
  5a.1, 5b.1, 5c.1, E.6.1; 29.154, 29.214, 29.215, 29.217) and "The
  Diameter application identifier assigned to the Sy interface application
  is 16777302." (29.219 clause 5.1.5; 29.343, 29.368, 29.468). The file
  lists them first, before the commands.

- `x.y.z Name (ABBR) Command` heading + `::= < Diameter Header: … >` →
  `Message`; per-run bold marks this-spec AVPs (only name runs are trusted).
  The keyword may be lower-case (`command`: TS 29.214's Rx commands in
  clause 5.6, 29.212's STR/STA in 5c.6.4–5).
  Behind `message-headings`, an `x.y.z Name message` heading over a rule
  spelled with the abbreviation (`<ACR> ::=`, TS 32.299) gives the long name,
  as RFC 6733's `<CER> ::=` does in the RFC extractor; message headings
  without a rule (32.299's 6.4.6–6.4.13, pointers to RFC 6733) are not
  definitions.
- `x.y.z Name AVP` heading + `::= < AVP header: … >` → `GroupedAvp`.
  Behind `access-type-headings`, the heading may name the access types the
  AVP applies to after it (TS 29.212's `Event-Trigger AVP (All access
  types)`, `Bearer-Operation AVP (Applicable access type 3GPP-GPRS)`, once
  without " AVP"; 29.214 clause 5.3.69), for this and the enumerated
  reading below. The
  rule name may be bracketed (`<Event-Type>::=`, `< Participant-Group > ::=`)
  and the keyword spaced (`AVP Header : 612`, 29.229).
- `x.y.z Name AVP` heading whose intro says "is of type Enumerated", with
  `ValueName (n)` items → `EnumeratedAvp`. Values are classified by content,
  not paragraph style (29.229 §6.3.34 inverts the B1/B2 convention).
  "Value n is reserved" notes become reserved ranges, inserted by value.
  Each departure from `NAME (n)` is read only where its quirk is declared,
  and a line needing two is read only with both: a label of several words
  keeps its spaces (`worded-enum-values`, TS 29.368's `Device Trigger
  Request (1)`); a leading list dash is dropped (`dashed-enum-values`), as
  is a comma or full stop after the value (`punctuated-enum-values`); a
  hexadecimal value is read as its number (`hex-enum-values`, TS 29.214's
  `OTHER (0xFFFFFFFF)` is 4294967295); the rest of the line after the value
  is its description (`described-enum-values`, TS 29.109's `NO (0) The
  sending node is not GBA_U aware`), the document's own one-line gloss, or,
  with no name before the value, its name less a closing full stop
  (`label-after-enum-value`, 29.109's `- (0) Private user identity.`, the
  label Wireshark records too); several values run together in one
  paragraph are each read (`run-on-enum-values`, TS 29.229 clause 6.3.58).
  Behind `value-first-enums`, TS 32.299's `0 PS to CS Transfer` lines are
  read too: the label ends at the first colon and the rest of the line is the
  value's description (`2 High priority: Lower than Pre-emptive priority`,
  7.2.132); `11 .. 99 Reserved for …` is a reserved range, and a range
  allocated otherwise (`100 .. 199 Vendor specific SM services`, 7.2.213)
  names no value and is reported. Behind `external-enum-values`, a clause
  that says where its values are defined instead of listing them gets that
  citation as `; Values:`, in the document's words: TS 29.272's twelve
  trace and MDT AVPs ("The possible values are those defined in TS 32.422
  [23] for Trace Depth", 7.3.67), TS 29.061's `MBMS-HC-Indicator` ("The
  enumeration values are defined in 3GPP TS 25.413 [92]", 17.7.25), TS 29.212's `Default-Access` ("the same as
  the ones defined in IP-CAN-Type AVP", 5.3.120), TS 32.299's `Type-Number`
  (OMNA WSP Content Type Numbers, 7.2.238) and `API-Network-Service-Node`
  (TS 23.682, 7.2.20eA). An enumerated clause yielding neither values nor a
  citation keeps an empty definition and warns; no clause in the corpus
  does today.
- The table with the "AVP Flag rules" header → `AvpTable`. A row whose code
  cell is a NOTE reference gets `code=None`; a note naming a defining RFC also
  produces a `ReusedAvps` row (`note-defined-in-rfc`). Behind
  `refer-type-cells`, a Value Type cell `refer [n]` (TS 32.299 table 7.2.0.1,
  for AVPs "just borrowed from other applications", clause 7.2.0) leaves the
  row untyped and adds a re-used row citing clause 2's reference n,
  thirteen of them `OMA-DDS-Charging_Data` (`[223]`); an entry naming no
  document warns and adds none. Behind `referred-type-sentences`, such a
  row whose own clause opens "The DCD-Information AVP (AVP code 2115) is of
  type Grouped." takes that type, the re-used row staying: clauses 7.2.50,
  7.2.69 and 7.2.191 type `DCD-Information`, `IM-Information` and
  `Service-Generic-Information` so, print no body and say "The AVP is
  defined in OMA-DDS-Charging_Data [223]". A clause giving another code
  fails, and one stating no type warns.
- Behind `vendor-id-sentence`, an AVP table whose clause says "The
  Vendor-ID header of all AVPs defined in this specification shall be set
  to 3GPP (10415)." gets V under Must in each row whose flag cells are all
  blank: TS 29.389 table 6.3.1-1 prints none for its three rows, in every
  version from V14.0.0 to V19.0.0, and the sentence in clause 6.3.1 is the
  document's one statement of the bit (RFC 6733 section 4.1.1 sets V
  exactly when the header carries a Vendor-ID). The M cells stay blank, as
  printed; a row printing any flag is left alone, and a clause without the
  sentence fails.
- The "re-used Diameter AVPs" table → `ReusedAvps` with M-bit overrides,
  and the code and type where the table prints them (TS 29.172 table
  7.4.1-2).
- Behind each mark column's quirk, its cells → the row's marks, in AVP and
  re-used tables alike. A cell is split at commas and spaces; behind
  `worded-marks` at commas only, since TS 29.468 names a feature "V2X
  Localized User Plane", as do TS 29.368 ("MSISDN-less MO-SMS Delivery")
  and TS 29.061's table 20.5a.1 ("MBMS Cell List"). A parenthetical stays
  with the mark it follows, as printed (`All (NOTE 5)`, `All (see NOTE 3
  and NOTE 6)`, `Non-3GPP-EPS (NOTE 11)`): TS 29.212's note 5 says the AVP
  "does not apply to 3GPP-GPRS access type", which a bare `All` would lose.
  A mark that is not words fails, for a patch: TS 29.212 line-wraps
  `NetLoc- Untrusted-WLAN` and `3GPP- EPS` and once separates with a full
  stop, `3GPP-GPRS. 3GPP-EPS`. A printed dash is no marks and a blank cell
  is none at all, kept apart because TS 32.299 says what the dash means
  (clause 7.1.0: "Those Diameter AVPs that are not used are marked '-'")
  and leaves four cells blank: table 7.1.0.1's `Tariff-Time-Change` under
  ACA and `Termination-Cause` under ACR, table 7.2.0.1's two
  `Related-IMS-Charging-Identifier` rows under CCA.
- Behind `vendor-avp-tables`, a table of other vendors' AVPs → `ReusedAvps`
  of its own, pairing with no AVP table: TS 32.299 tables 7.3.1 (3GPP2),
  7.4.1 (ETSI) and 7.5.1 (oneM2M) list AVP Name, AVP Code, "Used in" and a
  Reference cell holding a clause-2 number, and clauses 7.3–7.5 say "the
  specification including the detailed definition and description, is
  referred to". The Reference becomes the From cell (`[215]` is TS 29.212,
  `[300]` `ETSI-TS283.034`, `[301]` `oneM2M-TS-0004`); the AVP Code becomes
  the row's code and the "Used in" columns its command marks, and the
  vendor-id each clause states in prose (5535, 13019, 45687) is not read, a
  re-used row's identity being its origin's. A reference naming no document
  warns and adds no row.
- An AVP table whose labelled header is followed only by blank cells
  contributes no definitions and warns (TS 29.330 table 6.3.1-1); non-empty
  malformed tables still fail. The AST retains its non-empty table invariant.

Conventions worth knowing:

- `Page:` is where the *section* starts in the PDF bookmark outline; a table
  inherits its parent section's page.
- An enumerated AVP listed as re-used, or referenced from an AVP-table NOTE,
  gets no local definition: its section has nothing to emit (DRMP in 29.229,
  values in RFC 7944). Grouped AVPs are *not* treated that way: TS 29.272
  re-prints nine of 29.212's grouped AVPs in full and lists them as re-used;
  the bodies are kept and the linter reports the conflict. A row citing the
  document itself is no re-use: TS 29.212's Gxx, S9, Sd and St re-used
  tables (5a.4.0, 5b.4.0, 5c.4.1, E.6.4.1) list Gx's AVPs from TS 29.212,
  and 29.061's SGmb table (20.5) cites 29.061, so their enumerated clauses
  are still read.
- Enumerated AVPs take their code from the AVP table and their vendor-id from
  the spec's grouped-AVP headers; with no grouped header (29.109) the 3GPP
  vendor 10415 is used. Conflicting candidate vendors are an error.
- A flag named twice (`M,M`) fails rather than collapsing.
- Clause prose is not captured. `EnumValue.description` exists for
  hand-written files; a 3GPP clause has no one-line gloss to put there.
- Table captions are matched as a general dotted label (`Table 7.3.1/1`,
  `Table 6.3.1-1`, `Table B.1.1`, `9A.2.1`): a table whose caption goes
  unrecognised is rejected for having none.
- The publisher prefix on a From cell is optional for 3GPP and IETF
  (`TS 29.272 [10]` in 29.344, 29.388). A bare clause number cites the
  document itself (29.336's S6t table). Another publisher's document is
  read with its publisher, as the cell or clause 2's entry prints it:
  `ETSI TS 283 034` → `ETSI-TS283.034`, `3GPP2 X.S0057` →
  `3GPP2-X.S0057`, `OMA-DDS-Charging_Data`, `oneM2M TS-0004` →
  `oneM2M-TS-0004`; a clause-2 entry is read for what precedes its title.
  Behind `origins-by-reference`, a cell printing a TS series 3GPP does not
  number under 3GPP's name is read through the clause-2 entry it cites,
  which must name the same number: TS 29.212's "3GPP TS 283 034 [37]"
  (table 5.4.0.1, beside "ETSI TS 283 034 [37]" elsewhere) and TS 29.214's
  "3GPP TS 183.017 [15]" (table 5.4.0.1), whose entries are ETSI's. Without
  the quirk such a cell fails.
- More than one AVP/re-used table pair per document (29.336, 29.338) is
  paired in document order; counts that cannot pair are an error, and one
  name with two codes across tables is an error unless declared as above.
  Several AVP tables with no printed re-used table (32.299's 7.1.0.1 and
  7.2.0.1) each get their own synthesised block.
- A table whose every row merges each visible column across the same grid
  columns (29.336 table 8.4.1-2) is collapsed to its physical columns; mixed
  merge patterns keep their grid positions. Behind `physical-avp-columns`,
  an AVP table whose rows change grid spans (32.299 table 7.2.0.1: eight
  patterns over 42 grid columns) is read by physical cells, dropping the
  empty one-column sliver that ends some of its rows and its header.
- Column labels are matched by spelling map (`_AVP_TABLE_COLUMNS`,
  `_REUSED_TABLE_COLUMNS`), with note references stripped. The name column
  is "Attribute Name" or, in TS 32.299, "AVP Name"; a two-row header whose
  lower row carries the labels is read from that row, also when only the
  upper row prints the name label (32.299 table 7.2.0.1). "Comments",
  "Description" and "Comment" columns are dropped silently as prose; any
  other unmodelled column, or a mark column whose quirk the document does
  not declare, produces a warning. Standing: TS 29.212's label-less last
  columns in tables 5b.4.0.1 and 5c.3.1.1.
- A flags cell holding a lone `-` is empty (TS 32.299). A clause cell that
  is no clause number fails naming its row (29.368's `6. 4.2`, patched).
- The cover title is read from the cover table or a plain paragraph (29.061,
  29.212, 29.214). `attach_pages` reads the PDF's own cover and refuses a
  different specification or version, warns when the outline covers only
  some sections, and errors when it covers none.
- A second AVP table or re-used table beyond a pairable set is rejected
  naming the sections. Missing captions and split tables have no collected case.

ABNF is read line by line: a paragraph is split at its manual line breaks,
and bold and strikethrough belong to the line. TS 32.299 prints whole bodies
as one paragraph, and so do parts of 29.172 and 29.273, whose bodies the
paragraph-level reading had truncated. Blank lines inside a body are
skipped when another member follows (32.299's message rules); a line made
entirely of several members is read as several (32.299 clause 7.2.154I,
printed so in the PDF too); any other line ends the body. A struck-through
member carries `; strikethrough`, as a bold one carries `; bold`, and a
line only partly struck fails. Without a legend the extractor reads, the
member stays a member and warns, naming its rule. Behind
`struck-rules-unused`, TS 32.299's own legend (clauses 6.2.1.2, 6.4.1.2:
"An AVP in grey strikethrough … is not used by 3GPP") makes it no member,
and the line is commented out where it stood, marker kept, so `seanchai
format` and the corrections leave it in place. ACR (clause 6.2.2) strikes
five members:

```dad
<Accounting-Request> ::= < Diameter Header: 271, REQ, PXY >
        < Session-Id >
        ...
        [ Acct-Application-Id ]
;;      [ Vendor-Specific-Application-Id ] ; strikethrough
        [ User-Name ]
        [ Destination-Host ]
;;      [ Accounting-Sub-Session-Id ]      ; strikethrough
;;      [ Acct-Session-Id ]                ; strikethrough
;;      [ Acct-Multi-Session-Id ]          ; strikethrough
        [ Acct-Interim-Interval ]
;;      [ Accounting-Realtime-Required ]   ; strikethrough
```

ACA, CCR, CCA and clause 7.1.9 strike 29 more. A PDF's text layer keeps
the words and loses the strike, so text extracted from the PDF shows them as
ordinary optional members; the docx's run formatting is what records them as
struck.

Real-document cases handled in code or by patch, kept as evidence: heading
and rule-name mismatches (29.329 §6.1.8); Diameter headers omitting the
application id (29.272 VCSG → `application_id` optional); two ABNFs under
one command heading (29.272 IDR/DSR/RSR, S6a + S7a); empty clause cells
(29.272 3GPP2-MEID → `AvpTableRow.section` optional); merged rows
duplicating cell text; the H6 heading style (29.273 §6.2.2.1.1); headings
without " AVP" (29.272) or with it
hyphenated on (29.214, patched); an underscore in a published name
(29.109's `GBA_U-Awareness-Indicator`); `<AVP header: 632, 10415>` comma
separator (29.229); the RFC 3588 `P` flag still printed (29.061, 29.212,
29.214, 29.273); annex clause numbers (`E.6.3.6`); parenthesized note
references on name cells (`(NOTE 3)`, two stacked); a label-less empty
fourth column in a re-used table (29.212's 5b.4.0.1, dropped with a
warning); one AVP
printed with two bodies (29.336 §6.4.2 and §8.4.36, the second deleted by
correction); "Void" as an enum value label (29.214, deleted by correction);
a clause heading printed as a body paragraph (32.299 §7.2.135C,
`body-clause-headings`); names broken by a space after a hyphen (32.299,
29.343's heading 6.4.10, 29.154's table 5.4.1; a re-used name cell with a
space fails like an AVP table's), an en dash, a Symbol-font dash and `V/M`, `VM` flag
cells (32.299, patched); a trailing comma in a flags cell (29.217
table 5.3.1.1, patched); a brace closing an optional member (29.343 §6.6.4,
patched); a From cell dropping "RFC" (29.219 table 5.4, patched); a
drafting placeholder `5.3.x` for a clause number, "is of type of
Enumerated" in an enumerated clause's intro and an `Octetstring` type
(29.215, patched; "is of type of Enumerated" and "is type of Enumerated" in
29.212 too); "is of type enumerated" in lower case (29.338 §6.3.3.6,
patched); a space inside an enumerated value name
(`SIPTO_above_RAN _ALLOWED` in 29.272 §7.3.135, also 29.172 §7.4.9, 29.212
§5.3.7 and §5.3.31, 29.214 §5.3.1 and 29.338 §5.3.3.19, patched; unpatched, the value was silently not
a value).
Everything patched is listed with its reason in `edits/sources/`.

TS 29.228 v18.0.0 and TS 29.328 v18.2.0 contain procedure/IE mappings,
not Diameter ABNF or AVP definition tables. In both, annex A.1 assigns the
Diameter definitions to TS 29.229 and TS 29.329 respectively (already in the
corpus); table A.2.1 supplies command names and abbreviations, but no codes,
flags or bodies. `regenerate --add` rejects them with `no AVP table found`;
a message-only convention cannot supply those missing definitions. TS 29.213
also has no ABNF or definition tables and is outside this extractor's scope.

TS 29.305 v18.0.0 describes MAP/Diameter interworking (clause 1 and annex A)
without command ABNF or AVP definition tables, so it is also outside scope.
TS 29.201 v18.0.0 (a legacy `.doc`) carries TS 29.214's Rx messages over
REST: annex B is an XML Schema for 29.214's AVPs (B.1) and messages (B.2),
with no ABNF, AVP codes or AVP table, and `regenerate --add` rejects it with
`no AVP table found`. Nothing in the corpus cites it.
TS 29.230 v18.6.0 is an allocation registry rather than a definer, read
behind two quirks of its own:

- `registry-tables`: a table whose first column is "Application
  identifier" (4.1), "Command code value" (5.1/1–5.1/4), "AVP Code" (7.1)
  or "Experimental Result Code" (8.1.2–8.1.4) → `Registry`, one block per
  table, read by physical cells (table 7.1 merges its four columns across
  six grid columns in four patterns). A "Specified in" cell is one or more
  `29.229 [2]`, separated by commas or "and", and the row cites each by its
  number; a reference clause 2 lists for another document warns and the
  number is read: TS 29.215 defines TER, which table 5.1/4 cites as
  "29.215 [30]", clause 2's TS 29.338. A Data Type cell's dash and blank
  are both no type, the registry's type being informational. A row with no
  code warns and is not read: tables 7.1 (`29.561 [42]`), 8.1.2 (`29.109
  [7]`), 8.1.3 and 8.1.4 (`32.299 [5]`) print a document alone ahead of the
  range reserved for it.
- `unknown-type-tokens`: a Type cell naming no Diameter type is kept as
  printed, quoted, beside the closed set rather than patched to a guess:
  table 7.1 types code 314 (Charging-Characteristics, TS 29.234) `"Integer"`,
  which could be Integer32, Integer64 or neither, and TS 29.234 is outside
  the corpus. Undeclared, such a cell fails.

  No source settles 314's type, so the row stays as printed and no
  correction supplies one. TS 29.234 clause 10.1.27 says "of type Integer"
  in every version that has the AVP, V6.1.0 to its last, V11.2.0, never
  with a width; it carries "the charging mode … as described in 3GPP TS
  32.215", whose information element (clause 6.1 and annex A, and TS
  32.298's ASN.1 on 3GPP Forge today) is `OCTET STRING (SIZE(2))`, a
  16-bit string of Profile and Behaviour bits. Wireshark types 314
  OctetString since MR !4102 (commit `61e1e69218`, 2021), which states no
  rationale and rewrote `dictionary.xml`'s comment to `314
  Charging-Characteristics Integer [3GPP 29.234]`; freeDiameter, and Open5GS through
  it, and EasyDiameter read Integer32, python-diameter OctetString.
  OctetString fits the information element and Integer32 the document's
  word; neither is the document's statement.
- `reserved-range-notes`: a full-width note row → a reserved range per
  line reading "The AVP codes from a to b are reserved for P" or "The
  Experimental Result Codes from a to b …", P less its closing full stop the
  purpose, as printed ("TS and TS 29.389", "future use"), and every `TS
  n.n` it names the range's documents. Any other line of a note row warns:
  table 7.1's two "Note 2" lines on where 3GPP-AAA-Server-Name moved.

The input patches repair what fails these readings: three reference cells
(`29.153[37]`, `29.154[38]`, `29.109 [7`), `723 to799`, three type typos
(`OctectString`, `Groupe`, `UTF8Str`) and six names broken beside a hyphen (`Redirect- Support`, `Authentication- Information
-Request/Answer`). Forty-seven more respell table 7.1's names to the
defining clause's, twenty-one differing only in case (`Role-of-Node`, TS
32.299's `Role-Of-Node`) and the rest otherwise (`"Visited PLMN Id"`, TS
29.272's `Visited-PLMN-Id`); see [linter.md](linter.md#standing-findings).
A name with spaces no patch respells stays as printed, quoted
(`"SGSN-Absent-User-Subscriber-Diagnostic SM"`, whose defining clause
prints two names).

## oneM2M TS-0004

oneM2M TS-0004 (Service Layer Core Protocol) binds the Mch reference point
to Diameter accounting in its annex A, "Binding Mch to Diameter for
Charging". The downloader fetches the Word original of the Release 2 line,
V2.35.0, and converts it ([downloader.md](downloader.md)); ETSI mirrors the
line as TS 118 104, PDF only, whose V2.7.1 prints annex A's table A.4-1,
clause A.5 and `M2M-Information`'s ABNF as V2.35.0 does (the commands' ABNF
differs: V2.35.0 lists the RFC 6733 accounting members and no longer prints
`[ Service-Context-Id ]` and `[ Service-Information ]`). The document is on
3GPP's Word conventions — `PL` ABNF, `TH` captions, an "AVP Flag rules"
table — and the 3GPP extractor reads it whole; nothing outside annex A is a
definition it recognises.

- **The cover** prints the document number, `oneM2M-TS-0004-V2.35.0`, read
  as `; Specification: oneM2M TS-0004` and `; Version: 2.35.0`. The file's
  `; Vendor-ID:` is oneM2M's 45687, as 10415 is stated for 3GPP: "AVPs
  defined for oneM2M specific usage are assigned Vendor-Id of 45687"
  (clause A.4). No PDF of V2.35.0 exists, so no `; Page:`; `; Link:` is
  oneM2M's download.
- **Headings print no clause numbers** (`list-numbered-headings`). Annex A's
  carry a `w:numPr` whose level text in `word/numbering.xml` is `A.%1`,
  `A.%1.%2`, so "Accounting Request Command" is A.2.1 only as Word renders
  it. The extractor replays the numbering: every numbered paragraph of the
  body, in document order, advances its list's counter at its level, deeper
  levels restart as their `w:lvlRestart` says, and counters belong to the
  abstract numbering. A `w:num`'s `w:lvlOverride` redefines a level for its
  paragraphs, an embedded `w:lvl` property by property (start, level
  text, format, restart) and a `w:startOverride` its start; the level
  restarts at the `w:num`'s first paragraph and, whenever a level above
  restarts it, from that start. A paragraph's `w:numPr` gives its list and
  its level each, and what it leaves out comes from its style's (`basedOn`
  followed), as Word merges them. A heading that prints no number takes the
  rendered one; one that prints its own keeps it. The result is the
  document's own numbering: annex A's 39 headings read A.1 to A.5.32 as TS
  118 104 V2.7.1 and TS-0004 V5.2.0's Word file print them, and 350 of the
  351 headings whose title V2.7.1's contents list holds once agree with it,
  the one other a clause V2.35.0 renumbers. Paragraphs inside tables are
  not replayed; no heading list continues into one.
- **Commands.** Clauses A.2.1 and A.2.2 head them "Accounting Request
  Command" over `<ACR> ::=`. Input patches join the words to RFC 6733's
  names (clauses 9.7.1, 9.7.2; the clauses define the format "according to
  the Diameter Base Protocol in IETF RFC 6733 [14]"), and
  `message-headings` reads a "Name Command" heading as it reads TS 32.299's
  "Name message". Neither header prints an application id, and no clause
  says one beside them; clause A.5.2 says that Acct-Application-Id
  "shall contain the value of 3" on Mch, which a correction records as the
  `Mch` application scope over `A.2.*`, as TS 32.299's clause 7.1.5 is.
- **Table A.4-1** mixes vendors, each row printing its own "AVP Vendor Id"
  (0, 10415 or 45687), read into the `Vendor-ID` column
  ([grammar.md](grammar.md#avp-table)), which is modelled wherever a table
  prints the label. Behind `reference-cells`, its Reference column, "a
  reference to where this AVP is defined" (clause A.4), is read cell by
  cell: a bracketed clause (`[A.5.1]`) is the row's Section, a document
  (`IETF RFC 6733 [14]`, `IETF RFC 4006 [32]`, `3GPP TS 32.299 [31]`) a
  re-used row citing it, which the extractor adds to a re-used block of
  the table's own, as it does for TS 32.299's `refer [n]` rows. The row
  stays in the AVP table with its marks, type and flags. The "Used in"
  columns are `command-columns`' marks and `DiamIdent` is
  `type-short-forms`'. The table puts V under Must not in each row of
  vendor 45687, and in 3GPP's `Service-Information`, which
  `vendor-flag-mismatch` reports and the corrections move to Must, citing
  clause A.4's vendor and RFC 6733 section 4.1.1; they also type
  `Service-Context-Id` UTF8String, as clause A.5.26 does where the table
  says Grouped, and point three Reference cells at the clauses their
  headings name (`[5.5.1]`, `[5.4.2]` and `[A.5.2]` for A.5.2, A.5.3 and
  A.5.4).
- **Definitions.** `M2M-Information`'s rule (A.5.14) spells its operator `::
  =` (`spaced-rule-operator`) and prints `< AVP Header: 1011>`, no vendor
  (a correction gives it table A.4-1's 45687), and two members on one
  line. An enumerated AVP takes its vendor from its
  row's Vendor-ID cell where the table prints one, 0 being no vendor:
  `Accounting-Record-Type` is IETF space, `Protocol-Type` 45687.
  `Protocol-Type`'s values are value first (`value-first-enums`, "0 HTTP"
  to "3 WebSocket", "4 .. 99 Reserved for oneM2M defined protocol types";
  "100 .. 199 Operator and vendor specific protocol types" allocates a
  range and warns, as TS 32.299's SM-Service-Type does);
  `Request-Operation` and `Response-Status-Code` cite where theirs are
  ("The values are defined in Table 6.3.4.2.5-6.", "... in clause 6.6.3.",
  `external-enum-values`); `Accounting-Record-Type` names its one value in
  a sentence, "EVENT_RECORD (value 1)" (`prose-enum-values`).
  `Subscription-Id-Type`, "of type Enumerated as defined in IETF RFC 4006
  [32]", is re-used and gets no local definition.
- Not read: the type sentences of simple-typed clauses ("The
  Access-Network-Identifier AVP (AVP Code 1000) is of type Unsigned32"),
  whose rows carry code and type, as the ETSI transcriptions leave them;
  table A.3-1, mapping oneM2M's recorded information elements to AVP
  names; and the prose of clauses A.5.26-A.5.31.

## The RFC plain-text extractor

Same definitions, different carrier:

- **Page furniture.** Footer lines ending `[Page N]`, a form feed, then a
  running header recognised positionally, never by text. `; Page:` numbers
  are the RFC's own printed pages.
- **Wrapped rows.** A long name wraps (`Acct-` / `Interim-Interval`), and
  once the other way (`Inband-Security` / `-Id  299 …` with data cells on the
  continuation). A line whose name fragment sits at the Attribute Name column
  starts a row; anything deeper continues it; every cell must arrive on
  exactly one line. RFC 4004's fragments outside the box are
  `bare-name-continuation`; RFC 5778's "Rest of the AVPs" prose row is
  `prose-catchall-row`.
- **More than one table.** A repeated header after a page break continues
  the table; a header after closing prose starts another.
- **Border styles.** RFC 6733 boxes only the flag columns; 7683, 7944 and
  8581–8583 box the whole table with `+` intersections. RFC 8583's stray
  space in a closing rule is `ragged-separator`.
- **Header labels are whole spellings**, mapped in `_LEFT_HEADERS`; an
  unrecognised header fails loudly and earns an entry. Stacked flag labels
  (`MUST` over `NOT`) are read generically.
- **Short forms** (`DiamIdent`, `DiamURI`, `IPFiltrRule`, `QoSFltrRule`) are
  accepted per document behind `type-short-forms`.
- **Tables without flag columns** (RFC 5777's IANA table) map onto the four
  columns they have. **Clauses without tables** (RFC 4072, 5447) form the
  index behind `clause-avp-table`; RFC 4590's RADIUS attributes contribute
  Name, Code and Section behind `radius-attribute-table`, with no type
  fabricated.
- **Tables without a Code column** (RFC 7155): `prose-avp-codes` follows each
  row's Section cell to the defining sentence ("The NAS-Port AVP (AVP Code 5)
  is of type Unsigned32") and completes the row, extending `; Columns:` with
  Code and Type. A row with no sentence keeps `None` and warns; a sentence
  with no row warns.
- **Stated facts.** `; Vendor-ID: 0` always; no `; Version:` and no
  `; Table:`, since neither exists for an RFC.
- **Definitions anchor on section titles.** A bare-name title
  (`Capabilities-Exchange-Request`) or `Name AVP` is a candidate; a prose
  title is not, which keeps the CCF grammar's `Example-Request` and
  `<answer-message>` out. Commands take the long name from the heading and
  the abbreviation from the rule (or from an `AA-Request (AAR) Command`
  heading). RFC 6733's base commands print no application id and the file
  records its absence; no RFC states its ids in a wording a second one
  shares, so their application scopes come from corrections. Blank lines
  inside a body are page-break residue.
- **Grouped AVPs** may write the rule name bracketed or bare, and `1* {AVP}`
  without inner spaces. A body printed for another document's AVP is kept
  (RFC 8581/8582 re-print 7683's `OC-OLR`), for the linter to compare.
- **Enumerated AVPs**: a value list under a name-titled section, when the
  local table types the name Enumerated. Both layouts are read (value alone
  with description below; description on the value's line and wrapping) plus
  older `2 HMAC-SHA-1` and `0 | IN - …` forms. Value names are all-caps in
  every collected RFC and requiring that keeps prose out; RFC 6734's
  mixed-case `rRK (1)` is a declared quirk, as are names of several words
  (`"CHAP with MD5" = 5`, RFC 4005 §5.5, 7155 §4.3.5) and RFC 5777's
  `(0): QoS-Desired`. With `worded-enum-values`, RFC 4005's informational
  lists (§4.4, 5.3, 6.1, 6.10.1, 6.10.2, 6.10.4, 6.15.3, 7.2, 7.3) are read
  whole: a value-first line's label is every word after the number, a
  closing reference tag dropped as it is after a one-word label (`17
  Authorize Only  [RADDynAuth]`), and a line indented past the label's first
  character continues it (`12   ADSL-CAP - Asymmetric DSL, Carrierless
  Amplitude Phase` over `Modulation`). §7.3's `802 (includes all 802 media
  plus Ethernet "canonical format")` is written with the quotes escaped
  ([grammar.md](grammar.md#enumerated-avp)). §6.1 then re-lists four values
  it qualifies, two worded ones reading a second time; the raw file keeps
  both copies and corrections delete the repeats. Behind `external-enum-values`, a clause that says
  where its values are listed gets that citation as `; Values:`, in the
  document's words up to the sentence's end, with or without a list beside
  it: RFC 6733's `Termination-Cause` ("can be found in the IANA registry
  for Termination-Cause AVP Values [IANATCV]", §8.15), RFC 5777's six
  "managed by IANA under the … registry" AVPs, RFC 4005's and 7155's
  `[RADIUSTypes]` and `[RADIUSAttrVals]` (7155's `Accounting-Auth-Method`:
  "identical, to the Microsoft MS-Acct-Auth-Type vendor-specific RADIUS
  attribute [RFC2548]", §4.6.7), and RFC 5778's `MIP-Algorithm-Type`
  ("defined in [RFC4004] that also fulfill current RFC 4285 requirements",
  §6.13). Warnings record a value list for a name not typed Enumerated (RFC
  8581 extending 7683's `OC-Report-Type`, which `.dad` cannot express; RFC
  6733's `Inband-Security-Id` and `Session-Binding`), an Enumerated AVP
  with neither values nor a citation, and value-first lines an enumerated
  clause holds but the reading leaves out; no clause in the corpus has
  neither today.
- **Values printed outside a value list.** An Enumerated row whose own
  clause yields nothing is read in two more shapes, each behind its quirk.
  `cause-mapping-table`: RFC 4005's `Termination-Cause` row cites §9.3.5,
  which "extends the definitions in the 'Termination-Cause AVP' section of
  the Base Diameter specification" with a table mapping RADIUS
  Acct-Terminate-Cause values onto Diameter ones (`User Request | 1 |
  11`); the worded cause is the name, quoted, and the Diameter column the
  value, 11–32, with the four rows' closing `[RAD802.1X]` dropped as a
  citation. RFC 6733 §8.15 lists none of its own (it cites the IANA
  registry), so nothing repeats. `registry-enum-values`: RFC 5778 §6.20
  "defines only one value MIP6_AUTH_MN_AAA" without numbering it, and the
  IANA section §9.5, a registry "for use with the enumerated MIP6-Auth-Mode
  AVP", numbers it in a `Token | Value | Description` table. The
  definition cites §9.5, where its values are printed, and every token must
  be one the defining clause names, so the registry numbers values and adds
  none. The section's "The value 0 (zero) is reserved" is read too, as a
  reserved value.

## Transcriptions

ETSI ES 283 034 V2.2.0 (e4) and TS 183 017 V3.2.1 (Gq'), which 3GPP
documents cite for `Logical-Access-ID`, `Physical-Access-ID` and
`Reservation-Priority`, are published as PDF alone, frozen, and on 3GPP's
Word template. No extractor reads them: each is copied by hand into
`edits/transcriptions/<SpecRef>.dad`, named like the other edit files, in
`.dad` notation, and its header says so (`; Transcribed: by hand from <the
PDF>`, written in the transcription). The transcription stands where the
document does for an extraction, and the pipeline is the extractor's:

    transcription → input patches → raw → corrections → corrected

The transcription copies what the document prints, misprints included,
even where the grammar cannot hold it, so it need not parse. Input
patches in `edits/sources/<SpecRef>.toml`, with the 3GPP files' schema,
apply to its lines, a patch's `section` scope being the `; Section:` of
the line's block; the patched text must parse, and is the raw file
(`dad/raw/etsi/es283034-020200.raw.dad`, named with ETSI's version code as
the 3GPP files are with the archive's). Corrections
(`edits/corrections/ETSI-ES283.034.py`) make the corrected file from it.
`seanchai regenerate` reads `edits/transcriptions/` (`--transcriptions`)
as it reads the manifest's documents, version-range warnings and
`--expand-ranges` included, and `tests/test_transcription.py` pins each
committed raw file to its patched transcription.

A transcription gives each construct the shape the 3GPP extractor gives it:

- Commands and grouped AVPs as their ABNF prints them, bold members
  `; bold` ("New AVPs are represented in bold", both documents' clause
  7.1), ABNF comments as trailing `;;` comments and an empty `;` dropped.
- The AVP table as an `AVP Table`, `Y` read as `Yes`, its NOTE rows as
  `;;` comments after the rows. Pages follow the extractor's rule: a
  section's `; Page:` is where its clause starts, and a table takes its
  clause's.
- An enumerated clause, which prints no ABNF, as an `Enumerated AVP` named
  by its defining sentence, "The X AVP (AVP code n) is of type
  Enumerated", since TS 183 017's headings sentence-case the names
  ("Latching-indication AVP"). The code is the sentence's; the vendor is
  the sentence's where it prints one (ES 283 034's "AVP code 305 13019"),
  or else the one the paragraph introducing the AVP's table states (TS 183
  017 sets 13019 for table 7.3.1's AVPs and 3GPP's 10415 for the Gq AVPs
  of table 7.3.3). Values as `NAME (n)` reads, the hexadecimal `OTHER
  (0xFFFFFFFF)` as its number, the rest of a value's line as its
  description. A clause that re-prints an imported AVP's values is
  transcribed too: what it lists may differ from the origin's (ES 283 034
  clause 7.3.11's `PRIORITY 0`–`7` against TS 183 017's `DEFAULT` and
  `PRIORITY-ONE`–`FIFTEEN`).
- A table of imported AVPs ("Diameter AVPs imported from …", ES 283 034
  tables 11–13, TS 183 017 tables 7.3.2–7.3.5) as `Reused AVPs` with Name,
  Code, From and Type. From is the document the row's clause cell names
  ("See TS 129 209 [5]" → `TS29.209`, ETSI's number for a 3GPP document
  read as the 3GPP one) or, where the cell holds the present document's
  own clause, the caption's (`ETSI-ES283.034` for TS 183 017 table 7.3.2).
  The tables also state flag rules "in the context of the present
  document" and TS 183 017's the local clause, for which a re-used table
  has no column: a `;;` comment above the table records them.
- An application id stated in prose as an `Application Scope`: TS 183 017
  clause 7 re-uses Gq's 16777222 for commands whose headers print none.
- What the grammar cannot hold is copied as printed and patched on input,
  citing the clause that states it otherwise: ES 283 034's `< User-Data
  -Request >`, TS 183 017's `< AVP header: x >` for `Flows` (510 in its
  sentence and table 7.3.3), its `Octet String` cells and the
  `Media-Sub-Component AVP` name cell. Only the notation is the grammar's
  (`< AVP header: 300 13019 >` for the printed `< AVP Header: 300 13019 >`,
  `[ Address-Realm ]` for `[Address-Realm]`), spellings the 3GPP extractor
  reads in code.

Not transcribed, as an extractor reads none of it: clause prose, the
defining sentence of an AVP of a simple type (its AVP-table row carries
code and type; no section holds a sentence), experimental result codes and
the informative annexes.

## Strictness

Everything that can fail an extraction derives from `ExtractionError`,
including `PatchError`. Non-fatal inconsistencies go to a `warnings` list the
CLI prints to stderr, also when a later stage fails. The docx and the PDF
must be the same specification and version, which matters because the
downloader can fall back to an earlier ETSI rendering.
