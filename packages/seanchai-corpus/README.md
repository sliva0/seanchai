# seanchai-corpus

The corpus of [Seanchaí](https://github.com/sliva0/senchai): Diameter command
ABNFs and AVP definitions from 3GPP specifications, RFCs and a few other
documents, as `.dad` files, corrected and raw, with the record of known holes.
It holds the data and nothing else, and depends on nothing.

```sh
pip install seanchai-corpus
```

```python
import seanchai_corpus

seanchai_corpus.CORPUS_DIR  # a pathlib.Path: 3gpp/, rfc/, raw/, holes.toml, ...
seanchai_corpus.__version__  # "2026.11.2"
```

The [`seanchai`](https://pypi.org/project/seanchai/) library reads it with no
path:

```python
from seanchai import corpus, model

built = model.Model.build(corpus.Corpus.installed())
built.resolve("TS29.229", "Public-Identity")
```

The version is the date the corpus was regenerated, as `YEAR.MONTH.DAY` with no
leading zeros. The
[format](https://github.com/sliva0/senchai/blob/main/docs/dad-format.md) and
[grammar](https://github.com/sliva0/senchai/blob/main/docs/grammar.md) are
documented in the repository.

## License

MIT, see [LICENSE](LICENSE). The definitions are taken from 3GPP, ETSI, 3GPP2,
oneM2M and IETF documents, which stay under their publishers' terms.
