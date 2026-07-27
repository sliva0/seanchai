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
```

Errors exit non-zero; notes do not.

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
*extending* it with fields of its own. TS 29.272 does this nine times, and
`ProSe-Subscription-Data` really is extended. Which case a given one is cannot
be decided from this file — it needs the origin's definition to compare
against, so the comparison belongs to the cross-document rules and this layer
only reports that the situation exists.

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

Eight specifications, each committed raw and corrected. The raw files carry
their documents' own mistakes and the corrected files clear them, which is what
makes "the corrected corpus is clean" mean anything at all — a corpus that were
clean because the rules never matched would look identical otherwise. Between
them the raw files exercise every single-file rule:

| file | reports |
|------|---------|
| `29172-i10.raw.dad` | `duplicate-identity` — clause 7.4.45 names the AVP `Periodic-LDR-Info` while the table and both ABNFs say `Periodic-LDR-Information` at code 2540 |
| `29272-i60.raw.dad` | `duplicate-identity`, `table-definition-mismatch` (the `Area-Scope` case) and `vendor-id-mismatch` (`WLAN-offloadability`) |
| `29344-i10.raw.dad` | `one-name-two-commands`, twice — clauses 6.2.11/6.2.12 print 6.2.3/6.2.4's rule names above command 8388713 |
| `29388-i10.raw.dad` | `duplicate-definition`, `duplicate-identity` and `table-definition-mismatch`, all from clause 6.3.10 re-printing 6.3.3's rule name |

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

`Feature-Id` has no correction, because removing a re-used row is an operation
the correction layer does not have — it replaces fields, it does not delete
nodes. So `lint --corpus dad dad/**/*.dad` exits non-zero today, on a real
defect with no expressible fix. That is the linter working; see the roadmap
item on insert and delete operations.

Nine `local-and-reused` notes on 29.272 are now eight: `ProSe-Subscription-Data`
resolved into a `reused-body-differs` answer the moment 29.344 joined the
corpus. The remaining eight cite documents the corpus does not hold yet, and
each will resolve the same way as it grows — which is why acknowledging a
finding was never built. Silencing them individually would have been work
thrown away.
