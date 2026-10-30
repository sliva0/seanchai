# The linter

`src/seanchai/linter.py` reports what a `.dad` file says that cannot all be
true. It is the counterpart to the extractor's rule: the extractor records
contradictions, the linter says them out loud.

```sh
uv run seanchai lint dad/3gpp/rel-18/*.dad
uv run seanchai lint --no-notes FILE.dad          # errors only
uv run seanchai lint --corpus dad FILE.dad        # also the cross-file rules
uv run seanchai lint --corpus dad --show-accepted FILE.dad
uv run seanchai lint --output-format concise ...  # file: severity: [rule] message
```

Errors exit non-zero; notes do not. **Error** means the file asserts two
things that cannot both be true. **Note** means something a single file
cannot judge. **Accepted** is a note the specification's corrections module
acknowledges as an override its document states on purpose
([below](#acceptances)).

## Single-file rules

- `duplicate-definition` — one name defined by two clauses.
- `one-name-two-commands` — one command name with two command codes. A
  repeated message name alone is normal (TS 29.272 defines IDR/DSR/RSR for
  S6a and S7a); TS 29.344 clauses 6.2.11/6.2.12 print 6.2.3/6.2.4's rule
  names above command 8388713.
- `duplicate-enum-value` — one enumerated AVP using a value or a value name
  twice.
- `duplicate-identity` — two AVPs claiming one `(vendor-id, code)`. TS 29.272
  clause 7.3.138 printed `Area-Scope` with `Job-Type`'s code while every name
  stayed unique.
- `row-without-code` — a table that declares a Code column printing a row
  without one. TS 29.229 and 29.329 tabulate RFC 8583's `Load` code-less in
  their own tables; corrections move it to the re-used table.
- `table-definition-mismatch` — a row disagreeing with the local clause that
  defines the same AVP, on code or type. Rows with no local clause are not
  compared.
- `table-row-mismatch` — one AVP printed in two of the file's AVP tables
  with different type, flag rules or encrypt, compared where both tables
  have the column and the cell. A note: per-interface tables may differ on
  purpose, and only the document's editor knows. Two codes are an error,
  left to `table-definition-mismatch` when a clause defines the AVP.
- `vendor-id-mismatch` — a definition naming a vendor other than the file's
  `; Vendor-ID:`, or naming none while the AVP table marks `V` mandatory. A
  vendor-less definition with no such row is left alone: a genuine IETF-space
  AVP looks exactly like it, and a re-used one belongs to its origin.
- `application-scope-overlap` / `application-header-mismatch` — a command
  two `Application Scope` blocks apply to, or one whose header prints an id
  the block applying to it does not state. Errors with no case in the corpus: the model would
  otherwise settle them quietly, taking the first block and the header's
  id.
- `local-and-reused` — an AVP both defined locally and listed as re-used.
  A note, because a re-print and an extension look the same from one file;
  superseded by the cross-file rules when the origin is readable.
- `member-marked-unused` — a command's ABNF member that a table's column
  for that command marks with a dash, which TS 32.299 clause 7.1.0 reads as
  "not used". Rows are indexed by AVP name and command column (`ACR`, `ACA`,
  `CCR`, `CCA`), AVP and re-used tables alike, and one note reports each
  table's dash against each direct member; a blank cell marks nothing, and
  `* [ AVP ]` is grammar. A note: the ABNF is the wire format, and only the
  document's editor knows which statement is meant.
- `registry-range-overlap` — within one registry table, a code two rows
  allocate, two reserved ranges that overlap, or a reserved range covering
  codes a row allocates. A note: a range reserved for a document may hold
  its codes, and which statement is meant is the registry editor's.

A re-used row citing the file's own document is no re-use: TS 29.212's Gxx,
S9, Sd and St tables list Gx's AVPs from TS 29.212, and 29.061's SGmb table
cites 29.061. Those AVPs are the file's own to every rule (their headers'
vendor-ids included), and a self-cited name the file neither defines nor
tabulates is `reused-avp-not-in-origin`, with no corpus needed; the corpus
has no case.

## Cross-file rules

With `--corpus`, each re-used row is resolved against the document it cites.

- `reused-reprint` / `reused-extension` / `reused-body-differs` — what a
  local-and-reused AVP is doing, decided by comparing bodies. All notes: only
  the origin's editor knows which copy is current. TS 29.388's
  `V2X-Subscription-Data` neither re-prints nor extends 29.272's.
- `reused-code-conflict` — two documents giving one AVP two codes, also
  where a re-used table prints a code of its own (TS 29.172 table 7.4.1-2,
  TS 32.299 tables 7.3.1-7.5.1) that the origin does not give. An error:
  an AVP *is* its `(vendor-id, code)`.
- `reused-row-mismatch` — a row this file tabulates for an AVP it re-uses,
  reading its type, flag rules or encrypt differently from the origin's
  rows, or typed otherwise than the origin's Grouped or Enumerated
  definition when no origin row types it. `table-row-mismatch`'s discipline
  across two files: a cell is compared where both tables declare the column
  and both say something, and a flag where both rows place it in a column
  (RFC 7683 puts M in neither Must nor Must not, which leaves a citing
  interface free to forbid it). Only M and V are compared: RFC 6733 clause
  4.1 reserves the P bit, so a P cell records which side of RFC 6733 a
  document was written on. Agreeing with any one origin row agrees. A
  re-used table's M-bit column is not compared, being the interface's own
  setting by design; its Type column (TS 29.172) is, against the origin's
  rows or definition. A note: a citing interface may set its own rule.
- `reused-avp-not-in-origin` — the cited origin has never heard of it.
  TS 29.283 listed `Feature-Id` from TS 29.229 (now deleted by correction).
- `reused-origin-indirect` — the origin borrows it too. TS 29.172 cites
  `Service-Selection` from 29.272, which re-uses it from RFC 5778. Not
  corrected: "where I got this" and "who defined this" are different claims
  the From column does not distinguish.
- `origin-not-in-corpus` — one note per file listing the origins the corpus
  could not supply, so the reader knows which rules stayed silent.
- `unresolved-reference` — every AVP referenced in a message or grouped body
  must resolve to a local definition, a table row, a re-used row, or a
  `; Bases:` document. `* [ AVP ]` is grammar and is skipped. A note rather
  than an error while the standing cases below exist.
- `base-not-in-corpus` — a `; Bases:` document the corpus lacks; reference
  resolution is skipped for that file rather than reporting every base AVP.

With `--corpus`, `duplicate-identity` also runs over re-used rows, since the
origin's `; Vendor-ID:` is readable then.

## Registry rules

With `--corpus`, a file is also compared with the TS 29.230 registry the
corpus resolves for it, by the rule origins resolve by. TS 29.230 allocates
codes to the documents defining them; it is evidence, not a definer, so
every rule is a note, and a corpus file is corrected only where its own
defining clause supports the registry. Without a registry in the corpus the
rules stay silent.

- `registry-avp-name` — an AVP the file defines or tabulates as its own in
  the registry's vendor space (10415) whose code the registry allocates
  under another name, compared exactly, since a dictionary keys on it; the
  message says when the two differ only in case. A name the file lists as
  re-used is its origin's.
- `registry-avp-document` — the same AVPs, where the rows allocating the
  code cite documents and none is the file. A row citing none (table 7.1's
  1530–1542) claims nothing.
- `registry-reserved-code` — such an AVP whose code no row allocates but a
  reserved range covers, unless a covering range names the file's document
  among its documents or in its purpose: TS 29.061's RADIUS-compatible 1–33
  sit silently in 1..255, "backwards compatibility with 3GPP RADIUS Vendor
  Specific Attributes (See 3GPP TS 29.061 [13], …)".
- `registry-command-name` — a command whose code the registry allocates
  under neither the command's name nor its abbreviation, the row's
  `Name-Request/-Answer` pair read as both names. The defining documents
  are not compared: a command code is the application's to re-use (TS
  29.273's SWx carries TS 29.229's Cx codes). TS 29.215's `TE-Request`
  agrees with table 5.1/4's `Trigger-Establishment-Request/Answer` through
  `TER`. No corpus case.
