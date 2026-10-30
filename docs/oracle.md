# The Wireshark oracle

`src/seanchai/oracle.py` cross-checks every AVP a file defines — its
definitions and own AVP-table rows, skipping re-used names — against
Wireshark's Diameter dictionary by `(vendor-id, code)`, comparing name and
type. A row's vendor is read as the model reads it
([linter.md](linter.md#vendor-spaces)), from its Vendor-ID cell where the
table prints one (oneM2M TS-0004; TS 29.229's `Line-Identifier`, which
agrees with `etsie2e4.xml`'s ETSI 500) and its V flag otherwise: TS 29.273's
rows for RFC 5778's `MIP-Session-Key` forbid the V bit, so they are checked
in vendor 0. The
dictionary is an independent reading of the same specifications, which is
what makes disagreement informative.

```sh
uv run seanchai download                          # fetches the dictionary too
uv run seanchai crosscheck dad                    # 53 files, 98 findings
```

The check reads the newest copy of each document and no other: the
dictionary describes a document, and an older copy the corpus holds for a
citation across releases ([consumers.md](consumers.md#resolution-across-releases))
is no reading of it. `crosscheck` takes files or directories (a
directory's raw files skipped, as the corpus loader skips them), lists
each older copy it skips (TS 29.214 V7.12.0, TS 32.299 V11.20.0), and
refuses two files of one document and version, so a count over every
committed copy (116 findings in 55 files) cannot be reported by accident.
TS 29.140 V7.0.0 and TS 29.209 V6.8.0 are the newest copies of their
documents and are checked.

The `[wireshark]` entry in `specs.toml` pins a release tag; the downloader
fetches the whole `resources/protocols/diameter/` directory (the dictionary
is split across per-vendor entity files) through GitLab's tree and raw
endpoints and records it as one artifact.

## Tolerated type conventions

Wireshark's `typedefn`s include dissector conveniences, mapped before
anything is called a disagreement: `IPAddress` agrees with `Address` and
`OctetString`; `Enumerated` agrees with `Enumerated`, `Unsigned32` and
`Integer32` (any AVP with a value table is `Enumerated` there, including
`Result-Code`); `VendorId` and `AppId` stand for `Unsigned32`,
`OctetStringOrUTF8` for either reading, `MIPRegistrationRequest` for
`OctetString`. An unmapped dictionary type is reported, never guessed at.

## Findings are leads, not verdicts

**Wireshark is not a primary source.** It lags releases, carries its own
typos, and deliberately disambiguates names the specifications share. Every
finding is evaluated against the specification clause both projects read,
and the fix goes where the mistake is: a corpus correction when the document's
own table or the extractor was wrong, a merge request into Wireshark when the
dictionary is. The corpus **always keeps the specification's own spelling**;
Wireshark's is extra information in the consumer model.

## In the model

`model.Model.build(books, dictionary=Path("specifications/wireshark"))`
gives every AVP, and every hole with an identity, Wireshark's name for its
`(vendor-id, code)` in `wireshark_name`, for consumers that interoperate
with Wireshark-derived tooling: `Cx-User-Data` and `Sh-User-Data` for TS
29.229's and 29.329's `User-Data`, `Call-Barring-Infor-List` for TS 29.272's
`Call-Barring-Info`. `name` stays the document's. Where the identity
collides in the dictionary, an entry spelled like the corpus wins, then the
one whose type agrees; an identity the dictionary lacks or cannot settle is
None, as is every name in a model built without a dictionary.
`Oracle.name_for` is the lookup. The python-diameter generator writes the
name as a comment on the rule where it differs, since the library has no
place for another spelling
([README](../integrations/python_diameter/README.md#what-the-librarys-shape-cannot-carry)).

## What still reports

The first run's findings were triaged against the primary clauses; the
corpus-side fixes are corrections (RFC 5777's `Treatment-Action`, 29.229's
`Digest-QoP` for RFC 4590's `Digest-Qop`, 29.336's `Periodic-time`, RFC
4005's `Framed-Appletalk-*` table casing, 29.172's `Area-Identification`,
29.061's `MBMS-Flag`, where the dictionary agrees with clause 20.5a.9). What
remains:

- **Deliberate disambiguations and XML-imposed spellings**, correct on both
  sides: `Cx-User-Data`/`Sh-User-Data`, the `3GPP-SIP-*` and `3GPP-*`
  prefixes (32.299's `Reporting-Reason` and `SIP-Method` included),
  `Termination-Cause-3GPP`, `Wildcarded-PSI`, `S6-Service-ID`,
  `OnexRTT-RCID` (an XML name cannot start with a digit), `CUI`,
  `Tunnel-Connection-ID`, `NAF-Hostname`, and TS 29.140's
  `MM10-Sequence-Number` and `MM10-Recipient-Address` (1107, 1108), whose
  document calls them `Sequence-Number` and `Recipient-Address`, names
  TS 32.299 gives code 1201 too.
- **Wireshark-side defects**, each with a merge request staged under
  [`integrations/wireshark/`](../integrations/wireshark/README.md) and
  not yet submitted: `Call-Barring-Infor-List` for 29.272's
  `Call-Barring-Info`; `Accounting-Multi-Session-Id` for RFC 6733's
  `Acct-Multi-Session-Id`; `Authorization-Lifetime` typed Integer32 against
  §8.9's Unsigned32; `3GPP-IPv6-DNS-Server` for 29.061's plural;
  `Slg-Location-Type` against 29.172's `SLg`, and its `Cell-Portion-ID`
  typed OctetString against the Unsigned32 of clause 7.4.58 and table
  7.4.1-1; `PSR-Address` for 29.173's
  `PPR-Address`; `eNodeB-ID` and `Extended-eNodeB-ID` against 29.217's
  `-Id` (clauses 5.3.10, 5.3.15; 29.272 and 29.336 re-use them as `-ID`);
  and from 32.299, `Cellular-Network-Information` carrying a trailing space
  that leaves its two grouped references dangling, `ISUP-Release-Cause` for
  `ISUP-Cause`, `IP-Realm-Default-`, `Local-GW-Inserted-` and
  `Transcoder-Inserted-Indicator` for `-Indication`,
  `Number-of-Messages-Sent`, `User-Session-ID`, and `From-Address`,
  `ISUP-Cause-Location` and `Number-Of-Participants` typed IPAddress,
  OctetString and Integer32 against clauses 7.2.67A, 7.2.80D and 7.2.117;
  and from RFC 5777's verified errata, `IP-Bit-Mask-Width` for
  `IP-Mask-Bit-Mask-Width` (2335, the IANA name; the dictionary renamed
  its entry to the uncorrected ABNF's member in 2018) and
  `Time-Of-Day-Condition` without the three members 2333 restores, which
  the oracle, comparing names and types, does not report. Two more the
  oracle cannot see, the AVP being re-used or the defect a member list:
  `Application-Server-ID` (2101) typed Unsigned32 where OMA-DDS-Charging_Data
  V1.0 table 11, which TS 32.299 table 7.2.0.1 refers to and the corpus
  supplies the type from, says UTF8String; and `UWAN-User-Location-Info`
  (3918) listing only the four members TS 32.299 clause 7.2.242aaA printed
  up to V15.2.0, without `TCP-Source-Port`, `Civic-Address-Information`,
  `WLAN-Operator-Id` and `Logical-Access-ID`. TCP-Source-Port itself
  (2843, TS 29.212 clause 5.3.129) is absent from the dictionary, and its
  TS 29.212 addition supplies it. In ETSI's vendor 13019, whose entries
  `etsie2e4.xml` holds, the transcriptions' clauses name three AVPs
  otherwise: `Initial-Gate-Setting` (303) and `QoS-Profile` (304) for ES
  283 034's `Initial-Gate-Setting-Description` and
  `QoS-Profile-Description` (clauses 7.3.4, 7.3.5, table 10 and the
  ABNFs alike), and `Requested-Information-457` for TS 183 017's
  `Latching-Indication` (clause 7.3.8), an entry carrying its `LATCH` and
  `RELATCH` values under a name copied from ES 283 035's AVP 353.
- **Leads not staged**, resting on a reading the corpus makes rather than
  on a document's statement, or on nothing a merge request changes:
  `Monitoring-Event-Information` (3921) lists TS 29.336's
  `Monitoring-Event-Report` (3123), the name TS 32.299 clause 7.2.111AaC
  prints, where the corpus corrects the member to TS 32.299's own
  `Monitoring-Event-Report-Data` (3920); `dictionary.xml`'s comment `314
  Charging-Characteristics Integer [3GPP 29.234]` beside `TGPP.xml`'s
  OctetString entry, both from one 2021 commit, where no document settles
  the type ([extractor.md](extractor.md)); and `mobileipv4.xml`'s MSA
  members, which no source gives: `MIP-MN-to-HA-MSA` lists
  `MIP-MN-HA-SPI`, which resolves by name to RFC 5778's MIPv6 AVP 491
  (RFC 4004's verified erratum 1462 names the member `MIP-MN-to-HA-SPI`,
  which nothing defines), `MIP-MN-to-FA-MSA` and `MIP-FA-to-MN-MSA` list
  `MIP-MN-AAA-SPI` (341), a member of a 2004 draft, and
  `MIP-HA-to-MN-MSA` lists no SPI.
- **Display conveniences the mapping does not tolerate**, corpus correct:
  `3GPP-NSAPI`, `Codec-Data`, `Framed-Pool`, `EAP-Key-Name` and 32.299's
  `Access-Network-Information` (the dictionary comments its OctetString
  out) typed UTF8String where the specs say OctetString.
- **Absences**: AVPs newer than the pinned dictionary, one grouped note per
  file, 305 in 31 files, 304 AVPs. All but thirty-three have an addition
  staged under
  [`integrations/wireshark/additions/`](../integrations/wireshark/README.md#additions),
  written by `integrations/wireshark/additions.py` from the corpus, one
  patch per defining document; ten are named like an entry the
  dictionary or another addition already has, or grouped with no body the
  corpus holds, and twenty-three are oneM2M's.
- **oneM2M TS-0004, vendor 45687**: the pinned dictionary declares no such
  vendor and holds none of annex A's AVPs under any vendor, so the oracle
  checks the file unchanged: its IETF rows and its 3GPP ones (`Node-Id`
  2064, `Service-Information` 873) agree in name and type, the corrected
  `Service-Context-Id` (461, UTF8String) included, and all twenty-three of
  oneM2M's own AVPs are absent. No addition is staged for them: an entry
  goes beside its vendor's, and a vendor the dictionary lacks needs a
  `<vendor>` declaration, a file and its entity in `dictionary.xml`, a
  merge request of another shape than the series'.
- **ETSI TS 183 017, untriaged**: `Binding-information` (450), the
  spelling of table 7.3.1, clause 7.3.1's heading and its rule name, where
  the clause's sentence and the AAR and AAA ABNFs write
  `Binding-Information`, to which the corpus corrects it; and
  `ETSI-Service-Class` (459), the publisher prefix the dictionary gives
  some of ETSI's entries (`ETSI-Experimental-Result-Code` to keep apart
  from RFC 6733's), against clause 7.3.33's `Service-Class`, which no
  other entry in the pinned dictionary is named. The oracle compares no
  flags: the dictionary sets `Port-Number` and `Reservation-Class` (455,
  456) M to "may" and encryption off, where table 7.3.1 puts M in Must not
  and sets encryption.
- **Two untriaged leads from RFC 7155**: `Framed-IPX-Network` typed Unsigned32
  (clause 4.4.10.6.1's own sentence; RFC 4005 disagrees with itself here,
  clause 6.12.1 vs its table) against Wireshark's UTF8String; and
  `Framed-Appletalk-*`, which 7155 spells document-wide where 4005, RADIUS
  and Wireshark write `AppleTalk` — kept faithfully, erratum or name mapping
  undecided.
- **TS 32.299, untriaged**: where the document disagrees with itself and
  Wireshark took the other reading — `EPDG-Address` (clause 7.2.62A; the
  PS-Information body writes `ePDG-Address`),
  `PoC-Session-Initiation-Type` and `PoC-User-Role-Info-Units` (headings;
  table or body lower-case `type`/`info`), and the two Monitoring-Event
  rows its corrections type Enumerated after their clauses where Wireshark
  follows table 7.2.0.1's Integer32; `MMTel-SService-Type`, which 32.299
  misprints consistently and Wireshark spells `MMTel-Service-Type`. Table
  7.2.0.1's thirteen rows typed `refer [223]` are re-used
  from `OMA-DDS-Charging_Data` and so not checked; code 2117 is
  `Content-provider-ID` throughout OMA's document, as in Wireshark and TS
  29.230, and an input patch respells table 7.2.0.1's `Content-Provider-ID`
  to it.
