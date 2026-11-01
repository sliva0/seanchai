# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True` with the default `undefined=HOLE`. What stands
  in the way, by cause (the pinned `_STANDING_HOLES` in
  `tests/test_model.py`):
  - a type no source states: TS 29.061's `3GPP-Session-Stop-Indicator`
    row prints only a code, flag cells included, in Release 11 as in
    Release 18 (oneM2M TS-0004 reaches it through TS 32.299 V11.20.0), and
    TS 29.234's `Charging-Characteristics` is typed "Integer", no Diameter
    type, by table 10.1.1 and clause 10.1.27 alike. No policy answers for
    either, so they refuse a strict build under every `undefined=`;
  - two rows TS 29.061 V6.15.0 states only a code for, again under every
    `undefined=`: `3GPP-GPRS-Negotiated-QoS-Profile` and `3GPP-SGSN-MCC-MNC`,
    which TS 29.210 V6.7.0 re-uses and clause 16.4.7 numbers as RADIUS
    sub-attributes;
  - the nine names `Undefined AVP` blocks declare: RFC 4004's three SPI
    members, TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS
    29.154's `External-Group-Identifier`, TS 32.299's
    `Submission-Timestamp` and `Network-Element`, TS 29.234's
    `Error-Cause` ([consumers.md](consumers.md#undefined-names)). They stop
    being holes only for a consumer that passes `DROP`, `PLACEHOLDER` or a
    `SUPPLY` covering them; under the default they still refuse, and they
    leave the corpus only when their documents define them. Strict by
    default therefore needs all of: those four types, and either upstream definitions for the
    nine or a different default policy, which would drop or untype nine
    members, four of them required, for every consumer that did not ask.
