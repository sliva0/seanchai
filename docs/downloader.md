# The downloader

`src/seanchai/downloader/` fetches the catalog in its `specs.toml` into the
git-ignored `specifications/`: 3GPP archives with their ETSI PDF
renderings, pinned older 3GPP versions, the plain-text RFCs, oneM2M's Word
original at a pinned version, and Wireshark's Diameter dictionary. It
converts every legacy `.doc` to `.docx` with headless LibreOffice and
writes `specifications/manifest.json` with sha256 and size per artifact.
Dependencies: pypdf with its crypto extra (ETSI's TS 129 234 V11.2.0 is
AES-encrypted with an empty password), python-docx for validation, and the
`soffice` executable unless `--no-convert`.

In `specs.toml`, `title` and `reason` are prose, read with their whitespace
collapsed; every other field is exact.

```sh
uv run seanchai download --list     # show the catalog
uv run seanchai download            # fetch it, ETSI PDFs included
uv run seanchai download --no-convert   # without LibreOffice
uv run seanchai download --spec TS29.272 --version 18.6.0   # one older version
```

## Layout

```
specifications/
  manifest.json            what the published tree below holds
  3gpp/Rel-18/TS_29.272/   extracted archives          ┐
  3gpp/Rel-18/PDF/         ETSI renderings             │ published tree,
  3gpp/Rel-7/TS_29.140/    a pinned version, its release's │
  converted/               LibreOffice conversions     │ swapped in whole
  onem2m/Release-2/TS-0004/  the oneM2M document       │
  rfc/  wireshark/         RFC texts, the dictionary   ┘
  archives/                download cache: every file fetched, never pruned
  versions/TS29.272/18.6.0/   an older version, on request
  .staging/                a run in progress
```

The cache keys every file by its version-bearing name, so nothing in it is
ever replaced, and a version fetched once is read from disk afterwards. An
older version fetched with `--spec`/`--version` gets a tree of the
published shape under `versions/` with a one-record `manifest.json`, which
`regenerate --manifest` reads
([development.md](development.md#version-upgrades)).

PDFs are on by default because version selection depends on them:
`--no-pdfs` lets the newest archive replace a committed document's docx
with a version whose ETSI PDF is unpublished. It exists for catalog
experiments, not for refreshing the corpus.

## Behaviour

- **Every artifact is validated by opening it**, fresh or cached: ZIP
  member CRCs, the PDF page tree, the "Request for Comments:" header. A
  cached file that fails validation is deleted.
- **A run publishes all of it or nothing.** Every entry is extracted,
  converted and linked from the cache into `.staging/`, and the staged tree
  and manifest are swapped in only once every entry succeeded. A failed
  run leaves the previous tree and manifest as they were, unless the swap
  itself fails halfway: then the rollback restores what it can, writes no
  manifest, and the error names what `.previous/` still holds. The next
  run refuses to start until someone moves it back or deletes it.
- **3GPP versions come from `Specs/archive/`**, which keeps every version.
  The manifest's `url` is the archive's.
- **Version selection prefers page attachment over newness.** When the
  newest archive's ETSI rendering is unpublished, the downloader walks back
  to the highest version whose PDF exists and records the skipped version
  in `newer_source_version`. Only when no version of the release has a PDF
  does it take the newest archive with an earlier-version PDF, recorded in
  `pdf_version`; `attach_pages` checks the cover and refuses such a PDF. A
  `--version` is never walked back.
- **The ETSI URL is read off the deliver listing**, since a version
  directory carries an edition suffix (`18.07.00_60`) the version does not
  determine. That URL is the manifest's `pdf_url` and the `.dad` file's
  `; Link:`.
- **Selection does not depend on listing order**: the highest decoded
  version wins. Archive versions are base-36 (`i00` is 18.0.0); ETSI PDF
  names use two digits per component (`v180100`).
- **Legacy `.doc` archives are converted, not skipped.** Each run converts
  them into `converted/`, mirroring the extracted path, with `soffice
  --headless --infilter='MS Word 97' --convert-to 'docx:Office Open XML
  Text'` in a private temporary profile. The record's `conversions` list
  names the derived file, its source and the source's sha256, the
  converter version and the command. The converted file differs byte for
  byte between runs (zip timestamps, OLE object ids), so `source_sha256`
  and `converter` say whether the content changed. An absent LibreOffice, a
  non-zero exit or a conversion python-docx cannot open fails the download.
  A conversion still running after ten minutes is killed with its whole
  process group.
- **`--no-convert` skips the conversions.** The `.doc` is still extracted;
  the record's `conversions` is `[]`, and `regenerate` reports each such
  document as `not-converted` and leaves its committed pair alone. Whether
  a manifest can rebuild the whole corpus depends on what the run was
  asked, never on what happens to be installed.
- **Older 3GPP versions are pinned, and their claim is checked.** A
  `[[tgpp_pinned]]` entry names a document, one version and what it claims
  that version is: `final = "document"`, the document's last version in
  any release, or `final = "release"`, its release's last. Every run lists
  the document's archive and checks the claim before downloading anything,
  so a resolution never rests on a claim the archive stopped supporting.
  The version is fetched into its own release's tree
  (`3gpp/Rel-11/TS_32.299/` beside `3gpp/Rel-18/TS_32.299/`). How the
  corpus resolves to the pinned copies is in
  [consumers.md](consumers.md#resolution-across-releases).
- **A catalog entry can be downloaded and still be out of scope.** A `[[tgpp]]`
  entry's `out_of_scope` says why the extractor has nothing to read in it; the
  document is fetched for reference, and `regenerate --add` refuses it with
  those words ([extractor.md](extractor.md#out-of-scope)).
- **Hand transcriptions are in the catalog for their titles only.** A
  `[[transcribed]]` entry names a document under `edits/transcriptions/` and the
  title its cover prints. Nothing downloads it for the corpus; `seanchai export`
  reads the title.
- **oneM2M documents are pinned by the catalog, not discovered.** The
  document library serves a document id's latest revision with no archive,
  so the version is the catalog's to state and the download's to check: a
  zip carrying another version fails the run rather than replace the
  document under a committed corpus. Only the clean `(cl)` file is
  extracted and converted; the record has no PDF, since no rendering of
  V2.35.0 exists.
- A failed download cancels the remaining jobs; running ones finish.
- 3GPP and ETSI index pages are scraped with regexes over raw HTML, which
  is fine for the listing formats and brittle if the markup changes.
