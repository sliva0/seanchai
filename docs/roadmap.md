# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Format

- **A. `seanchai format`, preserving comments.** There is no way to
  normalise a hand-edited file from the CLI, and the parser discards `;;`
  comments, so normalising would delete every annotation. Proposal: a
  trailing comment belongs to the node on its line, a whole-line comment to
  the node on the next line; the parser returns `(spec, comments)` in the
  `Notes` shape `format_spec` already takes.
- **B. Key formatter notes and correction edits by tree path**, not
  `id(node)`. Works today because the tree outlives every use, but nothing
  enforces it. Same mechanism A wants; do them together.
- **C. `; EXTERNALLY-DEFINED` marker and a `Supply` correction.** For an
  enumerated AVP whose clause says the values live in another document
  (29.272's `Alert-Reason`): the extractor records the fact instead of an
  empty body, and `Supply` fills a whole hand-notated section, marked
  `;; supplied:` on every line, expecting the marker and no values. Waits
  for a consumer that needs those values. TS 32.299 adds two empty ones
  today: Type-Number (clause 7.2.238, values from the OMNA WSP registry) and
  API-Network-Service-Node (7.2.20eA, values from TS 23.682).
- **D. Model the machine-readable source columns when a consumer asks.**
  29.212's and 29.215's "Acc. Type" and "Applicability", 29.214's and
  29.468's "Applicability" (29.215 and 29.468 in their re-used tables too),
  29.061's "Applicable Reference Points", 29.172's re-used-table Code/Type,
  32.299's per-command "Used in" marks (ACR, ACA, CCR, CCA).
  Three axes under four labels; modelling means deciding what each means.
  The extractor warns about them today, which is the right amount of
  machinery until then.

## Linter and corpus

- **G. Stage the Wireshark merge requests** listed in
  [oracle.md](oracle.md#what-still-reports).

## Sources

- **J. TS 29.230 allocation registry.** Its application/command assignments,
  reserved AVP code ranges and multiple cited specifications need registry
  constructs in the format; treating the AVP allocation table as local
  definitions would lose those distinctions. Deferred until the format can
  preserve the registry.
- **K. Catalog gaps and format limits from the legacy documents.** Two
  TS 32.299 statements the format cannot hold yet: `refer [223]` cites
  OMA-DDS-Charging_Data, which a From cell cannot name (13 rows stay
  untyped), and SM-Service-Type's "100 .. 199 Vendor specific SM services"
  allocates a range. TS 32.299 cites `VAS-Id` and `VASP-Id` from TS
  29.140, which ends at Release 7 (V7.0.0): the downloader fetches one
  release and `Corpus.resolve` never crosses a major version, so the
  origin stays unresolved until the corpus holds more than one release
  *and* a resolution policy says when a Release 7 document may serve a
  Release 18 citation.
- **L. Downloader: read the 3GPP archive throughout**, not only for the
  PDF-matched fallback, so every old version stays available for raw-vs-raw
  diffs; derive the ETSI `Link:` URL (needs the edition suffix, probably by
  listing the ETSI deliver directory); and stage a whole corpus version
  before publishing it, since a half-failed run today leaves a mix of old
  and new specs.

## Consumers

- **M. The *generate* direction.** Validation exists; what remains is a
  dictionary in a format the consumer chooses (Python classes, a JSON schema,
  XML). Seanchaí supplies definitions and queries; output syntax is the
  script's business.
- **N. Make the model rigid.** `Avp.code`, data type and flag rules are all
  `| None`, and every `None` is a hole in the corpus, not a fact about
  Diameter. When the upstream gaps (tables without type or flag columns for
  re-used rows, the standing unresolved references) are worked off, make the
  fields required so the model fails to build on an incomplete corpus — with
  whatever escape hatch hand-authored files turn out to need.
- **O. Carry Wireshark's AVP name in the model** alongside the
  specification's, for consumers interoperating with Wireshark-derived
  tooling. Waits for a consumer that maps between the namings; the corpus
  itself always keeps the specification's spelling.
