# The Wireshark oracle

`src/seanchai/oracle.py` cross-checks every AVP a file defines, its
definitions and own AVP-table rows, skipping any name the file also lists
as re-used, against Wireshark's Diameter dictionary
by `(vendor-id, code)`, comparing name and type. The dictionary is an
independent reading of the same specifications, which is what makes
disagreement informative. A row's vendor is read as the model reads it
([linter.md](linter.md#vendor-spaces)).

```sh
uv run seanchai download          # fetches the dictionary too
uv run seanchai crosscheck        # the installed corpus, or name files
```

The check reads the newest copy of each document and no other: the
dictionary describes a document, and an older copy the corpus holds for a
citation across releases is no reading of it. `crosscheck` lists each older
copy it skips and refuses two files of one document and version.

The `[wireshark]` entry in `specs.toml` pins a release tag; the downloader
fetches the whole `resources/protocols/diameter/` directory through
GitLab's tree and raw endpoints.

## Tolerated type conventions

Wireshark's `typedefn`s include dissector conveniences, mapped before
anything is called a disagreement: `IPAddress` agrees with `Address` and
`OctetString`; `Enumerated` agrees with `Enumerated`, `Unsigned32` and
`Integer32`; `VendorId` and `AppId` stand for `Unsigned32`,
`OctetStringOrUTF8` for either reading, `MIPRegistrationRequest` for
`OctetString`. An unmapped dictionary type is reported, never guessed at.

## Accepted renames

Wireshark names some AVPs otherwise on purpose: its dictionary's `name` is
an XML ID, unique across the dictionary and starting with no digit, and
doubles as the display filter field, so of two documents' AVPs of one name
one is renamed (TS 29.229's `User-Data` is `Cx-User-Data`, TS 29.329's
`Sh-User-Data`). Such a rename is agreement when
[`integrations/wireshark/aliases.toml`](../integrations/wireshark/aliases.toml)
lists it: each `[[alias]]` gives the document, the corpus's name, the
dictionary's and a reason. `crosscheck` reads the file (`--aliases`, by
default that path), counts accepted renames in its summary line, and prints
them only with `--show-accepted`. An entry accepts only while the
dictionary's entry under the AVP's vendor and code carries the listed name
and agrees in type; otherwise it is reported as `stale-alias`. A corpus AVP
stating no type confirms no rename: its name disagreement stays a finding.

The list holds the `3GPP-SIP-*` prefixes TS 29.229's and TS 32.299's SIP
AVPs take to stay apart from RFC 4740's, `Cx-` and `Sh-User-Data`,
`OnexRTT-RCID` for an ID starting with a digit, `ETSI-Service-Class`, and
a dozen more of the same kind. A misspelling is no rename and is not
listed: those are defects, patched. Nor is a name the document has since
replaced.

## Findings are leads, not verdicts

Wireshark is not a primary source. It lags releases, carries its own typos,
and deliberately disambiguates names the specifications share. Every
finding is evaluated against the clause both projects read, and the fix
goes where the mistake is: a corpus correction when the document's own
table or the extractor was wrong, a merge request into Wireshark when the
dictionary is. The corpus always keeps the specification's own spelling.

## In the model

`model.Model.build(books, dictionary=Path("specifications/wireshark"))`
gives every AVP, and every hole with an identity, Wireshark's name for its
`(vendor-id, code)` in `wireshark_name`. `name` stays the document's. Where
the identity collides in the dictionary, an entry spelled like the corpus
wins, then the one whose type agrees; an identity the dictionary lacks,
or cannot settle between several names, is None. `Oracle.name_for` is the
lookup.

## What still reports

- **Names the documents have replaced**, which the dictionary keeps:
  `Wildcarded-PSI` for TS 29.229's `Wildcarded-Public-Identity` and
  `NAF-Hostname` for TS 29.109's `NAF-Id`. Not accepted renames; a merge
  request could bring either up to date.
- **`CUI`** for RFC 5778's `Chargeable-User-Identity`, RFC 4372's own
  abbreviation, which would be an accepted rename but for its type.
- **Wireshark-side defects**, each with a merge request staged under
  [`integrations/wireshark/`](../integrations/wireshark/README.md): misspelt
  names, wrong types and member lists short of the document's. Three the
  oracle cannot see, since the AVP is re-used or the defect is a member
  list: `Application-Server-ID` typed Unsigned32 where OMA's table says
  UTF8String, `UWAN-User-Location-Info` missing four members, and
  `Time-Of-Day-Condition` missing the three members erratum 2333 restores.
- **Leads not staged**, resting on a reading the corpus makes rather than a
  document's statement: `Monitoring-Event-Information` listing TS 29.336's
  `Monitoring-Event-Report` where the corpus corrects the member to TS
  32.299's own `Monitoring-Event-Report-Data`; `Charging-Characteristics`
  typed OctetString where no document settles the type; and
  `mobileipv4.xml`'s MSA members, which no source gives.
- **Display conveniences the mapping does not tolerate**: `3GPP-NSAPI`,
  `Codec-Data`, `Framed-Pool`, `EAP-Key-Name` and `Access-Network-Information`
  typed UTF8String where the specifications say OctetString.
- **Absences**: AVPs newer than the pinned dictionary, one grouped note per
  file. Most have an addition staged under
  [`integrations/wireshark/additions/`](../integrations/wireshark/README.md#additions).
  oneM2M's are not among them: the dictionary declares no vendor 45687,
  and adding one is a merge request of another shape.
- **Untriaged**: RFC 7155's `Framed-IPX-Network` typed Unsigned32 against
  Wireshark's UTF8String, where RFC 4005 disagrees with itself; RFC 7155's
  `Framed-Appletalk-*` against everyone else's `AppleTalk`;
  `Tunnel-Connection-ID` for RFC 4005's `Acct-Tunnel-Connection`, intent
  unverified; and TS 32.299 AVPs where the document disagrees with itself
  and Wireshark took the other reading (`EPDG-Address`, `Service-ID`,
  `MMTel-SService-Type`).
