# The downloader

`src/seanchai/downloader/` fetches the catalog in its `specs.toml` — 3GPP
archives with their ETSI PDF renderings, the plain-text RFCs, and Wireshark's
Diameter dictionary — into the git-ignored `specifications/`, and writes
`specifications/manifest.json` with sha256 and size per artifact. Standard
library only; the module returns records, reports progress through a callback
and raises `DownloadError`, and the CLI does the printing.

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
- A failed download cancels the remaining jobs; running ones finish. A failed
  run does not leave a stale manifest behind.
- 3GPP index pages are scraped with regexes over raw HTML — fine for the FTP
  listing format, brittle if the markup changes.

Legacy `.doc` archives remain unconverted. The manual TS 32.299 trial with
LibreOffice preserved its numbered content but exposed unsupported source
shapes in the docx extractor; see [extractor.md](extractor.md#legacy-doc-trial).
A converter is not wired into downloads until that file can be extracted and
reviewed end to end. Keep converted trial files outside the manifest, under
`specifications/converted/`, so they cannot masquerade as publisher artifacts.
