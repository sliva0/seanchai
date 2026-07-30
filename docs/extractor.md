# The 3GPP docx extractor

`src/seanchai/extractor/tgpp_docx.py` walks a 3GPP specification .docx
(paragraphs and tables in document order, grouped under numbered headings) and
produces a `.dad` AST. `attach_pages()` then reads the bookmark outline of the
matching ETSI PDF rendering and attaches page numbers.

All source text is normalized exactly once, while building the section model,
and input patches are applied at that same point — so patch application
counting is exact and every later parsing step sees patched text.

## What maps to what

- `x.y.z Name (ABBR) Command` headings with a `::= < Diameter Header: … >`
  paragraph → `Message`; per-run bold marks this-spec AVPs.
- `x.y.z Name AVP` headings with an `::= < AVP header: … >` run → `GroupedAvp`.
- `x.y.z Name AVP` headings whose intro says "is of type Enumerated", with
  `ValueName (n)` items → `EnumeratedAvp`; `B2` items are value descriptions,
  `NO`-style "Value n is reserved" notes become reserved ranges, inserted in
  numeric order.
- The AVP-flags table (header cell "AVP Flag rules") → `AvpTable`. Rows whose
  code cell is a NOTE reference get `code=None`, and note texts naming a
  defining RFC additionally produce `ReusedAvps` rows — a prose harvest,
  so it runs behind the `note-defined-in-rfc` quirk.
- The "re-used Diameter AVPs" table → `ReusedAvps` rows with M-bit overrides.

## What the extractor does not decide

**A `.dad` file records everything the source document says about a
definition.** The extractor translates the document into the format; it does
not curate it. Where a specification is redundant, self-contradictory or
plainly wrong, that is what the file records, because the file's job is to be a
reviewable, diffable record of the document — and because the next version's
diff is only trustworthy if this version wrote down everything that could
change.

The scope is *definitions*: names, codes, vendor-ids, types, flag rules, value
lists, ABNF bodies, and where each came from. Not the document's narrative. A
specification is mostly prose, and `.dad` has nowhere to put a clause's
paragraphs, bullet lists and `NOTE:`s without mangling them — so it does not
try, and `; Section:` points at the clause instead. That is a boundary, not a
licence: inside it, nothing gets dropped for being inconvenient.

Three things follow, and they are worth stating because each one is tempting to
get wrong in the same direction:

- **Do not drop a block because another block contradicts it.** An AVP defined
  locally *and* listed as re-used is a real inconsistency in the specification.
  Deleting either side makes the file agree with itself by making it disagree
  with the document. Report it in the linter instead.
- **Do not drop a block because it looks redundant.** A clause that re-prints
  another specification's AVP is still a clause this document printed, and its
  body can change between versions.
