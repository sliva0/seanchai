# Consumers: the model and the integrations

`seanchai` needs Python 3.12 or newer. With the corpus installed, every
snippet here runs as it stands:

```sh
pip install "seanchai[corpus]"
```

## Recipes

### Generate a dictionary

`Application.walk()` yields every member an application's commands hold, at
any depth, whichever document defines it. `Message.walk()` does the same for
one command. Cx's commands reach 104 AVPs, among them RFC 6733's
`Destination-Host`, which no table of TS 29.229 lists.

```python
import seanchai
from seanchai.corpus import Corpus
from seanchai.model import AvpFlag, Enumerated, Grouped, Model

corpus = Corpus.installed()
model = Model.build(corpus)
(cx,) = model.applications("TS 29.229", application_id=16777216)

# Record both versions: the generated output depends on both.
print(f"# seanchai {seanchai.__version__}, corpus {corpus.version}")

dictionary = {}
for member in cx.walk():
    if member.avp is not None:
        # A citing table can read one AVP two ways: keep one per identity.
        dictionary.setdefault(member.avp.identity, member.avp)
    elif member.hole is not None:
        # A name the corpus cannot complete; the hole says what it lacks.
        print(f"# skipped: {member.hole}")
    # Neither: the `* [ AVP ]` wildcard, which is grammar and not an AVP.

for (vendor_id, code), avp in sorted(dictionary.items()):
    rules = avp.flag_rules
    # M is in Must, May or Must not; or RFC 6733 leaves it to the application.
    open_m = AvpFlag.MANDATORY in rules.application_defined
    mandatory = "app" if open_m else AvpFlag.MANDATORY in rules.must
    print(vendor_id, code, avp.name, avp.data_type, mandatory)
    if isinstance(avp, Grouped):
        print("  holds", [member.name for member in avp.members])
    elif isinstance(avp, Enumerated):
        print("  values", len(avp.values))
```

### Look up one AVP

`definition` returns the defining document's reading of a name or a
`(vendor-id, code)`. `readings` returns every reading, because a citing
document's table can change the flags. `Avp.read_through` names the document
whose table did.

```python
from seanchai.model import Model

model = Model.installed()

avp = model.definition("Session-Id")
print(avp.identity, avp.data_type, avp.defined_in, avp.flag_rules.to_dict())

for reading in model.readings("Session-Id"):
    print(reading.read_through, reading.flag_rules.to_dict())

# As one document means it, which is the reading its commands hold:
print(model.resolve("TS29.229", "Session-Id"))

# A name two AVPs claim raises `ModelError`; ask by identity instead.
print(model.definition((45687, 1008)))
print(len(model.readings((0, 110))))  # RFC 4590's Digest-Qop, read two ways
```

### List an application's commands

```python
from seanchai.model import Model

model = Model.installed()

for application in model.applications("TS 29.212"):
    print(application.name, application.application_id, application.clause)
    for message in application.messages:
        kind = "request" if message.is_request else "answer"
        print(" ", message.abbreviation, message.command_code, kind)
```

## Without Python

An installed `seanchai[corpus]` answers from the command line, with no
checkout and no downloads:

```sh
seanchai show Session-Id          # the defining document's reading, and others
seanchai show 10415:601 --json    # by VENDOR:CODE
seanchai show Session-Id --document TS29.229   # as one document reads it
seanchai commands TS29.229        # code, request or answer, id, document, section
seanchai commands --application 16777216 --json
seanchai dictionary -o cx.json --application 16777216
```

`show --document REF --version V` reads an older copy of that document the
corpus holds. With `--json`, `show` and `commands` print the shapes
`dictionary` writes. All three are pydantic models in `seanchai.dictionary`,
under one `format_version`.

### The dictionary

`seanchai dictionary -o FILE` writes one compact JSON file with sorted keys.
The same corpus and options give the same bytes.

