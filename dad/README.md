# The `.dad` corpus

```
dad/
  3gpp/rel-18/   one directory per 3GPP release
  rfc/           RFCs have no release axis, so they sit flat
  etsi/          ETSI documents transcribed by hand; versions are ETSI's
  onem2m/        oneM2M documents; versions are oneM2M's
  raw/           unedited extractor output, mirroring the four trees
                 above
```

The corrected trees are what tools and consumers read. `raw/` mirrors them
file-for-file and exists for diffing and rot-checking.

Files are named as their publisher names them: `29272-i70` for TS 29.272
V18.7.0 (3GPP's archive naming), `rfc6733` for an RFC, `es283034-020200`
for ETSI ES 283 034 V2.2.0 (ETSI's), `ts-0004-v2_35_0` for oneM2M TS-0004
V2.35.0 (oneM2M's file name, `TS-0004-Service_Layer_Core_Protocol-V2_35_0`,
lower-cased and less its title). RFC files carry no
`; Version:` header because an RFC number names one immutable document.

Each specification is committed twice, and the pair is the point:

- `29272-i70.dad` — the **corrected** file, the one to use.
- `raw/3gpp/rel-18/29272-i70.raw.dad` — what the document said, mistakes
  included. The `.raw.dad` suffix is what the corpus loader and tests key on.

Every line a correction touched carries a `;;` note citing the declaration in
`edits/corrections/` by module and id; a deleted node's note stands alone
where the line was. A specification with no corrections still gets both
files, byte-identical. Nothing here is edited by hand: `seanchai
regenerate` rebuilds the whole tree from the downloaded sources, oneM2M's
included, and the `etsi/` pairs from their hand transcriptions in
`edits/transcriptions/`,
documents published only as PDF
([extractor.md](../docs/extractor.md#transcriptions)).

Keeping the raw file buys three things: a version upgrade can diff raw-vs-raw
with the correction layer held still, corrections can be re-checked without
re-downloading the sources, and the linter has something to fire on.

See [docs/workflow.md](../docs/workflow.md).
