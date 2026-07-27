# The linter

`src/seanchai/linter.py` reports structural inconsistencies in a parsed `.dad`
file. It is the counterpart to the rule the extractor works under: the
extractor records what a specification says, *including* where the document
contradicts itself, and this is the layer that says so out loud rather than
resolving it silently.

```sh
uv run seanchai lint dad/3gpp/rel-18/*.dad
uv run seanchai lint --no-notes FILE.dad     # errors only
```

Errors exit non-zero; notes do not.

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

## Rules

- `duplicate-definition` — one name defined by two clauses.
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
- `local-and-reused` — the note above.

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
only the origin document states that. So those rows are skipped here and left
to the cross-document rules, which load the origin and read its `; Vendor-ID:`.
Skipping is the honest answer rather than a limitation worked around: within
one file, two re-used AVPs sharing a code may or may not collide, and nothing
present can decide it.

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

The corpus commits both kinds, which is what makes this answerable.
`29272-i60.raw.dad` reports three errors — two are the `Area-Scope` case, the
third is `WLAN-offloadability`'s missing vendor-id — and `29272-i60.dad`
reports none, because correcting a file is what clears them. Both are pinned —
a corrected corpus that is clean because the rules never match anything would
look identical otherwise.

What remains is nine `local-and-reused` notes on 29.272 — the nine AVPs it both
defines and lists as re-used, which no single file can judge.
`tests/test_linter.py` pins exactly that, so a rule that starts firing on
something else fails the suite instead of adding noise to a report.

Worth being plain about: none of these rules found something a reviewer had not
already found. They were written *from* cases reviewers caught, on a corpus of
three files, so agreeing with those reviewers is the correct outcome —
`vendor-id-mismatch` included, since `WLAN-offloadability` was noticed while
working out where vendor-ids come from and the rule was written afterwards.
Their value is in the specifications not yet extracted, which is the argument
for landing them before extracting more.

The nine `local-and-reused` notes stay unsuppressed, and there is deliberately
no way to acknowledge one. Silencing them individually would be work thrown
away: the cross-document rules resolve each note into an answer — re-print or
extension — by loading the origin and comparing, which is a better outcome than
a reviewer recording that they looked. Revisit if they are still noise once the
cross-file linter exists.
