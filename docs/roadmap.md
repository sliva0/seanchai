# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Sources

- **Q. Registry documents the corpus lacks.** TS 29.211 (last V6.4.0), TS
  29.210 (last V6.7.0) and TS 29.234 (last V11.2.0) are retired and would
  be pinned. Nothing resolves into them: only TS 29.230's registry rows
  name them. *Decided:* pin them only if a corpus document comes to
  resolve into one.

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True` with the default `undefined=HOLE`. What stands
  in the way, by cause (the pinned `_STANDING_HOLES` in
  `tests/test_model.py`):
  - a type no source states: TS 29.061's `3GPP-Session-Stop-Indicator`
    row prints only a code, flag cells included, in Release 11 as in
    Release 18 (oneM2M TS-0004 reaches it through TS 32.299 V11.20.0). No
    policy answers for it, so it refuses a strict build under every
    `undefined=`, alone under `DROP` and `PLACEHOLDER`;
  - the eight names `Undefined AVP` blocks declare: RFC 4004's three SPI
    members, TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS
    29.154's `External-Group-Identifier`, TS 32.299's
    `Submission-Timestamp` and `Network-Element`
    ([consumers.md](consumers.md#undefined-names)). They stop being holes
    only for a consumer that passes `DROP`, `PLACEHOLDER` or a `SUPPLY`
    covering them; under the default they still refuse, and they leave the
    corpus only when their documents define them. Strict by default
    therefore needs both of: the TS 29.061 type, and either upstream
    definitions for the eight or a different default policy, which would
    drop or untype eight members, four of them required, for every
    consumer that did not ask.
