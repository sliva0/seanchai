# The downloader

`src/seanchai/downloader/` fetches the curated catalog in its `specs.toml`
into the git-ignored `output/`. It uses only the standard library, and keeps
its printing and exit codes in the CLI: the module returns records, reports
progress through a callback, and raises `DownloadError`.

```sh
uv run seanchai download --list     # show the catalog
uv run seanchai download            # fetch it
uv run seanchai download --pdfs     # include the ETSI PDF renderings
```

It downloads 3GPP archives and their matching ETSI PDF renderings, plus the
plain-text RFCs, and writes `output/manifest.json` recording sha256 and size
per artifact.

## Notes for whoever touches it next

- 3GPP index pages are scraped with regexes over raw HTML. That is fine for the
  FTP listing format, but brittle if 3gpp.org changes its markup.
- A failed download cancels the remaining jobs, but already-running ones finish.
- Keep `manifest.json` if the module is restructured: the extractor pipeline can
  use its hashes for change detection.
- ETSI PDF filenames encode versions as two digits per component (18.1.0 →
  `v180100`); `etsi_pdf_url()` handles this. Don't hand-build these URLs.
- **Every artifact is validated by opening it**, fresh or cached:
  `validate_zip` checks each member's CRC, `validate_pdf` reads the page tree,
  `validate_rfc_text` looks for the "Request for Comments:" header line. A
  `%PDF-` prefix is deliberately not enough — that is exactly what a truncated
  download has. A replacement is validated in its temporary file before it is
  put in place, and a cached file that fails validation is deleted even when
  its replacement fails too, so the same broken file is not rediscovered on
  every run.
- **Version selection does not depend on listing order.** `discover_3gpp_urls`
  picks the archive with the highest decoded version, not the last matching
  link on the index page.
- **A fallback ETSI PDF must never reach `attach_pages`.** When the exact
  version isn't published, `download_3gpp` falls back to an earlier one and
  records it in `pdf_version`. That file is still useful, but its page numbers
  belong to a different document. `attach_pages` now checks the PDF's cover and
  refuses, so this fails loudly; the manifest would still be a better place to
  say outright whether a PDF is page-attachment compatible.
- **Extraction replaces the specification directory, it does not merge into
  it.** `replace_extracted` stages the new contents in a sibling directory and
  swaps them in, so `output/3gpp/Rel-N/TS_29.272/` never holds members of two
  archive versions at once. `safe_extract` is the raw primitive underneath and
  does merge; call it directly only when that is what you want.

## Planned changes

- Fetch the docx zips from the 3GPP archive
  (`.../Specs/archive/<series>_series/<spec>/`, version encoded base-36:
  18.0.0 → `i00`). Prefer `Specs/archive/` over the current
  `Specs/latest/Rel-N/` index: the archive keeps every old version, which the
  raw-vs-raw diff workflow needs on version bumps.
- Derive the ETSI `Link:` URL instead of taking it from the caller. This needs
  the ETSI edition suffix (e.g. `18.00.00_60`), which is not in the docx —
  probably requires listing the ETSI deliver directory.
