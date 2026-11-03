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
