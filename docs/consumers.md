# Consumers: the model and the integrations

## The model

The AST mirrors a file one-to-one and may contradict itself. `model.Model`
is the opposite contract: built once from a `corpus.Corpus`, it hands a
consumer a `Message` whose entries point at real `Avp` objects, a `Grouped`
that enumerates its members, an `Enumerated` with its values, and every AVP
knowing its `(vendor-id, code)`, type, flag rules and defining document.

```python
from seanchai import corpus, model

built = model.Model.build(corpus.Corpus.load([Path("dad")]))
built.messages("TS29.229")  # bodies resolved
built.applications("TS29.212")  # commands per application and interface
built.avps("TS29.229")  # a spec's dictionary view
built.resolve("TS29.229", "DRMP")  # one name in one spec's reading
built.find("Public-Identity")  # every AVP under a name
built.identified(10415, 601)  # every AVP claiming an identity
built.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
built.holes("TS32.299")  # what the corpus cannot complete
```

The query set is thin on purpose: each query was written because a real
consumer needed it. `applications` groups a document's commands by header
application id and the clause they sit under, since documents share one id
between interfaces (TS 29.273's SWa, STa and SWd) or print none (TS 29.212's
Gx, Gxx, Sd and St, split by clauses 5, 5a, 5b and 5c). A `Member` carries
the ABNF rule as spelled and `min_occurs`/`max_occurs` as RFC 6733 §3.2
reads them: `[ X ]` may be absent, `* { X }` appears at least once. RFC
6733 §3.2 forbids a non-zero explicit minimum on an optional rule, so the
model reads `1*2 [ X ]` as `0*2`. The AST stays public underneath: `parser.parse(text)`
reads one file into it, discarding `;;` comments, and
`parser.parse_with_comments(text)` returns the comments too, as a
`formatter.Comments` (trailing, standing and detached, each keyed by
`ast.TreePath`) that `formatter.format_spec(spec, comments)` writes back in
place.

**Resolution policy.** A name resolves, in order, to the specification's own
definition, then to the origin its re-used table cites (recursively, so an
indirect citation lands on the real definition), then to an AVP-table row,
then to a `; Bases:` document. Local-over-reused makes an *extension* mean
what the extending document says, while a plain re-print resolves through
the origin. A name tabulated in several of one file's AVP tables takes its
table facts — flag rules, and type and code when no clause defines it — from
the first row in file order; `table_rows` returns every copy, which matters
where per-interface tables disagree (TS 29.061's `3GPP-IMSI`, the linter's
`table-row-mismatch`). The model never reports the conflicts this order
papers over; run the linter for those. Vendor spaces follow the linter's
reading. Origins and bases use `corpus.Corpus.resolve`, the
match-major-take-newest rule in [linter.md](linter.md#resolving-an-origin).

**Filling through.** A field the first reading leaves unstated comes from
the next reading along the order, if the two are the same AVP saying the
same thing: every field both state — code, type, flag rules, and vendor
where both state one — must be equal. A table row's vendor is inferred from
its file's `; Vendor-ID:`, so it agrees with any. TS 29.272's re-print of
`Allocation-Retention-Priority` takes TS 29.212's flag rules this way, and
TS 29.229's re-used `Digest-*` AVPs take their Diameter types from TS
29.229's own table, since RFC 4590 is a RADIUS document. A reading that
disagrees fills nothing, nor does any after it: the name stays a hole that
names the disagreeing document, rather than become one AVP assembled from
two documents that disagree about it.

**Holes.** An `Avp` has every field: code, type and flag rules are facts some
document states, never `None`. A name the corpus cannot complete is a
`model.Hole` instead, naming the document that falls short, the fields it
leaves unstated (`code`, `data_type`, `flag_rules`), or `definition` when
the name resolves nowhere, plus the re-used origin the corpus lacks or the
disagreeing reading, if either applies. A flag-rule row with every cell
blank is unstated, not "no flags". `Member.avp` is `None` for a hole and
`Member.hole` says which; the `* [ AVP ]` wildcard is the one `None` without
a hole. A hole keeps the vendor, code, type and flag rules its document
states, but not a grouped AVP's members or an enumerated AVP's values: RFC
5777's `Classifier` is a hole with no members. A consumer that wants those
reads the AST, through `table_rows` or the file's `corpus.Entry.spec`.

`Model.build(books, strict=True)` raises `model.IncompleteCorpusError`,
listing every hole, rather than build a model with any. The default is
`strict=False` because the committed corpus does not build strictly, and
every standing hole is a statement its source does not make. RFC 4072,
4590, 5447, 5777 and 6734 print no flag-rule columns (RFC 4590, a RADIUS
document, no Diameter types either), and TS 29.272's re-print of RFC 5447's
`MIP6-Agent-Info` inherits the gap. RFC 4005 and 7155 leave
`QoS-Filter-Rule`'s flag cells blank, as TS 29.389 does for three V2X rows.
TS 32.299's untyped rows are roadmap item K, TS 29.061's
`3GPP-Session-Stop-Indicator` row states only a code, and the names that
resolve nowhere are the linter's standing `unresolved-reference` cases and
re-used origins outside the corpus. The pinned list in `tests/test_model.py`
(`_STANDING_HOLES`) is the full account: the strict build's failure is
compared against it, so a hole worked off or a new one shows up as a diff.

## The integrations

Each target gets a directory under `integrations/`; scripts carry PEP 723
inline metadata naming their dependencies, so uv supplies everything:

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 -o out/
```

### python-diameter

[python-diameter](https://github.com/mensonen/diameter) folds every use of a
command into one class, so "is this class right?" has no single answer; the
script checks one specification's claims at a time. That document's commands
must exist under the right codes, each direction's `avp_def` must cover the
ABNF's members matched by `(vendor-id, code)`, `is_required` must agree with
the brackets, and the document's own AVPs must be right — name, type,
mandatory default — in the library's global dictionary. An "extra AVP" may
be another specification's legitimate use of the same command class. The
model is built non-strictly: a hole is checked on what its document states
(RFC 4072's `EAP-Payload` has an identity but no flag rules), and one with no
`(vendor-id, code)` is reported as unchecked.

The first Cx run (library 0.9.0, which pins TS 29.229 V13.1.0) reported 94
disagreements, the sharpest being three command classes carrying RFC 4740's
IETF `SIP-Auth-Data-Item` and `SIP-Number-Auth-Items` where TS 29.229
specifies 3GPP's codes 612 and 607 — a wire-level incompatibility. Findings
against a version-13 dictionary may simply be Release 13's truth; the reader
decides what becomes an upstream issue.

That run was also the corpus's sharpest review: it found an ABNF line the
extractor silently dropped (29.229's RTR prints `RTR-Flags ]` with no opening
bracket, now input-patched) and the `Load` rows that became the linter's
`row-without-code` rule.

`generate.py` is the other direction: a package of protocol-specific
classes, one per command per application and interface with that document's
own members, over one deduplicated module of AVP definitions, meant to sit
beside the library's merged classes rather than replace them. Holes stay in
the rule tables with their reason; a document whose command headers print no
application id gets `None`. The
[README](../integrations/python_diameter/README.md) covers the layout, where
it departs from the library's conventions, and which documents lack ids.
