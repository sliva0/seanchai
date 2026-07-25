# The downloader

`downloader/download_diameter_specs.py` is a standalone uv script (no
dependencies outside the standard library) that fetches the curated catalog in
`downloader/specs.toml` into the git-ignored `output/`.

```sh
downloader/download_diameter_specs.py --list     # show the catalog
downloader/download_diameter_specs.py            # fetch it
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
- **Known wart**: when a cached file fails the content-type check and the
  re-download also fails validation, `atomic_download` leaves the corrupt
  cached file in place instead of deleting it.

## Planned changes

- Fetch the docx zips from the 3GPP archive
  (`.../Specs/archive/<series>_series/<spec>/`, version encoded base-36:
  18.0.0 → `i00`). Prefer `Specs/archive/` over the current
  `Specs/latest/Rel-N/` index: the archive keeps every old version, which the
  raw-vs-raw diff workflow needs on version bumps.
- Derive the ETSI `Link:` URL instead of taking it from the caller. This needs
  the ETSI edition suffix (e.g. `18.00.00_60`), which is not in the docx —
  probably requires listing the ETSI deliver directory.
- Move the script into the package as `src/seanchai/downloader/` behind a
  `seanchai download` command, once it needs to share version decoding and the
  manifest with the extractor. See
  [plan-code-quality.md](plan-code-quality.md).
