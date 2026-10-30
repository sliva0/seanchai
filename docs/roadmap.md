# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Format

- **D. Model the machine-readable source columns when a consumer asks.**
  29.212's and 29.215's "Acc. Type" and "Applicability", 29.214's and
  29.468's "Applicability" (29.215 and 29.468 in their re-used tables too),
  29.061's "Applicable Reference Points", 29.172's re-used-table Code/Type,
  32.299's per-command "Used in" marks (ACR, ACA, CCR, CCA).
  Three axes under four labels; modelling means deciding what each means.
  The extractor warns about them today, which is the right amount of
  machinery until then.

## Linter and corpus

- **S. Read where the RFCs' value-less enumerated clauses point.** The RFC
  extractor warns "no value list found" for 27 AVPs (RFC 4005, 5777, 5778,
  6733, 7155). The clauses checked print no list: most cite a registry (RFC
  6733's `Termination-Cause` "can be found in the IANA registry", RFC 5777's
  seven "managed by IANA under the ... registry", RFC 4005's and 7155's
  `[RADIUSAttrVals]`), RFC 5778's `MIP-Algorithm-Type` borrows RFC 4004's,
  and its `MIP6-Auth-Mode` names its one value in prose and numbers it only
  in the IANA section. The first two shapes are what `; Values:` holds for
  the docx extractor.

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

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True`; the pinned list in `tests/test_model.py` is
  what stands in the way.
