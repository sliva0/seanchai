# The linter

`src/seanchai/linter.py` reports structural inconsistencies in a parsed `.dad`
file. It is the counterpart to the rule the extractor works under: the
extractor records what a specification says, *including* where the document
contradicts itself, and this is the layer that says so out loud rather than
resolving it silently.

```sh
uv run seanchai lint dad/3gpp/rel-18/*.dad
uv run seanchai lint --no-notes FILE.dad          # errors only
uv run seanchai lint --corpus dad FILE.dad        # also the cross-file rules
uv run seanchai lint --output-format concise ...  # one greppable line per finding
```

Errors exit non-zero; notes do not. The default output groups findings under
their file with colored severities and ends with a summary line; `concise`
prints the older `file: severity: [rule] message` lines, one per finding, for
grep and scripts — the finding quotes later in this document use that shape.

There are two layers. Without `--corpus` only the single-file rules run, and
they are careful to decline anything that needs a second document. With
`--corpus` the re-used AVPs are resolved against the other files it names and
the [cross-file rules](#cross-file-rules) run as well — including in place of
the single-file findings they supersede.

## Severity

- **error** — the file asserts two things that cannot both be true, whoever is
  at fault: two AVPs with one identity, a table row disagreeing with the clause
  it points at.
- **note** — something worth knowing that a single file cannot judge.

The distinction exists because one of the rules is genuinely not a defect. An
AVP both defined locally *and* listed as re-used may be a specification
re-printing another's AVP so a reader need not fetch the other document, or
*extending* it with fields of its own. TS 29.272 does this nine times. Which
case a given one is cannot be decided from that file alone — it needs the
origin's definition to compare against — so the single-file layer only reports
that the situation exists and the [cross-file rules](#cross-file-rules) say
which it is. When 29.344 joined the corpus the answer for
`ProSe-Subscription-Data` turned out to be neither: 29.272's copy is *missing*
two of the members 29.344 lists.

## Single-file rules

- `duplicate-definition` — one name defined by two clauses.
- `one-name-two-commands` — one command name carrying two command codes. Kept
  apart from `duplicate-definition` because a repeated *message* name is
  normal: TS 29.272 defines IDR/DSR/RSR once for S6a and once for S7a, same
  name, same code, two application ids. Two codes is the part that cannot be
  true, and TS 29.344 clauses 6.2.11/6.2.12 print 6.2.3/6.2.4's rule names
  above command 8388713.
- `duplicate-enum-value` — one enumerated AVP using a value, or a value name,
  twice.
- `duplicate-identity` — two AVPs claiming one `(vendor-id, code)`. Not the
  same rule as duplicate names, and the corpus is why: TS 29.272 clause 7.3.138
  printed `Area-Scope` with `Job-Type`'s code, so two differently-named AVPs
  shared an identity while every name in the file stayed unique.
- `row-without-code` — a table that declares a Code column printing a row
  without one. An AVP is its `(vendor-id, code)`, so a code-less row describes
  nothing a message could carry. Both real cases are one editorial slip: TS
  29.229 and TS 29.329 tabulate `Load` code-less among their own AVPs while
  their prose defines it only by reference to RFC 8583 — a re-used AVP printed
  in the wrong table, which the corrections move to the right one. Tables that
  carry no Code column at all are not checked; the missing column is the
  document's layout, not a claim about any one AVP. (RFC 7155's flag tables
  were the standing example until the `prose-avp-codes` quirk started
  completing their rows from the defining clauses — see
  [extractor.md](extractor.md#quirks).)
- `table-definition-mismatch` — an AVP-table row disagreeing with the clause
  that defines the same AVP, on code or on type. A row with no local clause is
  not compared: most rows are AVPs defined elsewhere, and comparing against
  nothing would report every one of them.
- `vendor-id-mismatch` — a definition whose vendor-id disagrees with the file's
  `; Vendor-ID:`, either by naming a different vendor or by naming none while
  the AVP table requires the `V` flag. See below for why the second half needs
  the table.
- `local-and-reused` — the note above. Superseded by the cross-file rules
  whenever the origin can actually be read.

## Cross-file rules

These need `--corpus`, and each of them is a question the single-file layer
explicitly refuses to guess at.

- `reused-reprint` / `reused-extension` / `reused-body-differs` — what an AVP
  both defined locally *and* listed as re-used is actually doing, decided by
  comparing bodies with the origin's definition. Identical is a re-print, a
  strict superset is an extension, and anything else is reported as exactly
  what it adds and omits. All three are notes: a body that differs is a fact
  about two documents rather than a defect in this one, and only the origin's
  editor knows which is current.
- `reused-code-conflict` — the same AVP given two codes by two documents. The
  one thing here that is not a judgement call, because an AVP *is* its
  `(vendor-id, code)`: two codes are two AVPs and one document is wrong.
- `reused-avp-not-in-origin` — an AVP the cited origin has never heard of.
  TS 29.283 lists `Feature-Id` as re-used from TS 29.229, which defines
  `Feature-List-ID` and no `Feature-Id`; neither Wireshark's dictionary nor
  mensonen/diameter has such an AVP either.
- `reused-origin-indirect` — the origin has the AVP, but is borrowing it too.
  TS 29.172 cites `Service-Selection` from TS 29.272, which carries it as
  RFC 5778's. A note, not an error: the AVP is real and the citation just names
  a middleman.
- `origin-not-in-corpus` — origins the corpus could not supply, so the reader
  knows which rules stayed silent for lack of input rather than for lack of
  problems. One note per file listing all of them, because 29.272 alone cites
  nineteen origins and a Rel-18 corpus with no RFC extractor cannot resolve a
  single RFC.
- `unresolved-reference` — phase two's rule, enforceable now that `; Bases:`
  names the document supplying `Session-Id`, `Origin-Host` and the other
  base-protocol AVPs no re-used table cites: every AVP referenced in a message
  or grouped body resolves to a local definition, an AVP-table row, a re-used
  entry, or a base document. The trailing `* [ AVP ]` is RFC 6733's any-AVP
  wildcard — grammar, not a reference — and is skipped rather than resolved to
  an AVP named `AVP`. A note rather than an error for now: the corrected
  corpus still carries 5 of them, every one a reference to an AVP no document
  defines, which no correction can repair (see
  [standing findings](#standing-findings-and-why-each-one-stays)).
- `base-not-in-corpus` — a `; Bases:` document the corpus could not supply.
  Reference resolution is skipped entirely for that file rather than reporting
  every base-protocol AVP as unresolved: the document is fine, the corpus is
  incomplete, and a hundred spurious findings would bury the real ones.

## Resolving an origin

A re-used row names a specification and not a version — `TS29.272`, never
`TS29.272 V18.6.0` — so a run that loads several files has to choose one. The
rule is **match the major version, then take the newest**: an 18.x document
resolves `TS29.272` against 18.x copies of 29.272, and reads 18.2.0 in
preference to 18.1.0 when both are present.

Nothing resolves across a major version. A release boundary is exactly where
3GPP is entitled to change what an AVP means, so checking a Rel-18 document
against a Rel-19 definition would report differences that are not errors. This
is also why the corpus is one directory per release — the version rule and the
directory layout say the same thing.

RFC numbers have no release axis: an RFC number identifies one immutable
document, so it resolves to whatever the corpus holds.

An origin the corpus does not hold resolves to nothing, which is a gap in the
corpus rather than a defect in the document. The rules that needed it are
skipped and the single-file findings they would have superseded are kept, so a
partial corpus is useful rather than an error. Raw files are excluded from a
corpus by default: a corpus holding both copies of one specification would hold
two documents that disagree on purpose and share a version number, leaving the
choice between them to whichever sorted first.

## Vendor spaces

`duplicate-identity` compares `(vendor-id, code)` pairs, and the rest of a
`.dad` file supplies only half of that. AVP tables have no vendor column, and a
clause header omits the vendor both when the AVP really is IETF-space and when
the document simply forgot.

TS 29.229 is the case that shows why it matters. Its AVP table gives code 621
to `Primary-Charging-Collection-Function-Name` **and** to
`OC-Supported-Features`, and 623 to `User-Authorization-Type` **and** to
`OC-OLR`. Those are not collisions: the second of each pair is an RFC 7683 AVP
in the IETF space, while the first is 3GPP's, vendor 10415. A duplicate-code
check over rows alone reports two false positives on the very first file it
reads.

The missing half comes from the file's own `; Vendor-ID:` directive, which states
the vendor-id its AVPs are defined in. The extractor writes it — 3GPP documents
are 10415, RFCs are 0 — and a hand-authored file states its own, which is how a
vendor extension gets its id in without anything else needing to know about it.
Vendor 0 is the IETF space, which the wire format spells as an absent vendor-id
and `.dad` as no vendor in a header rule; the two spellings are reconciled
before anything is compared.

An AVP the file merely **re-uses** belongs to the origin's vendor space, and
only the origin document states that. So those rows are skipped by the
single-file rule: within one file, two re-used AVPs sharing a code may or may
not collide, and nothing present can decide it. With `--corpus` the objection
goes away — the origin's own `; Vendor-ID:` is readable — and the identity
check is re-run over every row rather than the local ones only.

`vendor-id-mismatch` reads the same directive from the other side. A clause
header that names a vendor-id and disagrees with `; Vendor-ID:` is
straightforward. A clause header that names *no* vendor-id is not: RFC 5447's
`MIP6-Agent-Info` and 3GPP's `WLAN-offloadability` are both written
`< AVP header: nnn >` in TS 29.272, and one of them is right. Two other things
in the file tell them apart. `MIP6-Agent-Info` is listed as re-used, so its
vendor belongs to RFC 5447 and this file is not asserting anything about it.
`WLAN-offloadability` is not, and clause 7.3.181 defines it while table 7.3.1/1
marks its `V` flag mandatory — the document says in one place that the AVP
carries a vendor-id and in another that it has none. That contradiction is the
finding; a vendor-less definition with no such row is left alone, because a
genuinely IETF-space AVP looks exactly like it.

## What the corpus reports today

Eighteen 3GPP specifications and sixteen RFCs, each committed raw and corrected.
The raw files carry their documents' own mistakes and the corrected files clear
them, which is what makes "the corrected corpus is clean" mean anything at all
— a corpus that were clean because the rules never matched would look identical
otherwise. Between them the raw files exercise every single-file rule:

| file | reports |
|------|---------|
| `29172-i10.raw.dad` | `duplicate-identity` — clause 7.4.45 names the AVP `Periodic-LDR-Info` while the table and both ABNFs say `Periodic-LDR-Information` at code 2540 |
| `29128-i00.raw.dad` | two `duplicate-identity` findings — the two rule names spell `Number-of-UE-Per-Location-*` while their headings, table rows and references spell `Number-Of-UE-Per-Location-*` |
| `29272-i60.raw.dad` | `duplicate-identity`, `table-definition-mismatch` (the `Area-Scope` case) and `vendor-id-mismatch` (`WLAN-offloadability`) |
| `29344-i10.raw.dad` | `one-name-two-commands`, twice — clauses 6.2.11/6.2.12 print 6.2.3/6.2.4's rule names above command 8388713 |
| `29345-i00.raw.dad` | two `duplicate-identity` and six `table-definition-mismatch` findings — one capitalization mismatch, three copied AVP codes and three AVPs whose table type contradicts their grouped rules |
| `29388-i00.raw.dad` | `duplicate-definition`, `duplicate-identity` and `table-definition-mismatch`, all from clause 6.3.10 re-printing 6.3.3's rule name |
| `29336-i20.raw.dad` | `duplicate-definition` and two `duplicate-identity` findings — clause 8.4.36 prints a second, S6t-specific body for 6.4.2's `User-Identifier` at the same code, and clause 8.4.30 lowercases `Scheduled-Communication-Time` against its own table |
| `29338-i20.raw.dad` | `duplicate-identity` — clause 6.3.3.13's AVP format misprints both the name (`SMS-MI-Correlation-ID` for `SMSMI-Correlation-ID`) and the code (SM-RP-MTI's 3308 for 3324) |
| `29212-i20.raw.dad` | eight `vendor-id-mismatch` findings — grouped-AVP clauses printing `<AVP header: nnn>` with no vendor-id while the table marks V mandatory |
| `29214-i40.raw.dad` | `duplicate-enum-value` (Specific-Action labels values 0 and 5 both "Void") and ten `vendor-id-mismatch` findings of the same vendor-less-header shape |

`tests/test_linter.py` pins that table exactly, so a rule that starts firing on
something else fails the suite instead of adding noise to a report.

The single-file rules were written *from* cases reviewers had already caught,
so agreeing with those reviewers was the correct outcome and none of them found
anything new at first. That changed as the corpus grew: `one-name-two-commands`
was written because 29.344's defect turned up in an extractor warning that no
rule was reading, and it now catches that class automatically.

The cross-file rules did find new things on their first run, which is the
argument for them:

- **`Feature-Id` in TS 29.283** is listed as re-used from TS 29.229, which has
  no such AVP. Neither does any other dictionary. It appears in no ABNF, so it
  is inert — but it is wrong, and nothing short of reading 29.229 could say so.
- **`Service-Selection` in TS 29.172** is cited from TS 29.272, which re-uses
  it from RFC 5778 rather than defining it.
- **`V2X-Subscription-Data` in TS 29.388** neither re-prints nor extends
  29.272's: it adds `V2X-PC5-Allowed-PLMN` and omits `UE-PC5-AMBR` and
  `V2X-Permission`. Reported as exactly that, and left to a reader.

## Standing findings, and why each one stays

A finding nobody can act on is worse than no finding, so every one the corpus
still reports is written down here with what it would take to clear it. Nothing
in this list is an oversight.

### `Feature-Id` — cleared by the corrections layer's `Delete`

This used to be the one outstanding error, reported against the corrected
corpus:

```
29283-i00.dad: error: [reused-avp-not-in-origin] Feature-Id is listed as
re-used from TS29.229, but 3GPP TS 29.229 18.1.0 neither defines, tabulates
nor re-uses it
```

TS 29.283 table 7.3.1-2 lists four AVPs from TS 29.229: `Supported-Features`,
`Feature-List-ID`, `Feature-List` and `Feature-Id`. The first three are real.
The fourth is not an AVP 29.229 has ever defined, and it appears in no ABNF in
29.283 either, so nothing referenced it — an inert row that should not be
there. Guessing a replacement would have been worse than the row: `Feature-Id`
is not a misspelling of `Feature-List-ID`, which is already in the same table,
and there is no fourth AVP in 29.229 the row could plausibly have meant.

The repair is deleting the row, which no field replacement can express — this
was the concrete case that forced the `Delete` operation
([corrections.md](corrections.md#structural-edits)). The row is now removed by
`edits/corrections/TS29.283.py`, the corrected file carries a `;; deleted:`
note on the table it left, and the raw file still reports the error — which is
the committed pair doing its job. `lint --corpus` over the corrected corpus
exits zero.

### `Service-Selection` — deliberately not corrected

```
29172-i10.dad: note: [reused-origin-indirect] Service-Selection is listed as
re-used from TS29.272, which re-uses it from RFC5778 rather than defining it
```

Unlike the above this *is* expressible — `reused_row("Service-Selection")` with
`field="origin"` and `replace="RFC5778"` is three lines. It is not written
because it is not clear that 29.172 is wrong. 29.272 genuinely carries the AVP,
a reader following the citation finds it, and "where I got this from" and "who
defined this" are different claims that the `From` column does not distinguish.
Rewriting it would make the `.dad` file say something the specification does
not, which is the one thing the correction layer is not for. The note records
the indirection and leaves the chain visible.

### `reused-body-differs` — a fact, not a defect

```
29388-i00.dad: note: [reused-body-differs] V2X-Subscription-Data's body,
against TS29.272's definition: adds V2X-PC5-Allowed-PLMN, missing
UE-PC5-AMBR, V2X-Permission (clause 6.3.2)
29337-i00.dad: note: [reused-body-differs] Additional-Serving-Node's body,
against TS29.173's definition: adds the SMSF members and
MME-Number-for-MT-SMS, missing 3GPP-AAA-Server-Name, GMLC-Address and
LCS-Capabilities-Sets (clause 6.3.4)
29337-i00.dad: note: [reused-body-differs] Serving-Node's body, against
TS29.173's definition: adds the SMSF, IP-SM-GW and
MME-Number-for-MT-SMS members, missing 3GPP-AAA-Server-Name, GMLC-Address
and LCS-Capabilities-Sets (clause 6.3.3)
29128-i00.dad: note: [reused-body-differs] Terminal-Information's body,
against TS29.272's definition: missing 3GPP2-MEID (clause 6.4.30)
29272-i60.dad: note: [reused-body-differs] ProSe-Subscription-Data's body,
against TS29.344's definition: missing 3GPP-Charging-Characteristics,
ProSe-Allowed-PLMN (clause 7.3.180)
```

Two documents describe one AVP differently. There is no way to tell from either
which is current — the two are separately maintained and either may be the one
lagging — and correcting one to match the other would invent an agreement that
does not exist in the specifications. TS 29.337 is especially explicit:
clauses 6.3.3 and 6.3.4 say the two AVPs originate in TS 29.173 and then print
the T4-specific bodies above. These are notes so that a consumer choosing
between the definitions knows there is a choice to make.

### Notes waiting on corpus growth

Every `local-and-reused` note has an origin now — the last one, 29.272's
`MIP6-Agent-Info`, resolved when RFC 5447 was extracted — so what remains in
this class is `origin-not-in-corpus`, in twelve files. Every unresolved
origin is either a legacy `.doc` specification (TS 32.299, cited by six
files; TS 29.368, 29.217, 29.468; TS 29.154 is not even in the catalog yet),
TS 29.273 (a `.docx` with a command section the extractor cannot read yet),
or a document outside 3GPP and IETF entirely (ETSI's TS 283 034 and
TS 183 017, 3GPP2's X.S0057, and TS 23.329, which 29.338 cites).

These notes clear themselves as the corpus grows. This is why acknowledging a
finding was never built: suppressing them one by one would hide which
cross-file rules were skipped and turn into discarded work when the missing
origin arrives.

### `unresolved-reference` — five references to AVPs that do not exist

The 55 findings this rule stood at were triaged in July 2026, each against
its primary specification clause. Fifty resolved into corrections — RFC ABNF
misspellings (the `Redirected-*` family in RFC 4005/7155, RFC 4004's
`Session-ID` and `MIP-nonce`, RFC 5778's `MIP-Agent-Info` and
`Multi-Round-Time`, the `Framed-Appletalk-*` casing in RFC 4005/4072, all
confirmed by verified RFC errata where any exist: 5993/5994/5995 for 7155,
3035 for 5778), re-used rows the 3GPP tables omit (the `MME-Name` family in
29.336/29.337, 29.272's `Communication-Pattern-Set` members,
`MIP6-Home-Link-Prefix` and `ProSe-Permission`, 29.338's `IP-SM-GW-Realm`,
29.128's `IMEI`/`Software-Version` — inserted by the re-used-row `Insert`),
and 3GPP name typos (29.345's `WiFi-P2P-Assistance-Iinfo`, `ProSe-App-ID`
and `User-Identity`-for-`User-Identifier`, 29.172's
`LCS-Supported-GAD-Shapes`, 29.212's `CS-Service-Qos-Request-Identifier`
table cell).

Five stand, and they share one shape: the ABNF references an AVP that no
document defines, tabulates or allocates, so there is nothing a correction
could truthfully point the name at.

- **RFC 4004's `MIP-HA-to-MN-SPI`, `MIP-MN-FA-SPI`, `MIP-MN-HA-SPI`**
  (clauses 9.4, 9.5, 9.6). The RFC defines exactly three SPI AVPs —
  `MIP-FA-to-MN-SPI` (319), `MIP-FA-to-HA-SPI` (318), `MIP-HA-to-FA-SPI`
  (323) — and the three MSA ABNFs reference three others that have no
  definition and no code. Verified erratum 1462 renames 9.6's to
  `MIP-MN-to-HA-SPI`, which is *also* undefined and unallocated, so even
  the erratum does not make the reference resolve. Wireshark corroborates
  the dead end from the other side: its `MIP-HA-to-MN-MSA` silently drops
  the SPI member and its `MIP-MN-to-HA-MSA` carries a dangling
  `MIP-MN-HA-SPI` reference of its own.
- **TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`** (clauses
  6.3.53, 6.3.54). The Discovery-Auth ABNFs carry them and the prose
  discusses the ProSe Query/Response Code at length, but no clause, no
  table row and no cited document defines an AVP by either name; neither
  does Wireshark or any 3GPP AVP-code registry entry in the corpus.

The rule promotes to an error when these five are gone, which now requires
the upstream documents to move (or a decision to represent
irreparably-dangling references some other way) rather than more triage.
