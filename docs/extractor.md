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

## Conventions baked into the extractor

- `Page:` is where the *section* starts per the PDF bookmark outline. Table
  sections inherit their parent section's page, which can be one page before
  the table itself.
- AVPs listed in the reused table, or referenced from an AVP-table NOTE, get no
  local definition even when their section reads like one (DRMP is the case
  that forced this: "is of type Enumerated", but the values live in RFC 7944).
- Enumerated AVPs take their code from the AVP table and their vendor-id from
  the spec's grouped-AVP headers, because enumerated sections print neither.
- Enum values and descriptions are classified by content, not by paragraph
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
reason = "flags cell typo in table 7.3.1/1"
first_version = "18.6.0"   # oldest version known to need this patch
last_version = "18.6.0"    # newest version known to need this patch
```

A patch that applies more or fewer times than `count` produces a warning that
includes the known-needed version range, so patches cannot silently rot when
the source document changes between versions. The warning is currently the only
consequence: a patch that was required and did not apply still leaves `extract`
exiting zero. Treat any patch warning as a failed run until that is fixed (see
[plan-code-quality.md](plan-code-quality.md)).

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

The correction layer is [proposed but not implemented](proposal-corrections.md).

Structural damage (missing captions, split tables) has no collected case yet;
revisit override-style instructions only if one appears.

One accumulator limitation to know about: `extract()` keeps a single
`avp_table` and a single reused table, so a spec with two matching tables gets
the last one and the earlier one disappears without a warning. No collected
spec does this yet; the planned `extract()` split is where to fix it.

## Strictness

The extractor is strict. Typo-repair heuristics that used to be built in
(flags-cell `.` separators and lowercase flags, space-for-hyphen name repairs)
now raise `ExtractionError`, and the typos are fixed by input patches instead —
so an unpatched TS 29.272 fails loudly on `malformed flags cell 'M. V'` rather
than quietly guessing. Non-fatal inconsistencies are appended to a `warnings`
list that the CLI prints to stderr.

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
  trusted for the `; bold` marker).

## Gotchas

- **Keep the docx and PDF matched exactly** — same specification *and* same
  version (29.329 i10 ↔ TS 29.329 V18.1.0). `attach_pages` trusts the caller
  and will attach subtly wrong pages without any error if either differs.
  Making it verify both is planned — see
  [plan-code-quality.md](plan-code-quality.md). Note that the downloader will
  fall back to an earlier ETSI version when the exact one isn't published; that
  file is not valid input here.
- ETSI PDF filenames encode versions as two digits per component (18.1.0 →
  `v180100`). `etsi_pdf_url()` in the download script already does this
  correctly; don't hand-build these URLs.
- 29.328 is a stage-2 data spec with no Diameter AVP table at all — "no AVP
  table found" is correct there, not a bug.
- Only 29.329 has a hand-verified reference `.dad`. The 29.229 and 29.272 raw
  outputs round-trip and were spot-checked, but are otherwise unverified; the
  planned Wireshark cross-check is what will make them trustworthy at scale.
