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
  - what the retired documents re-use from releases the corpus does not
    hold, again under every `undefined=`: TS 29.210 V6.7.0's five
    `3GPP-*` AVPs from Release 6's TS 29.061 and `Charging-Information`
    from Release 6's TS 29.229, and TS 29.234 V11.2.0's fourteen from
    Release 11's TS 29.229 (`SIP-Auth-Data-Item` among them, its body
    printed but no flag rule);
  - the nine names `Undefined AVP` blocks declare: RFC 4004's three SPI
    members, TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS
    29.154's `External-Group-Identifier`, TS 32.299's
    `Submission-Timestamp` and `Network-Element`, TS 29.234's
    `Error-Cause` ([consumers.md](consumers.md#undefined-names)). They stop
    being holes only for a consumer that passes `DROP`, `PLACEHOLDER` or a
    `SUPPLY` covering them; under the default they still refuse, and they
    leave the corpus only when their documents define them. Strict by
    default therefore needs all of: the two types, those releases' copies
    or evidence for a stand-in, and either upstream definitions for the
    nine or a different default policy, which would drop or untype nine
    members, four of them required, for every consumer that did not ask.
