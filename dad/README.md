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

`*.raw.dad` is unedited extractor output, committed per specification version.
The corrected file is *generated* from the raw file plus its correction module
(`edits/corrections/`) and is not committed: see
[workflow.md](../docs/workflow.md) for why the durable pair is raw + corrections
rather than the corrected file.

`examples/` is not part of this corpus. It holds the hand-made reference file
that the format itself is described against.
