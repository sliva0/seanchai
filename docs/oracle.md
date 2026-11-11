# The Wireshark oracle

`seanchai corpus crosscheck` compares the corpus with Wireshark's Diameter
dictionary, an independent reading of the same documents. For each AVP a file
defines, in a definition or its own AVP-table row, it looks up the
`(vendor-id, code)` in the dictionary and compares name and type. Names the
file lists as re-used are skipped. A row's vendor is read as the model reads
it ([linter.md](linter.md#vendor-spaces)).

```sh
seanchai corpus download --only wireshark   # all it needs downloaded
seanchai corpus crosscheck                  # the installed corpus, or name files
```

- It checks only the newest copy of each document, since the dictionary
  describes that one. It lists each older copy it skips, and refuses two
  files of one document and version.
- Findings are reports for a reader to judge, so they never fail the run.
- The `[wireshark]` entry in `specs.toml` pins a Wireshark release tag. The
  downloader fetches its `resources/protocols/diameter/` directory.

## Tolerated type conventions

Some of Wireshark's types are dissector conveniences. These count as
agreement:

| Wireshark | Agrees with |
|---|---|
| `IPAddress` | `Address`, `OctetString` |
| `Enumerated` | `Enumerated`, `Unsigned32`, `Integer32` |
| `VendorId`, `AppId` | `Unsigned32` |
| `OctetStringOrUTF8` | `OctetString`, `UTF8String` |
| `MIPRegistrationRequest` | `OctetString` |

Any other dictionary type that does not match is reported.

## Accepted renames

Wireshark renames some AVPs on purpose. Its `name` is an XML ID, so it must
be unique and must not start with a digit, and it doubles as the display
filter field. Of two documents' AVPs with one name, one gets renamed: TS
29.229's `User-Data` is `Cx-User-Data`, TS 29.329's is `Sh-User-Data`.

[`integrations/wireshark/aliases.toml`](../integrations/wireshark/aliases.toml)
lists these renames. Each `[[alias]]` gives the document, the corpus's name,
the dictionary's name and a reason. `crosscheck` reads it (`--aliases`,
defaulting to that path), counts accepted renames in its summary line, and
prints them with `--show-accepted`. An alias holds only while the dictionary's
entry for the AVP's vendor and code has the listed name and agrees in type;
otherwise `crosscheck` reports `stale-alias`. A corpus AVP with no type cannot
confirm a rename, so its name disagreement stays a finding.

The list holds, among others:

- the `3GPP-SIP-*` prefixes that keep TS 29.229's, X.S0013-006's and TS
  32.299's SIP AVPs apart from RFC 4740's;
- `Cx-User-Data` and `Sh-User-Data`;
- `OnexRTT-RCID`, for an ID that would start with a digit;
- `ETSI-Service-Class`;
- the `3GPP2-` prefixes that keep X.S0013-014's AVPs apart from TS 29.212's.

A misspelling is a defect and gets a patch, so it is not listed. Neither is a
name the document has since replaced.

## Findings are leads

Wireshark is not a primary source: it lags releases, has its own typos and
renames shared names. Check each finding against the clause both projects
read. Fix the corpus with a correction when the document's table or the
extractor was wrong, and send Wireshark a merge request when the dictionary
is. The corpus always keeps the document's spelling.

## Value tables

The dictionary has `<enum>`s for `Result-Code`, `Experimental-Result-Code`
and a few bit masks. `value-disagrees` reports a value-table row the
dictionary names differently. `value-absent-from-dictionary` reports, once
per table, the numbers the dictionary lacks for an AVP it enumerates. An AVP
the dictionary enumerates none of is not reported.

On the committed corpus these report:

| Corpus | Dictionary |
|---|---|
| TS 29.283's `DIAMETER_ERROR_UNKNOWN_DATA` | `UNKNKOWN`, copying TS 29.230's misprint |
| `DIAMETER_ERROR_TRANSPARENT_DATA_OUT_OF_SYNC` with a space (TS 29.283, 29.329, 29.330, 29.230) | an `_` |
| TS 29.219's `DIAMETER_ERROR_NO_AVAILABLE_POLICY_COUNTERS` | an `LCS_CLIENT` tail |
| RFC 6733's `ELECTION_LOST` | `DIAMETER_ELECTION_LOST` |
| TS 29.344's name | `PROSE_NOT_ALLOWED` |
| TS 29.234's code | `DIAMETER_ERROR_W-DIAMETER_ERROR_NO_ACCESS_INDEPENDENT_SUBSCRIPTION` |
| TS 29.109's `DIAMETER_ERROR_IDENTITY_UNKNOWN` | the registry's `IMPI` |
| bit 0 of TS 29.212's `Presence-Reporting-Area-Node`, `OCS` | `PCRF` |

## In the model

`model.Model.build(corpus, wireshark=Path("specifications/wireshark"))` sets
`wireshark_name` on every AVP, and every hole with an identity, to
Wireshark's name for its `(vendor-id, code)`. `name` stays the document's.
Where several dictionary entries share the identity, one spelled like the
corpus wins, then one whose type agrees. An identity the dictionary lacks or
cannot settle gets None. `Oracle.name_for` does the lookup.

## What still reports

- A name no document gives: the dictionary calls ETSI TS 183 066's
  `Data-Operation-Indicator` (13019, 420) `ETSI-Event-Type-420`, though it
  cites that document. A merge request should fix it.
- Types the dictionary reads differently: 3GPP2 X.S0013-014's
  `Flow-Identifier` (OctetString, dictionary UTF8String);
  OMA-DDS-Charging_Data's `Application-Server-ID` (UTF8String in table 11,
  dictionary Unsigned32).
