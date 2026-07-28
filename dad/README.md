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
file with the document it was extracted from. RFC files are named as the RFC
Editor names its renderings (`rfc6733`), and carry no version code or
`; Version:` header because an RFC number names one immutable document.

Each specification is committed twice, and the pair is the point:

- `29272-i60.dad` — the **corrected** file. This is the one to use. A generator
  or a validator wants the AVP code that is right, not the one the document
  misprinted.
- `29272-i60.raw.dad` — unedited extractor output, saying exactly what the
  document said, mistakes included.

Every line a correction touched carries a trailing `;;` note in the corrected
file, citing the declaration in `edits/corrections/` it came from, so a
corrected value is never anonymous. What changed and why live at the cited
line — and the old value in the raw file — rather than being repeated in every
note:

```dad
Area-Scope ::= < AVP header: 1624 10415 > ;; corrected: (TS29.272.py:31)
```

A deleted node produces no line to mark, so its note stands alone before the
section that lost it (`;; deleted: (TS29.283.py:7)` in 29.283).

A specification with no corrections yet still gets both files, byte-identical
(`rfc6733`): the pair is the workflow's unit, and the corrected copy is the
one consumers and the corpus loader read either way.

Keeping the raw file costs a second copy and buys three things that are
awkward to get otherwise: a version upgrade can diff raw-vs-raw and see the
*document's* change with the correction layer held still; the corrections can
be re-applied and rot-checked without re-downloading the sources; and the
linter has something to fire on, so "the corrected corpus is clean" stays
distinguishable from "the rules never match anything".

A file without a `; Link:` header has no ETSI PDF of its own version, so it
also carries no `; Page:` directives. TS 29.388 is the case: 3GPP publishes the
docx at V18.1.0 while ETSI's rendering is still V18.0.0, and page numbers taken
from the wrong version point at the wrong pages, which is worse than having
none. The extractor refuses the mismatched pair rather than guessing.

See [workflow.md](../docs/workflow.md).

`examples/` is not part of this corpus. It holds the hand-made reference file
that the format itself is described against.
