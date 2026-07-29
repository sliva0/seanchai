# The Wireshark oracle

`src/seanchai/oracle.py` cross-checks extracted values against Wireshark's
Diameter dictionary — an independently maintained reading of the same
specifications, which is what makes it an oracle. The corpus's corrections
are otherwise justified by internal consistency alone (a clause checked
against the same document's own table), and only 29.329 has been verified by
hand; this is what lets the rest of the corpus's codes, vendor-ids and types
be checked at scale.

```sh
uv run seanchai download                          # fetches the dictionary too
uv run seanchai crosscheck dad/3gpp/rel-18/*.dad dad/rfc/*.dad
```

The dictionary arrives through the downloader like every other source: the
`[wireshark]` entry in `specs.toml` pins a release tag, and
`download_wireshark` fetches the whole `resources/protocols/diameter/`
directory (32 files — the dictionary is split across per-vendor XML entity
files, so `dictionary.xml` alone is useless) through GitLab's tree and raw
endpoints. Not a git submodule: a submodule is a whole repository, and
Wireshark's history is 1.2 GB for the 824 KB that matter. The manifest
records the directory as one artifact whose hash is the hash of the per-file
hashes in name order.

## What is compared, and what is deliberately tolerated

For every AVP a file *defines* — its definitions and its own AVP-table rows,
skipping re-used names, whose origin document is the one to check — the
cross-check resolves `(vendor-id, code)` in the dictionary and compares the
name and the type.

It is an oracle for values, not for the type vocabulary. Wireshark's
`typedefn`s include dissector conveniences, and the comparison maps each onto
the RFC 6733 types it stands for before it may call anything a disagreement:

- `IPAddress` agrees with `Address` *and* `OctetString` — NASREQ and the
  3GPP specs type their address-carrying AVPs OctetString (RFC 4005's
  `Framed-IP-Address`, 29.061's `3GPP-CG-Address`); `IPAddress` is how the
  dissector displays them.
- `Enumerated` agrees with `Enumerated`, `Unsigned32` and `Integer32` —
  Wireshark types any AVP with a value table `Enumerated` so the dissector
  shows labels, including RFC 6733's `Result-Code`, which the RFC types
  Unsigned32.
- `VendorId` and `AppId` stand for `Unsigned32`, `OctetStringOrUTF8` for
  either reading, `MIPRegistrationRequest` for `OctetString`.

An unmapped dictionary type is reported, never guessed at — the same closed
vocabulary discipline as the extractor's column labels.

Findings never fail the run, and — worth stating plainly — **Wireshark is
not a primary source**. It is a second, independent *reading* of the same
specifications, which is exactly what makes disagreement informative and
exactly why it settles nothing by itself: the dictionary lags releases,
carries its own typos, and deliberately disambiguates names the
specifications share. Every finding therefore gets evaluated against the
primary source — the specification clause both projects read — before
anything changes, and the fix goes wherever the mistake is: a corpus
correction when the extractor or the document's own table is wrong, a merge
request *into Wireshark* when the dictionary is (its `Call-Barring-
Infor-List` and `Accounting-Multi-Session-Id` are that case). Reflexively
patching `.dad` files to agree with the dictionary would just copy its
mistakes into the corpus.

## What the first run found

Fifty-seven findings over the 34-file corpus, in three shapes:

- **31 name disagreements**, most of them Wireshark's deliberate
  disambiguations (`Cx-User-Data`/`Sh-User-Data` for the two `User-Data`s,
  the `3GPP-SIP-*` prefixes, `Termination-Cause-3GPP`, `Wildcarded-PSI`) or
  XML-imposed spellings (`OnexRTT-RCID` for `1xRTT-RCID`, which cannot start
  an XML name). Those names are non-standard by construction — invented to
  keep one flat namespace unambiguous — and the corpus **always prefers the
  specification's own name**: `.dad` never adopts a Wireshark spelling, and
  a name correction may cite the dictionary as a witness but must justify
  itself from the specification. Disambiguation in the corpus is what
  `(vendor-id, code)` identity and the per-file scope are for. The place
  Wireshark's spellings *do* belong is the consumer-facing layer: where the
  dictionary's name differs, consumer output should carry it as an extra
  piece of information alongside the specification's, so tooling built on
  Wireshark-derived dictionaries can map between the two — the consumer-model
  item in [roadmap.md](roadmap.md) records this. The rest are one project or
  the other misreading: the
  dictionary corroborates 29.336's `Periodic-time` casing typo and
  RFC 4005's `Framed-Appletalk-*` (its ABNF and Wireshark both write
  `AppleTalk`), agrees with RFC 5777's ABNF against its own allocation table
  on `IP-Bit-Mask-Width` — both already on the linter's standing-findings
  list — and carries a few defects of its own (`Call-Barring-Infor-List`,
  `Accounting-Multi-Session-Id` for RFC 6733's `Acct-Multi-Session-Id`).
- **8 type disagreements** after the tolerated conventions, each a genuine
  two-readings case to settle against the source: the standout is RFC 5777's
  `Treatment-Action`, which the RFC's own allocation table types Grouped
  while its clause 5.1 says Enumerated — Wireshark read the clause, the
  extractor faithfully read the table, and the fix is a corpus correction
  citing 5.1.
- **18 absence groups** — AVPs the pinned dictionary does not carry, almost
  all newer than its coverage (the 5G-era additions in 29.214, the MC-service
  AVPs of 29.283, 29.272's NR trace parameters). Absence is dictionary lag,
  not disagreement, and is reported as one grouped note per file.

## The triage, and what stands after it

The first run's findings were triaged in July 2026, each against the
specification clause both projects read. The corpus-side fixes landed as
corrections: RFC 5777's `Treatment-Action` (Grouped in the allocation table,
Enumerated per clause 5.1) and `IP-Bit-Mask-Width` (clause heading and table
vs the clause body, ABNF and example), 29.336's `Periodic-time` casing,
RFC 4005's `Framed-Appletalk-*` table casing, 29.172's `Area-Identification`
(Grouped in the table, OctetString with a laid-out octet format in clause
7.4.42) and 29.061's `MBMS-Flag` (only the table cell drops the s of clause
20.5a.9's `MBMS-Flags`).

What still reports, and why each class stays:

- **Deliberate disambiguations and XML-imposed spellings** (the bulk of the
  name findings): `Cx-User-Data`/`Sh-User-Data`, the `3GPP-SIP-*` and
  `3GPP-Service-Type`/`3GPP-TWAN-Identifier`/`3GPP-PS-Data-Off-Status-Gx`
  prefixes, `Termination-Cause-3GPP`, `Wildcarded-PSI`, `S6-Service-ID`,
  `OnexRTT-RCID`, `CUI`, `Tunnel-Connection-ID`, `NAF-Hostname`. Correct on
  both sides; the consumer model is where the mapping belongs.
- **Wireshark-side defects**, merge-request candidates: `Call-Barring-
  Infor-List`, `Accounting-Multi-Session-Id`, `Authorization-Lifetime`
  typed Integer32 against RFC 6733 §8.9's Unsigned32, `3GPP-IPv6-DNS-Server`
  for 29.061's plural, `Slg-Location-Type` against 29.172's `SLg`,
  `PSR-Address` for 29.173's `PPR-Address`, `MBMS-Flag` (fixed in the
  corpus, the dictionary agrees with the clause).
- **Display conveniences the mapping does not tolerate**, correct in the
  corpus: `3GPP-NSAPI`, `Codec-Data`, `Framed-Pool` and `EAP-Key-Name`
  typed UTF8String where the specifications say OctetString, and
  `Cell-Portion-ID` typed OctetString against 29.172's Unsigned32.
- **Absences** — dictionary lag, unchanged.

Per the note above, none of the Wireshark-side defects patches the corpus;
each is a per-finding candidate for a merge request into Wireshark, which is
work this repository can only stage, not land.

## After RFC 7155's codes became checkable (July 2026)

The `prose-avp-codes` quirk (see [extractor.md](extractor.md#quirks)) gave
RFC 7155's 77 AVPs their codes and types, so the crosscheck can match them
for the first time. Four of the six findings it reports are new instances of
already-triaged classes: `Framed-Pool` (display convenience, above) and
`Acct-Tunnel-Connection` against Wireshark's `Tunnel-Connection-ID`
(deliberate disambiguation, above). Two are untriaged leads:

- **`Framed-IPX-Network` typed Unsigned32 against Wireshark's UTF8String.**
  The corpus value is RFC 7155 clause 4.4.10.6.1's own sentence — and RFC
  4005 already disagreed with *itself* here: its clause 6.12.1 also says
  Unsigned32 while its summary table prints UTF8String, which is the cell
  the corpus (and, apparently, Wireshark) carries for 4005. A reader with
  both documents and RFC 2865 open should decide which side a merge request
  argues.
- **`Framed-Appletalk-Link`/`-Network`/`-Zone` casing.** RFC 7155 spells
  `Appletalk` consistently — headings, ABNF and tables alike — where RFC
  4005's clauses, RADIUS and Wireshark spell `AppleTalk`. Unlike 4005's
  table-only slip (corrected in the triage), this is 7155's document-wide
  spelling, so the corpus keeps it faithfully; whether it is worth an
  erratum or a consumer-model name mapping is the open question.
