# Wireshark dictionary patches

The plugin checking Diameter traffic against the corpus is under
[`validator/`](validator/README.md).

Merge requests for Wireshark's Diameter dictionary, staged from the
[oracle](../../docs/oracle.md)'s findings, in two series. None has been
submitted.

- **Defects**, `0001` to `0026` here: entries the dictionary holds wrongly,
  a misspelt name, a wrong type or a member list short of the document's,
  each checked by hand against the clause that defines the AVP, or the
  verified erratum correcting it, which its commit message cites. One
  defect per patch.
- **Additions**, under [`additions/`](additions/): AVPs the dictionary has
  no entry for, one patch per defining document, written by `additions.py`
  from the corpus. Nothing the dictionary holds changes.

Both are `git format-patch` output against the release `specs.toml` pins
(`v4.7.2`), touching only `resources/protocols/diameter/`, and each patch's
commit message is the merge request's title and description.

[`aliases.toml`](aliases.toml) lists the renames that are no defect: names
the dictionary gives an AVP on purpose, mostly to keep it apart from another
document's AVP of the same name. The oracle counts them as accepted renames
([oracle.md](../../docs/oracle.md#accepted-renames)); no patch touches them.

## Defects

| Patch | Dictionary says | Specification says | Where |
|---|---|---|---|
| 0001 | `Call-Barring-Infor-List` | `Call-Barring-Info` | TS 29.272 clause 7.3.101 |
| 0002 | `Accounting-Multi-Session-Id` | `Acct-Multi-Session-Id` | RFC 6733 section 9.8.5 |
| 0003 | `Authorization-Lifetime` Integer32 | Unsigned32 | RFC 6733 section 8.9 |
| 0004 | `3GPP-IPv6-DNS-Server` | `3GPP-IPv6-DNS-Servers` | TS 29.061 clause 16.4.7.2 |
| 0005 | `Slg-Location-Type` | `SLg-Location-Type` | TS 29.172 clause 7.4.2 |
| 0006 | `PSR-Address` | `PPR-Address` | TS 29.173 clause 6.4.9 |
| 0007 | `eNodeB-ID`, `Extended-eNodeB-ID` | `eNodeB-Id`, `Extended-eNodeB-Id` | TS 29.217 clauses 5.3.10, 5.3.15 |
| 0008 | `Cellular-Network-Information ` (trailing space) | `Cellular-Network-Information` | TS 32.299 clause 7.2.35A |
| 0009 | `IP-Realm-Default-Indicator` | `IP-Realm-Default-Indication` | TS 32.299 clause 7.2.80A |
| 0010 | `ISUP-Release-Cause` | `ISUP-Cause` | TS 32.299 clause 7.2.80B |
| 0011 | `Local-GW-Inserted-Indicator` | `Local-GW-Inserted-Indication` | TS 32.299 clause 7.2.92A |
| 0012 | `Number-of-Messages-Sent` | `Number-Of-Messages-Sent` | TS 32.299 clause 7.2.116 |
| 0013 | `Transcoder-Inserted-Indicator` | `Transcoder-Inserted-Indication` | TS 32.299 clause 7.2.233A |
| 0014 | `User-Session-ID` | `User-Session-Id` | TS 32.299 clause 7.2.242 |
| 0015 | `From-Address` IPAddress | UTF8String | TS 32.299 clause 7.2.67A |
| 0016 | `ISUP-Cause-Location` OctetString | Unsigned32 | TS 32.299 clause 7.2.80D |
| 0017 | `Number-Of-Participants` Integer32 | Unsigned32 | TS 32.299 clause 7.2.117 |
| 0018 | `Cell-Portion-ID` OctetString | Unsigned32 | TS 29.172 clause 7.4.58 |
| 0019 | `IP-Bit-Mask-Width` | `IP-Mask-Bit-Mask-Width` | RFC 5777 erratum 2335 (verified) |
| 0020 | `Time-Of-Day-Condition` without three members | `Absolute-Start-Fractional-Seconds`, `Absolute-End-Fractional-Seconds`, `Timezone-Offset` | RFC 5777 erratum 2333 (verified) |
| 0021 | `Application-Server-ID` Unsigned32 | UTF8String | OMA-DDS-Charging_Data V1.0 table 11, which TS 32.299 table 7.2.0.1 refers to |
| 0022 | `UWAN-User-Location-Info` without four members | `TCP-Source-Port`, `Civic-Address-Information`, `WLAN-Operator-Id`, `Logical-Access-ID` | TS 32.299 clause 7.2.242aaA |
| 0023 | `Initial-Gate-Setting` | `Initial-Gate-Setting-Description` | ETSI ES 283 034 clause 7.3.4 |
| 0024 | `QoS-Profile` | `QoS-Profile-Description` | ETSI ES 283 034 clause 7.3.5 |
| 0025 | `Requested-Information-457` | `Latching-Indication` | ETSI TS 183 017 clause 7.3.8 |
| 0026 | `PDP-Session-operation` | `PDP-Session-Operation` | TS 29.210 clause 5.2.21 |

## Additions

```sh
uv run integrations/wireshark/additions.py   # rewrites additions/
```

Each entry is written in the shape of the entries around it: name, code,
`vendor-id`, a `<type>` with an `<enum>` per value of an enumerated AVP or
a `<grouped>` with a `<gavp>` per member, `mandatory` and `vendor-bit`
from the document's flag rules, and `may-encrypt` where its AVP table has
the column. Values a correction supplies from a cited document are
included, and the description says which. Corpus types map to the
dictionary's typedefns one to one, except `Address`, written `IPAddress`.
A member is named as the dictionary names it (`Cx-User-Data`), or as the
ABNF does where no entry carries it. Where a document states no M bit,
`mandatory` is left at the DTD's default and the description says so.

An entry goes after the dictionary entry of its vendor with the nearest
lower code, its own document's entries first. A place within three lines
of another patch's, or of a line a defect patch changes, is passed over,
so every addition applies to `v4.7.2` on its own, all apply in order, and
all apply after the defects; the script checks this before it writes, and
its output is the same byte for byte on every run
(`tests/test_wireshark_additions.py` pins it).

| Patch | Document | Entries | File |
|---|---|---|---|
| 0001 | TS 29.061 | 4 | `TGPP.xml` |
| 0002 | TS 29.109 | 1 | `dictionary.xml` |
| 0003 | TS 29.128 | 4 | `TGPP.xml` |
| 0004 | TS 29.153 | 2 | `dictionary.xml` |
| 0005 | TS 29.154 | 15 | `dictionary.xml` |
| 0006 | TS 29.172 | 1 | `dictionary.xml` |
| 0007 | TS 29.212 | 1 | `dictionary.xml` |
| 0008 | TS 29.214 | 19 | `TGPP.xml` |
| 0009 | TS 29.215 | 4 | `TGPP.xml` |
| 0010 | TS 29.217 | 12 | `dictionary.xml` |
| 0011 | TS 29.219 | 1 | `dictionary.xml` |
| 0012 | TS 29.229 | 8 | `TGPP.xml` |
| 0013 | TS 29.272 | 8 | `dictionary.xml` |
| 0014 | TS 29.273 | 1 | `dictionary.xml` |
| 0015 | TS 29.283 | 15 | `dictionary.xml` |
| 0016 | TS 29.329 | 3 | `TGPP.xml` |
| 0017 | TS 29.336 | 2 | `dictionary.xml` |
| 0018 | TS 29.338 | 3 | `TGPP.xml` |
| 0019 | TS 29.343 | 13 | `TGPP.xml` |
| 0020 | TS 29.345 | 65 | `TGPP.xml` |
| 0021 | TS 29.368 | 1 | `dictionary.xml` |
| 0022 | TS 29.388 | 5 | `dictionary.xml` |
| 0023 | TS 29.389 | 3 | `dictionary.xml` |
| 0024 | TS 29.468 | 14 | `TGPP.xml` |
| 0025 | TS 29.561 | 26 | `TGPP.xml` |
| 0026 | TS 32.299 | 46 | `dictionary.xml` |
| 0027 | ETSI TS 183 017 | 2 | `etsie2e4.xml` |
| 0028 | ETSI TS 183 059-1 | 4 | `etsie2e4.xml` |
| 0029 | RFC 5777 | 1 | `dictionary.xml` |
| 0030 | RFC 5866 | 2 | `dictionary.xml` |
| 0031 | RFC 6734 | 6 | `dictionary.xml` |
| 0032 | RFC 6736 | 13 | `dictionary.xml` |
| 0033 | RFC 6738 | 8 | `dictionary.xml` |
| 0034 | RFC 6942 | 2 | `dictionary.xml` |
| 0035 | RFC 8506 | 11 | `dictionary.xml` |
| 0036 | RFC 8582 | 1 | `dictionary.xml` |

Some absences stay out, named in their document's description:

- **Named like another entry.** Wireshark names each display filter field
  after its AVP, so a second entry named alike collides, and which of the
  two is renamed is a maintainer's call: TS 29.345's `Filter-Id` and
  `MAC-Address`, TS 29.283's `Sequence-Number`, TS 29.468's
  `MBMS-GW-SSM-IP-Address` and `-IPv6-Address`, TS 32.299's
  `Radio-Frequency`, and `Time-Window`.
- **Grouped with no members to list**, which the DTD's `<grouped>` cannot
  hold: RFC 5777's `QoS-Capability` and TS 29.128's
  `APN-Rate-Control-Status`.
- **A vendor the dictionary does not declare**: oneM2M TS-0004's AVPs in
  vendor 45687. Adding the vendor, its file and its entity is a merge
  request of another shape.

## Applying

In a Wireshark checkout, one branch per merge request:

```sh
git switch -c diameter-call-barring-info origin/master
git am -3 /path/to/seanchai/integrations/wireshark/0001-call-barring-info.patch
```

Every defect patch applies on its own to `v4.7.2`, and all apply in order
as one series; `-3` lets `git am` merge through context that has moved on
master. `git am` keeps the patch's author; use `git commit --amend
--reset-author` to submit under your own.

Before pushing a rename, grep the checkout for the old name: a dissector
or a test may refer to it. A renamed AVP also renames its display filter
field (`diameter.<name>`), which each rename's description says.

## Checking

`seanchai crosscheck --dictionary <checkout>/resources/protocols/diameter dad`
over the corpus no longer reports a patched AVP. The accepted renames hold
against the patched dictionary too.
