# The downloader

`src/seanchai/downloader/` fetches the catalog in `specs.toml` into the
git-ignored `specifications/`:

- 3GPP archives with their ETSI PDF renderings, and pinned older 3GPP
  versions;
- RFC plain texts;
- oneM2M's Word original, at a pinned version;
- the PDFs the hand transcriptions were copied from;
- Wireshark's Diameter dictionary.

It converts each legacy `.doc` to `.docx` with headless LibreOffice and
writes `specifications/manifest.json`, with the sha256 and size of every
artifact.

It needs the `seanchai[extract]` extra (pypdf with its crypto extra, since
ETSI's TS 129 234 V11.2.0 is AES-encrypted with an empty password, and
python-docx to validate) and `soffice` unless `--no-convert`.

```sh
uv run seanchai corpus download --list          # show the catalog
uv run seanchai corpus download                 # fetch it, ETSI PDFs included
uv run seanchai corpus download --no-convert    # without LibreOffice
uv run seanchai corpus download --spec TS29.272 --version 18.6.0  # one older
uv run seanchai corpus download --only wireshark --only rfc  # the small ones
uv run seanchai corpus download --only transcribed  # the transcriptions' PDFs
```

## The catalog

`specs.toml` has one table per entry. `title` and `reason` are prose, read
with whitespace collapsed; every other field is exact.

- `[[tgpp]]`: a 3GPP document in the release `RELEASE` in
  `downloader/catalog.py` names. An `out_of_scope` entry is fetched for
  reference and refused by `regenerate --add`
  ([extractor.md](extractor.md#out-of-scope)).
- `[[tgpp_pinned]]`: one older version, with a claim each run checks
  against the archive before downloading: `final = "document"` (its last
  version in any release) or `final = "release"` (its release's last). It
  goes into its own release's tree (`3gpp/Rel-11/TS_32.299/`). Every
  `cited_version` and `final_version` in `corpus.toml` must be such a pin,
  the latter with `final = "document"` (`tests/test_corpus.py`,
  [consumers.md](consumers.md#resolution-across-releases)).
- `[[rfc]]`: an RFC.
- `[[onem2m]]`: a oneM2M document at a pinned `version`, since oneM2M's
  library serves only a document's latest revision. A zip carrying another
  version fails the run. Only the clean `(cl)` file is extracted and
  converted, and there is no PDF.
- `[[transcribed]]`: the PDF a file in `edits/transcriptions/` was copied
  from. `title` is its cover's title, which `seanchai export` reads; `url`
  must equal the file's `; Transcribed:` URL. The URL is fixed in the
  catalog because ETSI's listing shows later versions and 3GPP2's shows
  nothing.
- `[wireshark]`: the release `tag` and `path` of Wireshark's Diameter
  dictionary directory.

## Layout

The published tree, which a run swaps in whole:

| Path | Holds |
|---|---|
| `manifest.json` | what the published tree holds |
| `3gpp/Rel-19/TS_29.272/` | extracted archives |
| `3gpp/Rel-19/PDF/` | ETSI renderings |
| `3gpp/Rel-7/TS_29.140/` | a pinned version, in its own release |
| `converted/` | LibreOffice conversions |
| `onem2m/Release-2/TS-0004/` | the oneM2M document |
| `transcriptions/` | the transcriptions' PDFs |
| `rfc/`, `wireshark/` | RFC texts and the dictionary |

Beside it:

| Path | Holds |
|---|---|
| `archives/` | the download cache: every file fetched, never pruned |
| `versions/TS29.272/18.6.0/` | an older version fetched on request |
| `.staging/` | a run in progress |

The cache keys files by their version-bearing names, so nothing in it is
replaced and a version is downloaded once. An older version fetched with
`--spec` and `--version` gets a tree of the published shape under
`versions/`, with a one-record `manifest.json` for `regenerate --manifest`
([development.md](development.md#version-upgrades)).

## Behaviour

- A run publishes all or nothing: entries are staged in `.staging/` and
  swapped in only when all succeeded. If the swap fails halfway, the rollback
  restores what it can, writes no manifest and names what `.previous/` holds;
  the next run refuses to start until `.previous/` is moved back or deleted.
- A failed download cancels the remaining jobs; running ones finish.
- Every artifact is validated by opening it, fresh or cached: ZIP member
  CRCs, the PDF page tree, an RFC's "Request for Comments:" header. A cached
  file that fails is deleted.
- `--only` fetches the named sources (`3gpp` with its pins, `onem2m`, `rfc`,
  `transcribed`, `wireshark`) and keeps what the manifest holds of the
  others. The manifest's `sources` lists what it holds; `3gpp_release` and
  `include_pdfs` are null without 3GPP documents. A kept record whose files
  are gone refuses the run. `regenerate` over a partial manifest fails with
  `not-in-manifest` unless `--spec` names only documents it holds.
- 3GPP versions come from `Specs/archive/`, which keeps every version; the
  manifest's `url` is the archive's.
- The downloader takes the highest version with a published ETSI PDF and
  records a newer, skipped one in `newer_source_version`. If no version of
  the release has a PDF, it takes the newest archive with an earlier
  version's PDF, recorded in `pdf_version`, which `attach_pages` refuses. An
  explicit `--version` is never walked back. Only ETSI's 404 for the exact
  PDF leads to an earlier one; any other fetch failure fails the run.
- `--no-pdfs` skips this, letting the newest archive replace a committed
  document. It is for catalog experiments only.
- The ETSI URL comes from the deliver listing, since the directory carries an
  edition suffix (`18.07.00_60`). It is the manifest's `pdf_url` and the
  `.dad` file's `; Link:`.
- The highest decoded version wins regardless of listing order. Archive
  versions are base-36 (`i00` is 18.0.0); ETSI PDF names use two digits per
  component (`v180100`).
- A legacy `.doc` is converted into `converted/`, mirroring its path, with
  `soffice --headless --infilter='MS Word 97' --convert-to 'docx:Office Open
  XML Text'` in a temporary profile. The record's `conversions` names the
  output, the source and its sha256, the converter version and the command;
  `source_sha256` and `converter` show whether content changed, since output
  bytes vary between runs. A missing LibreOffice, a non-zero exit or an
  output python-docx cannot open fails the run. A conversion is killed with
  its process group after ten minutes.
- `--no-convert` still extracts the `.doc` but records `conversions` as `[]`.
  `regenerate` reports such a document as `not-converted` and leaves its
  committed pair alone. What a manifest can rebuild depends on the options
  used, never on what is installed.
- A transcription's PDF goes to `transcriptions/` under its own name, with
  the publisher as `family` (`ETSI`, `3GPP2`, `OMA`), for
  `seanchai export --include-pdfs`. `regenerate` reads only the
  transcription, so it does not need this source.
- 3GPP and ETSI index pages are scraped with regular expressions over raw
  HTML, which breaks if their markup changes.
