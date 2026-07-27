# The `.dad` corpus

Committed `.dad` files, one directory tree per source family.

```
dad/
  3gpp/
    rel-18/     one directory per 3GPP release
  rfc/          RFCs have no release axis, so they sit flat
```

3GPP files are named as 3GPP names its archives — specification number and
version code, `29272-i60` for TS 29.272 V18.6.0 — because that is what pairs a
file with the document it was extracted from.

Each specification is committed twice, and the pair is the point:

- `29272-i60.dad` — the **corrected** file. This is the one to use. A generator
  or a validator wants the AVP code that is right, not the one the document
  misprinted.
- `29272-i60.raw.dad` — unedited extractor output, saying exactly what the
  document said, mistakes included.

Every line a correction touched carries a `;;` note in the corrected file,
naming the change and the declaration it came from, so a corrected value is
never anonymous:

```dad
;; corrected: code 1623 -> 1624 [edits/corrections/TS29.272.py:31]
; Type: Grouped AVP
; Name: Area-Scope
```

Keeping the raw file costs a second copy and buys three things that are
awkward to get otherwise: a version upgrade can diff raw-vs-raw and see the
*document's* change with the correction layer held still; the corrections can
be re-applied and rot-checked without re-downloading the sources; and the
linter has something to fire on, so "the corrected corpus is clean" stays
distinguishable from "the rules never match anything".

See [workflow.md](../docs/workflow.md).

`examples/` is not part of this corpus. It holds the hand-made reference file
that the format itself is described against.