- `registry-application-document` / `registry-application-name` — an
  application id a header or an application scope uses that the registry
  allocates to other documents, or that a scope names otherwise than the
  registry does, less table 4.1's "3GPP " prefix. Ids the registry does not
  list are not reported: IETF ids are IANA's, and TS 29.230 lists only
  3GPP's.

## Acceptances

A note can be a document saying deliberately what another says otherwise:
TS 29.336 clause 6.4.12 says `Serving-Node` "is originally defined in 3GPP
TS 29.173" and then prints the body T4-triggering uses, with the member
combinations it allows. An `Accept` in the specification's corrections
module ([corrections.md](corrections.md#acceptances)) acknowledges such a
note, citing the clause; it changes no data. With `--corpus`, `seanchai
lint` reads the module (`--corrections`, by default `edits/corrections`)
for every file but a raw one, which the acceptances do not describe, and
reports each acknowledged note as `accepted[rule]`, citing the acceptance
(`TS29.336.py#serving-node-t4-body`). Accepted findings are counted apart
in the summary line and printed only with `--show-accepted`.

An acceptance matches one finding: its rule, its message exactly, and the
node its target selects, which must be one the finding is about. A finding
records the tree paths of its nodes (the definition whose body differs,
each row of a name the tables disagree on), so a target is told from
another definition of the same name in another clause; a rule that records
none cannot be accepted. One matching none is a
`stale-acceptance` error, naming what the finding now reads where one is
about that node, so a document that changes what it says re-opens the
note. An error is never accepted.

## Resolving an origin

A re-used row names a specification, never a version. The rule is **match
the major version, then take the newest**: an 18.x document resolves
`TS29.272` against 18.x copies and prefers 18.2.0 over 18.1.0. Nothing
resolves across a major version — a release boundary is where 3GPP may
change what an AVP means — which is also why the corpus is one directory per
release. RFCs resolve to whatever the corpus holds. Raw files are excluded
from a corpus by default; loading both copies would leave the choice to sort
order.

## Vendor spaces

An AVP's identity is `(vendor-id, code)`, and a `.dad` file supplies only
half of it in its tables: no vendor column, and clause headers omit the vendor
both for genuine IETF-space AVPs and when the document forgot. The file's own
`; Vendor-ID:` supplies the other half for local rows, except that a row
whose V flag is Must-not is IETF space, vendor 0, as the model reads it
(TS 29.229's `Digest-QoP` row is RFC 4590's code 110). TS 29.229 gives 621 to
its own `Primary-Charging-Collection-Function-Name` and lists RFC 7683's
`OC-Supported-Features` at 621 too; without the vendor those are a false
collision. Vendor 0 (the IETF space, spelled as an absent vendor in header
rules) is reconciled before comparing.

## Standing findings

Two tests in `tests/test_linter.py` pin what the committed corpus reports:
every raw file's single-file findings, and every corrected file's cross-file
notes and accepted findings. The corrected corpus has no errors; "clean"
stays distinguishable from "the rules never match". What still reports, and
why each stays:

- **`reused-reprint`, `reused-body-differs`, `reused-origin-indirect`.** Two
  documents describe one AVP, and only the origin's editor knows which copy is
  current; correcting either would invent an agreement. TS 29.330's `Load`
  goes through TS 29.229 to RFC 8583, an indirect origin, and TS 32.299's
  `3GPP2-BSID` (table 7.3.1, reference [215]) through TS 29.212 to 3GPP2
  X.S0057. Six `reused-body-differs` stay open with clauses saying only
  where the AVP was "originally defined" before printing a body of their
  own: TS 29.128's `Terminal-Information` (6.4.30), TS 29.272's
  `ProSe-Subscription-Data` (7.3.180) and `Supported-Services` (7.3.199,
  naming no origin), TS 29.336's `MME-Location-Information` and
  `SGSN-Location-Information` (8.4.34, 8.4.35), and TS 29.283's
  `User-Identifier` (7.3.8), which "is extended to contain either an MCPTT
  ID, an MCVideo ID or an MCData ID" but also drops four of TS 29.336's
  members, which the clause does not say. A seventh is TS 29.338's
  `Serving-Node` (5.3.3.6): its clause lists the member combinations
  allowed, as its siblings' do, but its body also adds `IP-SM-GW-Realm`,
  which no combination and no other line of the document names.
- **`origin-not-in-corpus`.** Every missing origin is outside 3GPP/IETF
  (ETSI TS 283 034 and TS 183 017, 3GPP2 X.S0057) or has no
  Release 18 version: TS 29.140, cited by TS 32.299 for `VAS-Id` and
  `VASP-Id`, ends at V7.0.0, and nothing resolves across a major version.
- **`member-marked-unused`**, two. TS 32.299 table 7.1.0.1 marks
  `Error-Message` and `Failed-AVP` "-" under ACA, while clause 6.2.3's ACA
  ABNF lists both (and table 6.2.3.1 marks them OC). The generator keeps
  them, following the ABNF, with the mark as a comment.
- **`table-row-mismatch`**, nine. TS 29.061 prints `3GPP-IMSI`,
  `3GPP-SGSN-Address`, `3GPP-SGSN-IPv6-Address`, `3GPP-IMEISV`,
  `3GPP-RAT-Type`, `3GPP-User-Location-Info` and `3GPP-MS-TimeZone` with M
  in M.not in table 9a (clause 16a.5, Gi/SGi) and in Must in table 10
  (clause 17.7.0, Gmb). Clause 17.7.0's "All AVPs in table 10 are
  mandatory within Gmb interface unless otherwise stated" follows "The Gmb
  specific AVPs require to be supported to be compliant": it is about
  support, not the M bit, so nothing makes the difference deliberate. TS
  29.273 sets M for `AN-Trusted` in tables 5.2.3.1/1 and 6.2.3.1/1 but not
  in 8.2.3.0/1, and types `Mobile-Node-Identifier` UTF8String in 5.2.3.1/1
  and 6.2.3.1/1 but OctetString in 7.2.3.1/1; the tables' notes explain
  M-bit overrides for re-used AVPs only. Which reading an interface uses is the document's to
  say; the model reads the first row ([consumers.md](consumers.md)).
- **`reused-row-mismatch`**, two. TS 32.299 table 7.2.0.1 types
  `Feature-List` and `Feature-List-ID` by `refer [204]` (TS 29.229) and
  prints its own flags, setting M for the charging application where
  29.229 puts it in Must not. Clause 7.2.0 refers to the origin for the
  description and gives the table "along with the AVP flag rules", but no
  clause says why charging sets M on these two, as clause 6.5.10.3 does
  for `Supported-Features` (accepted, below). Where the citing clause
  defers to the origin, the row was corrected instead: TS 29.273's three
  `RAT-Type` rows (M in Must; clauses 5.2.3.6 and 8.2.3.5 follow TS 29.212,
  whose table sets M in Must not, and the re-used tables print no M-bit
  override), and TS 32.299 table 7.1.0.1's `Acct-Multi-Session-Id` (Unsigned32 against RFC
  6733's UTF8String) and `Experimental-Result`/`-Code` (M in Must not, the
  cell RFC 6733's table gives the Error-Reporting-Host row above them).
- **`registry-range-overlap`**, six, all in TS 29.230 as printed: table
  7.1 allocates 318 (3GPP-AAA-Server-Name) in TS 29.234's block and again,
  citing nothing, in TS 29.273's, beside a note that the definition moved
  to TS 29.273 from Rel-12; reserves 1..255 for RADIUS compatibility over
  its own 100–102 (TS 29.234's WLAN AVPs), 4605..4799 for TS 29.388 over
  4700–4702 (TS 29.389's) and 4703..4799 "for TS and TS 29.389" inside it;
  table 8.1.3 reserves 4182..4200 for TS 29.272 from its own 4182, and
  8.1.4 5455..5469 for TS 29.273 from its own 5455 and 5456.
- **`registry-avp-name`**, 32. Most are the registry spelling a name
  otherwise than its defining clause (`Authorised-QoS`/`Authorized-QoS`,
  `RAN-Start-Timestamp`/`RAN-Start-Time`) or as no name at all (`"Visited
  PLMN Id"`, `"MBMS GW-Address"`, `"Media-Sub-Component AVP"`). None is
  corrected: a document is the primary source for its own AVP's name, and
  where a document prints the registry's spelling somewhere too, that is
  the document disagreeing with itself, not its defining clause supporting
  the registry. Six, in four places, are the registry being wrong, its
  defining clause saying otherwise:
  - TS 29.336 3176/3177: the registry swaps `NIA-Flags` and
    `Group-User-Identifier`; table 8.4.1-1 and clause 8.4.73's header (`<AVP
    header: 3177 10415>`) agree with each other.
  - TS 29.283 4513/4514: the registry allocates `MCVideo-ID` and
    `MC-Data-ID`, and reserves from 4515; TS 29.283 defines `Data` (4513,
    clause 7.3.22's header), `MCVideo-ID` (4514) and `MCData-ID` (4515).
  - TS 29.109 402: the registry's `NAF-Hostname`; clause 6.3.1.3 reads "The
    NAF-Id AVP (AVP code 402)".
  - TS 29.061 912: the registry's `MBMS-Session-Identity-Repetition-Number`;
    clause 17.7.15 reads "The MBMS-Session-Repetition-Number AVP (AVP code
    912)".
  Where the defining clause supports the registry, the corpus was corrected
  instead: TS 29.273 table 9.2.3.1.1/1 listed `Trust-Relationship-Update`
  at 1515 for clause 9.2.3.1.4, which is "Void", and the registry
  allocates 1515 to `Reserved`; the row is deleted (RAR-Flags bit 0 carries
  the indication, table 9.2.3.1.5/1).
  A name differing only in case is a typo, patched on input rather than
  reported: TS 29.230's table 7.1 is respelled to the defining clause's
  spelling for 22 codes (`Role-of-Node` to TS 32.299 clause 7.2.177's
  `Role-Of-Node`), and where the defining document is the one printing two
  spellings, its stray one is patched too, which is the spelling table 7.1
  copied: TS 29.128's rule names in clauses 6.4.11–6.4.12, TS 29.212's
  table E.6.3.1.1, TS 29.345's table 6.3.1-1 and four rows of TS 32.299's
  table 7.2.0.1 and PoC-User-Role's rule. One stays, because case is all
  that tells two AVPs apart: table 7.1 allocates 855 to TS 32.299's
  `Service-Id` and 3103 to TS 29.336's `Service-ID`, while TS 32.299
  defines 855 as `Service-ID` (clause 7.2.190; table 7.2.0.1 prints
  `Service-Id`, which a correction aligns with the clause). Wireshark's
  dictionary calls 855 `Service-Id` and 3103 `S6-Service-ID`, a name no
  document prints, to keep the two apart.
- **`registry-avp-document`**, ten. TS 29.329 table 6.3.1 lists nine of TS
  29.229's AVPs among its own (`Public-Identity`, `Server-Name`,
  `Supported-Features` and six more), and its clauses 6.3.9–6.3.21 refer to
  TS 29.229 for each, as the registry does; the rows stay, since they also
  state the flag rules Sh uses. TS 29.273 defines `3GPP-AAA-Server-Name`
  (318), which the registry's first row still gives TS 29.234, its second
  row nothing.
- **`registry-reserved-code`**, two. TS 32.299 defines `PSCell-Info` (1324)
  and `Nr-Cgi` (1325) in a range table 7.1 reserves "for TS 32.229", most
  likely a misprint of TS 32.299, whose ranges surround it; reported as
  printed.
- **`registry-application-name`**, one. TS 29.272's VCSG application scope,
  inserted by correction citing clause 7.2.2, names 16777308 `S7a/S7d`;
  table 4.1 calls it "3GPP S7a".
- **`unresolved-reference`**, fourteen. Seven are AVPs no document
  defines, tabulates or allocates: RFC 4004's `MIP-HA-to-MN-SPI`,
  `MIP-MN-FA-SPI`, `MIP-MN-HA-SPI` (clauses 9.4–9.6, whose prose calls them
  `MIP-MN-to-FA-SPI` and the like, defined nowhere either; erratum 1462
  renames one to another undefined name, and Wireshark carries the same dead
  end; RFC 5778's later `MIP-MN-HA-SPI`, code 491, is not cited), TS
  29.345's `ProSe-Query-Code` and `ProSe-Response-Code` (clauses 6.3.53,
  6.3.54), and TS 29.273's `NSWO-Authorization` (clause 5.2.2.1.2 prints
  only a member reference), and TS 29.154's `External-Group-Identifier`
  (the ECR body, clause A.6.6.2; table A.6.4.1-1 does not list it, and
  Wireshark has no such AVP either). Seven are members whose definition the
  document neither prints nor cites in a form the file can hold: TS
  29.229's `Line-Identifier` (clause 6.3.42 gives it ETSI's vendor 13019,
  which a table row cannot state), and six in TS 32.299's grouped bodies.
  `M2M-Information` is tabulated in table 7.5.1 citing oneM2M TS-0004
  [301], which a From cell cannot name; `Monitored-HPLMN-Identifier`
  (7.2.154I), `Submission-Timestamp` (7.2.112aA), `Network-Element`
  (7.2.66aA) and `Monitoring-Event-Report` (7.2.111AaC) resolve nowhere.
  Each has a near-name the document does define — `Monitored-PLMN-Identifier`
  (7.2.111Aa), `Submission-Time` (7.2.217), `API-Network-Service-Node`
  (7.2.20eA), `Monitoring-Event-Report-Data` (7.2.111AaD), or TS 29.336's
  `Monitoring-Event-Report` — but nothing in TS 32.299 says which, so none
  is corrected. `TCP-Source-Port` (7.2.242aaA) sits beside
  `UDP-Source-Port`, which table 7.2.0.1 refers to TS 29.212 [215] for.
  TS 29.212 defines a `TCP-Source-Port` too (5.3.129), but TS 32.299 cites
  it for only the one, and sharing a name is no citation.
  The rule promotes to an error when these are gone, which needs the
  upstream documents to move.

Accepted, by acceptance (`edits/corrections/<SpecRef>.py#<id>`), each
citing the clause that makes the override deliberate:

- **`reused-body-differs`**, fourteen. Clauses printing a format for their
  interface: `TS29.128.py#monitoring-event-configuration-t6a-body` and
  `#monitoring-event-report-t6a-body` (6.4.2, 6.4.3: "For the T6a/T6b
  interface, the … AVP format is specified as following"),
  `TS29.272.py#monitoring-event-configuration-s6a-body`,
  `#monitoring-event-report-s6a-body` and
  `#ue-reachability-configuration-s6a-body` (7.3.195–7.3.197, "For S6a/S6d
  interface"), `TS29.388.py#v2x-subscription-data-v4-body` (6.3.2, "AVP
  format when used over V4 interface") and
  `TS29.273.py#sip-auth-data-item-swx-body` (8.2.3.9, "The optional AVPs
  that are needed in SWx reference point are included in the ABNF
  representation below"). `Serving-Node` and `Additional-Serving-Node`,
  whose clauses list the member combinations allowed, naming every member
  the body adds and none it drops: `TS29.336.py#serving-node-t4-body` and
  `#additional-serving-node-t4-body` (6.4.12, 6.4.13),
  `TS29.337.py#serving-node-t4-body` and `#additional-serving-node-t4-body`
  (6.3.3, 6.3.4) and `TS29.338.py#additional-serving-node-body` (5.3.3.7).
  And
  `TS32.299.py#multiple-services-credit-control-charging-body` and
  `#used-service-unit-charging-body` (7.1.9, 7.1.14: "It contains
  additional 3GPP specific charging parameters"; the members they drop are
  struck, "not used by 3GPP").
- **`reused-extension`**, one. `TS32.299.py#oc-olr-extension` (B.2.4: "It
  has been extended compared to the IETF RFC 7683").
- **`reused-row-mismatch`**, one.
  `TS32.299.py#supported-features-charging-m`: clause 6.5.10.3 answers a
  server not supporting Supported-Features "as per 'M' bit set rule" with
  DIAMETER_AVP_UNSUPPORTED, where TS 29.229 leaves M in May.
