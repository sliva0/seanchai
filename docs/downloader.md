# The downloader

`src/seanchai/downloader/` fetches the curated catalog in its `specs.toml`
into the git-ignored `specifications/`. It uses only the standard library, and keeps
its printing and exit codes in the CLI: the module returns records, reports
progress through a callback, and raises `DownloadError`.

```sh
uv run seanchai download --list     # show the catalog
uv run seanchai download            # fetch it, ETSI PDFs included (default)
```

PDFs are downloaded by default because they are not merely renderings: the
PDF-matched version selection below only runs with them, and a `--no-pdfs`
run rewrites `manifest.json` without any `pdf_url` — the manifest is what
re-extraction scripts read for `; Link:` values — while also letting
`Specs/latest/` replace a committed spec's docx with a newer version whose
ETSI PDF is unpublished (this happened to 29.388 before PDFs became the
default). `--no-pdfs` exists for quick catalog experiments, not for
refreshing the corpus.

It downloads 3GPP archives and their matching ETSI PDF renderings, plus the
plain-text RFCs, and writes `specifications/manifest.json` recording sha256 and size
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
- **With `--pdfs`, version selection prefers page-attachment over newness.**
  When the newest archive version's exact ETSI rendering is unpublished,
  `download_3gpp` walks back to the highest version whose PDF exists — listed
  from `Specs/archive/`, since `Specs/latest/` holds only one zip per spec —
  and records the version it passed over in `newer_source_version`, so the
  manifest says outright that a newer source exists. Only when no version of
  the release has a published PDF does the old behaviour remain: newest
  archive, earlier-version fallback PDF, the mismatch recorded in
  `pdf_version`.
- **A fallback ETSI PDF must never reach `attach_pages`.** When no version of
  the release has a published PDF, `download_3gpp` falls back to an earlier
  rendering and records it in `pdf_version`. That file is still useful, but
  its page numbers belong to a different document. `attach_pages` checks the
  PDF's cover and refuses, so this fails loudly.
- **Extraction replaces the specification directory, it does not merge into
  it.** `replace_extracted` stages the new contents in a sibling directory and
  swaps them in, so `specifications/3gpp/Rel-N/TS_29.272/` never holds members of two
  archive versions at once. `safe_extract` is the raw primitive underneath and
  does merge; call it directly only when that is what you want.

## Planned changes

- Fetch *all* docx zips from the 3GPP archive
  (`.../Specs/archive/<series>_series/<spec>/`, version encoded base-36:
  18.0.0 → `i00`). `discover_3gpp_archive_urls` now lists it, but only the
  PDF-matched version selection reads the listing; the default path still
  takes `Specs/latest/Rel-N/`. Preferring the archive throughout would keep
  every old version available, which the raw-vs-raw diff workflow needs on
  version bumps.
- Derive the ETSI `Link:` URL instead of taking it from the caller. This needs
  the ETSI edition suffix (e.g. `18.00.00_60`), which is not in the docx —
  probably requires listing the ETSI deliver directory.
