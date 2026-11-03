# Changelog

Changes to the `seanchai` library. The `seanchai-corpus` package is versioned by
the date it was regenerated, and `git log packages/seanchai-corpus` is its
record.

## Unreleased

Nothing has been published to PyPI yet.

- `seanchai regenerate` names an ETSI document in parts as ETSI does
  (`ts18305901-020101`), and the catalog gains ETSI TS 183 020, TS 183 059-1 and
  3GPP2 X.S0013-006.
- `seanchai download` fetches the catalog at Release 19 (`downloader.RELEASE`).
- A plain `regenerate` follows a committed copy into a later release's tree when
  the manifest no longer lists its own, reporting it `replaced` and leaving no
  empty tree behind.
- A declaration ranged with no upper bound, or none at all, no longer counts as
  having reviewed a later release: a file mixing them with closed ranges keeps
  all of its declarations through a release upgrade.
- A registry row's Code cell may print a placeholder, kept quoted as
  `RegistryRow.printed_code` with `code` None, behind the extractor's
  `placeholder-codes`: TS 29.230 V19.3.0 allocates TS 29.329's Sh-ee `"zz"`.
- The docx extractor reads a table whose every row merges a column across grid
  columns no cell starts in, and retires `conflicting-avp-codes`, TS 29.273
  V19.2.0 having settled the code it was for.
- A `Value Table` block for what a numeric AVP's numbers are named:
  `result-codes`, `bits` and `features`, read from 3GPP clause headings, lines
  and tables and from RFC text, with `value_table` and `value_row` selectors for
  corrections.
- `Model.value_tables`, `Model.feature_lists`, `Avp.value_tables` and
  `Avp.value_table`; `seanchai show` prints them, and `seanchai dictionary`
  format 2 holds them.
- The export's schema version 5 has search entries of kind `value` and links
  their names; `lint` has `duplicate-value`, `value-bit-out-of-range` and two
  `registry-result-code-*` notes; `crosscheck` compares the tables with
  Wireshark's `<enum>`s.
- A download takes an earlier ETSI rendering only on a 404 for the exact one,
  and fails on any other error fetching it.
- The docx extractor reads a command printed as a category table under
  `message-tables`, TS 32.299 V11.20.0's RAR, and fails on a caption naming a
  command over a table it cannot read.
- `; Type: Reprinted AVP` records a rule a document prints as another's, naming
  it with `; From:`, and defines nothing: TS 29.109's three copies of RFC 6733's
  `Vendor-Specific-Application-Id`. `ast.ReprintedAvp`; the linter's
  `reprint-not-in-origin` and `reprint-differs`.
- The RFC extractor fails on a line in an ABNF body that is no member, where it
  stopped reading in silence, and keeps a lone `…` or `...` as a comment behind
  `elided-members`. RFC 5778's DER and DEA and RFC 6738's commands gain the
  members they lost. A command abbreviation may have six letters, as RFC 6738's
  IKESKR does.
- The RFC extractor reads tables boxing every column, stacked captions, codes
  and flags in two tables, tables of re-used AVPs, and rules under a prose title
  a table row cites. RFC 4740, 5624, 5779, 5866, 6736, 6737, 6738 and 7075 join
  the corpus, and RFC 5777 gains `QoS-Capability`'s body.
- `seanchai lint` and the model resolve a non-specific citation by a document
  saying "the latest edition" applies to the newest copy, by citation
  (`corpus.LATEST_EDITIONS`), and `RELEASE_STAND_INS` answers a version an ETSI
  document names; `CrossRelease.specific` says which. A spec-ref keeps the part
  of a document in parts: `3GPP2-X.S0013-014`, `ETSI-TS183.059-1`.
- `seanchai download --only transcribed` fetches the PDFs the hand
  transcriptions were copied from into `specifications/transcriptions/`,
  recorded in the manifest, where `export --include-pdfs` finds them; a full
  download does too.
- `Model.definition`, `find`, `identified`, `avps()` and `seanchai show` know an
  identity only an older copy holds, where a citation reaches it, so every
  identity `seanchai dictionary` writes resolves.
- The docx extractor fails on a line inside an ABNF body that is no member,
  rather than ending the body there, and keeps a `…` line as a comment behind
  `elided-members`, which restores the members TS 29.273's, and 8 more
  documents', bodies lost.
- The docx extractor reads the text inside Word's smart tags, command headings
  spacing a name's words, TS 29.061's and TS 29.109's commands, and a command
  printed as a table, so 41 commands the corpus lacked are `Message` blocks.
- `Model.definition`, `Avp.read_through`, `Message.walk`, `Application.avps` and
  `Model.installed`; `messages`, `applications` and `avps` work corpus-wide.
- `Message.application_id` is the id on the wire; the header's is
  `header_application_id`.
- `Avp.flag_rules` is always a `model.FlagRules`.
- `SeanchaiError` is the base of every error the library raises on purpose.
- `seanchai.__version__`, `seanchai --version` and `Corpus.version`.
- `python-docx` and `pypdf` moved to the `seanchai[extract]` extra. `seanchai
  extract`, `regenerate` and a 3GPP or oneM2M `download` need it and name it;
  the model, the export and `lint` do not.
- `extractor/__init__.py` no longer imports `tgpp_docx`, and the catalog moved
  to `downloader/catalog.py`.
- `seanchai download --only {wireshark,rfc,3gpp,onem2m}`, keeping the manifest
  whole; its `sources` says what it holds, and `regenerate` names what is
  missing.
- `seanchai show`, `commands` and `dictionary`, for a stack not in Python
  (docs/consumers.md). `Model.canonical` is public.
- `lint` and `format` take directories, leaving out the raw mirror unless
  `--raw`, and `lint` with none reads the installed corpus. A file that does not
  parse is named by `lint` and `correct` too.
- A missing `specifications/` or Wireshark dictionary says which `seanchai
  download` to run. `regenerate --manifest`, `crosscheck --dictionary`, `export
  --specifications` and `--dictionary` given a missing path exit 1 saying so,
  and `export --include-pdfs` without `--specifications` is a usage error.
- Help shows every default the same way.
- `seanchai export` writes `syntax/dad.tmLanguage.json`, and each entry of a
  document's `sections` has a `title` and runs in document order. The grammar's
  source moved to `src/seanchai/dad/syntax/`, with `editors/vscode/` holding a
  copy.
- `index.json` says `generator`, which is what lets a later `seanchai export`
  replace its directory; a directory with any other `index.json` is refused,
  except the exact shape an earlier version wrote. `SCHEMA_VERSION` is 4.
- A failed `seanchai export` swap can no longer lose the previous export: it
  waits in `<output>.previous-<pid>` until replaced or restored, and an error
  names it if it cannot be restored.
