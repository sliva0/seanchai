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
  builds under `strict=True`. What stands in the way, by cause (the pinned
  `_STANDING_HOLES` in `tests/test_model.py`):
  - a type no source states: TS 29.061's `3GPP-Session-Stop-Indicator`
    row prints only a code, flag cells included, in Release 11 as in
    Release 18 (oneM2M TS-0004 reaches it through TS 32.299 V11.20.0);
  - names no corpus document defines: RFC 4004's three SPI members, TS
    29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
    `External-Group-Identifier`, TS 32.299's `Submission-Timestamp` and
    `Network-Element`. *Decided:* these stay in the corpus as explicit
    broken names; the model must present them as such and offer the
    consumer resolution options (skip, keep as an untyped placeholder,
    accept a supplied definition). Design pending.
