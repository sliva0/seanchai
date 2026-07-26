# Roadmap

Open work, roughly in the order it delivers value. What already exists is in
the README's status section; completed review rounds are recorded in
[history/](history/) and are not outstanding work.

When you learn something non-obvious while working — a source-document quirk, a
workflow gotcha, a convention that isn't visible in the code — write it down in
the document it belongs to ([extractor.md](extractor.md),
[workflow.md](workflow.md), [dad-format.md](dad-format.md),
[downloader.md](downloader.md)). Cheap to write now, expensive to rediscover
later.

Before adding items here, read the conventions in
[development.md](development.md#working-on-these-documents) — several
tempting additions are settled decisions, not gaps.

## Format

- **Write a formal grammar document.** The parser source is currently the
  specification. [dad-format.md](dad-format.md) records the design intent; the
  grammar itself is still missing, and it is the main blocker for a second
  implementation or an automated reviewer.
- **Restrict `AvpTableRow.data_type`** to the closed set of Diameter
  base/derived types (see `TODO(format)` in `ast.py`).

## Linter

A linter over a parsed `.dad` file. This is what makes an extracted corpus
trustworthy, and phase one should land before extracting more specs —
otherwise every new spec multiplies unverified data.

### Phase one: single-file structural rules

- no duplicate definitions, no duplicate enum values;
- no duplicate `(vendor-id, code)` identity, which is not the same rule as no
  duplicate names. TS 29.272's `Area-Scope` was the case: clause 7.3.138
  printed `Job-Type`'s code, giving two differently-named AVPs the same
  identity while every name in the file stayed unique. It is corrected now, but
  only because a reviewer read the file;
- no AVP both defined locally and listed as re-used. TS 29.272 does this nine
  times, re-printing another spec's grouped AVP in full while listing it as
  re-used. The extractor deliberately keeps both — see [what the extractor does
  not decide](extractor.md#what-the-extractor-does-not-decide) — so this rule
  is what turns those nine into a report instead of a surprise;
- AVP-table rows agree with the corresponding grouped/enumerated definition on
  code and type.

Everything above is decided inside one file, and every rule already has a real
case in the committed corpus. That is the point: these are not hypothetical
invariants, they are the inconsistencies three specifications actually contain.

Two things the linter will need that the current design leaves open. Some
findings are the source document's fault and will never be fixed upstream, so a
report that cannot be acknowledged becomes noise everyone learns to ignore —
there should be a way to record "known, explained, not a regression", and it
should look like the `reason` a patch or correction carries. And a linter that
loads several files needs the version question from phase two answered anyway.

### Phase two: reference resolution

"Every AVP referenced in a message or grouped body resolves to a local
definition, an AVP-table row, or a re-used entry" cannot be enforced as
written. Each committed file references 14–17 AVPs that appear in no table —
hundreds of occurrences — and almost all of them are RFC 6733's: `Session-Id`,
`Origin-Host`, `Proxy-Info`, the trailing `* [ AVP ]`. No 3GPP spec
re-declares them, because every Diameter application is assumed to have them.

So this rule needs a base-protocol import rule first — either an implicit
RFC 6733 dependency or an explicit dependency/import directive in the format.
The RFC extractor under [More sources](#more-sources) is what makes either one
checkable, since neither means anything until a base `.dad` exists.

Once the base AVPs are subtracted, the residue is small and interesting: two
references in TS 29.272 (`Additional-Context-Identifier` in clause 7.3.35 and
`Re-synchronization-Info` in clause 7.3.11) and none in 29.229 or 29.329.
Neither is a base AVP and neither appears in 29.272's own AVP table or re-used
table, so the document really does reference AVPs it never introduces. Adding
them is a *row*, which the correction layer cannot express — it replaces
fields, it does not insert nodes — so this is also the case that decides
whether corrections need an insert operation.

Resolving a re-used AVP to its `(vendor-id, code)` also means reading the
origin spec's `.dad`, so the linter must load several files at once — and that
needs an answer to a question the format currently ducks: `ReusedAvpRow.origin`
names a specification but not a version. Decide how a run picks which version
of an origin spec to resolve against before writing the cross-file rules;
"whatever happens to be on disk" is not a decision.

## Validation against an independent oracle

Cross-check extracted codes, vendor-ids and types against Wireshark's Diameter
`dictionary.xml`. Only 29.329 is hand-verified today; this is what would let the
other extracted specs be trusted at scale. Optionally borrow Wireshark's
disambiguated names for AVPs whose names clash across specs.

## More sources

- Run the extractor over the remaining 3GPP Diameter specs. Expect new document
  quirks; keep the acceptance loop from [workflow.md](workflow.md). 29.230's
  registry tables need their own path — they lack the "AVP Flag rules" header
  that the current table dispatch keys on.
- Add an RFC (plain-text) extractor for the base protocol and IETF
  applications. RFC AVP tables (RFC 6733 §4.5) will need plain-AVP rows like
  the 3GPP ones.
- Downloader changes for archive fetching and link derivation — see
  [downloader.md](downloader.md).

## Downstream consumers

Validators for existing hand-written dictionaries first; generators for
implementations' native dictionary formats after.

## Smaller items

- A version type shared by input patches and corrections, so a recorded range
  can be compared against the parsed version and *warn* when it no longer
  covers it. Both layers currently record ranges without comparing them, and
  both must keep applying regardless — the range explains, it never gates.
- A CLI flag that auto-expands an input patch's `first_version`/`last_version`
  range when a newer or older version is parsed and the patch still applied
  cleanly. Needs comment-preserving TOML rewriting (e.g. tomlkit), and the
  shared version type above.
- Fix the `atomic_download` corrupt-cache wart described in
  [downloader.md](downloader.md).
- Stage a whole corpus version before publishing it. `replace_extracted` now
  rolls back a failed directory swap, and a failed run no longer leaves a stale
  `manifest.json` behind, so no single artifact is corrupted — but a run that
  fails halfway still leaves a corpus where some specs are the new version and
  some are the old one. Only staging the whole thing fixes that.
