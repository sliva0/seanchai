# Consumers: the model and the integrations

## The model

The AST mirrors a file one-to-one and may contradict itself. `model.Model`
is the opposite contract: built once from a `corpus.Corpus`, it hands a
consumer a `Message` whose entries point at real `Avp` objects, a `Grouped`
that enumerates its members, an `Enumerated` with its values, and every AVP
knowing its `(vendor-id, code)`, type, flag rules and defining document.
An `Enumerated` whose clause defines its values elsewhere carries that
citation in `values_source` (TS 29.272's `Trace-Depth`: "TS 32.422 [23] for
Trace Depth"), its `values` those a correction supplies from the cited
document; with no values beside it (TS 29.272's `Report-Interval`, whose
source numbers each RAT apart) the AVP is complete, not a hole.
`values` holds the body as the file prints it, named values, reserved
ranges and vendor-specific ranges in order; `vendor_specific` picks out the
last, the ranges a consumer validating values must allow under names the
document does not give (TS 32.299's `SM-Service-Type` 100-199, "Vendor
specific SM services"), as it must refuse a reserved one.

```python
from seanchai import corpus, model
from seanchai.dad import ast

built = model.Model.build(corpus.Corpus.load([Path("dad")]))
# or with dictionary=Path("specifications/wireshark") for Avp.wireshark_name
built.messages("TS29.229")  # bodies resolved
built.applications("TS29.212")  # commands per application and interface
built.avps("TS29.229")  # a spec's dictionary view
built.resolve("TS29.229", "DRMP")  # one name in one spec's reading
built.find("Public-Identity")  # every AVP under a name
built.identified(10415, 601)  # every AVP claiming an identity
built.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
built.marks("TS29.212", "AN-GW-Address")  # what each table marks about it
built.holes("TS32.299")  # what the corpus cannot complete
built.across_releases()  # what citations resolved across releases
built.registry(ast.RegistryKind.APPLICATION_IDS, 16777216)  # TS 29.230's say
```

The query set is thin on purpose: each query was written because a real
consumer needed it. `applications` groups a document's commands by
application id and the clause they sit under, since documents share one id
between interfaces (TS 29.273's SWa, STa and SWd). The id is the header's,
or, for commands whose headers print none, the one an `Application Scope`
block covering their clause states: TS 29.212's Gx, Gxx, Sd and St take
theirs from clauses 5.1, 5a.1, 5b.1 and 5c.1, applying to `5.*`, `5a.*`,
`5b.*` and `5c.*`, and TS 32.299's Rf (3) and Ro (4) split its clause 6
between `6.2.*` and `6.4.*`. `Application.name` and `stated_in` name the
block and its clause; both are None for an id the headers print. RFC
6733's RAR, STR and ASR carry the using application's id (clause 2.5), so
their group's id stays None. A `Member` carries the ABNF rule as spelled,
markers included (a struck member with no legend saying otherwise is still
a member, `rule.strikethrough` set; TS 32.299's commented-out ones are
none), and `min_occurs`/`max_occurs` as RFC 6733 §3.2 reads them: `[ X ]`
may be absent, `* { X }` appears at least once. RFC 6733 §3.2 forbids a non-zero explicit minimum on an optional rule, so the
model reads `1*2 [ X ]` as `0*2`. The AST stays public underneath: `parser.parse(text)`
reads one file into it, discarding `;;` comments, and
`parser.parse_with_comments(text)` returns the comments too, as a
`formatter.Comments` (trailing, standing and detached, each keyed by
`ast.TreePath`) that `formatter.format_spec(spec, comments)` writes back in
place.

**Resolution policy.** A name resolves, in order, to the specification's own
definition, then to the origin its re-used table cites (recursively, so an
indirect citation lands on the real definition), then to an AVP-table row,
then to a `; Bases:` document. Local-over-reused makes an *extension* mean
what the extending document says, while a plain re-print resolves through
the origin. A name tabulated in several of one file's AVP tables takes its
table facts — flag rules, and type and code when no clause defines it — from
the first row in file order (a re-used name's flag rules per flag, below);
`table_rows` returns every copy, which matters where per-interface tables
disagree (TS 29.061's `3GPP-IMSI`, the linter's `table-row-mismatch`). The model never reports the conflicts this order
papers over; run the linter for those. Vendor spaces follow the linter's
reading. Origins and bases use `corpus.Corpus.resolve`, the
drafting rules below ([resolution across releases](#resolution-across-releases);
within a release, the match-major-take-newest rule in
[linter.md](linter.md#resolving-an-origin)),
which also reads 3GPP's `ETSI-TS283.034` as the ETSI ES 283 034 it names,
and takes TS 32.299's `oneM2M-TS-0004` to the oneM2M document the corpus
extracts, whatever its version: `M2M-Information` is (45687, 1011) there.
TS 29.212's `3GPP2-X.S0057` goes to the 3GPP2 transcription, revision 0
V2.0 standing in for the revision B its reference [24] names (below):
`3GPP2-BSID` is (5535, 9010), and TS 32.299's row, re-used through TS
29.212, the same.

**The citing table's flag rules.** Flag rules are the application's: RFC
6733 section 4.1 has the M bit set "according to the rules defined in the
application specification that introduces or reuses this AVP", and
section 4.5 has each application tabulate its AVPs' flags. So where a
document re-uses an AVP and its own AVP tables state flag cells for it,
those cells outrank every other reading's when the name resolves through
that document. They count per flag: each flag is where the first of the
document's rows placing it puts it, a row leaving a flag in no column
saying nothing of it, so a later table's row is read for a flag no earlier
row places. The origin still supplies the code, type and vendor, names
the defining document, and supplies each flag no row places (rows of `-`
cells place none and take the origin's rules whole). TS 29.229 table
6.3.0.1 puts M in Must for `Digest-Realm`, `Digest-Algorithm`,
`Digest-Qop` and `Digest-HA1`, so through TS 29.229 they are M in Must, P
in May (RFC 4590's stand-in rules supplying P, which the row leaves out)
and V in Must not, and through RFC 4590 M in May as RFC 4590's corrections
give them. TS 32.299 table 7.2.0.1 sets M for the charging application on
`Supported-Features`, `Feature-List` and `Feature-List-ID`, TS 29.229's.
TS 29.229 and 29.329 forbid M on RFC 7944's `DRMP` and RFC 7683's
`OC-OLR` and `OC-Supported-Features`, and TS 32.299 on six of RFC 7683's
`OC-*`, where the RFCs leave M to the application; TS 29.330, citing TS
29.229 for them, reads them TS 29.229's way. A re-used table's M-bit
column is the citing interface's M rule too, ranked below its AVP-table
cells and above the origin: `MUST` puts M in Must and `MUST-NOT` in Must
not, and a `-` says nothing, so the first of the name's re-used rows
whose cell states a rule is the one read. TS 29.272 table 7.3.1/2 marks
TS 29.212's `RAT-Type` `MUST`, where TS 29.212 forbids M, and 21 of TS
29.336's AVPs, `SCEF-ID` among them, `MUST-NOT`, where TS 29.336 sets it;
TS 29.283, 29.344, 29.345, 29.388 and 29.389 set M on RFC 7683's `OC-OLR`
and `OC-Supported-Features`, and ten documents forbid it on RFC 7944's
`DRMP` or RFC 8583's `Load`. TS 29.336 prints `-` for `DRMP`, `Load`,
`OC-OLR` and `OC-Supported-Features` in table 6.4.1/2 and `MUST-NOT` in
table 8.4.1-2, so through TS 29.336 their M is in Must not, as TS 29.273's
`OC-OLR` and `OC-Supported-Features` are by table 8.2.3.0/2 and TS
29.338's `SGSN-Number`, TS 29.272's, by table 6.3.3.1/2. An
IETF reading stating no flags takes the M-bit with RFC 6733's V rule (TS
29.273's `Key`, from RFC 6734, which prints no flag columns, is M and V in
Must not); a vendor reading stating none stays a hole rather than become M
alone. Resolution through the origin is unchanged, so `identified` returns
both readings of such an identity.

A grouped AVP defined elsewhere keeps the defining document's body, which
members and with what qualifiers, but each member the citing document
defines, tabulates or re-uses is read through it, with the precedence
above, where that reading is the same AVP, the same `(vendor-id, code)`;
a member it says nothing of, or reads as another AVP or as none it can
identify, keeps the origin's reading. The body names its members in the
defining document's sense: TS 32.299's own `Originator` is (10415, 864)
Enumerated, but its re-used `M2M-Information`, oneM2M TS-0004's, holds
oneM2M's `Originator`, (45687, 1008) UTF8String, and TS 29.061's
re-used `Local-M1-Information`, TS 29.468's, holds TS 29.468's
`MBMS-GW-SSM-IP-Address` and `MBMS-GW-SSM-IPv6-Address`, 3522 and 3523
Address, not TS 29.061's 924 and 925 OctetString. TS 32.299's
`Supported-Features` is TS 29.229's body with TS 32.299's `Feature-List`
and `Feature-List-ID`, M in Must, where through TS 29.229 they are M in
Must not; TS 29.272's `Monitoring-Event-Configuration` holds TS 29.272's
`SCEF-ID`, M in Must not as its re-used table says. A grouped member read
through the citing document has its own members read the same way, and one
among its own descendants is cut as any body cuts it, where the reading
being resolved is the member's AVP: a citing document's own `Feature`
holding a re-used `Bundle` whose `Feature` is another document's, another
`(vendor-id, code)`, keeps that member, not a cut. The linter's
`reused-row-mismatch` still reports each disagreement between an AVP-table
row and its origin, saying which side the model follows for the disputed
flag.

**Filling through.** A field the first reading leaves unstated comes from
the next reading along the order, if the two are the same AVP saying the
same thing: every field both state — code, type, flag rules, and vendor
where both state one — must be equal. A table row's Vendor-ID cell, where
its table prints one (oneM2M TS-0004 table A.4-1, and TS 29.229 table
6.3.0.1's `Line-Identifier`, ETSI's 500 by clause 6.3.42, inserted by
correction), is its vendor; otherwise
its V flag says it (`ast.AvpTableRow.stated_vendor`, which the linter's
`duplicate-identity` reads too): V under Must-not is IETF space, vendor 0
(TS 29.229's `Digest-Qop`, code 110, is RFC 4590's; TS 29.273's
`QoS-Capability`, `QoS-Resources`, `Mobile-Node-Identifier`,
`MIP-MN-HA-SPI` and `MIP-Session-Key` are RFC 5777's and RFC 5778's), V
under Must the file's `; Vendor-ID:`, and a row stating neither infers its
file's vendor, which agrees with any. TS 29.272's re-print of
`Allocation-Retention-Priority` takes TS 29.212's flag rules this way, and
TS 29.229's re-used `Digest-*` AVPs resolve to RFC 4590's rows, which
its corrections type UTF8String with Wireshark's flag rules, RFC 4590
being a RADIUS document. The citing table's own flag cells, and its
re-used row's M-bit, take no part in this: they are laid over the result,
so they neither fill another reading nor disagree with one. A reading that
disagrees fills nothing, nor does any after it: the name stays a hole that
names the disagreeing document, rather than become one AVP assembled from
two documents that disagree about it.

**Marks.** `marks` returns, per row of a table printing mark columns (AVP
and re-used tables alike, in file order), the table's label and clause and
the row's marks per column: a tuple of marks, `()` where the cell prints a
dash, None where it is blank. The marks keep the document's spelling,
with the note reference printed beside one (`All (NOTE 5)`, whose note
excludes 3GPP-GPRS); what they mean is the legend's, per label:

- `Acc-Type` (TS 29.212, 29.215): the IP-CAN access types the AVP applies
  to, `All` or a list (`3GPP-EPS`, `Non-3GPP-EPS`, `3GPP-GPRS`, `3GPP2`,
  `FBA`, `xDSL`).
- `Applicability`: the supported features the AVP belongs to ("AVPs marked
  with a supported feature are applicable as described in clause 5.4.1",
  TS 29.212 table 5.3.0.1 note 9; also 29.061, 29.154, 29.214, 29.215,
  29.217, 29.219, 29.368, 29.468, whose `V2X Localized User Plane` is one
  feature), and in TS 29.212 and 29.215 the function too: `CC` charging
  control, `PC` policy control, `Both`, `ADC` application detection and
  control, `ABC` application based charging (note 3). Blank is the base
  functionality.
- `Reference-Points` (TS 29.061 table 9a): `Gi`, `Sgi`.
- `ACR`, `ACA`, `CCR`, `CCA` (TS 32.299): whether the AVP is used in that
  command, `M`, `OM` or `OC` in table 7.1.0.1 (clause 7.1.0), `X` in tables
  7.2.0.1 and 7.3.1-7.5.1, `()` for the dash clause 7.1.0 reads as "not
  used", None for the four cells the document leaves blank.

None of these names an interface. A document tabulating several interfaces
gives each its own tables, so a row's interface is its table's clause: TS
29.212 marks `AN-GW-Address` `Both, Rel8, EPC-routed` for Gx in table
5.3.0.1 and `EPC-routed (See NOTE 8)` for Gxx in re-used table 5a.4.0.1.

**The registry.** `registry(kind, code)` returns what the corpus's
registries say of a code, as `model.Allocation`s naming the registry
document, table and clause: the rows allocating it and the reserved ranges
covering it, or with no code every row and range of that kind, in file
order. TS 29.230 table 4.1 allocates 16777216 to "3GPP Cx/Px" in TS 29.228
and 29.229, and table 7.1 allocates 318 twice. It is evidence beside the
model, not a reading of it: no `Avp`, `Message` or `Application` takes
anything from it, and the linter's `registry-*` rules
([linter.md](linter.md#registry-rules)) report where documents and
registry differ.

**IETF flag rules.** RFC 6733 section 4.1 makes the M bit the business
of "the application specification that introduces or reuses this AVP",
and RFC 7423 section 4.4.1 has a re-using application "specify the setting
of the M-bit"; section 4.1.1 puts a Vendor-ID in the header exactly when V
is set, and forbids a Vendor-ID of zero. So an IETF-space (vendor 0) AVP
whose readings place neither bit has rules all the same: V under
Must-not, and M application-defined, a `model.FlagRules` (an
`ast.AvpFlagRules` with an `application_defined` column) holding M there
rather than in any of the four columns, since Must or May would be a
guess. RFC 4072, 5447, 5777 and 6734 print no flag columns and say
nothing of either bit, RFC 4005 and 7155 leave `QoS-Filter-Rule`'s cells
blank, and RFC 7683, 7944 and 8581–8583 place V alone, 7683 and 8583
saying that "the M-bit usage for a given AVP in a given command may be
defined by the application"; each gets the rule for the bit it leaves
unplaced. It is
the last reading, after every document's: TS 29.273's tables set M for
RFC 5777's `QoS-Capability`, and TS 29.273's reading takes that, while
RFC 5777's own keeps the rule. A vendor AVP gets no such rule: TS 29.389's
three V2X rows print blank flag cells, and their V bit is read from clause
6.3.1's "The Vendor-ID header of all AVPs defined in this specification
shall be set to 3GPP (10415)" ([extractor.md](extractor.md#quirks)), their M
bit staying in no column, as TS 29.212 leaves `PDN-Connection-ID`'s. The
python-diameter generator writes an application-defined M as no
`is_mandatory`, the dictionary's default.

**Resolution across releases.** The corpus holds one copy of each
document per release tree, and a citation means the copy the drafting rules
on references say it means. A *specific* reference, one whose entry in the
citing document's references clause names a version or a release, means
that version (3GPP TR 21.801 V19.1.0 clause 6.6.6.5.2, references
"identified by date of publication, edition number, version number,
etc."; the ETSI Drafting Rules as published in ETSI SR 001 262 V2.0.0,
clause 12: "For a specific reference, subsequent revisions do not apply";
and the citing documents' own clause 2, ETSI TS 183 017 V3.2.1's "For
dated references, only the edition cited applies" and oneM2M TS-0004
V2.35.0's "For specific references, only the cited version applies"). A
reference naming a release means its last version. A *non-specific*
reference, one naming neither, means "the latest version of the referenced
TS or TR in the Release in question", the citing document's release (TR
21.801 clause 6.6.6.5.3, and every 3GPP document's clause 2: "a
non-specific reference implicitly refers to the latest version of that
document in the same Release as the present document"), which is the
match-major-take-newest rule; and for a document outside 3GPP the latest
version of the referenced document (SR 001 262 clause 12: "For a
non-specific reference, subsequent revisions do apply", conditions in
clause 12.4; TS 183 017's clause 2: "the latest edition of the referenced
document (including any amendments) applies"). The Drafting Rules in force
today are part of the ETSI Directives, which are not public; the clause 2
boilerplate ETSI's drafts quote from them, citing EDR clause 2.10.1, reads
"For specific references, only the cited version applies. For
non-specific references, the latest version of the referenced document
(including any amendments) applies", as oneM2M's does. Neither rule says what a non-specific 3GPP
reference means when the cited document ended before the citing
document's release; the corpus reads it as the document's *final* version,
its last in any release, the latest there is. So `corpus.Corpus.resolution`
takes, in order: a specific reference's named version and no other; the
newest copy in the citing document's major version; and failing one, a
later release's copy standing in by an evidenced entry (below), or the
cited document's final version when it ended in an earlier release. A
document outside 3GPP has no release, so its non-specific reference is the
final version or nothing. The `.dad` grammar names no versions, so the two
facts this needs live beside `corpus.CITED_AS`, each entry citing its
source: `corpus.CITED_VERSIONS`, the version a specific reference names
keyed by (citing, cited) reference and read from the citing document's
references clause (ETSI TS 183 017's "3GPP TS 29.209 Release 6" [4] and
"3GPP TS 29.214 Release 7" [19], oneM2M TS-0004's "3GPP TS 32.299 ...
(Release 11)" [31]), and `corpus.FINAL_VERSIONS` (TS 29.140 V7.0.0, TS
29.209 V6.8.0). Every version either names is a catalog pin the downloader
checks against the 3GPP archive on each download, so a later version
appearing fails the download rather than the reading
([downloader.md](downloader.md)). A 3GPP2 revision letter (X.S0057-0,
-A, -B) is 3GPP2's release, which a spec-ref does not keep either: a
reference naming one is specific to it, recorded in
`corpus.CITED_REVISIONS`, and resolves to a copy of that revision only.
Where the corpus cannot hold the cited revision, a copy of another answers
only by an entry in `corpus.STAND_INS` that names it and states the
evidence; without one the citation resolves to nothing. TS 29.212 cites
"3GPP2 X.S0057-B" [24], and 3GPP2's library publishes X.S0057-0 V1.0 and
V2.0 alone (checked 2026-10-30 at its X-series index), so revision 0 V2.0
stands in.

An older copy held for a citation cites in turn, and its non-specific
references mean its own release's last versions. TS 32.299 V11.20.0,
which oneM2M TS-0004 names, cites eight 3GPP documents so for what
`Service-Information` reaches; the corpus holds two at Release 11, TS
29.212 V11.19.0 and TS 29.214 V11.16.0, catalog pins verified as their
release's last, because Release 18's differ where it matters: Release
18's `QoS-Information` has seven members Release 11's lacks, and its
`Flows` adds `Content-Version`, `Media-Component-Status` and `* [ AVP ]`
to Release 11's closed body. The other six, TS 29.061, 29.173, 29.229,
29.272, 29.273 and 29.329, define everything TS 32.299 V11.20.0 re-uses
from them alike in Release 11 and Release 18: codes, vendors, types, each
table row's flag rules, grouped bodies and enumerated values, members those
bodies reach included. Their Release 18 copies stand in, each by an entry
in `corpus.RELEASE_STAND_INS`, keyed by citing document, citing version
and cited document, naming the version meant and the copy answering and
stating that evidence, as `corpus.STAND_INS` does for a revision; without
one, such a citation resolves to nothing. The pinned copies' own Release 11
citations of TS 29.061, 29.229 and 29.272 have no entry, and stay
unresolved: TS 29.212 V11.19.0 re-uses TS 29.272's `Trace-Data`, whose
Release 11 body differs from Release 18's.

Twelve citations resolve across releases or revisions: TS 32.299's TS
29.140 (`VAS-ID`, `VASP-ID`) and ES 283 034's TS 29.209 (`Media-Type`,
`AF-Application-Identifier`) as final versions, TS 183 017's TS 29.209 and
TS 29.214 and oneM2M TS-0004's TS 32.299 as the versions named, TS
29.212's 3GPP2 X.S0057 (`3GPP2-BSID`) as the revision standing in, and
TS 32.299 V11.20.0's six as the Release 18 copies standing in. An `Avp`
or `Hole` that took a field from such a copy carries `across_releases`, a
`corpus.CrossRelease` naming the citing and cited documents, the version
and the rule (`corpus.SPECIFIC`, `corpus.NON_SPECIFIC`, or
`corpus.STAND_IN` with the cited and held revisions, or with `meant`, the
version a release stand-in answers for); `across_releases()` lists them
for a reader to audit, sixty-two, what an older copy reached across
releases cites across releases in turn included (thirty-five through TS
32.299 V11.20.0's stand-ins, under oneM2M TS-0004's
`Service-Information`), and the linter's `cross-release-origin` note says
the same per citing file. An older copy answers only through a citation:
reference-level queries (`avps("TS32.299")`, `holes`, `references`) read
the newest copy of each document, and Release 18's TS 32.299 never reads
its Release 11 copy.

**Holes.** An `Avp` has every field: code, type and flag rules are facts some
document states, or RFC 6733's rule for an IETF AVP's unplaced bits, never
`None`. A name the corpus cannot complete is a
`model.Hole` instead, naming the document that falls short, the fields it
leaves unstated (`code`, `data_type`, `flag_rules`), or `definition` when
the name resolves nowhere, plus the re-used origin the corpus lacks or the
disagreeing reading, if either applies. A flag-rule row with every cell
blank is unstated, not "no flags". `Member.avp` is `None` for a hole and
`Member.hole` says which; the `* [ AVP ]` wildcard is the one `None` without
a hole. A hole keeps the vendor, code, type and flag rules its document
states, but not a grouped AVP's members or an enumerated AVP's values: RFC
5777's `Classifier` is a hole with no members. A consumer that wants those
reads the AST, through `table_rows` or the file's `corpus.Entry.spec`.
A reading's holes include those of the grouped AVPs it reaches in an
older copy through a citation across releases, which no reading of that
copy's own reports: such a hole carries the copy's `version`, and
`Hole.document` reads "TS32.299 V11.20.0". One reached in a newest copy,
standing in or not, is that copy's reading's to report: TS 32.299
V11.20.0's `PS-Information` reaches TS 29.061's
`3GPP-Session-Stop-Indicator`, a hole of TS 29.061's own.

**Wireshark's names.** Built with `dictionary=` a Wireshark dictionary
directory, the model fills `Avp.wireshark_name` and `Hole.wireshark_name`
with Wireshark's name for the identity (`Cx-User-Data` for TS 29.229's
`User-Data`); built without one, both are None. The dictionary is optional
and never changes `name`, which is always the document's spelling;
[oracle.md](oracle.md#in-the-model) has the lookup rule.

`Model.build(books, strict=True)` raises `model.IncompleteCorpusError`,
listing every hole, rather than build a model with any. The default is
`strict=False` because the committed corpus does not build strictly, and
every standing hole is a statement its source does not make.
TS 29.061's `3GPP-Session-Stop-Indicator` row states only a code, and the
names that resolve nowhere are the corpus's `Undefined AVP` blocks, the
linter's standing `undefined-avp` notes. oneM2M TS-0004 reaches no other: its
`Service-Information`, TS 32.299 V11.20.0's, resolves through the pinned
Release 11 copies and the Release 18 ones standing in (above), so
`holes("oneM2M-TS-0004")` is empty. TS 32.299's thirteen OMA rows are no
holes: their flags, and the types of the ten its clauses do not type, are
supplied from OMA-DDS-Charging_Data
([corrections.md](corrections.md#operations)), and a grouped one is an
`Avp` typed Grouped with no members, since the corpus holds no body for
it. V11.20.0's three that `Service-Information` reaches, `DCD-Information`,
`IM-Information` and `Service-Generic-Information`, are supplied the same
way, their clauses and reference [223] reading as Release 18's do. The pinned list in `tests/test_model.py`
(`_STANDING_HOLES`) is the full account: the strict build's failure is
compared against it, so a hole worked off or a new one shows up as a diff.
Roadmap item N lists them by cause.

## The integrations

Each target gets a directory under `integrations/`; scripts carry PEP 723
inline metadata naming their dependencies, so uv supplies everything:

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 -o out/
```

### python-diameter

[python-diameter](https://github.com/mensonen/diameter) folds every use of a
command into one class, so "is this class right?" has no single answer; the
script checks one specification's claims at a time. That document's commands
must exist under the right codes, each direction's `avp_def` must cover the
ABNF's members matched by `(vendor-id, code)`, `is_required` must agree with
the brackets, and the document's own AVPs must be right — name, type,
mandatory default — in the library's global dictionary. An "extra AVP" may
be another specification's legitimate use of the same command class. The
model is built non-strictly: a hole is checked on what its document states
(TS 29.061's `3GPP-Session-Stop-Indicator` has an identity but no type),
and one with no `(vendor-id, code)` is reported as unchecked.

The first Cx run (library 0.9.0, which pins TS 29.229 V13.1.0) reported 94
disagreements, the sharpest being three command classes carrying RFC 4740's
IETF `SIP-Auth-Data-Item` and `SIP-Number-Auth-Items` where TS 29.229
specifies 3GPP's codes 612 and 607 — a wire-level incompatibility. Findings
against a version-13 dictionary may simply be Release 13's truth; the reader
decides what becomes an upstream issue.

That run was also the corpus's sharpest review: it found an ABNF line the
extractor silently dropped (29.229's RTR prints `RTR-Flags ]` with no opening
bracket, now input-patched) and the `Load` rows that became the linter's
`row-without-code` rule.

`generate.py` is the other direction: one module per application and
interface, whose command classes carry that document's own members and are
written the way the library writes its own — `DefinedMessage` subclasses
whose `AvpGenDef` tables reference the library's `AVP_*`, `VENDOR_*` and
grouped classes — so the library can carry them beside its merged classes.
What its dictionary lacks, or types otherwise than the document, goes to an
`additions.py` in the dictionary's shape rather than being papered over.
Holes stay in the tables with their reason; an application's id is the
model's, so a module whose document states it only in prose gets it, and
only RFC 6733's clause 8 gets `None`. Where no application scope names the
application, the `APPLICATION_ID` comment names it as the registry does
(`# 16777216, 3GPP Cx/Px, TS29.230 table 4.1`); the id stays the model's.
TS 29.230 is a corpus document like any other, so `--all` lists "3GPP TS
29.230 V18.6.0" among the sources in `__init__.py` and `additions.py`,
though it contributes no module and no addition; and since TS 29.273's
`Trust-Relationship-Update` row is corrected away (clause 9.2.3.1.4 is
"Void"), `additions.py` no longer carries its 1515 constant. The ABNF decides a class's members,
and the tables' marks are comments on them: TS 32.299's per command, the
others from the command's interface clause. The
[README](../integrations/python_diameter/README.md) covers the layout, the
additions, how the library would adopt the modules, and what its shape
cannot carry.
