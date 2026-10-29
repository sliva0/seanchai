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
- **Q. Record application ids the command headers omit.** RFC 6733, 4005
  and 4006, TS 29.212, 29.214, 32.299 and others print bare `272, REQ, PXY`
  headers and state the id in prose (or leave it to the base application),
  so the python-diameter generator writes `APPLICATION_ID = None` for 27
  modules ([list](../integrations/python_diameter/README.md#what-the-documents-leave-to-the-reader)).
  Needs a format construct naming the id per interface clause, cited like
  any other statement; a header correction would claim the header says it.

## Linter and corpus

- **R. Read the value lists the enumerated reading misses.** Seventeen
  clauses print values the extractor drops, warning "lists no values": TS
  29.109's six (`NO (0) The sending node ...`, `YES(1)`, `- (0) Private user
  identity.`), 29.214's `Media-Type` and `Service-Info-Status` (a leading
  dash, a label in words), 29.229's `Priviledged-Sender-Indication` (two
  values on one line, 6.3.58), 29.272's `Error-Diagnostic` and
  `SIPTO-Permission` (a leading dash, a space inside the name) and 29.338's
  six (a leading dash, a trailing comma). Each shape needs a reading or a
  patch.

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
