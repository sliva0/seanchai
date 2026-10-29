# Wireshark dictionary patches

Merge requests for Wireshark's Diameter dictionary, staged from the
[oracle](../../docs/oracle.md)'s Wireshark-side findings. Each one is
checked against the clause of the specification that defines the AVP, which
its commit message cites. None has been submitted.

The patches are `git format-patch` output against the release `specs.toml`
pins (`v4.7.2`), touching only `resources/protocols/diameter/`. Each patch
is one defect, and its commit message is the merge request's title and
description.

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

## Applying

In a Wireshark checkout, one branch per merge request:

```sh
git switch -c diameter-call-barring-info origin/master
git am -3 /path/to/seanchai/integrations/wireshark/0001-call-barring-info.patch
```

Every patch applies on its own to `v4.7.2`, and all eighteen apply in
order as one series; `-3` lets `git am` merge through context that has moved
on master since. `git am` keeps the patch's author; use
`git commit --amend --reset-author` to submit under your own.

Before pushing a rename, grep the checkout for the old name: a dissector or
a test may refer to it. A renamed AVP also renames its display filter field
(`diameter.<name>`), which each rename's description says.

## Checking

`seanchai crosscheck --dictionary <checkout>/resources/protocols/diameter`
over the corpus no longer reports a patched AVP; with all eighteen applied
to `v4.7.2`, it reports 71 findings instead of 90, and none that the
unpatched dictionary did not.
