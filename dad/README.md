# The `.dad` corpus

```
dad/
  3gpp/rel-18/   one directory per 3GPP release
  rfc/           RFCs have no release axis, so they sit flat
  raw/           unedited extractor output, mirroring the two trees above
```

The corrected trees are what tools and consumers read. `raw/` mirrors them
file-for-file and exists for diffing and rot-checking.

Files are named as their publisher names them: `29272-i60` for TS 29.272
V18.6.0 (3GPP's archive naming), `rfc6733` for an RFC. RFC files carry no
`; Version:` header because an RFC number names one immutable document.

Each specification is committed twice, and the pair is the point:

- `29272-i60.dad` — the **corrected** file, the one to use.
- `raw/3gpp/rel-18/29272-i60.raw.dad` — what the document said, mistakes
  included. The `.raw.dad` suffix is what the corpus loader and tests key on.

Every line a correction touched carries a `;;` note citing the declaration in
`edits/corrections/`; a deleted node's note stands alone where the line was.
A specification with no corrections still gets both files, byte-identical.

Keeping the raw file buys three things: a version upgrade can diff raw-vs-raw
with the correction layer held still, corrections can be re-checked without
re-downloading the sources, and the linter has something to fire on.

A file without a `; Link:` has no ETSI PDF of its own version, so it carries no
`; Page:` directives either (TS 29.388: docx at V18.1.0, ETSI PDF at V18.0.0).

See [docs/workflow.md](../docs/workflow.md).