- **Do not normalize a value into what it "should" be.** That is what the two
  patch layers are for, and they are separate precisely so the unedited reading
  stays on disk: [input patches](#source-declarations) fix honest typos in the source
  text — a flags cell reading `M. V`, a rule name written with spaces — and
  only where the document is typographically wrong, never where it is
  semantically wrong. [Corrections](corrections.md) fix data that extracts and
  parses fine but is wrong, and they are declared as data, so re-extracting
  without them always shows what the document said.

Making sense of the result — resolving references, choosing between a local
definition and a re-used row, filtering to what a particular consumer needs —
is the job of whatever reads `.dad` files, not of what writes them. A consumer
can always ignore information the file carries; it can never recover a
definition the extractor threw away.

## Conventions baked into the extractor

- `Page:` is where the *section* starts per the PDF bookmark outline. Table
  sections inherit their parent section's page, which can be one page before
  the table itself.
- An enumerated AVP listed in the reused table, or referenced from an AVP-table
  NOTE, gets no local definition even when its section reads like one. This is
  not a filtering rule — such a section has nothing to emit. DRMP is the case
  that forced it: "is of type Enumerated", and then no values, because RFC 7944
  defines them.
- Grouped AVPs are *not* treated the same way, deliberately. TS 29.272 §7.3.40
  re-prints TS 29.212's `Allocation-Retention-Priority` in full, code and all,
  while listing it as re-used one clause later; nine of its clauses do this.
  Those definitions are kept, because the document printed a body. The
  local/re-used conflict that results is a real inconsistency in the source,
  and reporting it is the linter's job — see
  [what the extractor does not decide](#what-the-extractor-does-not-decide).
- Enumerated AVPs take their code from the AVP table and their vendor-id from
  the spec's grouped-AVP headers, because enumerated sections print neither.
- A flag named twice (`REQ, REQ`, `M,M`) fails rather than collapsing into the
  single flag a `frozenset` would leave. The repeat means nothing the one flag
  does not, so it cannot be recorded faithfully — and collapsing it would make
  the file quietly disagree with the document. Failing routes the fix through
  an input patch, where it is declared and reviewed.
- A clause's explanatory prose is not captured. `EnumValue.description` is a
  one-line gloss, and a 3GPP clause does not contain one — it contains
  paragraphs, with lead-ins ("This value is used:"), nested bullet lists,
  `NOTE:`s, and caveats about the AVP rather than about any one value. Any rule
  for flattening that onto a `;` comment picks an arbitrary subset. The rule
  that used to be here took paragraphs styled `B1` or `B2`, which in 29.272
  §7.3.24 kept two bullets and dropped the sentence introducing them, and in
  29.229 §6.3.15 kept "The request is generated in the following cases:" and
  dropped the cases. `; Section:` is the pointer; a reader who wants the prose
  reads it in the specification, undamaged. The field stays in the format for
  hand-written files, where a human can write an actual one-line gloss.
- Enum values are classified by content, not by paragraph
  style: the usual convention is value=`B1`/description=`B2`, but human-written
  specs invert it.
- A table caption's *label* is matched as a general dotted token rather than as
  a numbering scheme. 3GPP has no single one: `Table 7.3.1/1` in 29.229 and
  29.272, `Table 6.3.1-1` in 29.172, 29.283, 29.388 and 29.389, `Table B.1.1`
  in annexes, and clause components carrying a letter in either case (`9A.2.1`,
  `2a.1.1.1`). Across the Rel-18 corpus a pattern written for the slash form
  alone misses 208 of 500 captions. The label reaches `; Table:` and nothing
  parses it further, so recognising *that* a paragraph is a caption is the
  whole job — and getting it wrong is not cosmetic, because a table whose
  caption went unrecognised is rejected for having none.
- The publisher prefix on a re-used table's origin reference is optional.
  "3GPP TS 29.336" and "IETF RFC 6733" are the convention, but From cells are
  hand-written and 29.344 and 29.388 both spell it `TS 29.272 [10]` — the
  document's own bibliography number, no publisher. The spec number identifies
  the origin; the prefix is decoration.

## Source declarations

Everything declared about reading one source document lives in one TOML file
per specification, named by its reference (`edits/sources/TS29.272.toml`),
holding two kinds of block: input patches and quirks. Both carry the same
contract — a required `reason`, an advisory version range, and must-fire
accounting — because both assert something about the source document that the
next reader has to be able to check, and both rot silently without the
accounting.

### Input patches

Genuine typos in a source document are fixed *before* parsing, by patching the
normalized paragraph, cell and title text — not the raw docx XML, which has
arbitrary run splits and is hopeless as a patch target.

```toml
[[patch]]
find = "M. V"
replace = "M, V"
exact = true               # match the whole text unit, not a substring
count = 1                  # must apply exactly this many times
section = "7.3"            # optional: only inside this section (prefix)
reason = "flags cell typo in table 7.3.1/1"   # required
first_version = "18.6.0"   # oldest version known to need this patch
last_version = "18.6.0"    # newest version known to need this patch
```

`find`, `replace` and `reason` are required, `find` must be non-empty and
`count` positive. An empty `find` is the one declaration that defeats the
accounting below rather than being caught by it: `str.replace` and `str.count`
both work on the gaps between characters, so `find = ""` turns `"abc"` into
`"XaXbXcX"` and still applies exactly as many times as it claimed it would.

A patch that applies more or fewer times than `count` fails the extraction with
a `PatchError` naming the known-needed version range, so patches cannot silently
rot when the source document changes between versions. A patch that stops
matching is a fix dropped from the output, which is too easy to miss in a
stderr warning.

`first_version`/`last_version` are advisory: they describe where the patch is
known to be needed and make the warning message useful. They do **not** gate
application — a patch outside its recorded range still applies, because the
alternative is silently dropping a fix on the next release, which is exactly
the rot the accounting exists to catch.

### Quirks

A quirk enables, by name, an extractor reading that is heuristic enough to
misfire on a document it was not written for, and that therefore stays off
unless the document's declaration names it:

```toml
[[quirk]]
name = "prose-avp-codes"   # must be in the extractor's vocabulary
reason = "the AVP tables print no Code column; each clause prints its code"
```

What earns a behavior a quirk is misfire *risk*, not rarity. The header
spelling maps and the ABNF grammars are also per-document knowledge, but an
unrecognized header fails loudly on its own, so they stay in extractor code;
harvesting facts out of prose would succeed silently on prose it was never
meant to read, so it must be opted into. Each extractor defines its own
vocabulary (`QUIRKS` in `rfc_text.py` and `tgpp_docx.py`); declaring a name
outside it fails at load with the list of what the extractor can be told, so
a typo cannot silently leave a quirk off. A declared quirk that fires zero
times fails the extraction exactly like a rotted patch — a reading the source
stopped needing must be loud.

A quirk deliberately carries no parameters: it is a named boolean with a
reason, and the behavior it names lives in extractor code. TOML that carried
logic would make the extractor an interpreter and the declaration
unreviewable.

The RFC extractor's vocabulary today — see
[the RFC extractor](#the-rfc-plain-text-extractor) for each behavior:
`prose-avp-codes` (RFC 7155), `clause-avp-table` (RFC 4072, RFC 5447),
`radius-attribute-table` (RFC 4590), `type-short-forms` (RFC 6733, 4004,
4005, 4006), `prose-catchall-row` (RFC 5778), `bare-name-continuation`
(RFC 4004) and `ragged-separator` (RFC 8583). The docx extractor's:
`note-defined-in-rfc` (TS 29.229, 29.329), `dotted-flags` (TS 29.061,
29.212) and `clause-parenthetical` (TS 29.061). Deliberately *not* gated,
on the same criterion: the "Y"/"N" Encrypt spellings and TS 29.338's
"Must"/"Must not" M-bit short forms — closed vocabularies whose misreading
is impossible ("Y" cannot be a typo of anything), where `DiamIdent` or a
dotted flags cell plausibly could be.

**Division of labor**, deliberately kept sharp:

| Layer          | Fixes                                                  |
|----------------|--------------------------------------------------------|
| input patches  | typos in the source document that break extraction     |
| quirks         | readings too heuristic to run undeclared               |
| extractor code | exact-match structure that fails loudly on its own     |
| corrections    | data that parses fine but is semantically wrong        |

The correction layer is documented in [corrections](corrections.md).

Structural damage (missing captions, split tables) has no collected case yet;
revisit override-style instructions only if one appears.

A document with two AVP tables or two re-used tables is rejected, naming the
sections involved. No collected spec does this yet, and the shape of a
multi-table policy would depend on the case that forces it — but it must not
pass silently, which is what the old single-accumulator code did.

## Strictness

The extractor is strict. Typo-repair heuristics that used to be built in
(flags-cell `.` separators and lowercase flags, space-for-hyphen name repairs)
now raise `ExtractionError`, and the typos are fixed by input patches instead —
so an unpatched TS 29.272 fails loudly on `malformed flags cell 'M. V'` rather
than quietly guessing. Non-fatal inconsistencies are appended to a `warnings`
list that the CLI prints to stderr — including when a later stage fails, since
a run that aborts on a mismatched PDF is exactly when the source-document
warnings are worth reading.

Everything that can fail an extraction derives from `ExtractionError`
(`extractor/errors.py`), including `PatchError`: a batch over a corpus asks one
question — did this document fail? — and a rotted input patch is the same
answer as a malformed table.

## Collected source-document weirdness

Every case below is handled, in extractor code or by an input patch. Keep this
list as evidence of what real documents do; when a new case gets handling, add a
fixture for it in `tests/conftest.py` too.

- heading/rule name mismatches (29.329 §6.1.8 "Push-Notifications-Answer");
- rule names with spaces for hyphens (29.272 §7.3.196 "Monitoring Event
  Report") — input-patched;
- an AVP reference dropping one letter (`Old-Rference-Number` in 29.337
  §6.2.3, while §6.2.4 and table 6.3.1/2 spell
  `Old-Reference-Number`) — input-patched;
- AVP-table name cells line-wrapped losing a hyphen (29.272 "MME-Location
  Information") — input-patched;
- flags cells "M. V" and lowercase "v" (29.272) — input-patched;
- Diameter headers omitting the application id (29.272 VCSG commands →
  `application_id` is optional in the AST);
- one command section holding two ABNFs for two application ids (29.272
  IDR/DSR/RSR: S6a + S7a);
- empty clause cell (29.272 3GPP2-MEID → `AvpTableRow.section` is optional);
- merged table row duplicating cell text (29.272 Battery-Indicator M-bit);
- re-used-table M-bit overrides shortened from "Must set"/"Must not set" to
  "Must"/"Must not" (29.338);
- enum value/description paragraph styles inverted (29.229 §6.3.34);
- "x.y.z Name" headings without the " AVP" suffix (29.272);
- an AVP name containing the underscore RFC 6733's `name-fmt` excludes
  (`GBA_U-Awareness-Indicator`, used consistently throughout 29.109), which
  the source-fidelity AST and `.dad` grammar preserve;
- enumerated AVPs in a specification with no grouped-AVP header from which to
  read their implicit vendor-id (29.109); the extractor uses 3GPP's publisher
  vendor space, 10415, rather than emitting them as IETF AVPs;
- `<AVP header: 632, 10415>` comma separator (29.229);
- bold applied to bracket runs but not to the AVP name (only name runs are
  trusted for the `; bold` marker);
- Value Type cells naming a type that does not exist: "Enumerate" (29.272
  clause 7.3.83, Alert-Reason), "Enumarated" (29.212), "OctedString" (29.109)
  and "OctetSstring" (29.128) — input-patched. All four were invisible until
  `AvpTableRow.data_type` became a closed set, and three of them turned up in
  the first corpus-wide run after it;
- flags cells naming the RFC 3588 `P` bit (29.061, 29.212, 29.214, 29.273).
  RFC 6733 deprecated it; the specifications kept printing it, so `AvpFlag`
  carries it;
- Encrypt cells spelled "Y"/"N" rather than "Yes"/"No" (29.061, 29.212,
  29.214). A document convention, so it is normalized here rather than
  input-patched several hundred times;
- more than one AVP/re-used-table pair per document: 29.336 prints S6m/S6n
  and S6t definition sets, 29.338 S6c and S6d, one AVP table and one re-used
  table each, in document order. `_resolve` pairs them by that order and
  rejects counts that cannot pair; enumerated codes resolve across all AVP
  tables, with an error if two tables give one name different codes;
- a re-used table's From cell citing a clause of the *same* document
  ("6.4.2" in 29.336's S6t table, whose AVPs the S6m set defines) — the
  origin becomes the document's own reference, which the cross-file rules
  treat like any other;
- a table whose every row merges each visible column across two grid columns
  (29.336 table 8.4.1-2: 8 grid cells, 4 physical, in all 45 rows).
  `_sections` collapses a table-wide *uniform* merge pattern to its physical
  columns; mixed patterns — full-width NOTE rows, spanning headers — keep
  their grid positions, which the positional column mapping relies on;
- a placeholder instead of a code in an AVP-header line (29.336 §8.4.85
  prints `<AVP header: xxxx 10415>`; table 8.4.1-1 gives Include-Identifiers
  the code 3189) — input-patched;
- one clause misprinting both the name and the code of its AVP-header line
  (29.338 §6.3.3.13 writes `SMS-MI-Correlation-ID`/3308 — SM-RP-MTI's code —
  for `SMSMI-Correlation-ID`/3324) — two corrections on one node;
- the cover title printed as a plain paragraph rather than in the cover-page
  table (29.061, 29.212, 29.213, 29.214) — `_spec_and_version` reads both;
- flags cells separated by periods with no space, "M.V" (29.061 eleven times,
  29.212 seven) — a separator convention, but a per-document one, so reading
  it is the declared `dotted-flags` quirk rather than a global rewrite;
- clause cells annotated "16.4.7 (see Note)" in both casings (29.061, 37
  times) — a clause number has no syntax for parentheses, so the tail is
  almost certainly prose, but dropping text is the declared
  `clause-parenthetical` quirk, not an assumption;
- parenthesized note references on name cells, "(NOTE 3)"/"(Note 2)", and two
  stacked on one cell (29.212, 29.214) — stripped whole, or the remainder
  would be the non-name "3GPP-RAT-Type ()";
- annex clause numbers leading with the annex letter ("E.6.3.6", 29.212) —
  the section-number lexicon admits them, and they sort after every numbered
  clause;
- a re-used table with a fourth, label-less column of empty cells (29.212) —
  dropped with a warning like an unmodelled column;
- table name cells line-wrapped with a space after a hyphen, four in 29.212
  alone — input-patched;
- headings that hyphenate the " AVP" suffix onto the name
  ("Service-Info-Status-AVP", 29.214 twice) — input-patched, because a
  blanket strip would eat genuine names like RFC 6733's `Failed-AVP`;
- "Void" printed as the label of two enumerated values (29.214's
  Specific-Action, values 0 and 5) — deleted by corrections; `enum_value`
  grew a `value` discriminator so each deletion can name its target;
- origins outside the TS/RFC lexicon: ETSI documents spelled "3GPP TS 283
  034" and "3GPP TS 183.017" (three-digit series, either separator) and
  3GPP2's "X.S0057", which keeps its publisher's numbering in `SpecRef`;
- one AVP printed with two different bodies in one document (29.336 defines
  `User-Identifier` in §6.4.2 and prints an S6t-specific variant in §8.4.36
  at the same code, swapping LMSI for Type-Of-External-Identifier). The
  §8.4.36 copy is deleted by a correction: the clause's own prose says the
  AVP "is defined in clause 6.4.2", and the S6t re-used table's row points
  at that clause.

## Columns the format does not model

Both table kinds are read by matching the label row, not by counting positions,
and a label with no modelled counterpart is **dropped**. Rows are still read
positionally against the source table, so dropping a column in the middle does
not disturb the ones after it.

What gets dropped, in every table examined, is prose: a column headed
"Comments" (13 specifications), "Description" (29.061, 29.212) or "Comment"
(29.172), holding anything from "See clause 7.3.36" to a whole paragraph — 209
non-empty cells in the corpus, averaging 96 characters and reaching 1657.
Carrying them was tried and removed: `.dad` records definitions, not narrative,
and `; Section:` already points at the clause that holds the prose undamaged.

Those three labels are dropped silently. **Anything else unmodelled produces a
warning**, because a column with machine-readable values is a reason to model
it — to give it a name, a cell grammar and a place in `; Columns:` — rather
than to carry it anonymously or lose it. The standing candidates, if the work
ever calls for them:

- 29.212 table 5.3.0.1, "Acc. Type" — access network type: `All`, `3GPP-EPS`,
  `3GPP-GPRS`, `Non-3GPP-EPS`, `3GPP2`, `FBA`, freely combined;
- 29.212 table 5.3.0.1, "Applicability" — two things in one cell: a functional
  domain (`CC` charging control, `PC` policy control, `Both`, `ADC`) followed
  by zero or more supported-feature names, as in `Both Rel8`;
- 29.214 table 5.3.0.1, "Applicability" — supported-feature names only, no
  domain tag, empty for 31 of its rows;
- 29.061 table 9a, "Applicable Reference Points" — `Gi, Sgi`, `Sgi`, `Gi`;
- 29.172's re-used table — "AVP Code" and "Value Type", which the AVP-table
  side already models.

Note that the two columns both labelled "Applicability" do not carry the same
thing, and "Acc. Type" and "Applicable Reference Points" are both "where does
this apply" on different axes. Three axes under four labels: modelling them
means deciding what they actually mean, which is why none of it was invented
while merely carrying the text.

## Column labels

The same column is spelled differently across specifications, and the
differences are typographic rather than semantic: "Clause defined" and "Section
defined", "May Encr." and "May Encrypt", "Clause  defined" with a double space.
`_AVP_TABLE_COLUMNS` and `_REUSED_TABLE_COLUMNS` map the spellings onto one
column each. A label may also carry a note reference ("Value Type (NOTE 2)",
"Applicability (notes 3, 9)"), which is stripped — it points at prose the
format does not carry.

Column *order* has been identical in all 20 AVP tables examined: Attribute
Name, AVP Code, Clause/Section defined, Value Type, Must, May, Should not, Must
not, then any extras. The column *set* has not:

- **29.273** (examined, not yet committed) has 8 — no "May Encr." column
  at all;
- **29.061** and **29.214** have 10, **29.212** has 11;
- re-used tables in **29.128**, **29.173** and **29.336** have no M-bit column,
  so the dispatch keys on "Reference" rather than on "M-bit";
- and RFC 6733 §4.5, read by [the RFC extractor](#the-rfc-plain-text-extractor),
  has neither MAY nor SHOULD NOT nor an encrypt column.

## The RFC plain-text extractor

`src/seanchai/extractor/rfc_text.py` is the second input path into the same
format: the Attribute Name / AVP Code / Section Defined / Data Type (or Value
Type) columns in RFC AVP tables map onto `AvpTableRow` as it stands.
`seanchai extract-rfc rfc6733.txt` drives it; the downloader already fetches
the catalog's RFCs as `specifications/rfc/*.txt`. The same source-declaration
layer applies (`edits/sources/RFC6733.toml`): input patches per content line
after page furniture is stripped, and quirks for the prose readings below.

What is different is the carrier, and everything this extractor knows is about
that:

- **Page furniture.** Footer lines ending `[Page N]`, a form feed, then a
  running header. The running header is recognised as the first non-blank line
  after a page break — not by its text, so a content line starting "RFC" is
  never eaten. `; Page:` numbers are the RFC's own printed pages (the text is
  the RFC's sole rendering, so there is no PDF step), and point at where the
  *section* starts, same convention as the docx extractor.
- **Wrapped rows.** A long name wraps across physical lines
  (`Acct-` / `Interim-Interval`, concatenated back without a joiner), and once
  the wrap goes the other way: `Inband-Security` / `-Id  299 6.10 Unsigned32`
  puts the *data* cells on the continuation line and the flag cells on the
  first. A physical line starting a new logical row is the one whose name
  fragment sits at the Attribute Name column; anything deeper continues the
  row above, and every cell must arrive on exactly one of a row's lines.
  RFC 4004 prints a handful of continuation fragments *outside* the table
  box, without their otherwise-empty flag cells — accepting loose text into
  a name is the `bare-name-continuation` quirk. RFC 5778 closes its
  application table with a "Rest of the AVPs" prose catch-all spanning three
  physical rows; dropping table lines on a text match is the
  `prose-catchall-row` quirk.
- **More than one table.** Older application RFCs split their AVPs into
  several category tables. A repeated header after a page break continues the
  current table; a header after table-closing prose starts another one.
- **Border styles.** RFC 6733 boxes only the flag columns; RFCs 7683, 7944 and
  the 8581–8583 family box the complete table. The latter adds a structural
  leading border to every row and uses `+` at column intersections. Both
  normalize into the same fixed-width row reader. A stray space in RFC 8583's
  closing rule is still unambiguously box drawing — a field holding nothing
  but dashes and whitespace — but only that document is known to print it,
  so accepting it is the `ragged-separator` quirk.
- **Header labels are matched as whole spellings, not tokenized.** The label
  rows print `Code Defined` (two columns) and `Attribute Name` (one label)
  with the same single space, so only vocabulary tells them apart —
  `_LEFT_HEADERS` maps each collected header spelling onto its columns, the
  same collected-cases discipline as the docx column maps. The vertically
  stacked flag labels (`MUST` over `NOT`) are unambiguous and read
  generically, including the later RFCs' lowercase `AVP flag` caption. An
  unrecognised header fails loudly and earns its own entry; RFC 4006/8506 and
  RFC 7155 already print different spellings, so extending the table is the
  expected cost of each new RFC.
- **Declared short forms.** §4.5 says "the short form DiamIdent is used to
  represent DiameterIdentity", and then also writes DiamURI. RFCs 4004,
  4005 and 4006 likewise print `IPFiltrRule`/`IPFltrRule` and `QoSFltrRule`.
  The vocabulary lives in extractor code; *accepting* it is per-document,
  behind the `type-short-forms` quirk, so a new document's typo cannot ride
  in on another document's declared convention.
- **Tables without flag columns, and clauses without tables.** RFC 5777's
  IANA allocation table carries Name, Code, Section, and Data Type and maps
  directly onto those four columns. RFCs 4072 and 5447 publish the same facts
  only in regular per-AVP definition sentences, so those clauses form the
  document's AVP index — the `clause-avp-table` quirk, declared per document
  because deciding which sentences are definitions is exactly the judgement
  a prose reading can get wrong. RFC 4590's Diameter-compatible RADIUS
  attributes contribute Name, Code, and Section (`radius-attribute-table`);
  no Diameter data type is fabricated.
- **Tables without a Code column.** RFC 7155 inherits its AVP codes from
  RADIUS attribute numbers, so its per-category tables print only Name,
  Section and flag rules; each code and type appears once, in the defining
  sentence of the clause the row's Section cell points at ("The NAS-Port AVP
  (AVP Code 5) is of type Unsigned32"). The `prose-avp-codes` quirk follows
  that citation and completes the rows, extending `; Columns:` with Code and
  Type — the file's own statement that those cells were read from the
  clauses rather than from the printed table. Three defining sentences cite
  the RADIUS origin between the identity and the type ("(AVP Code 8)
  [RFC2865] is of type"); a citation there marks heritage, not an import,
  unlike one inside the parentheses. A row with no matching sentence keeps
  its `None` and warns; a sentence matching no row warns; the two
  Accounting-*-Packets clauses that drop the word "AVP" from their own
  sentences are input-patched.
- **Stated facts.** Every AVP an RFC defines is in the IETF vendor space, so
  `; Vendor-ID: 0`; and an RFC number names one immutable document, so the
  file carries no `; Version:` line and its table — introduced by prose, with
  no "Table N" caption — no `; Table:` either. Both directives became optional
  for exactly this.

Beyond the table, the extractor reads the same definitions the docx one does,
from their prose-embedded RFC forms. The committed RFC corpus currently covers
4004, 4005, 4006, 4072, 4590, 5447, 5777, 5778, 6733, 7155, 7683, 7944,
8506, 8581, 8582 and 8583.

- **Definitions anchor on section titles.** A section titled with a bare name
  (`Capabilities-Exchange-Request`) or `Name AVP` (`Proxy-Info AVP`) is a
  definition candidate; a prose title is not. That distinction is what keeps
  the CCF grammar's own illustrations out of the output — `Example-Request`,
  `Example-AVP` and `<answer-message>` all sit under prose titles ("Command
  Code Format Specification", "Grouped AVP Values", "Error Bit").
- **Commands.** `<CER> ::= < Diameter Header: 257, REQ >` under a
  name-titled section becomes a `Message` — the heading carries the long
  name and the rule the abbreviation, the reverse of a 3GPP heading, which
  prints both. Older RFC headings such as `AA-Request (AAR) Command` carry
  both directly; later application RFCs put `(DER)` or `(MIR)` in the prose.
  RFC 6733's base commands print no application id, and the
  file records that as its absence rather than fabricating the base
  protocol's 0. Blank lines inside a body are page-break residue and are
  skipped; the first non-blank non-rule line closes it.
- **Grouped AVPs.** `Proxy-Info ::= < AVP Header: 284 >` plus body; the rule
  name is angle-bracketed in some clauses (`<Failed-AVP> ::=`) and bare in
  others, and `1* {AVP}` prints without inner spaces. A body an RFC prints
  for another document's AVP is kept, the docx extractor's deliberate call:
  RFC 8581 and 8582 both reprint RFC 7683's `OC-OLR` with their own member
  added, and cross-file divergence is the linter's to report
  (`reused-body-differs`).
- **Enumerated AVPs.** A value list under a name-titled section becomes an
  `EnumeratedAvp` when the local AVP table types that name as Enumerated;
  the code comes from the table, as in the docx extractor. Both printed
  layouts are read — the value alone on its line with the description
  indented below (RFC 6733), and the description starting on the value's own
  line and wrapping (RFC 7944, 8583, with 8581's trailing-colon variant).
  Older RFCs' `2 HMAC-SHA-1` and `0 | IN - ...` forms are also read.
  Value names are all-caps in every collected RFC, and requiring that is
  what keeps prose lines out. Descriptions are dropped for the same reason
  as the docx extractor's: they are wrapped prose, not a one-line gloss.
- **What the warnings say, and why each is right.** A value list under a
  `Name AVP`-titled section whose name the local table does not type as
  Enumerated is dropped with a warning: RFC 8581 §7.2.1 adds `PEER_REPORT 2`
  to 7683's `OC-Report-Type`, and `.dad` has no way to extend another
  document's enum. RFC 6733 itself earns three: `Termination-Cause` is
  Enumerated with no local values (they moved to the IANA registry), and
  `Inband-Security-Id` and `Session-Binding` print value-shaped lists for
  AVPs the table types Unsigned32 (the latter a bit mask). All three record
  what the document actually does.

Commands and grouped bodies wait no longer; what still does is anything a
consumer has not asked for — RFC 6733's `<answer-message>` template, and enum
extensions to another document's AVP, which need format design, not
extraction.

## Gotchas

- **The docx and the PDF must be the same specification and version** (29.329
  i10 ↔ TS 29.329 V18.1.0). `attach_pages` reads the PDF's own cover title and
  refuses a mismatch, so this is now an error rather than silently wrong page
  numbers — which matters because the downloader falls back to an earlier ETSI
  rendering when the exact version isn't published yet. It also warns when the
  bookmark outline covers only some sections, and errors when it covers none.
- ETSI PDF filename and URL derivation belongs to the downloader — see
  [downloader.md](downloader.md); don't hand-build those URLs.
- 29.328 holds the Sh *messages* while 29.329 holds the AVPs, so "no AVP
  table found" is correct today; modelling the message-only document shape
  is roadmap work.
- Only 29.329 has a hand-verified reference `.dad`; the Wireshark
  cross-check ([oracle.md](oracle.md)) is what checks the rest at scale.
