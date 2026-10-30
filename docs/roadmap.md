# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Sources

- **K. Catalog gaps and format limits from the legacy documents.** An
  AVP the corpus only re-uses from a document outside 3GPP and IETF stays
  a hole while that document is absent: a re-used row's identity, vendor
  included, is its origin's, so a type supplied into the citing file has
  nowhere to go. 3GPP2 X.S0057, cited by TS 29.212 for `3GPP2-BSID`,
  could not be fetched. SM-Service-Type's "100 .. 199 Vendor specific SM
  services", and oneM2M TS-0004's Protocol-Type "100 .. 199 Operator and
  vendor specific protocol types", allocate a range the format cannot
  hold.
  TS 32.299 cites `VAS-ID` and `VASP-ID` from TS 29.140, which ends at
  Release 7 (V7.0.0): the downloader fetches one release and
  `Corpus.resolve` never crosses a major version, so the origin stays
  unresolved until the corpus holds more than one release *and* a
  resolution policy says when a Release 7 document may serve a Release 18
  citation. The same holds for the ETSI transcriptions' own citations of
  TS 29.209 (Release 6) and TS 29.214 Release 7, and oneM2M TS-0004's of
  TS 32.299 Release 11, whose policy would also read the release from the
  citing document's references.

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True`. What stands in the way, by cause (the pinned
  `_STANDING_HOLES` in `tests/test_model.py`):
  - types no source states: RFC 4590 is a RADIUS document; TS 29.061's
    `3GPP-Session-Stop-Indicator` row prints only a code, flag cells
    included; TS 32.299's `VAS-ID`/`VASP-ID` are item K, as are the ETSI
    transcriptions' TS 29.209 and TS 29.214 Release 7 imports;
  - names no corpus document defines: RFC 4004's three SPI members, TS
    29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
    `External-Group-Identifier`, TS 32.299's `Submission-Timestamp` and
    `Network-Element`;
  - a name undefined in the citing document, which another corpus document
    defines under the same name without being cited: TS 32.299's
    `TCP-Source-Port` (TS 29.212; table 7.2.0.1 refers to [215] for
    `UDP-Source-Port` only);
  - re-used origins outside 3GPP and IETF, item K: `3GPP2-X.S0057` (TS
    29.212's `3GPP2-BSID`).
