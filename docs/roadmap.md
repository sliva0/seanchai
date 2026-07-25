# Roadmap

Open work, roughly in the order it delivers value. What already exists is in
the README's status section; the current code-quality work has its own plan in
[plan-code-quality.md](plan-code-quality.md).

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

## Output corrections

The second half of the two-layer patch design: fixes for data that extracts and
parses fine but is semantically wrong. Designed in
[proposal-corrections.md](proposal-corrections.md), scheduled in
[plan-code-quality.md](plan-code-quality.md). Pairs with the linter below —
corrections are what make a corrected `.dad` pass it.

## Linter

A cross-section linter over a parsed `.dad` file:

- every AVP referenced in a message or grouped body resolves to a local
  definition, an AVP-table row, or a reused-AVPs entry;
- no duplicate definitions, no duplicate enum values;
- AVP-table rows agree with the corresponding grouped/enumerated definition on
  code and type.

This is what makes an extracted corpus trustworthy, and it should land before
extracting more specs — otherwise every new spec multiplies unverified data.

The rules above are single-file, but the interesting one isn't: resolving a
reused AVP to its `(vendor-id, code)` means reading the origin spec's `.dad`,
so the linter needs to load several files at once and needs an answer to a
question the format currently ducks — `ReusedAvpRow.origin` names a
specification but not a version. Decide how a run picks which version of an
origin spec to resolve against before writing the cross-file rules; "whatever
happens to be on disk" is not a decision.

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

- A CLI flag that auto-expands an input patch's `first_version`/`last_version`
  range when a newer or older version is parsed and the patch still applied
  cleanly. Needs comment-preserving TOML rewriting (e.g. tomlkit).
- An optional regression pin of the extractor against the real docx sources,
  skipped unless `output/manual/` is present.
- Fix the `atomic_download` corrupt-cache wart described in
  [downloader.md](downloader.md).
