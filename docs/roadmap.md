# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Linter and corpus

- **S. Read the two RFC value lists left unread.** RFC 4005's
  `Termination-Cause` values are a RADIUS-to-Diameter mapping table of
  worded causes (§9.3.5, extending RFC 6733's clause) and RFC 5778's
  `MIP6-Auth-Mode` value is numbered only in its IANA registry (§9.5); both
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
  untyped; table 7.5.1's `[301]`, oneM2M TS-0004, leaves `M2M-Information`
  unresolved the same way), and SM-Service-Type's "100 .. 199 Vendor specific SM services"
  allocates a range. TS 32.299 cites `VAS-Id` and `VASP-Id` from TS
  29.140, which ends at Release 7 (V7.0.0): the downloader fetches one
  release and `Corpus.resolve` never crosses a major version, so the
  origin stays unresolved until the corpus holds more than one release
  *and* a resolution policy says when a Release 7 document may serve a
  Release 18 citation.

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True`. What stands in the way, by cause (the pinned
  `_STANDING_HOLES` in `tests/test_model.py`):
  - flag rules no source states: RFC 4072, 5447, 5777 and 6734 print no
    flag columns and say nothing of the M or V bit in prose (TS 29.272's
    re-print of RFC 5447's `MIP6-Agent-Info` inherits it); RFC 4005's and
    7155's `QoS-Filter-Rule` and TS 29.389's three V2X rows print blank
    cells;
  - types no source states: RFC 4590 is a RADIUS document; TS 29.061's
    `3GPP-Session-Stop-Indicator` row prints only a code; TS 32.299's 13
    OMA rows and `VAS-Id`/`VASP-Id` are item K;
  - names no corpus document defines: RFC 4004's three SPI members, TS
    29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.273's
    `NSWO-Authorization`, TS 29.154's `External-Group-Identifier`, TS
    32.299's `Monitored-HPLMN-Identifier`, `Submission-Timestamp` and
    `Network-Element`;
  - names undefined in the citing document, which another corpus document
    defines under the same name without being cited: TS 32.299's
    `Monitoring-Event-Report` (TS 29.336) and `TCP-Source-Port` (TS 29.212;
    table 7.2.0.1 refers to [215] for `UDP-Source-Port` only);
  - definitions the format cannot hold: TS 29.229's `Line-Identifier`
    (ETSI vendor 13019 in a clause, no row can state it) and TS 32.299's
    `M2M-Information` (cited from oneM2M TS-0004, item K);
  - re-used origins outside the corpus: ETSI TS 283 034 (TS 29.212, 29.219,
    29.273, 32.299), TS 183 017 (TS 29.214) and 3GPP2 X.S0057 (TS 29.212).
