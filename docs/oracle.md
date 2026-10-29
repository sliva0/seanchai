# The Wireshark oracle

`src/seanchai/oracle.py` cross-checks every AVP a file defines — its
definitions and own AVP-table rows, skipping re-used names — against
Wireshark's Diameter dictionary by `(vendor-id, code)`, comparing name and
type. The dictionary is an independent reading of the same specifications,
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
Wireshark's belongs, if anywhere, in the consumer model as extra information.

## What still reports

The first run's findings were triaged against the primary clauses; the
corpus-side fixes are corrections (RFC 5777's `Treatment-Action` and
`IP-Bit-Mask-Width`, 29.336's `Periodic-time`, RFC 4005's
`Framed-Appletalk-*` table casing, 29.172's `Area-Identification`, 29.061's
`MBMS-Flag`). What remains:

- **Deliberate disambiguations and XML-imposed spellings**, correct on both
  sides: `Cx-User-Data`/`Sh-User-Data`, the `3GPP-SIP-*` and `3GPP-*`
  prefixes, `Termination-Cause-3GPP`, `Wildcarded-PSI`, `S6-Service-ID`,
  `OnexRTT-RCID` (an XML name cannot start with a digit), `CUI`,
  `Tunnel-Connection-ID`, `NAF-Hostname`.
- **Wireshark-side defects**, merge-request candidates:
  `Call-Barring-Infor-List`; `Accounting-Multi-Session-Id` for RFC 6733's
  `Acct-Multi-Session-Id`; `Authorization-Lifetime` typed Integer32 against
  §8.9's Unsigned32; `3GPP-IPv6-DNS-Server` for 29.061's plural;
  `Slg-Location-Type` against 29.172's `SLg`; `PSR-Address` for 29.173's
  `PPR-Address`; `MBMS-Flag`.
- **Display conveniences the mapping does not tolerate**, corpus correct:
  `3GPP-NSAPI`, `Codec-Data`, `Framed-Pool`, `EAP-Key-Name` typed UTF8String
  where the specs say OctetString; `Cell-Portion-ID` OctetString against
  29.172's Unsigned32.
- **Absences**: AVPs newer than the pinned dictionary, one grouped note per
  file.
- **Two untriaged leads from RFC 7155**: `Framed-IPX-Network` typed Unsigned32
  (clause 4.4.10.6.1's own sentence; RFC 4005 disagrees with itself here,
  clause 6.12.1 vs its table) against Wireshark's UTF8String; and
  `Framed-Appletalk-*`, which 7155 spells document-wide where 4005, RADIUS
  and Wireshark write `AppleTalk` — kept faithfully, erratum or name mapping
  undecided.
- **TS 29.217, untriaged**: `eNodeB-Id` and `Extended-eNodeB-Id`, which
  29.217 spells so throughout and Wireshark, like 29.272 and 29.336 (whose
  re-used rows are corrected to the origin's spelling), writes `-ID`.
- **TS 32.299, untriaged**: fourteen name casings (`User-Session-Id` against
  Wireshark's `User-Session-ID`), six type disagreements — two of them the
  Monitoring-Event rows its corrections type Enumerated after their clauses,
  where Wireshark follows table 7.2.0.1's Integer32 — and 47 absences.
