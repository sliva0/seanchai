# Consumers: the model and the integrations

## The model

The AST mirrors a file one-to-one and may contradict itself. `model.Model`
is the opposite contract: built once from a `corpus.Corpus`, it hands a
consumer a `Message` whose entries point at real `Avp` objects, a `Grouped`
that enumerates its members, an `Enumerated` with its values, and every AVP
knowing its `(vendor-id, code)`, type, flag rules and defining document.
An `Enumerated` whose clause defines its values elsewhere carries that
citation in `values_source` (TS 29.272's `Trace-Depth`: "TS 32.422 [23] for
Trace Depth"); with no values beside it the AVP is complete, not a hole.

```python
from seanchai import corpus, model

built = model.Model.build(corpus.Corpus.load([Path("dad")]))
# or with dictionary=Path("specifications/wireshark") for Avp.wireshark_name
built.messages("TS29.229")  # bodies resolved
built.applications("TS29.212")  # commands per application and interface
built.avps("TS29.229")  # a spec's dictionary view
built.resolve("TS29.229", "DRMP")  # one name in one spec's reading
built.find("Public-Identity")  # every AVP under a name
built.identified(10415, 601)  # every AVP claiming an identity
built.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
built.marks("TS29.212", "AN-GW-Address")  # what each table marks about it
built.holes("TS32.299")  # what the corpus cannot complete
```

The query set is thin on purpose: each query was written because a real
consumer needed it. `applications` groups a document's commands by
application id and the clause they sit under, since documents share one id
between interfaces (TS 29.273's SWa, STa and SWd). The id is the header's,
or, for commands whose headers print none, the one an `Application Scope`
block covering their clause states: TS 29.212's Gx, Gxx, Sd and St take
theirs from clauses 5.1, 5a.1, 5b.1 and 5c.1, applying to `5.*`, `5a.*`,
`5b.*` and `5c.*`, and TS 32.299's Rf (3) and Ro (4) split its clause 6
between `6.2.*` and `6.4.*`. `Application.name` and `stated_in` name the
block and its clause; both are None for an id the headers print. RFC
6733's RAR, STR and ASR carry the using application's id (clause 2.5), so
their group's id stays None. A `Member` carries the ABNF rule as spelled,
markers included (a struck member with no legend saying otherwise is still
a member, `rule.strikethrough` set; TS 32.299's commented-out ones are
none), and `min_occurs`/`max_occurs` as RFC 6733 §3.2 reads them: `[ X ]`
may be absent, `* { X }` appears at least once. RFC 6733 §3.2 forbids a non-zero explicit minimum on an optional rule, so the
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
where both state one — must be equal. A table row prints no vendor, so its
V flag says it (`ast.AvpTableRow.stated_vendor`, which the linter's
`duplicate-identity` reads too): V under Must-not is IETF space, vendor 0
(TS 29.229's `Digest-QoP`, code 110, is RFC 4590's; TS 29.273's
`QoS-Capability`, `QoS-Resources`, `Mobile-Node-Identifier`,
`MIP-MN-HA-SPI` and `MIP-Session-Key` are RFC 5777's and RFC 5778's), V
under Must the file's `; Vendor-ID:`, and a row stating neither infers its
file's vendor, which agrees with any. TS 29.272's re-print of
`Allocation-Retention-Priority` takes TS 29.212's flag rules this way, and
TS 29.229's re-used `Digest-*` AVPs take their Diameter types from TS
29.229's own table, since RFC 4590 is a RADIUS document. A reading that
disagrees fills nothing, nor does any after it: the name stays a hole that
names the disagreeing document, rather than become one AVP assembled from
two documents that disagree about it.

**Marks.** `marks` returns, per row of a table printing mark columns (AVP
and re-used tables alike, in file order), the table's label and clause and
the row's marks per column: a tuple of marks, `()` where the cell prints a
dash, None where it is blank. The marks keep the document's spelling,
with the note reference printed beside one (`All (NOTE 5)`, whose note
excludes 3GPP-GPRS); what they mean is the legend's, per label:

- `Acc-Type` (TS 29.212, 29.215): the IP-CAN access types the AVP applies
  to, `All` or a list (`3GPP-EPS`, `Non-3GPP-EPS`, `3GPP-GPRS`, `3GPP2`,
  `FBA`, `xDSL`).
- `Applicability`: the supported features the AVP belongs to ("AVPs marked
  with a supported feature are applicable as described in clause 5.4.1",
  TS 29.212 table 5.3.0.1 note 9; also 29.061, 29.154, 29.214, 29.215,
  29.217, 29.219, 29.368, 29.468, whose `V2X Localized User Plane` is one
  feature), and in TS 29.212 and 29.215 the function too: `CC` charging
  control, `PC` policy control, `Both`, `ADC` application detection and
  control, `ABC` application based charging (note 3). Blank is the base
  functionality.
- `Reference-Points` (TS 29.061 table 9a): `Gi`, `Sgi`.
- `ACR`, `ACA`, `CCR`, `CCA` (TS 32.299): whether the AVP is used in that
  command, `M`, `OM` or `OC` in table 7.1.0.1 (clause 7.1.0), `X` in tables
  7.2.0.1 and 7.3.1-7.5.1, `()` for the dash clause 7.1.0 reads as "not
  used", None for the four cells the document leaves blank.

None of these names an interface. A document tabulating several interfaces
gives each its own tables, so a row's interface is its table's clause: TS
29.212 marks `AN-GW-Address` `Both, Rel8, EPC-routed` for Gx in table
5.3.0.1 and `EPC-routed (See NOTE 8)` for Gxx in re-used table 5a.4.0.1.

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

**Wireshark's names.** Built with `dictionary=` a Wireshark dictionary
directory, the model fills `Avp.wireshark_name` and `Hole.wireshark_name`
with Wireshark's name for the identity (`Cx-User-Data` for TS 29.229's
`User-Data`); built without one, both are None. The dictionary is optional
and never changes `name`, which is always the document's spelling;
[oracle.md](oracle.md#in-the-model) has the lookup rule.

`Model.build(books, strict=True)` raises `model.IncompleteCorpusError`,
listing every hole, rather than build a model with any. The default is
`strict=False` because the committed corpus does not build strictly, and
every standing hole is a statement its source does not make. RFC 4072,
5447, 5777 and 6734 print no flag-rule columns and state no M or V bit in
prose (RFC 6942, which does, is read), RFC 4590 is a RADIUS document with
no Diameter types or flags, and TS 29.272's re-print of RFC 5447's
`MIP6-Agent-Info` inherits the gap. RFC 4005 and 7155 leave
`QoS-Filter-Rule`'s flag cells blank, as TS 29.389 does for three V2X rows.
TS 32.299's untyped rows are roadmap item K, TS 29.061's
`3GPP-Session-Stop-Indicator` row states only a code, and the names that
resolve nowhere are the linter's standing `unresolved-reference` cases and
re-used origins outside the corpus. The pinned list in `tests/test_model.py`
(`_STANDING_HOLES`) is the full account: the strict build's failure is
compared against it, so a hole worked off or a new one shows up as a diff.
Roadmap item N lists them by cause.

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

`generate.py` is the other direction: one module per application and
interface, whose command classes carry that document's own members and are
written the way the library writes its own — `DefinedMessage` subclasses
whose `AvpGenDef` tables reference the library's `AVP_*`, `VENDOR_*` and
grouped classes — so the library can carry them beside its merged classes.
What its dictionary lacks, or types otherwise than the document, goes to an
`additions.py` in the dictionary's shape rather than being papered over.
Holes stay in the tables with their reason; an application's id is the
model's, so a module whose document states it only in prose gets it, and
only RFC 6733's clause 8 gets `None`. The ABNF decides a class's members,
and the tables' marks are comments on them: TS 32.299's per command, the
others from the command's interface clause. The
[README](../integrations/python_diameter/README.md) covers the layout, the
additions, how the library would adopt the modules, and what its shape
cannot carry.
