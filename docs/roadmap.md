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

Items are numbered so they can be referred to in a conversation. Finishing one
leaves a gap rather than renumbering what follows, so a number keeps meaning the
same item for as long as that item is open — which is the point of having them.
New work takes the next unused number. Nothing outside this file should cite
one, because the numbers do not survive a reorganisation of the document
itself.

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

2. **Add a `seanchai format` command, and make it preserve comments.** There is
   no way to normalise a `.dad` file from the CLI today, which
   [dad-format.md](dad-format.md) nonetheless assumes when it says hand edits
   are normalised by running the formatter. Adding the command is small; the
   part that needs designing is that `;;` comments do not survive a round trip.
   The parser discards them and the formatter regenerates only what the AST
   holds, so normalising a file silently deletes every comment in it.

   That is harmless for correction notes, which the tool that owns them
   rewrites on every run, and not harmless at all for a hand-authored file —
   the one input the format explicitly means to support. Someone writing a
   vendor extension and annotating it loses the annotation the first time they
   format.

   How comments attach is the open question, not whether. A comment above a
   section block has an obvious owner; one above a table row or an ABNF line
   does too; one floating between blocks does not, and answering that badly
   makes canonical form ambiguous. Worth settling before hand-authored files
   exist rather than after, because it is much easier to add preservation than
   to change where a comment is understood to belong.

## Linter

Phase one is done — five single-file rules, described in
[linter.md](linter.md).

The raw/corrected question is settled: the corpus commits both. The corrected
file is what any real use consumes and what must lint clean; the raw file keeps
saying what the document said, which is what makes a version upgrade a
raw-vs-raw diff and lets the corrections be rot-checked offline. Corrections
mark the lines they touch with a `;;` note citing their own declaration, so a
corrected value is never anonymous.

The `vendor-id-mismatch` rule landed after the other four, once `; Vendor-ID:`
gave it something to compare against, and `WLAN-offloadability`'s missing
vendor-id in TS 29.272 clause 7.3.181 is now a correction rather than a defect
the corpus carries silently.

Acknowledging a finding was considered and deliberately not built. The nine
`local-and-reused` notes on 29.272 are the only standing noise, and the
cross-document rules below resolve each of them into an answer — re-print or
extension — instead of recording that a reviewer looked at it. Reopen this if
they are still noise once the cross-file linter exists.

A linter that loads several files also needs the version question below (7)
answered anyway.

### Phase two: reference resolution

"Every AVP referenced in a message or grouped body resolves to a local
definition, an AVP-table row, or a re-used entry" cannot be enforced as
written. Each committed file references 14–17 AVPs that appear in no table —
hundreds of occurrences — and almost all of them are RFC 6733's: `Session-Id`,
`Origin-Host`, `Proxy-Info`, the trailing `* [ AVP ]`. No 3GPP spec
re-declares them, because every Diameter application is assumed to have them.

5. **A base-protocol import rule** — either an implicit RFC 6733 dependency or
   an explicit dependency/import directive in the format. The RFC extractor
   below (16) is what makes either one checkable, since neither means anything
   until a base `.dad` exists.
6. **Decide whether corrections need an insert operation.** Once the base AVPs
    are subtracted, the residue is small and interesting: two references in
    TS 29.272 (`Additional-Context-Identifier` in clause 7.3.35 and
    `Re-synchronization-Info` in clause 7.3.11) and none in 29.229 or 29.329.
    Neither is a base AVP and neither appears in 29.272's own AVP table or
    re-used table, so the document really does reference AVPs it never
    introduces. Adding them is a *row*, which the correction layer cannot
    express — it replaces fields, it does not insert nodes.
7. **Decide which version of an origin spec a run resolves against.**
    Resolving a re-used AVP to its `(vendor-id, code)` means reading the origin
    spec's `.dad`, so the linter must load several files at once — and
    `ReusedAvpRow.origin` names a specification but not a version. Settle this
    before writing the cross-file rules; "whatever happens to be on disk" is
    not a decision.
8. **Build the first resolvable tree.** The corpus needed for these rules is
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
    base-protocol problem above. 29.388 is a small spec and now extracts
    cleanly, so nothing stands between here and the tree but committing it.

    Afterwards, in rough order of what each adds: 29.344 (PC4a) reaches 29.173,
    which extracts today, and 29.061, which does not; 29.330 (Sc) needs 29.336;
    29.389 (V6) depends on 29.388 itself, which is what would first exercise a
    two-hop chain and therefore the version question.

## Validation against an independent oracle

9. **Fetch Wireshark's Diameter dictionary through the downloader.** It is
    the oracle the next item compares against, and it needs to arrive pinned
    and reproducible like every other source. Not a git submodule: a submodule
    is always a whole repository, and Wireshark's history is 1.2 GB for the
    824 KB of `resources/protocols/diameter/` (32 files) that matter — the
    dictionary is split across per-vendor XML entity files, so the whole
    directory is needed, not just `dictionary.xml`. A catalog entry fetching
    that directory at a pinned tag is the shape; it needs a third family
    alongside `tgpp` and `rfc` in `specs.toml` and its own download function,
    which is why it is an item rather than a config edit.

