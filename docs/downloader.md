# The downloader

`src/seanchai/downloader/` fetches the catalog in its `specs.toml` — 3GPP
archives with their ETSI PDF renderings, the older 3GPP versions citing
documents mean and the retired ones TS 29.230 still lists, pinned, the
plain-text RFCs, oneM2M's Word
originals at a pinned version, and Wireshark's Diameter dictionary — into the
git-ignored `specifications/`, converts every legacy binary `.doc` to `.docx`
with headless LibreOffice, and writes `specifications/manifest.json` with
sha256 and size per artifact. Standard library plus pypdf, with its crypto
extra (ETSI's TS 129 234 V11.2.0 is AES-encrypted with an empty user
password), and python-docx for validation and
the `soffice` executable (unless `--no-convert`); the module returns records, reports progress through a callback and raises
`DownloadError`, and the CLI does the printing.

```sh
uv run seanchai download --list     # show the catalog
uv run seanchai download            # fetch it, ETSI PDFs included
uv run seanchai download --no-convert   # without LibreOffice; see below
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
  onem2m/Release-2/TS-0004/  the clean oneM2M document │
  rfc/  wireshark/         RFC texts, the dictionary   ┘
  archives/                download cache: every file fetched, never pruned
    3gpp-rel-18/29272-i60.zip  29272-i70.zip  3gpp-rel-7/29140-700.zip
    etsi/18.07.00_60/  onem2m/TS-0004-V2_35_0.zip  rfc/  wireshark/v4.7.2/
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
- **Legacy `.doc` archives are converted, not skipped.** Ten catalogued
  archives (TS 32.299, 29.153, 29.154, 29.201, 29.215, 29.217, 29.219,
  29.343, 29.368, 29.468) hold a `.doc` and no `.docx`, and so do all ten
  pinned versions. Each run converts them into
  `converted/`, mirroring the extracted path
  (`converted/3gpp/Rel-18/TS_32.299/32299-i00.docx`; TS 29.153's archive
  stores its `.doc` under `Temp/Promotion/Upgraded/`, and its conversion
  sits under the same directories), with `soffice
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
- **`--no-convert` skips the conversions**, and with them the need for
  LibreOffice. The `.doc` is still extracted and listed in `files`; the
  record's `conversions` is `[]`, where an archive with a `.docx` of its own
  (or a `--no-extract` run) has `null`, and the progress line ends `(legacy
  .doc not converted)`. `regenerate` reports each such specification as
  `not-converted` and leaves its committed pair alone, and the sources test
  fails naming them, so this manifest is for working on the other
  specifications, not for checking the corpus. A missing `soffice` without
  the flag stays a failure, whose message names the flag: whether a run's
  manifest can rebuild the whole corpus depends on what the run was asked,
  never on what happens to be installed.
- **Older 3GPP versions are pinned, and their claim is checked.** A
  `[[tgpp_pinned]]` entry names a document, one version and what it claims
  that version is: `final = "document"`, the document's last version in any
  release, or `final = "release"`, its release's last. TS 29.140 V7.0.0
  and TS 29.209 V6.8.0 are their documents' final versions, which TS
  32.299 and ETSI ES 283 034 cite non-specifically; TS 29.214 V7.12.0 and
  TS 32.299 V11.20.0 are the last of the releases ETSI TS 183 017 and
  oneM2M TS-0004 name in their references; TS 29.212 V11.19.0 and TS
  29.214 V11.16.0 are Release 11's last, which TS 32.299 V11.20.0's
  non-specific references mean, pinned because Release 18's
  `QoS-Information` and `Flows` differ from theirs. TS 29.210 V6.7.0, TS
  29.211 V6.4.0 and TS 29.234 V11.2.0 are their documents' final versions,
  retired, and held because TS 29.230's tables cite them (Gx and Gx over
  Gy; Rx; Wx, Pr and table 7.1's 100-102 and 300-319), though no corpus
  document resolves into them; TS 29.061 V6.15.0 is Release 6's last, which
  TS 29.210 V6.7.0's non-specific reference means, pinned because Release
  18's flag rules for what it re-uses differ. How the corpus
  resolves to them is in [consumers.md](consumers.md). Every run lists the document's
  archive across releases and checks the claim (`check_final`): a version
  archived later than the pin, in any release or in its own, fails the run
  naming it, before anything is downloaded, so a resolution never rests on
  a claim the archive stopped supporting. The version is then fetched as
  `--version` fetches one, never walked back, its exact ETSI rendering
  attached (all ten are published), into its own release's tree
  (`3gpp/Rel-7/TS_29.140/`, `3gpp/Rel-11/TS_32.299/` beside
  `3gpp/Rel-18/TS_32.299/`), its legacy `.doc` converted like any other.
  TS 29.214 is held at three: V7.12.0, V11.16.0 and the catalog's
  V18.4.0.
  Its record carries the claim in `final`, None for the catalog's release;
  a document the catalog holds at both releases has two records under one
  identifier, ordered by version. `regenerate` keys a copy by its
  reference and its corpus tree (`dad/3gpp/rel-7/`), so neither replaces
  the other. `--spec`/`--version` reaches a pinned document's other
  versions too.
- **oneM2M documents are pinned by the catalog, not discovered.** An
  `[[onem2m]]` entry names the document (`number = "0004"`), its release,
  version and the document library's id; TS-0004 Release 2 is V2.35.0, the
  Word original of the line ETSI mirrors only as PDF (TS 118 104 V2.7.1).
  The library serves a document id's latest revision with no archive of
  earlier ones
  (`https://member.onem2m.org/Application/documentapp/downloadLatestRevision/default.aspx?docID=36771`,
  no login), so the version is the catalog's to state and the download's
  to check: the zip must hold exactly one top-level
  `TS-0004-…-V2_35_0(cl).doc`, and one carrying another version fails the
  run naming it, rather than replace the document under a committed corpus.
  Once fetched, the pinned zip is the cache's
  (`archives/onem2m/TS-0004-V2_35_0.zip`) and later runs read it from
  disk. Only the clean `(cl)` file is extracted, to
  `onem2m/Release-2/TS-0004/`; the zip's revision-marked `(rm)` twin and
  its `__MACOSX/` metadata are not. It is converted like a 3GPP legacy
  `.doc` (`converted/onem2m/Release-2/TS-0004/…(cl).docx`), recorded in
  `conversions` the same way, and `--no-convert` leaves it unconverted
  with `conversions: []`. The record's family is `oneM2M`, its
  `source_version` the pinned version, and it has no PDF: no rendering of
  V2.35.0 exists to attach pages from.
- A failed download cancels the remaining jobs; running ones finish.
- 3GPP and ETSI index pages are scraped with regexes over raw HTML — fine
  for the listing formats, brittle if the markup changes.
