# The linter

`src/seanchai/linter.py` reports what a `.dad` file says that cannot all be
true. It is the counterpart to the extractor's rule: the extractor records
contradictions, the linter says them out loud.

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

The cross-file rules run against a corpus: the one `--corpus` names, or else
the installed `seanchai-corpus`
([consumers.md](consumers.md#installing-the-corpus)). `--no-corpus`, or no such
package, lints each file alone.

Errors exit non-zero; notes do not. **Error** means the file asserts two
things that cannot both be true. **Note** means something a single file
cannot judge. **Accepted** is a note the document's corrections module
acknowledges as an override its document states on purpose
([below](#acceptances)).

## Single-file rules

- `duplicate-definition`: one name defined by two clauses.
- `one-name-two-commands`: one command name with two command codes. A
  repeated message name alone is normal (TS 29.272 defines IDR, DSR and RSR
  for S6a and S7a).
- `duplicate-enum-value`: one enumerated AVP using a value or a value name
  twice.
- `duplicate-value`: one value table giving one number twice. An error: a
  number means one thing in one table.
- `value-bit-out-of-range`: a bit past what the AVP holds: 31 for an Unsigned32,
  63 where the file's own table types it Unsigned64. An error.
- `vendor-specific-overlap`: a `; VENDOR-SPECIFIC` range covering a value
  its AVP names, a range it reserves, or another vendor-specific range. An
  error: a value is named, left to vendors, or illegal, never two of them.
- `duplicate-identity`: two AVPs claiming one `(vendor-id, code)`.
- `row-without-code`: a table that declares a Code column printing a row
  without one. A note where the row has a clause and no flag or Encrypt cell,
  the whole of what its clause states (TS 29.229's `Wildcarded-IMPU`).
- `table-definition-mismatch`: a row disagreeing with the local clause that
  defines the same AVP, on code or type.
- `table-row-mismatch`: one AVP printed in two of the file's AVP tables
  with different type, flag rules or encrypt. A note: per-interface tables
  may differ on purpose. Two codes or two Vendor-ID cells are an error.
- `vendor-id-mismatch`: a definition naming a vendor other than the file's
  `; Vendor-ID:`, or naming none while the AVP table marks `V` mandatory
  or prints a Vendor-ID cell other than 0. A vendor-less definition with
  no such row is left alone: a genuine IETF-space AVP looks the same.
- `vendor-flag-mismatch`: a row whose Vendor-ID cell its V flag
  contradicts. RFC 6733 section 4.1.1 sets V exactly when the header
  carries a Vendor-ID.
- `application-scope-overlap` / `application-header-mismatch`: a command
  two `Application Scope` blocks apply to, or one whose header prints an id
  the block applying to it does not state. Errors.
- `local-and-reused`: an AVP both defined locally and listed as re-used. A
  note, since a re-print and an extension look the same from one file;
  superseded by the cross-file rules when the origin is readable.
- `member-marked-unused`: a command's ABNF member that a table's column for
  that command marks with a dash, which TS 32.299 clause 7.1.0 reads as
  "not used". A note: the ABNF is the wire format.
- `registry-range-overlap`: within one registry table, a code two rows
  allocate, two reserved ranges that overlap, or a reserved range covering
  codes a row allocates. A note.
- `undefined-avp`: one note per `Undefined AVP` block, naming the clauses
  whose bodies reference the name
  ([consumers.md](consumers.md#undefined-names)).
- `undefined-avp-unused`: a block whose name no body references. An error.
- `undefined-avp-defined`: a block for a name the file defines, tabulates
  or lists as re-used, or, with a corpus, one a `; Bases:` document
  resolves. An error: the claim is stale.
- `section-mismatch`: a row citing a clause for an AVP a block here holds
  elsewhere: TS 29.214 V19.3.0's table 5.3.0.1 cites 5.3.142 for
  `PC-Session-Recovery-Status`, which clause 5.3.81 defines. A definition, a
  re-print and a bit table hold an AVP, and a row may cite any block of its AVP
  or a clause above one. A result code or feature table holds none: TS 29.229
  tabulates `Feature-List` at clause 6.3.31 and prints its features in 7.1.1.
- `section-unknown`: an `; Applies-To:` or a bare `; Values: clause N` naming a
  clause no block sits at or under.

Both are notes, and both say what the file holds, not what the document does:
the known clauses are the `; Section:` values, a value row's clause, and their
parents. A row whose AVP no block holds is not checked, since a simple-typed AVP
has no block. Against the documents' own headings, such a check reports 1249 of
2257 citations and one is wrong, `PC-Session-Recovery-Status`, which
`section-mismatch` reports anyway. A re-used row, a registry row and `; From:`
cite documents and no clause.

A re-used row citing the file's own document is no re-use: those AVPs are
the file's own to every rule.

## Cross-file rules

With a corpus, each re-used row is resolved against the document it
cites.

- `reused-reprint` / `reused-extension` / `reused-body-differs`: what a
  local-and-reused AVP is doing, decided by comparing bodies. All notes:
  only the origin's editor knows which copy is current.
- `reused-code-conflict`: two documents giving one AVP two codes, also
  where a re-used table or a `Reprinted AVP` block prints a code of its own
  that the origin does not give. An error: an AVP is its `(vendor-id, code)`.
- `reprint-not-in-origin`: a `Reprinted AVP` block naming a document that does
  not define the AVP. An error.
- `reprint-differs`: such a block listing other members than the document it
  names. Occurrence qualifiers are not compared, since TS 29.109 prints RFC
  3588's `0*1 { Auth-Application-Id }` for what RFC 6733 writes
  `[ Auth-Application-Id ]`. A note.
- `reused-row-mismatch`: a row this file tabulates for an AVP it re-uses,
  reading its type, flag rules or encrypt differently from the origin's. A
  cell is compared where both tables declare the column and both say
  something, and a flag where both rows place it. Only M and V are
  compared, since RFC 6733 reserves the P bit. A re-used table's M-bit
  column is not compared, being the interface's own setting by design. A
  note, whose message says which side the model follows for the disputed
  flag ([consumers.md](consumers.md#the-model)).
- `reused-row-vendor-mismatch`: such a row placing the AVP in another
  vendor space than the origin does. An error.
- `reused-avp-not-in-origin`: the cited origin has never heard of it.
- `reused-origin-indirect`: the origin borrows it too. Not corrected:
  "where I got this" and "who defined this" are different claims the From
  column does not distinguish.
- `origin-not-in-corpus`: one note per file listing the origins the corpus
  could not supply.
- `cross-release-origin`: an origin resolved outside the citing file's
  release ([below](#resolving-an-origin)), one note per cited document,
  naming the rule and the evidence.
- `external-origin-not-in-corpus`: the same for origins outside 3GPP and
  IETF, apart because no download closes the gap.
- `unresolved-reference`: every AVP referenced in a message or grouped body
  must resolve to a local definition, a table row, a re-used row or a
  `; Bases:` document, or be declared by an `Undefined AVP` block. An
  error.
- `base-not-in-corpus`: a `; Bases:` document the corpus lacks; reference
  resolution is skipped for that file.

With a corpus, `duplicate-identity` also runs over re-used rows.

## The record of known holes

With a corpus, a directory holding `holes.toml`
([consumers.md](consumers.md#known-holes)) has the record linted once,
under its own path, as a default `Model.build` holds the corpus to it.

- `unrecorded-hole`: a hole the record does not list, or lists with other
  `missing` fields. An error: the corpus can no longer build by default.
- `stale-hole-record`: an entry naming no hole. An error: working a hole
  off shrinks the record.

## Registry rules

With a corpus, a file is also compared with the TS 29.230 registry the
corpus resolves for it. The registry is evidence, not a definer, so every
rule is a note, and a corpus file is corrected only where its own defining
clause supports the registry.

- `registry-avp-name`: an AVP the file defines as its own in vendor 10415
  whose code the registry allocates under another name, compared exactly,
  since a dictionary keys on it.
- `registry-avp-document`: the same AVPs, where the rows allocating the
  code cite documents and none is the file.
- `registry-reserved-code`: such an AVP whose code no row allocates but a
  reserved range covers, unless the range names the file's document.
- `registry-command-name`: a command whose code the registry allocates
  under neither the command's name nor its abbreviation.
- `registry-application-document` / `registry-application-name`: an
  application id the registry allocates to other documents, or names
  otherwise than the file's scope does.

- `registry-result-code-document`: an experimental result code the file lists
  in the registry's vendor space, where the rows allocating the code cite
  documents and none is the file.
- `registry-result-code-name`: such a code the registry allocates under another
  name, compared exactly. A plain `Result-Code` value is the IETF's, which TS
  29.230 does not hold, and a code no row allocates is left alone.

## Acceptances

A note can be a document saying deliberately what another says otherwise:
TS 29.336 clause 6.4.12 says `Serving-Node` "is originally defined in 3GPP
TS 29.173" and then prints the body T4-triggering uses. An `Accept` in the
document's corrections module ([corrections.md](corrections.md#acceptances))
acknowledges such a note, citing the clause. With a corpus, `seanchai
lint` reads the module (`--corrections`, by default `edits/corrections`)
for every file but a raw one and reports each acknowledged note as
`accepted[rule]`, counted apart in the summary and printed only with
`--show-accepted`. Loading a module executes it, so against the installed
corpus outside this repository the default directory goes unread:
`--corrections` has to name one.

A clause citation is the other case: the corpus records what is printed, so a
misprinted one stays, and its acceptance cites the real clause.

An acceptance matches one finding: its rule, its message exactly, and the
node its target selects. One matching none is a `stale-acceptance` error,
so a document that changes what it says re-opens the note. An error is
never accepted.

## Resolving an origin

A re-used row names a document, never a version. A non-specific reference
means **match the major version, then take the newest**: an 18.x document
resolves `TS29.272` against 18.x copies, the latest version in the citing
document's release, as 3GPP TR 21.801 clause 6.6.6.5.3 says. A release
boundary is where 3GPP may change what an AVP means, which is why the
corpus is one directory per release, and a citation crosses it only where
the drafting rules say which version it means
([consumers.md](consumers.md#resolution-across-releases)): a specific
reference resolves to the version it names; a non-specific reference to a
document that ended before the citing release resolves to its final
version; and an older copy whose release's last version the corpus lacks
resolves to a later release's copy only where `corpus.RELEASE_STAND_INS`
states the evidence that both define alike what the citing copy re-uses.
Each such resolution is a `cross-release-origin` note.

RFCs resolve to whatever the corpus holds, and so does a document outside
3GPP and IETF, whose versions are its publisher's. A 3GPP2 revision letter
is 3GPP2's release: a citation naming one means that revision only, and a
held copy of another answers it only where `corpus.STAND_INS` says so. TS
29.212 cites X.S0057-B, which 3GPP2 does not publish, and revision 0 V2.0
stands in. A reference the citing documents spell otherwise than the
publisher resolves through a table in `corpus.py` with one entry per
misnaming: 3GPP cites "ETSI TS 283 034", which ETSI publishes as ES 283
034, so a raw file's cell still resolves, and corrections name ES 283 034 in the
corrected files. Raw files are excluded from a corpus by default.

## Vendor spaces

An AVP's identity is `(vendor-id, code)`, and a `.dad` file supplies only
half of it in most tables. The file's own `; Vendor-ID:` supplies the other
half for local rows, except that a row whose V flag is Must-not is IETF
space, vendor 0, and a row printing a Vendor-ID cell states its own,
whatever its V flag says; `vendor-flag-mismatch` reports where the two
disagree. TS 29.229 gives 621 to its own
`Primary-Charging-Collection-Function-Name` and lists RFC 7683's
`OC-Supported-Features` at 621 too; without the vendor those would be a
false collision.

## Standing findings

Two tests in `tests/test_linter.py` pin what the committed corpus reports:
every raw file's single-file findings, and every corrected file's
cross-file notes and accepted findings. The corrected corpus has no errors.
What still reports, and why each stays:

- **`reused-reprint`, `reused-extension`, `reused-body-differs`,
  `reused-origin-indirect`.** Two documents describe one AVP, and only the
  origin's editor knows which copy is current; correcting either would
  invent an agreement. The open `reused-body-differs` notes are clauses
  saying only where the AVP was "originally defined" before printing a
  body of their own, or adding or dropping members the clause does not
  mention (TS 29.128's `Terminal-Information`, TS 29.272's
  `ProSe-Subscription-Data`, TS 29.283's `User-Identifier`, TS 29.338's
  `Serving-Node`, TS 29.234's `SIP-Auth-Data-Item`, and the ETSI
  transcriptions' re-prints of each other's and TS 29.209's values, ES 283
  026's `Reservation-Priority` stopping at seven of TS 183 017's fifteen).
  TS 29.561's indirect `External-Identifier` is more than a citation: table
  12.4-1 prints code 28, its RADIUS sub-attribute number, typed OctetString, and
  TS 29.061 re-uses the AVP from TS 29.336, code 3111, UTF8String. The row stays
  as printed and the model follows the origin.
- **`cross-release-origin`.** TS 32.299 cites TS 29.140 non-specifically,
  which reads as its final version; TS 32.299 V11.20.0's non-specific
  Release 11 references, and TS 29.210's and TS 29.234's of TS 29.229, are
  answered by Release 19 copies standing in; ES 283 034, ES 283 035 and ES 283
  026 cite TS 29.209's final version; TS 183 017 and oneM2M TS-0004 name
  releases; TS 29.212 names 3GPP2 X.S0057-B, for which revision 0 stands in; TS
  183 033 names TS 29.229 V6.6.0, for which V19.1.0 stands in; and ES 283 035's
  TS 29.329 is the latest edition, as its clause 2.1 says.
- **`origin-not-in-corpus`.** The older copies held for those citations
  cite in turn what the corpus holds at Release 19 only, and nothing
  stands in for them: TS 29.212 V11.19.0's `Trace-Data` has a body Release
  19's differs from, and no citation reaches them from oneM2M TS-0004.
  OMA-DDS-Charging_Data cites TS 32.299 and TS 29.214 by no version and its
  clause 2 does not say what that means, so neither resolves from it, and table
  11's own rows answer for what they tabulate.
- **`member-marked-unused`.** TS 32.299 table 7.1.0.1 marks
  `Error-Message` and `Failed-AVP` "-" under ACA, while clause 6.2.3's ACA
  ABNF lists both. OMA-DDS-Charging_Data table 11 marks eleven members of clause
  8.2's CCR and CCA "-".
- **`table-row-mismatch`.** TS 29.061 prints seven AVPs with M in Must not
  in table 9a (Gi/SGi) and in Must in table 10 (Gmb); TS 29.273 sets M for
  `AN-Trusted` in two tables and not a third, and types
  `Mobile-Node-Identifier` two ways. Which reading an interface uses is the
  document's to say; the model reads the first row.
- **`reused-row-mismatch`.** ES 283 034 types `Reservation-Priority`
  Unsigned32 where TS 183 017 and its own clause say Enumerated; TS 32.299
  sets M on `Feature-List` and `Feature-List-ID` where TS 29.229 forbids
  it; TS 29.229 sets M on four `Digest-*` AVPs where RFC 4590 states no
  rule. The model follows the citing tables. Where the citing clause defers
  to the origin, the row was corrected instead.
- **`registry-range-overlap`.** TS 29.230 as printed: 318 allocated twice,
  1..255 reserved over its own 100 to 102 and 110 to 134, and nested ranges.
- **`registry-avp-name`.** Table 7.1's names are patched on input to the
  defining clause's wherever the clause settles the spelling. What stays is
  no spelling the clause settles: TS 29.336's 3176 and 3177 swapped, TS
  29.283's 4513 to 4515 shifted, TS 29.338's 3315 printed with two names,
  and TS 32.299's 855, where case is all that tells
  `Service-ID` from TS 29.336's `Service-Id`.
- **`registry-avp-document`.** TS 29.329 lists nine of TS 29.229's AVPs
  among its own, each clause referring to TS 29.229; TS 29.273 defines
  `3GPP-AAA-Server-Name` (318), which the registry's first row still gives
  TS 29.234.
- **`registry-result-code-document`.** A clause listing a code the registry
  gives another document without saying so: TS 29.272's
  `DIAMETER_ERROR_USER_UNKNOWN` and `DIAMETER_ERROR_ROAMING_NOT_ALLOWED`, TS
  29.337, 29.338 and 29.345's `DIAMETER_ERROR_USER_UNKNOWN`, TS 29.345's
  `DIAMETER_ERROR_UNAUTHORIZED_SERVICE`, TS 29.128's
  `DIAMETER_ERROR_SCEF_REFERENCE_ID_UNKNOWN`, TS 29.273's
  `DIAMETER_ERROR_ILLEGAL_EQUIPMENT` and TS 29.336's
  `DIAMETER_ERROR_USER_NO_APN_SUBSCRIPTION`. A clause that does say so is
  accepted.
- **`registry-result-code-name`.** TS 29.109's `DIAMETER_ERROR_IDENTITY_UNKNOWN`
  against table 8.1.4's `DIAMETER_ERROR_IMPI_UNKNOWN`, and TS 29.283's
  `DIAMETER_ERROR_DATA OUT_OF_SYNC` against TS 29.329's
  `DIAMETER_ERROR_TRANSPARENT_DATA OUT_OF_SYNC`: no clause settles either. A
  space misprinted in a heading is corrected.
- **`registry-application-name`.** TS 29.272's VCSG scope names 16777308
  `S7a/S7d`; table 4.1 calls it "3GPP S7a".
- **`undefined-avp`.** The twelve names
  ([consumers.md](consumers.md#undefined-names)), each declared by a block
  whose reason lists what was searched. Where the document itself names the
  AVP a member means, the member was corrected instead (TS 32.299's
  `Monitored-PLMN-Identifier` and `Monitoring-Event-Report-Data`); where
  the document defines the member in prose alone, the row was inserted (TS
  29.229's `Line-Identifier`).
- **Retired documents draw no `registry-*` notes.** A Release 6 or 11 file
  resolves no Release 19 TS 29.230.

Accepted, by acceptance (`edits/corrections/<SpecRef>.py#<id>`), each
citing the clause that makes the override deliberate:

- **`reused-body-differs`**: clauses printing a format for their interface
  ("For the T6a/T6b interface, the … AVP format is specified as
  following": TS 29.128, 29.272, 29.388, 29.273), clauses listing the
  member combinations allowed (TS 29.336, 29.337, 29.338's `Serving-Node`
  and `Additional-Serving-Node`), and TS 32.299's charging bodies ("It
  contains additional 3GPP specific charging parameters").
- **`reused-extension`**: TS 32.299's `OC-OLR` ("It has been extended
  compared to the IETF RFC 7683") and TS 183 017's
  `Media-Component-Description` (table 7.3.3 NOTE 3).
- **`reused-body-differs`, for an endorsement or an interface's own events**: TS
  183 033's `SIP-Auth-Data-Item` ("is modified compared to 3GPP TS 29.229 [2] as
  follows") and ES 283 026's `Specific-Action` (clause 6.4.13's "two new
  events").
- **`reused-row-mismatch`**: TS 32.299's `Supported-Features`, whose clause
  6.5.10.3 answers a server not supporting it "as per 'M' bit set rule".
- **`registry-result-code-document`**: a result code whose clause says where it
  is defined, "This error code is defined in 3GPP TS 29.229 [4]" (TS 29.128,
  29.172, 29.173, 29.212, 29.215, 29.217, 29.273, 29.283, 29.329, 29.330,
  29.336, 29.344, 29.388, 29.389, 32.299): the document lists a code it re-uses.
- **`section-mismatch`**: TS 29.214's `PC-Session-Recovery-Status`, a misprint
  the corpus keeps as printed, whose acceptance cites the real clause, 5.3.81;
  TS 29.273's `MIP6-Agent-Info`, whose row is right and whose clause 9.2.3.6.2
  copy `TS29.273.py#mip6-agent-info-duplicate` deletes; RFC 5778's
  `MIP6-Auth-Mode`, defined in clause 6.20 with its values in clause 9.5.
- **`section-unknown`**: RFC 6942's scope over clauses 5.2 and 6, which are
  prose, and oneM2M TS-0004's clause 6.6.3, outside its Diameter annex. Each
  clause exists, and the file has no block there.
