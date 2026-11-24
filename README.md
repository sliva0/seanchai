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

Browse the corpus online at
[seanchai-explorer](https://sliva0.github.io/seanchai-explorer/).

## A dictionary for your stack

S6a, from install to the JSON a dictionary or codec generator reads:

```sh
pip install "seanchai[corpus]"
seanchai commands --application 16777251        # S6a's commands, TS 29.272
seanchai dictionary --application 16777251 --strict -o s6a.json
seanchai show Emergency-Services --document TS29.272
seanchai dictionary --application 16777358 --strict -o nta.json   # refused
```

`s6a.json` holds S6a's commands with their bodies, request and answer paired,
each member's information element and its category, M, C or O, from TS
29.272's per-command tables, the error answer RFC 6733 gives them, and every
AVP they reach at any depth, whichever document defines it. Each AVP has its
code, vendor, type and basic type, flag rules and Encrypt cell; each value
table it carries comes too, and each feature list only for the application it
numbers. `Emergency-Services`
is one TS 29.272 re-uses: `show` prints TS 29.273's definition and its bits,
both in `s6a.json`. TS 29.272's clauses are also read for what their prose
says of each AVP's value and presence (a PLMN identity's layout, a range, a
member allowed only beside another), as
[interpreted constraints][constraints], each pinned to the sentences read.
Where two documents read one AVP differently, the file lists the conflict and
where each reading is met.

`--strict` refuses a selection reaching what the corpus cannot complete. TS
29.154's Nta names `External-Group-Identifier`, which no document defines;
`--policy supply --alias External-Group-Identifier TS29.336
External-Identifier` reads it as the AVP you take it for. `--with FILE.dad`
adds your own AVPs and commands, from a file naming a private document
(`; Specification: Private ACME-HSS`) in your own vendor's space.

[The dictionary][dictionary] describes the file, and
[`seanchai dictionary --schema`][dictionary] writes its JSON Schema.
[python-diameter's integration][python-diameter] generates a stack's modules
from the same model.

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

Read the installed corpus, with no checkout and no downloads; `show`,
`commands` and `dictionary` read another with `--corpus DIR` and your own
`.dad` files beside it with `--with FILE`:

```sh
seanchai show NAME_OR_IDENTITY [--json] # one AVP and its other readings
seanchai commands [REF | --application ID] [--json]
seanchai dictionary -o OUT.json [--strict] [--schema FILE]  # JSON to generate from
seanchai export -o DIR                  # the corpus as JSON for the static site
seanchai export -o DIR --include-pdfs --specifications specifications
seanchai wireshark-plugin -o FILE.lua   # a Wireshark plugin checking traffic
seanchai diff OLD.dad NEW.dad [--json]  # what changed for a stack, and where from
seanchai vectors -o OUT.json [--pcap F] # test messages, valid and breaking one rule
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
seanchai corpus regenerate --acknowledge-unclaimed  # list new unclaimed tables
seanchai corpus extract DOCX --pdf PDF --link URL [--corrections DIR] -o OUT.dad
seanchai corpus extract-rfc RFC.txt --link URL [--corrections DIR] -o OUT.dad
seanchai corpus correct RAW.dad --corrections DIR -o OUT.dad
seanchai corpus crosscheck [FILE.dad | DIR]...  # against Wireshark's dictionary
```

Commands exit 1 on an error or a finding and 2 on a usage error.
`corpus crosscheck` exits 0 on findings.

## Documentation

- [Using the model, the CLI's JSON and the corpus][consumers]
- [Interpreted constraints: what a clause's prose says][constraints]
- [The site export][website]
- [The `.dad` format][format]
- [Extraction][extractor] and [corrections][corrections]
- [Checking traffic with a Wireshark plugin][validator]
- [Development][development]

## License

MIT, see [LICENSE][license]. The corpus contains text from 3GPP, ETSI, 3GPP2,
OMA, oneM2M and IETF documents, which stay under their publishers' terms.

[constraints]: https://github.com/sliva0/seanchai/blob/main/docs/constraints.md
[consumers]: https://github.com/sliva0/seanchai/blob/main/docs/consumers.md
[dictionary]: https://github.com/sliva0/seanchai/blob/main/docs/consumers.md#the-dictionary
[corrections]: https://github.com/sliva0/seanchai/blob/main/docs/corrections.md
[development]: https://github.com/sliva0/seanchai/blob/main/docs/development.md
[extractor]: https://github.com/sliva0/seanchai/blob/main/docs/extractor.md
[format]: https://github.com/sliva0/seanchai/blob/main/docs/dad-format.md
[license]: https://github.com/sliva0/seanchai/blob/main/LICENSE
[linter]: https://github.com/sliva0/seanchai/blob/main/docs/linter.md
[oracle]: https://github.com/sliva0/seanchai/blob/main/docs/oracle.md
[python-diameter]: https://github.com/sliva0/seanchai/blob/main/integrations/python_diameter/README.md
[validator]: https://github.com/sliva0/seanchai/blob/main/docs/wireshark-plugin.md
[versions]: https://github.com/sliva0/seanchai/blob/main/docs/consumers.md#what-the-version-covers
[website]: https://github.com/sliva0/seanchai/blob/main/docs/website.md
