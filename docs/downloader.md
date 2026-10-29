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
```

PDFs are on by default because version selection depends on them: `--no-pdfs`
rewrites the manifest without `pdf_url` and lets `Specs/latest/` replace a
committed spec's docx with a version whose ETSI PDF is unpublished. It exists
for catalog experiments, not for refreshing the corpus.

## Behaviour worth knowing

- **Every artifact is validated by opening it**, fresh or cached: ZIP member
  CRCs, the PDF page tree, the "Request for Comments:" header. A `%PDF-`
  prefix is not enough. A replacement is validated in its temporary file
  before being put in place, and a cached file that fails validation is
  deleted even when its replacement fails too.
- **Version selection prefers page-attachment over newness.** When the
  newest archive's exact ETSI rendering is unpublished, the downloader walks
  back to the highest version whose PDF exists, listed from `Specs/archive/`,
  and records the skipped version in `newer_source_version`. Only when no
  version of the release has a PDF does it take the newest archive with an
  earlier-version fallback PDF, recorded in `pdf_version`. A fallback PDF
  never reaches `attach_pages`, which checks the cover and refuses.
- **Selection does not depend on listing order**: the highest decoded
  version wins. Archive versions are base-36 (`i00` = 18.0.0); ETSI PDF
  filenames use two digits per component (`v180100`); `etsi_pdf_url()` does
  the derivation, so don't hand-build those URLs.
- **Extraction replaces the specification directory** (`replace_extracted`
  stages and swaps, rolling back on failure) so a directory never holds two
  archive versions. `safe_extract` underneath does merge.
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
- A failed download cancels the remaining jobs; running ones finish. A failed
  run does not leave a stale manifest behind.
- 3GPP index pages are scraped with regexes over raw HTML — fine for the FTP
  listing format, brittle if the markup changes.
