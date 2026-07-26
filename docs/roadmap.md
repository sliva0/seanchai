# Roadmap

Open work, roughly in the order it delivers value. What already exists is in
the README's status section; completed review rounds are recorded in
[history/](history/) and are not outstanding work.

When you learn something non-obvious while working — a source-document quirk, a
workflow gotcha, a convention that isn't visible in the code — write it down in
the document it belongs to ([extractor.md](extractor.md),
[workflow.md](workflow.md), [dad-format.md](dad-format.md),
[downloader.md](downloader.md)). Cheap to write now, expensive to rediscover
later.

Before adding items here, read the conventions in
[development.md](development.md#working-on-these-documents) — several
tempting additions are settled decisions, not gaps.

Items are numbered so they can be referred to in a conversation. A number is a
position in this document, not an identity: inserting work renumbers what
follows, and nothing outside this file should cite one.

## Format

The grammar ([grammar.md](grammar.md)), the closed `data_type` set, the
`; Columns:` directive for both table kinds, the `P` flag and the `Y`/`N`
Encrypt spelling are all done. The format is deliberately unstable until
publication — see the notices in [grammar.md](grammar.md) and
[dad-format.md](dad-format.md) — so a change that needs it should just make it.

Free columns were tried and removed: every unmodelled source column turned out
to hold prose, which `.dad` does not carry. What is left is the case that is
not prose.

1. **Model the per-specification columns that carry machine-readable values,
   when a consumer needs them.** The extractor warns about every unmodelled
   column that is not a known prose label, so these are visible rather than
   lost — see [extractor.md](extractor.md#columns-the-format-does-not-model).
   The candidates are TS 29.212's "Acc. Type" (`3GPP-EPS`, `All`, `FBA`) and
   "Applicability" (`CC`/`PC`/`Both` plus feature names), TS 29.214's
   "Applicability" (feature names only), TS 29.061's "Applicable Reference
   Points" (`Gi`, `Sgi`), and the AVP Code / Value Type columns TS 29.172
   prints in its *re-used* table.

   Modelling them means deciding what they mean, and they do not all mean the
   same thing: three axes under four labels, with the two columns named
   "Applicability" overlapping only partly. That is the work, and it wants a
   consumer asking for the data rather than a tidy-up impulse — until then the
   warning is the right amount of machinery.

## Linter

A linter over a parsed `.dad` file. This is what makes an extracted corpus
trustworthy, and phase one should land before extracting more specs —
otherwise every new spec multiplies unverified data.

### Phase one: single-file structural rules

2. No duplicate definitions, no duplicate enum values.
3. No duplicate `(vendor-id, code)` identity, which is not the same rule as no
   duplicate names. TS 29.272's `Area-Scope` was the case: clause 7.3.138
   printed `Job-Type`'s code, giving two differently-named AVPs the same
   identity while every name in the file stayed unique. It is corrected now,
   but only because a reviewer read the file.
4. No AVP both defined locally and listed as re-used. TS 29.272 does this nine
   times, re-printing another spec's grouped AVP in full while listing it as
   re-used. The extractor deliberately keeps both — see [what the extractor does
   not decide](extractor.md#what-the-extractor-does-not-decide) — so this rule
   is what turns those nine into a report instead of a surprise.
5. AVP-table rows agree with the corresponding grouped/enumerated definition on
   code and type.

Everything above is decided inside one file, and every rule already has a real
case in the committed corpus. That is the point: these are not hypothetical
invariants, they are the inconsistencies three specifications actually contain.

One more thing the linter will need that the current design leaves open:

6. A way to acknowledge a finding. Some are the source document's fault and
   will never be fixed upstream, so a report that cannot be acknowledged
   becomes noise everyone learns to ignore — there should be a way to record
   "known, explained, not a regression", and it should look like the `reason` a
   patch or correction carries.

A linter that loads several files also needs the version question below (9)
answered anyway.

### Phase two: reference resolution

"Every AVP referenced in a message or grouped body resolves to a local
definition, an AVP-table row, or a re-used entry" cannot be enforced as
written. Each committed file references 14–17 AVPs that appear in no table —
hundreds of occurrences — and almost all of them are RFC 6733's: `Session-Id`,
`Origin-Host`, `Proxy-Info`, the trailing `* [ AVP ]`. No 3GPP spec
re-declares them, because every Diameter application is assumed to have them.

7. **A base-protocol import rule** — either an implicit RFC 6733 dependency or
   an explicit dependency/import directive in the format. The RFC extractor
   below (18) is what makes either one checkable, since neither means anything
   until a base `.dad` exists.
8. **Decide whether corrections need an insert operation.** Once the base AVPs
    are subtracted, the residue is small and interesting: two references in
    TS 29.272 (`Additional-Context-Identifier` in clause 7.3.35 and
    `Re-synchronization-Info` in clause 7.3.11) and none in 29.229 or 29.329.
    Neither is a base AVP and neither appears in 29.272's own AVP table or
    re-used table, so the document really does reference AVPs it never
    introduces. Adding them is a *row*, which the correction layer cannot
    express — it replaces fields, it does not insert nodes.
9. **Decide which version of an origin spec a run resolves against.**
    Resolving a re-used AVP to its `(vendor-id, code)` means reading the origin
    spec's `.dad`, so the linter must load several files at once — and
    `ReusedAvpRow.origin` names a specification but not a version. Settle this
    before writing the cross-file rules; "whatever happens to be on disk" is
    not a decision.
10. **Build the first resolvable tree.** The corpus needed for these rules is
    smaller than it looks, because closure is per-AVP rather than
    per-specification. A re-used row resolves as soon as the spec it names
    defines that AVP locally; it does not matter that the origin re-uses two
    dozen AVPs of its own from elsewhere. TS 29.272 re-uses from nineteen
    specifications, but a file re-using `V2X-Subscription-Data` *from* 29.272
    resolves in one hop, because 29.272 defines it.

    That makes **TS 29.388 (V4)** the cheapest first cross-file tree. Its
    entire re-used table cites four origins: `V2X-Subscription-Data`,
    `Visited-PLMN-Id`, `User-Id` and `Reset-ID` from 29.272; `MSISDN` from
    29.329; `Supported-Features`, `Feature-List-ID` and `Feature-List` from
    29.229 — all three already extracted, and all seven AVPs verified as
    locally defined there — plus `User-Name`, `OC-Supported-Features`,
    `OC-OLR`, `DRMP` and `Load` from RFCs 6733, 7683, 7944 and 8583. So one
    added specification closes every 3GPP edge, and the residue is exactly the
    base-protocol problem above. 29.388 is a small spec and currently fails on
    the missing-caption class (14).

    Afterwards, in rough order of what each adds: 29.344 (PC4a) reaches 29.173,
    which extracts today, and 29.061, which does not; 29.330 (Sc) needs 29.336;
    29.389 (V6) depends on 29.388 itself, which is what would first exercise a
    two-hop chain and therefore the version question.

## Validation against an independent oracle

11. **Fetch Wireshark's Diameter dictionary through the downloader.** It is
    the oracle the next item compares against, and it needs to arrive pinned
    and reproducible like every other source. Not a git submodule: a submodule
    is always a whole repository, and Wireshark's history is 1.2 GB for the
    824 KB of `resources/protocols/diameter/` (32 files) that matter — the
    dictionary is split across per-vendor XML entity files, so the whole
    directory is needed, not just `dictionary.xml`. A catalog entry fetching
    that directory at a pinned tag is the shape; it needs a third family
    alongside `tgpp` and `rfc` in `specs.toml` and its own download function,
    which is why it is an item rather than a config edit.

12. **Cross-check extracted codes, vendor-ids and types against Wireshark's
    Diameter `dictionary.xml`.** Only 29.329 is hand-verified today; this is
    what would let the other extracted specs be trusted at scale. Optionally
    borrow Wireshark's disambiguated names for AVPs whose names clash across
    specs.

    Use it as an oracle for values, not for the type vocabulary: its
    `typedefn`s include `IPAddress`, `VendorId`, `AppId`, `OctetStringOrUTF8`
    and `MIPRegistrationRequest`, which are dissector conveniences rather than
    Diameter types. A comparison has to map those onto RFC 6733's fifteen
    before it can report a disagreement — and mensonen/diameter collapses in
    the opposite direction, folding `DiameterIdentity` and `DiameterURI` into
    `OctetString`/`UTF8String`. Two consumers, two different reductions, which
    is why `.dad` keeps every distinction the specification draws.

## More sources

Run the extractor over the remaining 3GPP Diameter specs. Expect new document
quirks; keep the acceptance loop from [workflow.md](workflow.md). Running it
over the whole downloaded corpus is cheap and says where the work is: of the 34
specifications the downloader fetches, five extract cleanly today — 29.173,
29.229, 29.272, 29.329 and 29.337. The rest fail in a handful of classes, and
the classes matter more than the individual specs.

13. **Nine specifications never reach the extractor at all**, because 3GPP
    ships them as legacy binary `.doc` rather than `.docx`: 29.201, 29.215,
    29.217, 29.219, 29.343, 29.368, 29.468, 32.299 and TR 29.909. Among them
    32.299, which 29.272 and 29.389 both re-use from, and 29.368, which 29.337
    does. Reading that format, or finding a source that offers those nine as
    `.docx`, is a prerequisite the corpus does not currently admit to having.
14. **Six stop at "AVP table without a caption"**: 29.172, 29.283, 29.330,
    29.344, 29.388 and 29.389. This is the highest-value single fix, because it
    is what stands between the corpus and the first cross-file linter tree (10).
15. **Four cannot find the spec number on the cover page**: 29.061, 29.212,
    29.213 and 29.214.
16. **Four report no AVP table, in three different senses.** For 29.228 and
    29.328 the extractor is right and the assumption is wrong: those
    specifications hold the Cx and Sh *messages* while 29.229 and 29.329 hold
    their AVPs, so a message-only document is a shape the extractor should
    model rather than reject. 29.230's registry tables need their own path —
    they lack the "AVP Flag rules" header the current table dispatch keys on.
    29.305 is unexamined. Related, and also a shape assumption: 29.273 has a
    command section with no ABNF.
17. **Five trip deliberate strictness on a single cell** — a space inside a
    name cell in 29.336 and 29.338, `M. V` for flags in 29.345, and a
    misspelled data type in 29.109 ("OctedString") and 29.128 ("OctetSstring").
    This is the input-patch layer working as designed, so these are patches to
    write rather than code to change. Two things left this list rather than
    joining it: 29.389's empty Encrypt cell is now a representable value, and
    the four specs blocked on the `P` flag are no longer blocked on it.
18. **Add an RFC (plain-text) extractor** for the base protocol and IETF
    applications. This is a new input path rather than a new format: RFC 6733
    §4.5 is the same kind of table as a 3GPP AVP table, and its Attribute Name,
    AVP Code, Section Defined and Data Type columns map onto `AvpTableRow` as
    it already stands, plain scalar AVPs included. `vendor_id` is already
    optional on the definition nodes, so IETF-space AVPs need no change there.
    Its narrower flag columns are already representable — `; Columns:` lets a
    table declare that it has only MUST and MUST NOT — so the one real cost
    left is the fixed-width layout itself, where a long name wraps across
    physical lines (`Acct-` / `Interim-Interval`).
19. **Downloader changes** for archive fetching and link derivation — see
    [downloader.md](downloader.md).

## Downstream consumers

This is the point of the project, and the reason the rest of it is worth doing:
Diameter has no published machine-readable schema the way 5G's 3GPP protocols
have OpenAPI, so every implementation invents its own dictionary format. The
deliverable is not a format everyone adopts — it is that generating *your*
format becomes a short script over a reviewed corpus.

20. **A consumer model, distinct from the `.dad` AST.** These are two type
    hierarchies with opposite jobs, and collapsing them into one would damage
    both.

    The AST mirrors a file one-to-one and its job is fidelity. It has to be
    able to represent a specification that contradicts itself, because that is
    what the extractor is for: a grouped AVP both defined locally and listed as
    re-used stays as two nodes, an AVP-table row whose type disagrees with its
    definition keeps disagreeing. Nodes are frozen, round-trip is exact, and
    references are unresolved strings because that is what the file contains.
    Pressure to make this layer convenient is pressure to make it lie.

    The consumer model is what a generator or validator actually wants: a
    message whose ABNF entries point at real AVP objects rather than names, a
    grouped AVP that can enumerate its members, an AVP that knows its own
    `(vendor-id, code)` identity, its type, its flag rules and which
    specification introduced it — with methods, and with cross-references
    already followed across files. Built once from a parsed corpus and handed
    to the consumer resolved.

    The seam between the two is where every unresolved question in the linter
    sections lands, which is the useful consequence of naming the split: you
    cannot resolve a reference into an object without deciding what an
    unresolved base AVP means (7), which version of an origin spec to follow
    (9), or which of two conflicting definitions wins (4, 5). The consumer
    model is therefore downstream of phase two, not a parallel effort — and the
    linter is the tool that reports those conflicts instead of the model having
    to silently pick.

    The queries every consumer would otherwise rewrite belong here: every
    message defined in a specification with its ABNF and metadata, every
    grouped AVP, every plain AVP, every enumerated AVP with its values, and
    lookup of a single AVP by name or by `(vendor-id, code)`. Keep the set thin
    — the test for adding one is that a real consumer wrote it by hand first,
    which keeps [development.md](development.md#working-on-these-documents)'s
    rule about not designing API ahead of a second consumer intact. The AST
    stays public underneath for anything the model does not cover, so an
    unanticipated need is never blocked.

    What neither layer carries is prose: `.dad` has nowhere to put a clause's
    paragraphs, and automatic description capture was tried and removed
    (`e9856a9`). A message carries its ABNF, name, code, flags and its
    `; Section:` pointer; narrative stays in the specification the pointer
    names.
21. **Two consumer directions, both first-class**, over the same model (20):

    *Generate* a dictionary in a format the consumer chooses — Python class
    definitions for a library like
    [mensonen/diameter](https://github.com/mensonen/diameter), a JSON schema
    shaped like the 5G ones, an XML dictionary, whatever a given customer asks
    for. Seanchaí supplies the definitions and the queries; the output syntax
    is the script's business.

    *Validate* a dictionary that already exists. Someone who has already
    hand-written their format does not want it regenerated and rediffed — they
    want to know whether it is correct. A script walks their dictionary,
    resolves each entry against the corpus, and reports what disagrees: a wrong
    code, a stale type, an AVP the spec no longer defines that way. This is the
    more valuable of the two for anyone with an existing implementation, since
    it costs them nothing to adopt.

    Validation is also the better one to build first, because it needs no
    opinion about output syntax. It exercises exactly the lookups a generator
    needs — resolve by name, resolve by identity, enumerate a spec's messages —
    while being judged against an artifact that already exists, so the model is
    tested before any code-generation design has to be right.
22. **Keep hand-authored `.dad` files viable**, so a proprietary Diameter
    extension or an uncovered specification can be written directly and slot
    into the same parser, linter and consumers. Nothing needs building for this
    now, and it should not grow features ahead of a real case; it is here
    because it is a standing constraint on format changes — see the design
    intent in [dad-format.md](dad-format.md#design-intent).

## Smaller items

23. A version type shared by input patches and corrections, so a recorded range
    can be compared against the parsed version and *warn* when it no longer
    covers it. Both layers currently record ranges without comparing them, and
    both must keep applying regardless — the range explains, it never gates.
24. A CLI flag that auto-expands an input patch's `first_version`/`last_version`
    range when a newer or older version is parsed and the patch still applied
    cleanly. Needs comment-preserving TOML rewriting (e.g. tomlkit), and the
    shared version type above (23).
25. Fix the `atomic_download` corrupt-cache wart described in
    [downloader.md](downloader.md).
26. Stage a whole corpus version before publishing it. `replace_extracted` now
    rolls back a failed directory swap, and a failed run no longer leaves a
    stale `manifest.json` behind, so no single artifact is corrupted — but a
    run that fails halfway still leaves a corpus where some specs are the new
    version and some are the old one. Only staging the whole thing fixes that.