10. **Cross-check extracted codes, vendor-ids and types against Wireshark's
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
specifications the downloader fetches, ten extract cleanly today — 29.172,
29.173, 29.229, 29.272, 29.283, 29.329, 29.337, 29.344, 29.388 and 29.389. The
rest fail in a handful of classes, and the classes matter more than the
individual specs.

11. **Nine specifications never reach the extractor at all**, because 3GPP
    ships them as legacy binary `.doc` rather than `.docx`: 29.201, 29.215,
    29.217, 29.219, 29.343, 29.368, 29.468, 32.299 and TR 29.909. Among them
    32.299, which 29.272 and 29.389 both re-use from, and 29.368, which 29.337
    does. Reading that format, or finding a source that offers those nine as
    `.docx`, is a prerequisite the corpus does not currently admit to having.
13. **Four cannot find the spec number on the cover page**: 29.061, 29.212,
    29.213 and 29.214.
14. **Five report no AVP table, in four different senses.** For 29.228 and
    29.328 the extractor is right and the assumption is wrong: those
    specifications hold the Cx and Sh *messages* while 29.229 and 29.329 hold
    their AVPs, so a message-only document is a shape the extractor should
    model rather than reject. 29.330 is the same shape arrived at differently:
    its table 6.3.1-1 exists but holds a header row and one blank row, because
    the Sc interface defines no AVPs of its own. It currently fails the AST's
    "tables are non-empty" invariant, which should stay — an empty table
    otherwise means the extractor found a caption and lost the contents — so
    the fix is to drop an all-blank table and then handle the message-only
    document it leaves. 29.230's registry tables need their own path — they
    lack the "AVP Flag rules" header the current table dispatch keys on. 29.305
    is unexamined. Related, and also a shape assumption: 29.273 has a command
    section with no ABNF.
15. **Five trip deliberate strictness on a single cell** — a space inside a
    name cell in 29.336 and 29.338, `M. V` for flags in 29.345, and a
    misspelled data type in 29.109 ("OctedString") and 29.128 ("OctetSstring").
    This is the input-patch layer working as designed, so these are patches to
    write rather than code to change. Two things left this list rather than
    joining it: 29.389's empty Encrypt cell is now a representable value, and
    the four specs blocked on the `P` flag are no longer blocked on it.
16. **Add an RFC (plain-text) extractor** for the base protocol and IETF
    applications. This is a new input path rather than a new format: RFC 6733
    §4.5 is the same kind of table as a 3GPP AVP table, and its Attribute Name,
    AVP Code, Section Defined and Data Type columns map onto `AvpTableRow` as
    it already stands, plain scalar AVPs included. `vendor_id` is already
    optional on the definition nodes, so IETF-space AVPs need no change there.
    Its narrower flag columns are already representable — `; Columns:` lets a
    table declare that it has only MUST and MUST NOT — so the one real cost
    left is the fixed-width layout itself, where a long name wraps across
    physical lines (`Acct-` / `Interim-Interval`).
17. **Downloader changes** for archive fetching and link derivation — see
    [downloader.md](downloader.md).

## Downstream consumers

This is the point of the project, and the reason the rest of it is worth doing:
Diameter has no published machine-readable schema the way 5G's 3GPP protocols
have OpenAPI, so every implementation invents its own dictionary format. The
deliverable is not a format everyone adopts — it is that generating *your*
format becomes a short script over a reviewed corpus.

18. **A consumer model, distinct from the `.dad` AST.** These are two type
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
    unresolved base AVP means (5), which version of an origin spec to follow
    (7), or which of two conflicting definitions wins — the last being exactly
    what the `local-and-reused` note declines to decide. The consumer
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
19. **Two consumer directions, both first-class**, over the same model (18):

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
20. **Keep hand-authored `.dad` files viable**, so a proprietary Diameter
    extension or an uncovered specification can be written directly and slot
    into the same parser, linter and consumers. Nothing needs building for this
    now, and it should not grow features ahead of a real case; it is here
    because it is a standing constraint on format changes — see the design
    intent in [dad-format.md](dad-format.md#design-intent).

## Smaller items

21. A version type shared by input patches and corrections, so a recorded range
    can be compared against the parsed version and *warn* when it no longer
    covers it. Both layers currently record ranges without comparing them, and
    both must keep applying regardless — the range explains, it never gates.
22. A CLI flag that auto-expands an input patch's `first_version`/`last_version`
    range when a newer or older version is parsed and the patch still applied
    cleanly. Needs comment-preserving TOML rewriting (e.g. tomlkit), and the
    shared version type above (21).
23. Fix the `atomic_download` corrupt-cache wart described in
    [downloader.md](downloader.md).
24. Stage a whole corpus version before publishing it. `replace_extracted` now
    rolls back a failed directory swap, and a failed run no longer leaves a
    stale `manifest.json` behind, so no single artifact is corrupted — but a
    run that fails halfway still leaves a corpus where some specs are the new
    version and some are the old one. Only staging the whole thing fixes that.
