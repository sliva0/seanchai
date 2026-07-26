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
  defining RFC additionally produce `ReusedAvps` rows.
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
  stays on disk: [input patches](#input-patches) fix honest typos in the source
  text — a flags cell reading `M. V`, a rule name written with spaces — and
  only where the document is typographically wrong, never where it is
  semantically wrong. [Corrections](corrections.md) fix data that extracts and
  parses fine but is wrong, and they apply to a *separate* output file, so the
  committed raw file always still says what the document said.

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

## Input patches

Genuine typos in a source document are fixed *before* parsing, by patching the
normalized paragraph, cell and title text — not the raw docx XML, which has
arbitrary run splits and is hopeless as a patch target.

Patch files are TOML, one per specification, named by its reference
(`patches/TS29.272.toml`):

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

**Division of labor**, deliberately kept sharp:

| Layer          | Fixes                                                  |
|----------------|--------------------------------------------------------|
| input patches  | typos in the source document that break extraction     |
| extractor code | recurring conventions that carry information           |
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
- AVP-table name cells line-wrapped losing a hyphen (29.272 "MME-Location
  Information") — input-patched;
- flags cells "M. V" and lowercase "v" (29.272) — input-patched;
- Diameter headers omitting the application id (29.272 VCSG commands →
  `application_id` is optional in the AST);
- one command section holding two ABNFs for two application ids (29.272
  IDR/DSR/RSR: S6a + S7a);
- empty clause cell (29.272 3GPP2-MEID → `AvpTableRow.section` is optional);
- merged table row duplicating cell text (29.272 Battery-Indicator M-bit);
- enum value/description paragraph styles inverted (29.229 §6.3.34);
- "x.y.z Name" headings without the " AVP" suffix (29.272);
- `<AVP header: 632, 10415>` comma separator (29.229);
- bold applied to bracket runs but not to the AVP name (only name runs are
  trusted for the `; bold` marker);
- Value Type cells naming a type that does not exist: "Enumerate" (29.272
  clause 7.3.83, Alert-Reason) and "Enumarated" (29.212) — input-patched. Both
  were invisible until `AvpTableRow.data_type` became a closed set.

## Per-specification AVP-table columns

The extractor reads an AVP table's columns off its label row rather than
assuming nine positions, because the label row is the only thing that says what
the table actually holds.

Column *order* has been identical in all 20 specifications examined:
Attribute Name, AVP Code, Clause/Section defined, Value Type, Must, May, Should
not, Must not, then any extras. The column *set* has not:

- **29.273** has 8 — no "May Encr." column at all;
- **29.061** and **29.214** have 10 — one extra trailing column;
- **29.212** has 11 — two extra;
- and RFC 6733 §4.5, for the future RFC extractor, has neither MAY nor
  SHOULD NOT nor an encrypt column.

Labels vary typographically without varying in meaning: "Clause defined" and
"Section defined", "May Encr." and "May Encrypt", "Clause  defined" with a
double space. `_AVP_TABLE_COLUMNS` maps the spellings onto one column each. A
label may also carry a note reference ("Value Type (NOTE 2)"), which is
stripped — it points at prose the format does not carry.

The extra columns are kept as free columns under their source labels. They are
*not* canonicalized across specifications, because they do not mean the same
thing:

- 29.061 table 9a, "Applicable Reference Points" — which of this spec's own
  reference points the AVP applies to: "Gi, Sgi", "Sgi", "Gi";
- 29.212 table 5.3.0.1, "Acc. Type" — access network type: "All", "3GPP-EPS",
  "3GPP-GPRS", "Non-3GPP-EPS", "3GPP2", "FBA", freely combined;
- 29.212 table 5.3.0.1, "Applicability" — two things in one cell: a functional
  domain ("CC" charging control, "PC" policy control, "Both", "ADC") followed
  by zero or more supported-feature names, as in "Both Rel8" or "Both
  CondPolicyInfo, CondPolicyInfo-DefaultQoS";
- 29.214 table 5.3.0.1, "Applicability" — supported-feature names only, with no
  domain tag, and empty for 31 of its rows.

Three axes under four labels. The two columns sharing the name "Applicability"
overlap on the supported-feature dimension and differ on the domain tag; "Acc.
Type" and "Applicable Reference Points" are both "where does this apply" but on
different axes. Collapsing them would be inventing a claim no specification
makes, so the extractor records the label and leaves the judgement to a
consumer.

## Gotchas

- **The docx and the PDF must be the same specification and version** (29.329
  i10 ↔ TS 29.329 V18.1.0). `attach_pages` reads the PDF's own cover title and
  refuses a mismatch, so this is now an error rather than silently wrong page
  numbers — which matters because the downloader falls back to an earlier ETSI
  rendering when the exact version isn't published yet. It also warns when the
  bookmark outline covers only some sections, and errors when it covers none.
- ETSI PDF filenames encode versions as two digits per component (18.1.0 →
  `v180100`). `etsi_pdf_url()` in the download script already does this
  correctly; don't hand-build these URLs.
- 29.328 is a stage-2 data spec with no Diameter AVP table at all — "no AVP
  table found" is correct there, not a bug.
- Only 29.329 has a hand-verified reference `.dad`. The 29.229 and 29.272 raw
  outputs round-trip and were spot-checked, but are otherwise unverified; the
  planned Wireshark cross-check is what will make them trustworthy at scale.
