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

- **S. Read the RFC value lists left unread.** RFC 4005's informational
  lists label values in words after the number (`2   ISDN Sync`, 65 lines
  over nine clauses, some wrapping) and only one-word labels are read; one
  label, Tunnel-Medium-Type's `802 (includes … "canonical format")`, holds
  a double quote no value name can. RFC 4005's `Termination-Cause` values
  are a RADIUS-to-Diameter mapping table (§9.3.5) and RFC 5778's
  `MIP6-Auth-Mode` value is numbered only in its IANA section (§9.5); both
  still warn "no value list found".

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