- Names the documents have replaced: `Wildcarded-PSI` for TS 29.229's
  `Wildcarded-Public-Identity`, `NAF-Hostname` for TS 29.109's `NAF-Id`. A
  merge request could update either.
- `CUI` for RFC 5778's `Chargeable-User-Identity`, RFC 4372's abbreviation. It
  would be an accepted rename if its type agreed.
- Wireshark defects with a merge request staged under
  [`integrations/wireshark/`](../integrations/wireshark/README.md): misspelt
  names, wrong types, and short member lists. Two of these the oracle cannot
  see, because the defect is a member list: `UWAN-User-Location-Info` lacks
  four members, and `Time-Of-Day-Condition` lacks the three that erratum 2333
  restores.
- Leads not staged, because they rest on the corpus's reading and not on a
  document's statement: `Monitoring-Event-Information` lists TS 29.336's
  `Monitoring-Event-Report` where the corpus corrects the member to TS
  32.299's `Monitoring-Event-Report-Data`; `Charging-Characteristics` is typed
  OctetString where no document settles the type; `mobileipv4.xml`'s MSA
  members appear in no source.
- Display conveniences the mapping does not tolerate: `3GPP-NSAPI`,
  `Codec-Data`, `Framed-Pool`, `EAP-Key-Name` and `Access-Network-Information`
  typed UTF8String where the documents say OctetString.
- Absences: AVPs newer than the pinned dictionary, one grouped note per file.
  Most have an addition staged under
  [`integrations/wireshark/additions/`](../integrations/wireshark/README.md#additions).
  oneM2M's do not: the dictionary declares no vendor 45687, and adding one
  needs a different kind of merge request.
- Untriaged:
  - RFC 7155's `Framed-IPX-Network`, Unsigned32 against Wireshark's
    UTF8String, where RFC 4005 disagrees with itself;
  - RFC 7155's `Framed-Appletalk-*` against everyone else's `AppleTalk`;
  - `Tunnel-Connection-ID` for RFC 4005's `Acct-Tunnel-Connection`, intent
    unverified;
  - TS 32.299 AVPs where the document disagrees with itself and Wireshark
    took the other reading (`EPDG-Address`, `Service-ID`,
    `MMTel-SService-Type`).
