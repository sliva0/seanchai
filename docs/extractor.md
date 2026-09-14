# The extractors

Two extractors produce the same `.dad` AST: `extractor/tgpp_docx.py` for 3GPP
`.docx` specifications (page numbers attached from the matching ETSI PDF) and
`extractor/rfc_text.py` for RFC plain text. Both read per-document
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

Typos in the source that break extraction, patched on the normalized
paragraph, cell and title text before parsing:

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
RFC 5580 declares `mixed-table-borders` (clause 6 boxes only flags in the
header but whole data rows) and `radius-avp-codes` (clause 6 takes the codes
from the Type fields in 4.1–4.7). RFC 6734 uses `clause-avp-table` (3.1–3.1.5,
including the bare Key-SPI heading) and `parenthesized-enum-values` (3.1.1's
mixed-case `rRK (1)` and `rMSK (2)`). RFC 6942 uses `clause-avp-table` and
`prose-cleared-flags` for the explicit cleared M/V bits in 8.1–8.2.
Docx extractor: `message-only` (TS 29.330 §6.3.1 has no local AVPs;
commands and re-used rows are retained), `note-defined-in-rfc` (TS 29.229, 29.329), `dotted-flags`
(TS 29.061, 29.212), `clause-parenthetical` (TS 29.061). TS 29.273 declares
`command-reference-only` (clauses
4.2.2.4.3–4, 5.2.2.3.5–6, 11.2.2.1.1–2 contain only clause pointers),
`procedure-commands` (8.2.2.1–4 name commands in preceding intros),
`physical-reused-columns` (table 8.2.3.0/2 changes its grid spans),
`independent-avp-tables` (clauses 5–11 have no one-to-one pairing), and
`conflicting-avp-codes` (table 8.2.3.0/1 contradicts 5.2.3.24; retain
both rows, refuse an ambiguous enum code). Not gated: the
"Y"/"N" Encrypt spellings and TS 29.338's "Must"/"Must not" M-bit short
forms, closed vocabularies that cannot be misread.

## The 3GPP docx extractor

Walks paragraphs and tables in document order under numbered headings:

- `x.y.z Name (ABBR) Command` heading + `::= < Diameter Header: … >` →
  `Message`; per-run bold marks this-spec AVPs (only name runs are trusted).
- `x.y.z Name AVP` heading + `::= < AVP header: … >` → `GroupedAvp`.
- `x.y.z Name AVP` heading whose intro says "is of type Enumerated", with
  `ValueName (n)` items → `EnumeratedAvp`. Values are classified by content,
  not paragraph style (29.229 §6.3.34 inverts the B1/B2 convention).
  "Value n is reserved" notes become reserved ranges, inserted by value.
- The table with the "AVP Flag rules" header → `AvpTable`. A row whose code
  cell is a NOTE reference gets `code=None`; a note naming a defining RFC also
  produces a `ReusedAvps` row (`note-defined-in-rfc`).
- The "re-used Diameter AVPs" table → `ReusedAvps` with M-bit overrides.
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
  the bodies are kept and the linter reports the conflict.
- Enumerated AVPs take their code from the AVP table and their vendor-id from
  the spec's grouped-AVP headers; with no grouped header (29.109) the 3GPP
  vendor 10415 is used. Conflicting candidate vendors are an error.
- A flag named twice (`M,M`) fails rather than collapsing.
- Clause prose is not captured. `EnumValue.description` exists for
  hand-written files; a 3GPP clause has no one-line gloss to put there.
- Table captions are matched as a general dotted label (`Table 7.3.1/1`,
  `Table 6.3.1-1`, `Table B.1.1`, `9A.2.1`): a table whose caption goes
  unrecognised is rejected for having none.
- The publisher prefix on a From cell is optional (`TS 29.272 [10]` in
  29.344, 29.388). A bare clause number cites the document itself (29.336's
  S6t table). ETSI (`TS 283 034`, `TS 183.017`) and 3GPP2 (`X.S0057`)
  references are accepted as origins.
- More than one AVP/re-used table pair per document (29.336, 29.338) is
  paired in document order; counts that cannot pair are an error, and one
  name with two codes across tables is an error unless declared as above.
- A table whose every row merges each visible column across the same grid
  columns (29.336 table 8.4.1-2) is collapsed to its physical columns; mixed
  merge patterns keep their grid positions.
- Column labels are matched by spelling map (`_AVP_TABLE_COLUMNS`,
  `_REUSED_TABLE_COLUMNS`), with note references stripped. "Comments",
  "Description" and "Comment" columns are dropped silently as prose; any
  other unmodelled column produces a warning. The standing machine-readable
  candidates are 29.212's "Acc. Type" and "Applicability", 29.214's
  "Applicability", 29.061's "Applicable Reference Points", and the Code/Type
  columns 29.172 prints in its re-used table — see the roadmap.
- The cover title is read from the cover table or a plain paragraph (29.061,
  29.212, 29.214). `attach_pages` reads the PDF's own cover and refuses a
  different specification or version, warns when the outline covers only
  some sections, and errors when it covers none.
- A second AVP table or re-used table beyond a pairable set is rejected
  naming the sections. Missing captions and split tables have no collected case.

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
fourth column in a re-used table (29.212, dropped with a warning); one AVP
printed with two bodies (29.336 §6.4.2 and §8.4.36, the second deleted by
correction); "Void" as an enum value label (29.214, deleted by correction).
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
TS 29.230 v18.6.0 is an allocation registry: tables 4.1, 5.1/1–4, 7.1 and
8.1.2–4 assign applications, commands, AVPs and result codes. Reserved ranges
and multiple cited specifications cannot be preserved by the current
`.dad` definition blocks; its extraction remains deferred, not an empty
corpus file.

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
  records its absence. Blank lines inside a body are page-break residue.
- **Grouped AVPs** may write the rule name bracketed or bare, and `1* {AVP}`
  without inner spaces. A body printed for another document's AVP is kept
  (RFC 8581/8582 re-print 7683's `OC-OLR`), for the linter to compare.
- **Enumerated AVPs**: a value list under a name-titled section, when the
  local table types the name Enumerated. Both layouts are read (value alone
  with description below; description on the value's line and wrapping) plus
  older `2 HMAC-SHA-1` and `0 | IN - …` forms. Unparenthesized value names require all-caps to keep prose out;
  RFC 6734 declares its mixed-case parenthesized form separately. Warnings record a
  value list for a name not typed Enumerated (RFC 8581 extending 7683's
  `OC-Report-Type`, which `.dad` cannot express; RFC 6733's
  `Inband-Security-Id` and `Session-Binding`) and an Enumerated AVP with no
  local values (`Termination-Cause`).

## Strictness

Everything that can fail an extraction derives from `ExtractionError`,
including `PatchError`. Non-fatal inconsistencies go to a `warnings` list the
CLI prints to stderr, also when a later stage fails. The docx and the PDF
must be the same specification and version, which matters because the
downloader can fall back to an earlier ETSI rendering.
