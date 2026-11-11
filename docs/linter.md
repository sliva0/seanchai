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
| `duplicate-definition` | error | one name defined by two clauses |
| `one-name-two-commands` | error | one command name with two command codes; a repeated message name alone is normal |
| `duplicate-enum-value` | error | an enumerated AVP using a value or value name twice |
| `duplicate-value` | error | a value table giving one number twice |
| `value-bit-out-of-range` | error | a bit past what the AVP holds: 31 for Unsigned32, 63 for Unsigned64 |
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
| `reused-code-conflict` | error | two documents giving one AVP two codes, including a code a re-used table, `Reprinted AVP` block or AVP table prints for a re-used AVP |
| `reprint-not-in-origin` | error | a `Reprinted AVP` naming a document that does not define the AVP |
| `reprint-differs` | note | a `Reprinted AVP` listing other members than its document; occurrence qualifiers are not compared |
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

Accepted findings, each cited by `edits/corrections/<SpecRef>.py#<id>`:

| Rule | Accepted for |
|---|---|
| `reused-body-differs` | clauses printing a format for their interface (TS 29.128, 29.272, 29.273, 29.388); clauses listing allowed member combinations (TS 29.336, 29.337, 29.338); TS 32.299's charging bodies; TS 183 033's `SIP-Auth-Data-Item`; ES 283 026's `Specific-Action` |
| `reused-extension` | TS 32.299's `OC-OLR`; TS 183 017's `Media-Component-Description` |
| `reused-row-mismatch` | TS 32.299's `Supported-Features` |
| `section-mismatch` | misprinted clauses kept as printed (TS 29.214's `PC-Session-Recovery-Status`, TS 29.273's `Trace-Info`); TS 29.273's `MIP6-Agent-Info`; RFC 5778's `MIP6-Auth-Mode` |
| `section-unknown` | RFC 6942's scope over prose clauses 5.2 and 6; oneM2M TS-0004's clause 6.6.3 |
