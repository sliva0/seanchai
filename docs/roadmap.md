# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Sources

- **K. Catalog gaps and format limits from the legacy documents.** The
  AVPs the corpus only re-uses from documents outside 3GPP and IETF stay
  holes: a re-used row's identity, vendor included, is its origin's, so a
  type supplied into the citing file has nowhere to go, and the origin
  would have to be a hand-written `.dad` file. ETSI ES 283 034 V2.2.0 (cited
  as "ETSI TS 283 034"), ETSI TS 183 017 V3.2.1 and oneM2M TS-0004 are
  readable; 3GPP2 X.S0057 could not be fetched. SM-Service-Type's "100 .. 199
  Vendor specific SM services" allocates a range the format cannot hold.
  TS 32.299 cites `VAS-Id` and `VASP-Id` from TS 29.140, which ends at
  Release 7 (V7.0.0): the downloader fetches one release and
  `Corpus.resolve` never crosses a major version, so the origin stays
  unresolved until the corpus holds more than one release *and* a
  resolution policy says when a Release 7 document may serve a Release 18
  citation.

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True`. What stands in the way, by cause (the pinned
  `_STANDING_HOLES` in `tests/test_model.py`):
  - types no source states: RFC 4590 is a RADIUS document; TS 29.061's
    `3GPP-Session-Stop-Indicator` row prints only a code, flag cells
    included; TS 32.299's `VAS-Id`/`VASP-Id` are item K;
  - names no corpus document defines: RFC 4004's three SPI members, TS
    29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
    `External-Group-Identifier`, TS 32.299's `Submission-Timestamp` and
    `Network-Element`;
  - a name undefined in the citing document, which another corpus document
    defines under the same name without being cited: TS 32.299's
    `TCP-Source-Port` (TS 29.212; table 7.2.0.1 refers to [215] for
    `UDP-Source-Port` only);
  - definitions the format cannot hold: TS 29.229's `Line-Identifier`
    (ETSI vendor 13019 in a clause, no row can state it);
  - re-used origins outside 3GPP and IETF, item K: `ETSI-TS283.034` (TS
    29.212, 29.219, 29.273, 32.299), `ETSI-TS183.017` (TS 29.214),
    `3GPP2-X.S0057` (TS 29.212) and `oneM2M-TS-0004` (TS 32.299's
    `M2M-Information`).