| Option | Keeps |
|---|---|
| `--document REF` | that document's applications; alone, also every AVP its tables list |
| `--application ID` | that application's commands and the AVPs they use |
| `--policy` | what becomes of [undefined names](#undefined-names): `hole` (default), `drop`, `placeholder` or `supply` |
| `--supply SIDECAR.dad` | the sidecar `--policy supply` reads |

`--document`, `--application` and `--supply` repeat. Every field is always
written, null or empty where it says nothing.

```text
format_version     1, changes when a reader would have to
seanchai_version, corpus_version, undefined_policy
documents, application_ids    what was selected; no ids is every application
applications[]     reference, application_id, clause, name, stated_in
  commands[]       name, abbreviation, command_code, is_request, flags,
                   application_id (on the wire), header_application_id,
                   defined_in, section, members[], dropped[], walk[],
                   answer_message
answer_messages[]  id, defined_in, section, read_through, members[], dropped[],
                   walk[]
avps[]             id, defining, kind (plain, grouped, enumerated), name,
                   vendor_id, code, data_type, flag_rules, defined_in, section,
                   read_through, completed_by, across_releases, supplied,
                   members[], dropped[], values[], values_source
holes[]            id, name, reference, version, missing, what it does state,
                   recorded (the reason)
value_tables[]     kind (result-codes, bits, features), avp, avp_id, reference,
                   version, vendor_id, section, page, table, application,
                   feature_list_id, rows[]
```

- A member has `name`, `presence` (`fixed`, `required`, `optional`),
  `min_occurs`, `max_occurs` (null is unbounded) and `kind`. Kind `avp` names
  an `avps[].id` in `avp`; `hole` names a `holes[].id` in `hole`;
  `placeholder` holds its block; `wildcard` is the `* [ AVP ]` line. `alias`
  is set for a `model.Alias`.
- `walk` lists every AVP `id` the command reaches, at any depth.
- An AVP `id` is `vendor:code`. A citing table can read an identity
  differently, so each further reading in the selection is `vendor:code#2`,
  `#3` and so on. `defining` marks the defining document's reading. For one
  entry per identity, take the ids without `#`.
- `values[]` entries have `kind` (`value`, `reserved`, `void`,
  `vendor-specific`), `name`, `value`, `first`, `last` and `description`. No
  dictionary may assign a `reserved` or `void` value.
- `dropped` lists what `--policy drop` removed, each naming its hole.
- `answer_message` names the `answer_messages[]` entry an answer takes with
  the E bit set ([error answers](#error-answers)); it is null for a request.
  That entry's `id` is `read_through/defined_in:section`, as
  `TS29.272/RFC6733:7.2`.
- `value_tables[]` holds the selected documents' tables; with
  `--application`, those of the documents defining the application. `avp_id`
  names the `avps[]` entry for the document's reading of `avp`, or is null
  where the selection holds none. A row has `name`, `value`, a result code's
  own `section`, and a feature's `mark` (the M/O column).

### One AVP

`seanchai show NAME --json` prints a `dictionary.Lookup`, indented:

```text
format_version, seanchai_version, corpus_version, undefined_policy
avp                the id of the reading asked for
avps[]             that reading first; then the identity's other readings, by
                   id; then every AVP their bodies name, at any depth
holes[]            what their bodies name and the corpus cannot complete
value_tables[]     those of the identity's readings, each its avp_id
```

Entries have the dictionary's shapes, and every id a member names is in the
output. Ids are numbered over this output only, so a `#2` here need not be
the dictionary's `#2`.

```json
{
  "format_version": 1,
  "corpus_version": "2026.11.11",
  "undefined_policy": "hole",
  "avp": "0:110#2",
  "avps": [
    {"id": "0:110#2", "defining": false, "name": "Digest-Qop",
     "read_through": "TS29.229", "...": "..."},
    {"id": "0:110", "defining": true, "name": "Digest-Qop",
     "read_through": "RFC4590", "...": "..."}
  ],
  "holes": [],
  "value_tables": [],
  "...": "..."
}
```

### Commands

`seanchai commands --json` prints a `dictionary.Listing`: `format_version`,
`seanchai_version`, `corpus_version` and `applications[]` as the dictionary
writes them, each command without `members`, `dropped`, `walk` and
`answer_message`.

## Installing the corpus

The library and the corpus are separate packages, released separately, so pin
each on its own:

```sh
pip install seanchai seanchai-corpus   # or "seanchai[corpus]"
```

- `corpus.Corpus.installed()` loads the installed corpus with its record of
  known holes; `installed(raw=True)` loads its raw mirror. Without the package
  it raises `corpus.CorpusNotInstalledError`.
- `corpus.Corpus.load(path)` loads another directory, file, or list of them.
  A file named twice counts once. Two files of the same document, version and
  3GPP2 revision raise `corpus.CorpusError`.
- `seanchai_corpus.CORPUS_DIR` is the data directory.
- `Corpus.version` is the corpus package's version, the date it was
  regenerated, when `installed()` loaded it, and None otherwise.
  `seanchai.__version__` is the library's.

The corpus states its format as `format` in its `corpus.toml`, and
`corpus.FORMATS` lists the formats the library reads. `installed()`, and
`load` of a directory holding `corpus.toml`, raise `corpus.CorpusFormatError`
for any other. The error names the package to upgrade: `seanchai` for a newer
corpus, `seanchai-corpus` for an older one. `corpus.toml` also holds the
[resolution rules](#resolution-across-releases). A directory without it, a
subdirectory or a list of files loads with no format check and no rules.

`Corpus.interfaces`, read from the directory's `interfaces.toml`, names the
Diameter interfaces or reference points each document specifies, or an RFC's
application: `books.interfaces.of(entry)` gives `("Gx", "Gxx", "Sd", "St",
"S15")` for TS 29.212, `()` for one with none, and None for a document the
record does not list or a corpus without one.

Every error the library raises derives from `seanchai.SeanchaiError`.

## What the version covers

`seanchai` follows semantic versioning over:

- the names in the `__all__` of `seanchai`, `seanchai.model`,
  `seanchai.corpus`, `seanchai.dictionary`, `seanchai.export`,
  `seanchai.export_schema`, `seanchai.dad` and its modules (`ast`, `parser`,
  `formatter`, `corrections`, `abnf`), `seanchai.linter`, `seanchai.oracle`,
  `seanchai.errors`, the `seanchai.downloader` package and the modules of
  `seanchai.extractor`;
- the command line's commands, options and exit statuses;
- the format version of each JSON output: the dictionary's `format_version`
  and the export's `schema_version`;
- the corpus formats it reads, `corpus.FORMATS`.

Modules whose names start with an underscore, names outside every `__all__`,
and the Python of `seanchai.cli` may change in any release. `seanchai-corpus`
is versioned by the date it was regenerated.

## The model

`model.Model` resolves a corpus. A `Message`'s members point at `Avp` objects,
a `Grouped` lists its members, an `Enumerated` its values, and every AVP has
its `(vendor-id, code)`, type, flag rules and defining document. Unlike the
AST, the model never contradicts itself.

```python
from seanchai.model import Model, RegistryKind, ValueKind

# wireshark="specifications/wireshark" adds Avp.wireshark_name.
# `Model.build(corpus)` is the same over any corpus.
model = Model.installed()
model.references()  # every document, a tuple as every query returns
model.canonical("ts 29.229")  # how it spells a reference: TS29.229
model.messages("TS29.229")  # bodies resolved; no reference: the whole corpus
model.applications("TS29.212")  # commands per application and interface
model.applications(application_id=16777216)  # one id, across documents
model.answer_message("TS29.272")  # what its answers take with the E bit set
model.avps("TS29.229")  # what a document's tables list; no reference: all
model.resolve("TS29.229", "DRMP")  # one name in one document's reading
model.definition("Public-Identity")  # the defining document's reading
model.readings("Public-Identity")  # every reading under a name
model.readings((10415, 601))  # every reading claiming an identity
model.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
model.marks("TS29.212", "AN-GW-Address")  # what each table marks about it
model.holes("TS32.299")  # what the corpus cannot complete; no reference: all
model.undefined("TS29.345")  # the names its Undefined AVP blocks declare
model.across_releases()  # what citations resolved across releases
model.registry(RegistryKind.APPLICATION_IDS, 16777216)  # TS 29.230's say
model.value_tables("TS29.272", avp="ULR-Flags")  # the numbers a document names
model.value_tables(kind=ValueKind.FEATURES)  # one kind, the whole corpus
model.feature_lists()["S6a/S6d", 1]  # a feature list, by application and list id
model.definition("ULR-Flags").value_table  # the bits, read through resolution
```

- `Model.build` and `Model.installed` are the only constructors; `Model(...)`
  raises `TypeError`. Both check the build against the corpus's
  [record of holes](#known-holes).
- A reference may be spelled "TS 29.229", "ts29.229" or "3GPP TS 29.229". One
  the corpus lacks raises `ModelError`, suggesting close ones.
- `applications` groups a document's commands by application id and clause,
  because documents share one id between interfaces (TS 29.273's SWa, STa and
  SWd).
- `Message.application_id` is the id on the wire: the header's, or, where the
  header prints none, the one the `Application Scope` block covering the
  command's clause states. `header_application_id` is what the header prints.
  `is_request` reads the R bit.
- A `Member` carries the ABNF `rule` as spelled, and `min_occurs` and
  `max_occurs` as RFC 6733 section 3.2 reads them.
- `Enumerated.values` also holds `ast.ReservedValues` and `ast.VoidValues`,
  which a validator must refuse: a void value was assigned and withdrawn, a
  reserved one never assigned. `vendor_specific` holds the ranges a validator
  must allow without names. Where the clause defines its values elsewhere,
  `values_source` holds the citation and `values` only what a correction
  supplied.
- Built with `wireshark=`, a Wireshark Diameter dictionary directory, the
  model fills `Avp.wireshark_name` and `Hole.wireshark_name`
  ([oracle.md](oracle.md#in-the-model)). `name` is always the document's
  spelling.
- Every model type has a one-line `repr` and a `to_dict()` for `json.dumps`.

The AST stays public underneath. `parser.parse(text)` reads one file and drops
`;;` comments; `parser.parse_with_comments(text)` returns them too, for
`formatter.format_spec(spec, comments)` to write back.
`parser.parse_with_layout(text)` returns a `parser.Layout` beside the tree:
each section's lines and directives, the tree path each line states and each
table row's cells, for a reader tying the tree to the file's lines.

### Holes

An `Avp` has every field set: code, type and flag rules are never `None`. A
name the corpus cannot complete is a `model.Hole` instead. Where one appears
in a body, `Member.avp` is `None` and `Member.hole` is the hole. The
`* [ AVP ]` wildcard, and a placeholder under the `PLACEHOLDER` policy, are
the only members with neither.

A `Hole` has:

- `reference`, the document that falls short;
- `missing`, the `model.Missing` fields it leaves unstated (`VENDOR_ID`,
  `CODE`, `DATA_TYPE`, `FLAG_RULES`), or `DEFINITION` when the name resolves
  nowhere, or `UNDEFINED` when an `Undefined AVP` block declares it so;
  serialized as `code`, `definition` and so on;
- `origin`, the re-used origin the corpus lacks, or `conflict`, the
  disagreeing reading, where either applies;
- the vendor, code, type and flag rules its document does state;
- `recorded`, the reason from the record of known holes.

A hole has no members or values. For those, read the AST through
`table_rows` or `corpus.Entry.spec`.

### Known holes

Seventeen names are holes, each a fact its source does not state. The
corpus's `holes.toml` records each by document, name, missing fields and a
reason citing the version, the clause and what was searched
([corrections.md](corrections.md#the-record-of-known-holes)).
`corpus.Corpus.load` reads it into `Corpus.record` for the directory holding
it directly; a file list, a subdirectory and a raw corpus have no record.

`Model.build(corpus, holes=model.HolePolicy.…)` sets which holes a build
allows:

| `holes` | A hole the record lists | A hole it does not | An entry naming no hole |
|---|---|---|---|
| `RECORDED` (default) | builds; `Hole.recorded` its reason | `IncompleteCorpusError` | `StaleHoleRecordError` |
| `NONE` | `IncompleteCorpusError` | `IncompleteCorpusError` | not read |
| `ANY` | builds; `Hole.recorded` its reason | builds | not read |

A recorded hole is still a hole: `holes()` lists it and `resolve` returns
None. Use `ANY` for a partial or foreign corpus. `unrecorded_holes()` and
`stale_record_entries()` return what the default would refuse.

The seventeen, by cause:

- A field no source states, under every policy:
  - TS 29.061's `3GPP-Session-Stop-Indicator` row states only a code.
  - TS 29.234's `Charging-Characteristics` is typed "Integer", which is no
    Diameter type.
  - TS 29.229's `Wildcarded-IMPU` states no code or flag rule. TS 29.329's
    reading is complete, and Sh's commands hold that one.
  - ETSI TS 183 020's `Privacy-Indicator` states no flag rule.
- An origin the corpus does not hold: RFC 6736 table 3 re-uses
  `Egress-VLANID` from RFC 4675, a RADIUS document.
- The twelve [undefined names](#undefined-names), holes under the default
  policy.

### Undefined names

Twelve names the documents use as members are defined nowhere:

- RFC 4004's three SPIs;
- RFC 5866's `Authorization-Session-Volume`;
- TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`;
- TS 29.154's `External-Group-Identifier`;
- TS 32.299's `Submission-Timestamp` and `Network-Element`;
- TS 29.234's `Error-Cause`;
- TS 29.061's and TS 29.561's `Delegated-IPv6-Prefix`, a RADIUS attribute of
  RFC 4818, which the corpus does not hold.

Each has an `Undefined AVP` block in its document's file, added by a
correction. `undefined(reference)` returns them as `model.Undefined`: the
name, document, clause, what the document says of the name, and every clause
whose body names it.

`Model.build(corpus, undefined=model.UndefinedPolicy.…)` chooses what the
model makes of these names:

| Policy | `resolve` | `hole` | Body member | `holes()` | `HolePolicy.NONE` |
|---|---|---|---|---|---|
| `HOLE` (default) | None | missing `undefined` | `Member.hole` | lists it | refuses |
| `DROP` | None | None | removed; `Grouped.dropped`, `Message.dropped` keep it | no | builds |
| `PLACEHOLDER` | None | None | in place, `Member.placeholder` a `model.Placeholder` | no; `placeholders()` | builds |
| `SUPPLY`, supplied | the consumer's `Avp`, `supplied` its source | None | `Member.avp` | no | builds |
| `SUPPLY`, `Alias` | the named AVP, unchanged | None | `Member.avp`, `Member.alias` the `Alias` | no | builds |
| `SUPPLY`, neither | as `HOLE` | | | | |

The policy applies only to names a block declares. `undefined_policy`
reports it; record it in generated output. `DROP` also removes required
members, such as RFC 4004's SPIs; `dropped` keeps each member's `rule`. For
a required member, use `SUPPLY`.

`SUPPLY` takes `supply=`, a mapping from a name, or from a more specific
`(reference, name)`, to one of:

- `model.Supplied`: vendor, code, type, flag rules, members for a Grouped AVP,
  values for an Enumerated one, and a required `source`. Its `Avp` names the
  block's document in `defined_in`, carries `source` in `supplied`, and
  resolves its members in the block's document.
- `model.Alias`: reads the name as an AVP the corpus completes, with a
  `source`. TS 29.336's `External-Identifier` carries an external group
  identifier on S6t and is most likely what TS 29.154 means by
  `External-Group-Identifier`; the corpus does not assume it.

```python
from seanchai.model import (
    Alias,
    AvpFlag,
    DataType,
    FlagRules,
    Model,
    Supplied,
    UndefinedPolicy,
)

model = Model.installed(
    undefined=UndefinedPolicy.SUPPLY,
    supply={
        "External-Group-Identifier": Alias(
            "TS29.336", "External-Identifier", source="our reading of TS 29.154"
        ),
        ("TS29.345", "ProSe-Query-Code"): Supplied(
            vendor_id=10415,
            code=59999,
            data_type=DataType.OCTET_STRING,
            flag_rules=FlagRules(must=frozenset({AvpFlag.VENDOR})),
            source="ACME HSS 4.2 dictionary",
        ),
    },
)
print(model.resolve("TS29.154", "External-Group-Identifier"))
print(model.resolve("TS29.345", "ProSe-Query-Code").supplied)
```

`model.supplied_from(*paths)` reads `Supplied`s from hand-authored `.dad`
sidecars: each `Grouped AVP` or `Enumerated AVP` section with its table row,
and each AVP-table row alone. It refuses, listing every such fact, a name two
sidecars supply, a row contradicting its definition's code, type or vendor,
and a V flag contradicting the vendor.

The build raises `ModelError` for:

- `SUPPLY` without `supply=`, or `supply=` under another policy;
- a key naming no block (a typo, or upstream has since defined the name);
- an `Alias` to a name the corpus does not complete, or a cycle of aliases;
- a `Supplied` claiming the `(vendor-id, code)` of an AVP the corpus defines,
  or two names' `Supplied`s claiming one identity.

### How a name resolves

In one document, a name resolves to the first of:

1. the document's own definition;
2. the origin its re-used table cites, followed recursively to the real
   definition;
3. an AVP-table row;
4. a `; Bases:` document.

Where several of one file's AVP tables list a name, the first row in file
order wins; `table_rows` returns every row. The [linter](linter.md) reports
the conflicts this order hides. Which copy of an origin answers is in
[linter.md](linter.md#resolving-an-origin) and
[below](#resolution-across-releases).

Flag rules belong to the application that uses the AVP (RFC 6733 section
4.1). When a document re-uses an AVP, flags in its own AVP tables win, each
from the first row placing it. A re-used table's M-bit column comes next
(`MUST`, `MUST-NOT`, or `-` for nothing). The origin supplies everything
else. For example, TS 29.229 table 6.3.0.1 puts M in Must for four
`Digest-*` AVPs for which RFC 4590 states no rule, and `readings` returns
both readings.

`Avp.flag_rules` and `Hole.flag_rules` are a `model.FlagRules`: the AST's
four columns plus `application_defined`. An IETF reading stating no flags has
M there (application-defined) and V in Must not (RFC 6733 sections 4.1 and
4.1.1); a vendor reading stating none stays a hole. A table row keeps the
AST's rules; compare it through `model.FlagRules.printed(row.flag_rules)`.

A grouped AVP defined elsewhere keeps the defining document's body, in that
document's sense: TS 32.299's own `Originator` is (10415, 864), but its
re-used `M2M-Information`, from oneM2M TS-0004, holds oneM2M's `Originator`,
(45687, 1008). A member the citing document also describes, with the same
`(vendor-id, code)`, is read through the citing document.

A field the first reading leaves unstated comes from the next reading in the
order, if the two agree on every field both state. If they disagree, the name
becomes a hole naming the disagreeing document. `Avp.completed_by` names the
document that filled each field: through TS 29.329, `Wildcarded-IMPU` is TS
29.229's, with code, vendor and flags from TS 29.329 table 6.3.1. A table
row's vendor is its Vendor-ID cell, or else its V flag
([linter.md](linter.md#vendor-spaces)).

### Resolution across releases

The corpus can hold several copies of a document, one per release tree.
`corpus.Corpus.resolution` picks the copy a citation means, following 3GPP TR
21.801 clauses 6.6.6.5.2–6.6.6.5.3 and ETSI SR 001 262 clause 12:

1. A specific reference, one whose entry in the citing document's references
   clause names a version or release, means that version (a release: its
   last version).
2. A non-specific reference means the newest copy in the citing document's
   major version. Outside 3GPP, it means the latest version held.
3. Failing that, a later release's copy can answer if `corpus.toml` has an
   entry with evidence that it defines the cited AVPs alike. A document that
   ended before the citing release resolves to its final version.

The `.dad` files name no versions, so the corpus's `corpus.toml` states
these facts. `Corpus.load` reads it into `Corpus.rules`, a `corpus.Rules`.
Its tables:

| Table | Says |
|---|---|
| `cited_as` | a document its citers number otherwise than its publisher ("ETSI TS 283 034" for ES 283 034) |
| `cited_version` | the version a specific reference names |
| `latest_edition` | a non-3GPP copy whose references mean the latest edition |
| `final_version` | a document that ended before the citing release |
| `cited_revision`, `stand_in` | a 3GPP2 revision a citation names, and the held revision answering for it |
| `release_stand_in` | a later release's copy answering for a release version the corpus lacks |
| `release_fill` | named fields of named AVPs that a later release states and the meant copy leaves unstated |

Maintaining entries is covered in [development.md](development.md). `load`
raises `corpus.CorpusError` for a malformed entry or one naming a copy the
corpus does not hold. Without `corpus.toml`, only the drafting rules apply.
`corpus.Corpus(entries, rules=..., record=...)` takes parsed entries, rules
and record as given.

What you get back:

- An `Avp` or `Hole` that took a field from another release's copy carries
  `across_releases`, a `corpus.CrossRelease` naming the citing and cited
  documents, the version and the `corpus.CitationRule`.
  `across_releases()` lists them all; the linter's `cross-release-origin`
  note reports them per file.
- For a `release_fill`, `Avp.completed_by` names the copy per field
  (`TS29.061 V19.1.0`) and the rule is `CitationRule.LATER_RELEASE`.
- Reference-level queries (`avps`, `holes`, `references`) read the newest
  copy of each document. An older copy answers only through a citation.
- Corpus-wide lookups (`readings`, `definition`, `avps()`) also find an
  identity only an older copy holds, where a citation reaches it, such as TS
  32.299 V11.20.0's `WLAN-Information`.

### Error answers

With the E bit set, an answer takes RFC 6733 section 7.2's
`<answer-message>` in place of its command's body.
`answer_message(reference)` returns the one `reference`'s answers take, as a
`model.AnswerMessage`: the document's own, or else the first its `; Bases:`
documents print, depth first. TS 29.229 prints its own in clause 7.3.1; TS
29.272 prints none and takes RFC 6733's. The body is read through
`reference`, and `read_through` says so.

### Marks

`marks` returns, for each row of a table with mark columns, the table's label
and clause and the row's marks per column. Each cell is a tuple of marks,
`()` for a dash, or None when blank. The document's legend gives their
meaning:

| Column | Documents | Means |
|---|---|---|
| `Acc-Type` | TS 29.212, 29.215 | the IP-CAN access types the AVP applies to, `All` or a list |
| `Applicability` | several | the supported features the AVP belongs to (blank: base functionality); in TS 29.212 and 29.215 also the function (`CC`, `PC`, `Both`, `ADC`, `ABC`) |
| `Reference-Points` | TS 29.061 table 9a | `Gi`, `Sgi` |
| `ACR`, `ACA`, `CCR`, `CCA` | TS 32.299 | whether the command uses the AVP; `()` is "not used" |

None of them names an interface. A row's interface is its table's clause.

### Value tables

`value_tables` returns the tables a document prints for a numeric AVP's
values, as `model.ValueTable`s: `kind` (`ValueKind.RESULT_CODES`, `BITS` or
`FEATURES`), `avp`, the document, clause, page, table label and `rows`. A row
is an `ast.ValueRow` with `name` and `value`, plus a result code's `section`
and `origin` where they apply and a feature's M/O `mark`. A plain
`Result-Code` table has `vendor_id` 0; any other has the file's
`; Vendor-ID:`.

`Avp.value_tables` holds the tables the reading document prints for the
name, or else its origin's; `Avp.value_table` is the first.
`resolve("TS29.229", "Experimental-Result-Code").value_tables` gives TS
29.229's codes, though the AVP is RFC 6733's. A value table is not part of
the AVP's identity and does not make a second reading: a reading from
`readings` or `avps()` carries the tables of its `read_through` document, as
`resolve` there gives them.

`feature_lists()` keys feature tables by `(application, feature_list_id)`,
spelled as the caption does. Where two documents print one list, the first
in reference order answers.

### The registry

`registry(kind, code)` returns what the corpus's registries say of a code,
as `model.Allocation`s naming the registry document, table and clause. No
`Avp`, `Message` or `Application` takes anything from it. The linter's
`registry-*` rules report where documents and registry differ.

## The export

`seanchai export -o DIR` writes the resolved corpus as JSON for the static
site and other consumers without Python. It needs no checkout or downloads.
From Python, call `seanchai.export.export_corpus(corpus, output)`;
`seanchai.export_schema` holds the shape. The layout and fields are in
[website.md](website.md#data-boundary).

## The integrations

Each target has a directory under `integrations/`. Its scripts declare their
dependencies as PEP 723 inline metadata, so `uv run` works from any
directory:

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 -o out/
```

They read the committed corpus unless `--corpus` names another.
`validate.py` checks [python-diameter](https://github.com/mensonen/diameter)
against a document; `generate.py` writes modules for it. See its
[README](../integrations/python_diameter/README.md).
