# The linter

`seanchai lint` reports what a `.dad` file says that cannot all be true. The
extractor records contradictions; the linter reports them.

```sh
uv run seanchai lint                              # the whole installed corpus
uv run seanchai lint packages/seanchai-corpus/src/seanchai_corpus/dad/3gpp/rel-19
uv run seanchai lint --raw DIR                    # with the raw mirror under DIR
uv run seanchai lint --no-notes FILE.dad          # errors only
uv run seanchai lint --corpus DIR FILE.dad        # against another corpus
uv run seanchai lint --no-corpus FILE.dad         # each file alone
uv run seanchai lint --show-accepted FILE.dad
uv run seanchai lint --output-format concise ...  # file: severity: [rule] message
```

The cross-file rules run against the corpus `--corpus` names, or else the
installed `seanchai-corpus`
([consumers.md](consumers.md#installing-the-corpus)). With `--no-corpus`, or
no such package, each file is linted alone.

Errors exit non-zero; notes do not.

- **Error**: the file asserts two things that cannot both be true.
- **Note**: something a single file cannot judge.
- **Accepted**: a note the document's corrections module acknowledges as
  deliberate ([acceptances](#acceptances)).

## Single-file rules

| Rule | Severity | Reports |
|---|---|---|
| `duplicate-definition` | error | one name defined by two clauses; a block with `; Reprints:` defines nothing |
| `one-name-two-commands` | error | one command name with two command codes; a repeated message name alone is normal |
| `duplicate-enum-value` | error | an enumerated AVP using a value or value name twice |
| `enum-value-out-of-range` | note | an enumerated value past 2147483647, which an Enumerated, an Integer32 on the wire, reads as negative (TS 29.214's `Media-Type` `OTHER`, 4294967295) |
| `duplicate-value` | error | a value table giving one number twice |
| `value-bit-out-of-range` | error | a bit past what the AVP holds: 31 where the file's table types it other than Unsigned64, 63 where it types it Unsigned64 or not at all |
| `vendor-specific-overlap` | error | a `; VENDOR-SPECIFIC` range covering a named value, a reserved or void range, or another vendor-specific range |
| `void-overlap` | error | a `; VOID` line covering a named value, a reserved range, or another void line |
| `duplicate-identity` | error | two AVPs claiming one `(vendor-id, code)`; with a corpus, re-used rows too |
| `row-without-code` | error, or note | a row with no code in a table with a Code column; a note when the row has a clause and no flag or Encrypt cell |
| `table-definition-mismatch` | error | a row disagreeing on code or type with the clause defining the AVP |
| `table-row-mismatch` | note, or error | one AVP in two AVP tables with different type, flags or encrypt; an error for two codes or two Vendor-ID cells |
| `vendor-id-mismatch` | error | a definition naming a vendor other than `; Vendor-ID:`, or none while the AVP table marks V mandatory or prints a nonzero Vendor-ID |
| `vendor-flag-mismatch` | error | a row whose V flag contradicts its Vendor-ID cell (RFC 6733 section 4.1.1) |
| `application-scope-overlap` | error | a command two `Application Scope` blocks apply to |
| `application-header-mismatch` | error | a header printing an id other than the one its scope states |
| `local-and-reused` | note | an AVP both defined locally and listed as re-used; the cross-file rules replace it when the origin is readable |
| `member-marked-unused` | note | an ABNF member that the table's column for the command marks `-`, "not used" (TS 32.299 clause 7.1.0) |
| `registry-range-overlap` | note | in one registry table, a code two rows allocate, or overlapping or covering reserved ranges |
| `undefined-avp` | note | each `Undefined AVP` block, naming the clauses that reference it ([consumers.md](consumers.md#undefined-names)) |
| `undefined-avp-unused` | error | an `Undefined AVP` block no body references |
| `undefined-avp-defined` | error | an `Undefined AVP` block for a name the file defines, tabulates or re-uses, or a `; Bases:` document resolves |
| `section-mismatch` | note | a row citing a clause for an AVP that a block here holds elsewhere |
| `section-unknown` | note | an `; Applies-To:` or a bare `; Values: clause N` naming a clause no block sits at or under |

`section-mismatch` and `section-unknown` check only what the file holds: the
known clauses are the `; Section:` values, value rows' clauses, and their
parents. A row may cite any block of its AVP (a definition, a re-print or a bit
table) or a clause above one. A row whose AVP no block holds is not checked.

A re-used row citing the file's own document is no re-use: every rule treats
those AVPs as the file's own.

## Cross-file rules

With a corpus, each re-used row is resolved against the document it cites
([resolving an origin](#resolving-an-origin)).

| Rule | Severity | Reports |
|---|---|---|
| `reused-reprint` | note | a local-and-reused AVP whose body matches the origin's |
| `reused-extension` | note | one whose body adds members to the origin's |
| `reused-body-differs` | note | one whose body lacks members of the origin's, or is another kind of AVP |
| `reused-code-conflict` | error | two documents giving one AVP two codes, including a code a re-used table, reprinted rule or AVP table prints for a re-used AVP |
| `reprint-not-in-origin` | error | a `Grouped AVP` whose `; Reprints:` names a document that does not define the AVP |
| `reprint-differs` | note | such a block listing other members than its document; occurrence qualifiers are not compared |
| `reused-row-mismatch` | note | a tabulated re-used AVP whose type, M or V flag, or encrypt differs from the origin's |
| `reused-row-vendor-mismatch` | error | such a row placing the AVP in another vendor space |
| `reused-avp-not-in-origin` | error | an origin that neither defines, tabulates nor re-uses the AVP |
| `reused-origin-indirect` | note | an origin that re-uses the AVP from a third document |
| `result-code-not-in-origin` | error | a result code listed from a document that does not list it |
| `result-code-origin-name` | note | a result code its origin names otherwise |
| `result-code-origin-indirect` | note | a result code its origin lists from a third document |
| `origin-not-in-corpus` | note | one per file, listing the origins the corpus could not supply |
| `external-origin-not-in-corpus` | note | the same, for origins outside 3GPP and IETF |
| `cross-release-origin` | note | an origin resolved outside the citing file's release, or a field a later release's copy fills in, one per cited document |
| `unresolved-reference` | error | a member that is no local definition, table row, re-used row, `; Bases:` AVP or `Undefined AVP` |
| `base-not-in-corpus` | note | a `; Bases:` document the corpus lacks; reference resolution is skipped for the file |

The three `reused-*` body notes stay notes because only the origin's editor
knows which copy is current. `reused-row-mismatch` compares a cell only where
both tables have the column and both say something; it skips the P bit, which
RFC 6733 reserves, and a re-used table's M-bit column, which is the interface's
own setting. Its message says which side the model follows
([consumers.md](consumers.md#the-model)).

## Information elements

An `Information Elements` block, or a `Command Result Codes` block under the
same `elements-*` rules, is held to the command it describes, the file's
own, else the document its `; From:` names, else a `; Bases:` document's,
as the model finds it
([grammar.md](grammar.md#information-elements)). Without a corpus a command
the file does not print is not judged.

| Rule | Severity | Reports |
|---|---|---|
| `elements-unattached` | note | a table naming no command; a correction names the one it describes |
| `elements-command-unknown` | error | a command neither the file nor the documents it cites for it print, or none at the clause the table names |
| `elements-command-ambiguous` | error | a command the file prints for several applications, the table naming none, or more than once under the one application, the table naming no clause |
| `element-unmapped` | note | a row whose mapping cell names no AVP, kept as printed |
| `element-not-in-command` | note | a row mapping an AVP the command's body, or the grouped AVP's the table describes, does not hold |
| `element-required-in-abnf` | note | an AVP the body requires (`{ }` or `< >`) that a row gives category O or C, or TS 32.299's OM or OC |
| `element-optional-in-abnf` | note | an AVP the body makes optional (`[ ]`) that a row gives category M |
| `element-unused-in-abnf` | note | an AVP the command's body holds that a TS 32.299 row marks not used (`-`) |
| `element-misplaced` | error | a row set off more than one level under the row above it |
| `result-code-undefined` | note | a code a Command Result Codes table lists that neither the file nor, with a corpus, any document's result-code tables define |

A row set off under a grouped AVP's row (TS 32.299's) is held to that AVP's
body as the file reads it, its own or the one of the document its re-used
rows name or a base's, and not judged where the corpus has none. A row
marked not used, and every row under it, is compared with nothing else: its
member is struck from the command's body, and a grouped AVP's body serving
request and answer alike holds members one of them does not use ("Not used
in CCR").

A row offering one of several AVPs ("Result-Code / Experimental-Result") is
not compared, since its category is the choice's. The category notes stay
notes: the table states what a command needs in a procedure, the ABNF what
the wire carries, and documents differ on purpose (TS 29.283 marks
`User-Identifier` M where its DPR's ABNF has `[ User-Identifier ]`). Each is
countable by rule and acceptable through `Accept` like any note.

## Interpreted constraints

An `Interpreted Constraints` block ([constraints.md](constraints.md)) is held
to what the documents print. Types, values and bits come from the file, and
with a corpus from the document its re-used row cites and its bases; one no
document read states is not judged.

| Rule | Severity | Reports |
|---|---|---|
| `constraint-avp-unknown` | error | a name the block constrains, scopes or conditions on that the file does not hold |
| `constraint-command-unknown` | error | a `; Command:` the file does not print, or prints for several applications with no `; Application-ID:`, or more than once for one with no `; Command-Section:`, or not at the clause it names |
| `constraint-not-member` | error | an AVP, or one a rule reads, that the printed body of its command or grouped AVP does not hold, or a `request/` name the request's body does not; a member a `members` rule names that the grouped AVP's body does not hold |
| `constraint-type-mismatch` | error | a rule the AVP's type cannot meet: a range or `values` on an OctetString, a codec or a registered element for another type, an octet length on an integer, `bits` on neither an unsigned integer nor an OctetString, `members` on no grouped AVP; a condition testing a value or a bit of an AVP holding none, or a bit past its width; `equals`, or a condition's value read from another AVP, comparing AVPs of two types |
| `constraint-request-unknown` | error | a rule reading the request (`request/`) in a block scoped to a request, or to an answer whose request the file does not print under its application, prints more than once there with no `; Request-Section:`, or does not print at the clause that names |
| `constraint-value-unknown` | error | a condition naming a value or bit the AVP's values, result codes or bit table do not name |
| `constraint-contradiction` | error | rules on one AVP in one place that cannot all hold: two codecs, lengths or ranges leaving nothing, a length beyond its codec's, an exclude covering its range, a bit both set and clear or set beside `only` others |
| `constraint-element-unknown` | note | an `encoding element` rule naming an element the element registry has no entry for, which nothing checks ([constraints.md](constraints.md#elements)) |

Rules in one place are a block's with those of every block for the same AVP,
scope and those holding wherever the document reads it.

`seanchai lint FILE.dadx` checks a document's interpretations file
([constraints.md](constraints.md#the-interpretations-file)), and a directory
named in SOURCES its `.dadx` files too. Reading it checks its syntax, its
rules, its ids and its clause order. With a corpus, each copy of the document
the corpus holds is read with the file's blocks whose range spans it in place
of its own, and these rules run over them; a finding is reported under the
file and the copy, `TS29.272.dadx (in 29272-j60.dad)`, its message opening
with the block's line.

## The record of known holes

With a corpus, a directory holding `holes.toml`
([consumers.md](consumers.md#known-holes)) has the record linted once, under
its own path.

| Rule | Severity | Reports |
|---|---|---|
| `unrecorded-hole` | error | a hole the record does not list, or lists with other `missing` fields; the corpus no longer builds by default |
| `stale-hole-record` | error | an entry naming no hole |

## Registry rules

With a corpus, each file is compared with the TS 29.230 registry the corpus
resolves for it. The registry is evidence, not a definition, so every rule is
a note. A file is corrected only where its own defining clause supports the
registry. Names are compared exactly.

| Rule | Severity | Reports |
|---|---|---|
| `registry-avp-name` | note | an AVP the file defines in vendor 10415 whose code the registry allocates under another name |
| `registry-avp-document` | note | such an AVP whose allocating rows cite other documents only |
| `registry-reserved-code` | note | such an AVP whose code no row allocates but a reserved range covers, unless the range names the file's document |
| `registry-command-name` | note | a command whose code the registry allocates under neither its name nor its abbreviation |
| `registry-application-document` | note | an application id the registry allocates to other documents |
| `registry-application-name` | note | an application id the registry names otherwise than the file's scope |
| `registry-result-code-document` | note | an experimental result code the file lists as its own whose allocating rows cite other documents only |
| `registry-result-code-name` | note | such a code the registry allocates under another name |

A result code the file lists from another document is held to that document
instead. A plain `Result-Code` value is the IETF's and is not checked. A file
of Release 6 or 11 resolves no Release 19 TS 29.230 and draws no registry
notes.

## Acceptances

An acceptance marks a note as deliberate. Write it as an `Accept` in the
document's corrections module, citing the clause that makes the override
deliberate ([corrections.md](corrections.md#acceptances)). For example, TS
29.336 clause 6.4.12 says `Serving-Node` "is originally defined in 3GPP TS
29.173" and then prints its own body.

With a corpus, `seanchai lint` reads the modules in `--corrections` (by default
`edits/corrections`) for every file but a raw one. An acknowledged note is
reported as `accepted[rule]`, counted apart in the summary and printed only
with `--show-accepted`. Loading a module runs it, so against an installed corpus
outside this repository the default directory is not read; pass
`--corrections` to read one.

An acceptance matches one finding by rule, exact message and target node. One
matching nothing is a `stale-acceptance` error, so a document that changes
re-opens the note. Errors cannot be accepted.

## Resolving an origin

A re-used row names a document, not a version. The linter resolves it to the
newest copy in the citing document's release: an 18.x document resolves
`TS29.272` to the latest 18.x copy (3GPP TR 21.801 clause 6.6.6.5.3). The
corpus keeps one directory per release because a release is where 3GPP may
change what an AVP means. A citation crosses a release only where the drafting
rules say which version it means
([consumers.md](consumers.md#resolution-across-releases)):

- A specific reference resolves to the version it names.
- A non-specific reference to a document that ended before the citing release
  resolves to its final version.
- An older copy whose release's last version the corpus lacks resolves to a
  later release's copy only where a `release_stand_in` entry in `corpus.toml`
  gives evidence that both define alike what the citing copy re-uses.
- A `release_fill` entry lets a later release's copy supply named fields the
  citation's own copy leaves unstated, for named AVPs.

Each such resolution is a `cross-release-origin` note naming its entry, such as
`(corpus.toml, release_stand_in)`. Every entry keyed by a citing document
names the copy whose references clause it read, `citing_version`, and answers
for that copy alone. The rules that apply are those of the corpus being linted:
a directory holding its `corpus.toml`, not a file list or a subdirectory.

RFCs resolve to whatever the corpus holds, and so does a document outside 3GPP
and IETF. A 3GPP2 revision letter acts as a release: a citation naming a
revision means that revision, and another revision answers only through a
`stand_in` entry. A reference the citing documents misspell resolves through a
`cited_as` entry: 3GPP cites "ETSI TS 283 034", which ETSI publishes as ES 283
034. Raw files are excluded from a corpus by default.

## Vendor spaces

An AVP's identity is `(vendor-id, code)`, and most tables print only the code.
A local row takes the file's `; Vendor-ID:`, except that a row with V under
Must not is vendor 0, and a row with a Vendor-ID cell uses that cell.
`vendor-flag-mismatch` reports where the cell and the V flag disagree. Without
the vendor, TS 29.229's own `Primary-Charging-Collection-Function-Name` and RFC
7683's `OC-Supported-Features`, both code 621, would collide.

## Standing findings

The corrected corpus has no errors. Two tests in `tests/test_linter.py` pin
what it does report: every raw file's single-file findings, and every corrected
file's cross-file notes and accepted findings. The notes below stay because
correcting them would invent something the documents do not say.

| Rule | What stays | Why |
|---|---|---|
| `reused-reprint`, `reused-extension`, `reused-body-differs`, `reused-origin-indirect` | two documents describing one AVP, such as TS 29.272's `ProSe-Subscription-Data` | only the origin's editor knows which copy is current |
| `cross-release-origin` | citations answered by a final version, a named release or version, or a stand-in, such as TS 32.299's of TS 29.140 | each resolution rests on an entry in `corpus.toml` |
| `origin-not-in-corpus` | what the older copies cite, held at Release 19 only; OMA-DDS-Charging_Data's unversioned citations | nothing stands in for them |
| `member-marked-unused` | TS 32.299 table 7.1.0.1's `Error-Message` and `Failed-AVP` under ACA; eleven members in OMA-DDS-Charging_Data table 11 | the ABNF is the wire format |
| `table-row-mismatch` | TS 29.061 tables 9a and 10; TS 29.273's `AN-Trusted` and `Mobile-Node-Identifier` | per-interface tables may differ; the model reads the first row |
| `reused-row-mismatch` | ES 283 034's `Reservation-Priority`; TS 32.299's `Feature-List`; TS 29.229's `Digest-*` | the model follows the citing table; where the citing clause defers to the origin, the row is corrected instead |
| `registry-range-overlap` | TS 29.230 as printed | the registry overlaps itself |
| `registry-avp-name` | names in TS 29.230 table 7.1 no defining clause settles, such as TS 29.336's 3176 and 3177 swapped | other names are patched or corrected |
| `registry-avp-document` | TS 29.329's nine TS 29.229 AVPs; TS 29.273's `3GPP-AAA-Server-Name` | the registry and the documents disagree |
| `registry-result-code-document` | codes a clause lists as its own that the registry gives another document, such as TS 29.272's `DIAMETER_ERROR_USER_UNKNOWN` | the clause does not say the code is another's ([dad-format.md](dad-format.md#design)) |
| `registry-result-code-name` | TS 29.109's `DIAMETER_ERROR_IDENTITY_UNKNOWN`; TS 29.283's `DIAMETER_ERROR_DATA OUT_OF_SYNC` | no clause settles the name |
| `registry-application-name` | TS 29.272's `S7a/S7d` for 16777308, "3GPP S7a" in table 4.1 | names differ |
| `undefined-avp` | the names defined nowhere ([consumers.md](consumers.md#undefined-names)) | each block's reason lists what was searched |
| `element-optional-in-abnf`, `element-required-in-abnf` | 82 and 5 rows, TS 29.273's 58 the most, most a `User-Name` its tables give M where the ABNF has `[ User-Name ]`; TS 32.299's CCR profiling TS 29.212's QoS-Information members | the table and the ABNF say different things |
| `element-not-in-command` | 36 rows, as TS 29.172's `Age-of-Location-Estimate` in PLA and TS 29.273's `Transport-Access-Type` in STa's DER | the table lists what the body does not |
| `element-unmapped` | 68 cells, 36 of them TS 29.234's | most print a name with a space or another's spelling; a correction may name the AVP |

Accepted findings, each cited by `edits/corrections/<SpecRef>.py#<id>`:

| Rule | Accepted for |
|---|---|
| `reused-body-differs` | clauses printing a format for their interface (TS 29.128, 29.272, 29.273, 29.388); clauses listing allowed member combinations (TS 29.336, 29.337, 29.338); TS 32.299's charging bodies; TS 183 033's `SIP-Auth-Data-Item`; ES 283 026's `Specific-Action` |
| `reused-extension` | TS 32.299's `OC-OLR`; TS 183 017's `Media-Component-Description` |
| `reused-row-mismatch` | TS 32.299's `Supported-Features` |
| `section-mismatch` | misprinted clauses kept as printed (TS 29.214's `PC-Session-Recovery-Status`, TS 29.273's `Trace-Info`); TS 29.273's `MIP6-Agent-Info`; RFC 5778's `MIP6-Auth-Mode` |
| `section-unknown` | RFC 6942's scope over prose clauses 5.2 and 6; oneM2M TS-0004's clause 6.6.3 |
| `elements-unattached` | TS 29.234's 45 element tables and its result codes table 6.3.3.3, an old copy held for citations; TS 29.328 table 7.1.1, User-Identity's content, which four commands carry |
