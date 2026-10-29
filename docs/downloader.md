# The downloader

`src/seanchai/downloader/` fetches the catalog in its `specs.toml` — 3GPP
archives with their ETSI PDF renderings, the plain-text RFCs, and Wireshark's
Diameter dictionary — into the git-ignored `specifications/`, converts the
archives that ship a legacy binary `.doc` to `.docx` with headless
LibreOffice, and writes `specifications/manifest.json` with sha256 and size
per artifact. Standard library plus pypdf and python-docx for validation and
the `soffice` executable; the module returns records, reports progress through a callback and raises
`DownloadError`, and the CLI does the printing.

```sh
uv run seanchai download --list     # show the catalog
uv run seanchai download            # fetch it, ETSI PDFs included
uv run seanchai download --spec TS29.272 --version 18.6.0   # one older version
```

## Layout

```
specifications/
  manifest.json            what the published tree below holds
  3gpp/Rel-18/TS_29.272/   extracted archives          ┐
  3gpp/Rel-18/PDF/         ETSI renderings             │ published tree,
  converted/               LibreOffice conversions     │ swapped in whole
  rfc/  wireshark/         RFC texts, the dictionary   ┘
  archives/                download cache: every file fetched, never pruned
    3gpp-rel-18/29272-i60.zip  29272-i70.zip
    etsi/18.07.00_60/  rfc/  wireshark/v4.7.2/
  versions/TS29.272/18.6.0/   an older version, on request
  .staging/                a run in progress
```

The cache keys every file by its version-bearing name (an ETSI PDF under
its edition directory too, since ETSI names every edition's PDF alike; the
Wireshark files by tag), so nothing in it is ever replaced, and a version fetched once is
read from disk afterwards. Only the versions a run selects are downloaded;
an older one is fetched when `--spec`/`--version` asks for it. Its tree,
`versions/<SpecRef>/<version>/`, has the published tree's shape and a
one-record `manifest.json` of its own, so `regenerate --manifest` reads it
(see [workflow.md](workflow.md#version-upgrades)); the version's major is
the release. The cached archive is hard-linked into it, so the directory
can be deleted on its own.

PDFs are on by default because version selection depends on them: `--no-pdfs`
rewrites the manifest without `pdf_url` and lets the newest archive replace a
committed spec's docx with a version whose ETSI PDF is unpublished. It exists
for catalog experiments, not for refreshing the corpus.

## Behaviour worth knowing

- **Every artifact is validated by opening it**, fresh or cached: ZIP member
  CRCs, the PDF page tree, the "Request for Comments:" header. A `%PDF-`
  prefix is not enough. A replacement is validated in its temporary file
  before being put in place, and a cached file that fails validation is
  deleted even when its replacement fails too.
- **A run publishes all of it or nothing.** Every entry is extracted,
  converted and linked from the cache into `.staging/`, and `publish` swaps
  the staged tree and manifest in only once every entry succeeded: the
  current entries are renamed into `.previous/`, the staged ones into place,
  and on any failed rename the swap is rolled back: directories first, the
  manifest only once every directory is back. A failed run leaves the
  previous tree and the manifest describing it as they were, never a mix of
  old and new specifications; a directory the rollback cannot restore leaves
  no manifest, and the error names what `.previous/` holds. The manifest is taken aside first and put in
  last, so an interruption mid-swap leaves no manifest rather than one
  describing a half-swapped tree. A `.previous/` a failed rollback left
  behind holds the last published tree, and the next run refuses to start
  until someone moves it back or deletes it.
- **3GPP versions come from `Specs/archive/`**, one listing per
  specification, which keeps every version; `Specs/latest/` lists only the
  newest and drops it when the next lands. The manifest's `url` is the
  archive's, which stays valid.
- **Version selection prefers page-attachment over newness.** When the
  newest archive's exact ETSI rendering is unpublished, the downloader walks
  back to the highest version whose PDF exists and records the skipped
  version in `newer_source_version`. Only when no version of the release has
  a PDF does it take the newest archive with an earlier-version fallback
  PDF, recorded in `pdf_version`. A fallback PDF never reaches
  `attach_pages`, which checks the cover and refuses. A `--version` is never
  walked back.
- **The ETSI URL is read off the deliver listing**, since a version
  directory carries an edition suffix (`18.07.00_60`) the version does not
  determine. `discover_etsi_editions()` lists
  `etsi.org/deliver/etsi_ts/<range>/<number>/` and takes each version's
  highest edition; `etsi_listed_pdf_url()` then lists that directory for the
  version's PDF. That URL is the manifest's `pdf_url` and the `.dad` file's
  `; Link:`. Where a listing is unreachable it falls back to the derived
  `_60` name (`etsi_pdf_url()`); every catalogued TS publishes `_60` today.
- **Selection does not depend on listing order**: the highest decoded
  version wins. Archive versions are base-36 (`i00` = 18.0.0); ETSI PDF
  filenames use two digits per component (`v180100`); the functions above
  do the derivation, so don't hand-build those URLs.
- **Legacy `.doc` archives are converted, not skipped.** Nine catalogued
  archives (TS 32.299, 29.154, 29.201, 29.215, 29.217, 29.219, 29.343,
  29.368, 29.468) hold a `.doc` and no `.docx`. Each run converts them into
  `converted/`, mirroring the extracted path
  (`converted/3gpp/Rel-18/TS_32.299/32299-i00.docx`), with `soffice
  --headless --infilter='MS Word 97' --convert-to 'docx:Office Open XML
  Text'` in a private temporary profile. The `.doc` stays where it was
  extracted. The record's `conversions` list names the derived file and
  its source, the source's sha256, the converter (`soffice --version`) and
  the command:

  ```json
  "conversions": [{
    "file": "converted/3gpp/Rel-18/TS_32.299/32299-i00.docx",
    "source": "3gpp/Rel-18/TS_32.299/32299-i00.doc",
    "source_sha256": "646db9a8…",
    "converter": "LibreOffice 26.8.1.1 bf8adb13…",
    "command": ["soffice", "-env:UserInstallation={profile}", "--headless",
                "--infilter=MS Word 97", "--convert-to",
                "docx:Office Open XML Text", "--outdir", "{outdir}", "{source}"],
    "sha256": "79897b54…", "size": 1323656
  }]
  ```

  The converted file differs byte for byte between runs (zip timestamps,
  random OLE object ids), so its own hash says which file this manifest
  describes, not whether the content changed; `source_sha256` and
  `converter` do. `regenerate` reads the conversion through this record and
  no other way. An absent LibreOffice, a non-zero exit, or a conversion
  that writes no `.docx` python-docx can open fails the download and names
  the specification. A conversion still running after ten minutes is killed
  with its whole process group, `soffice.bin` included, not just the
  `soffice` launcher.
- A failed download cancels the remaining jobs; running ones finish.
- 3GPP and ETSI index pages are scraped with regexes over raw HTML — fine
  for the listing formats, brittle if the markup changes.
