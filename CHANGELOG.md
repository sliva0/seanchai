# Changelog

Changes to the `seanchai` library. The `seanchai-corpus` package is versioned by
the date it was regenerated, and `git log packages/seanchai-corpus` is its
record.

## Unreleased

Nothing has been published to PyPI yet.

- The RFC extractor fails on a line in an ABNF body that is no member, where it
  stopped reading in silence, and keeps a lone `…` or `...` as a comment behind
  `elided-members`. RFC 5778's DER and DEA and RFC 6738's commands gain the
  members they lost. A command abbreviation may have six letters, as RFC 6738's
  IKESKR does.
- The RFC extractor reads tables boxing every column, stacked captions, codes
  and flags in two tables, tables of re-used AVPs, and rules under a prose title
  a table row cites. RFC 4740, 5624, 5779, 5866, 6736, 6737, 6738 and 7075 join
  the corpus, and RFC 5777 gains `QoS-Capability`'s body.
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
