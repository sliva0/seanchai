# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Sources

- **K. Value ranges the format cannot hold.** SM-Service-Type's "100 ..
  199 Vendor specific SM services", and oneM2M TS-0004's Protocol-Type
  "100 .. 199 Operator and vendor specific protocol types", allocate a
  range of enumerated values, which the format has no line for.

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True`. What stands in the way, by cause (the pinned
  `_STANDING_HOLES` in `tests/test_model.py`):
  - types no source states: RFC 4590 is a RADIUS document; TS 29.061's
    `3GPP-Session-Stop-Indicator` row prints only a code, flag cells
    included;
  - names no corpus document defines: RFC 4004's three SPI members, TS
    29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
    `External-Group-Identifier`, TS 32.299's `Submission-Timestamp` and
    `Network-Element`;
  - a name undefined in the citing document, which another corpus document
    defines under the same name without being cited: TS 32.299's
    `TCP-Source-Port` (TS 29.212; table 7.2.0.1 refers to [215] for
    `UDP-Source-Port` only);
  - what oneM2M TS-0004's `Service-Information` reaches in TS 32.299
    V11.20.0, the version its reference [31] names: forty-one members
    re-used from Release 11's TS 29.061, 29.173, 29.212, 29.214, 29.229,
    29.272, 29.273 and 29.329, whose non-specific references mean Release
    11's last versions, which the corpus would have to pin, extract and
    correct as it does TS 32.299's, and three OMA-DDS-Charging_Data rows
    the Release 11 copy has no supply for.
