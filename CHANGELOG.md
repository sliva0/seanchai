# Changelog

Changes to the `seanchai` library. The `seanchai-corpus` package is versioned by
the date it was regenerated, and `git log packages/seanchai-corpus` is its
record.

## Unreleased

Nothing has been published to PyPI yet.

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
