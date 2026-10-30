# The Wireshark oracle

`src/seanchai/oracle.py` cross-checks every AVP a file defines — its
definitions and own AVP-table rows, skipping re-used names — against
Wireshark's Diameter dictionary by `(vendor-id, code)`, comparing name and
type. A row's vendor is read from its V flag as the model reads it
([linter.md](linter.md#vendor-spaces)): TS 29.273's rows for RFC 5778's
`MIP-Session-Key` forbid the V bit, so they are checked in vendor 0. The dictionary is an independent reading of the same specifications,
which is what makes disagreement informative.

```sh
uv run seanchai download                          # fetches the dictionary too
uv run seanchai crosscheck dad/3gpp/rel-18/*.dad dad/rfc/*.dad
```

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
corpus-side fixes are corrections (RFC 5777's `Treatment-Action` and
`IP-Bit-Mask-Width`, 29.336's `Periodic-time`, RFC 4005's
`Framed-Appletalk-*` table casing, 29.172's `Area-Identification`, 29.061's
`MBMS-Flag`, where the dictionary agrees with clause 20.5a.9). What remains:

- **Deliberate disambiguations and XML-imposed spellings**, correct on both
  sides: `Cx-User-Data`/`Sh-User-Data`, the `3GPP-SIP-*` and `3GPP-*`
  prefixes (32.299's `Reporting-Reason` and `SIP-Method` included),
  `Termination-Cause-3GPP`, `Wildcarded-PSI`, `S6-Service-ID`,
  `OnexRTT-RCID` (an XML name cannot start with a digit), `CUI`,
  `Tunnel-Connection-ID`, `NAF-Hostname`.
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
  OctetString and Integer32 against clauses 7.2.67A, 7.2.80D and 7.2.117.
- **Display conveniences the mapping does not tolerate**, corpus correct:
  `3GPP-NSAPI`, `Codec-Data`, `Framed-Pool`, `EAP-Key-Name` and 32.299's
  `Access-Network-Information` (the dictionary comments its OctetString
  out) typed UTF8String where the specs say OctetString.
- **Absences**: AVPs newer than the pinned dictionary, one grouped note per
  file.
- **One untriaged lead from TS 29.229**: its row for RFC 4590's code 110
  spells `Digest-QoP`, where RFC 4590 (section 3.8) and Wireshark write
  `Digest-Qop`.
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
  misprints consistently and Wireshark spells `MMTel-Service-Type`; and 47
  absences. Table 7.2.0.1's thirteen rows typed `refer [223]` are re-used
  from `OMA-DDS-Charging_Data` and so not checked: Wireshark spells code
  2117 `Content-provider-ID`, as OMA's own table 11 does, where 32.299
  writes `Content-Provider-ID`.
