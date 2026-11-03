# Seanchaí

Seanchaí extracts Diameter command ABNFs and AVP definitions from 3GPP
specifications, RFCs and a few other documents into one plain-text format,
`.dad`, and gives you a parser and a resolved model over the result. From
there, generating your implementation's dictionary format, or checking an
existing dictionary against the specifications, is a short script.

5G protocols ship OpenAPI. Diameter ships ABNF blocks and tables inside Word
documents and RFC text, and every implementation transcribes them by hand.
Seanchaí does that transcription once, with every edit declared and reviewed.

## How it works

1. **Extract.** Source documents become raw `.dad` files. 3GPP specifications
   are read from their `.docx` (legacy `.doc` files are converted with
   LibreOffice), with page numbers from the matching ETSI PDF; RFCs are read
   from their plain text. See [docs/extractor.md][extractor].
2. **Correct.** Three things are committed per document: the raw output, the
   corrections declared against it, and the corrected file they produce.
   Every corrected line carries a `;;` note naming its correction. See
   [docs/corrections.md][corrections].
3. **Consume.** The parser turns `.dad` back into an AST, and `seanchai.model`
   resolves the corpus into messages whose members point at real AVP
   objects. See [docs/consumers.md][consumers].

The rule everything rests on: **a `.dad` file records everything its source
document says about a definition**, including where the document is
redundant, self-contradictory or wrong. The extractor translates and never
curates. The only edits are the two declared layers, input patches for
source typos and corrections for wrong data, and both are reviewable. The
[linter][linter] reports the contradictions, and the
[Wireshark oracle][oracle] cross-checks values against an
independent reading of the same documents.

## Installing

Seanchaí needs Python 3.14 or newer. The library and the corpus are two
packages, each versioned on its own: `seanchai` follows semantic versioning, and
`seanchai-corpus`, which also installs alone on Python 3.10 or newer, is
versioned by the date the corpus was regenerated.

```sh
pip install "seanchai[corpus]"   # or seanchai and seanchai-corpus, pinned apart
pip install "seanchai[extract]"  # to rebuild a corpus from source documents
```

The `extract` extra is `python-docx` and `pypdf`, which `seanchai extract`,
`regenerate` and a 3GPP or oneM2M `download` need and a consumer does not.

```python
from seanchai import model

built = model.Model.installed()
built.resolve("TS29.229", "Public-Identity")
```

## Commands

```sh
seanchai download                       # fetch the catalog into specifications/
seanchai download --no-convert          # without LibreOffice; legacy .doc unread
seanchai download --spec SPECREF --version X.Y.Z   # one older version, for diffs
seanchai regenerate [--add SPECREF]     # rebuild the corpus from the downloads
seanchai regenerate --expand-ranges     # also widen stale declaration ranges
seanchai extract DOCX --pdf PDF --link URL [--corrections DIR] -o OUT.dad
seanchai extract-rfc RFC.txt --link URL [--corrections DIR] -o OUT.dad
seanchai correct RAW.dad --corrections DIR -o OUT.dad
seanchai format [--check] FILE.dad...   # canonical form, ;; comments kept
seanchai lint [--corpus DIR | --no-corpus] [--show-accepted] FILE.dad...
seanchai crosscheck [FILE.dad | DIR]... # against Wireshark's dictionary
seanchai export -o DIR                  # the corpus as JSON for the static site
seanchai export -o DIR --include-pdfs --specifications specifications
```

## Development

The repository layout and how to work on Seanchaí itself are in
[docs/development.md][development].

## License

MIT, see [LICENSE][license]. The corpus packages text taken from 3GPP, ETSI,
3GPP2, oneM2M and IETF documents; those documents stay under their
publishers' terms.

[consumers]: https://github.com/sliva0/senchai/blob/main/docs/consumers.md
[corrections]: https://github.com/sliva0/senchai/blob/main/docs/corrections.md
[development]: https://github.com/sliva0/senchai/blob/main/docs/development.md
[extractor]: https://github.com/sliva0/senchai/blob/main/docs/extractor.md
[license]: https://github.com/sliva0/senchai/blob/main/LICENSE
[linter]: https://github.com/sliva0/senchai/blob/main/docs/linter.md
[oracle]: https://github.com/sliva0/senchai/blob/main/docs/oracle.md
