# Seanchaí

Seanchaí extracts Diameter command ABNFs and AVP definitions from 3GPP
specifications, RFCs and a few other documents into one plain-text format,
`.dad`. It gives you a parser and a resolved model over the result, so
generating your stack's dictionary, or checking it against the
specifications, takes a short script.

Each `.dad` file records what its source document says, mistakes included.
The only edits are declared patches and corrections, each with its reason.
The [linter][linter] reports contradictions, and the
[Wireshark oracle][oracle] compares the corpus with Wireshark's dictionary.

## Installing

Seanchaí needs Python 3.12 or newer.

```sh
pip install "seanchai[corpus]"   # the library and the corpus
pip install "seanchai[extract]"  # also rebuild the corpus from source documents
```

The library (`seanchai`) and the data (`seanchai-corpus`) are separate
packages with separate versions ([what the version covers][versions]).

```python
from seanchai.model import Model

model = Model.installed()
model.resolve("TS29.229", "Public-Identity")
```

## Commands

Read the installed corpus, with no checkout and no downloads:

```sh
seanchai show NAME_OR_IDENTITY [--json] # one AVP and its other readings
seanchai commands [REF | --application ID] [--json]
seanchai dictionary -o OUT.json         # the corpus as JSON, to generate from
seanchai export -o DIR                  # the corpus as JSON for the static site
seanchai export -o DIR --include-pdfs --specifications specifications
```

Check and rewrite `.dad` files, the corpus's or your own sidecars:

```sh
seanchai lint [--corpus DIR | --no-corpus] [--show-accepted] [FILE.dad | DIR]...
seanchai format [--check] [FILE.dad | DIR]...  # canonical form, ;; comments kept
```

Maintain the corpus, from the root of a checkout:

```sh
seanchai corpus download                    # fetch the catalog into specifications/
seanchai corpus download --no-convert       # without LibreOffice; .doc unread
seanchai corpus download --only wireshark   # one source, keeping the others
seanchai corpus download --only transcribed # the hand transcriptions' PDFs
seanchai corpus download --spec SPECREF --version X.Y.Z   # an older version
seanchai corpus regenerate [--add SPECREF]  # rebuild the corpus from the downloads
seanchai corpus regenerate --expand-ranges  # also widen stale declaration ranges
seanchai corpus extract DOCX --pdf PDF --link URL [--corrections DIR] -o OUT.dad
seanchai corpus extract-rfc RFC.txt --link URL [--corrections DIR] -o OUT.dad
seanchai corpus correct RAW.dad --corrections DIR -o OUT.dad
seanchai corpus crosscheck [FILE.dad | DIR]...  # against Wireshark's dictionary
```

Commands exit 1 on an error or a finding and 2 on a usage error.
`corpus crosscheck` exits 0 on findings.

## Documentation

- [Using the model, the CLI's JSON and the corpus][consumers]
- [The site export][website]
- [The `.dad` format][format]
- [Extraction][extractor] and [corrections][corrections]
- [Checking traffic with a Wireshark plugin][validator]
- [Development][development]

## License

MIT, see [LICENSE][license]. The corpus contains text from 3GPP, ETSI, 3GPP2,
OMA, oneM2M and IETF documents, which stay under their publishers' terms.

[consumers]: https://github.com/sliva0/seanchai/blob/main/docs/consumers.md
[corrections]: https://github.com/sliva0/seanchai/blob/main/docs/corrections.md
[development]: https://github.com/sliva0/seanchai/blob/main/docs/development.md
[extractor]: https://github.com/sliva0/seanchai/blob/main/docs/extractor.md
[format]: https://github.com/sliva0/seanchai/blob/main/docs/dad-format.md
[license]: https://github.com/sliva0/seanchai/blob/main/LICENSE
[linter]: https://github.com/sliva0/seanchai/blob/main/docs/linter.md
[oracle]: https://github.com/sliva0/seanchai/blob/main/docs/oracle.md
[validator]: https://github.com/sliva0/seanchai/blob/main/integrations/wireshark/validator/README.md
[versions]: https://github.com/sliva0/seanchai/blob/main/docs/consumers.md#what-the-version-covers
[website]: https://github.com/sliva0/seanchai/blob/main/docs/website.md
