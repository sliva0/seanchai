# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Sources

- **K. Value ranges the format cannot hold.** SM-Service-Type's "100 ..
  199 Vendor specific SM services", and oneM2M TS-0004's Protocol-Type
  "100 .. 199 Operator and vendor specific protocol types", allocate a
  range of enumerated values, which the format has no line for.
  *Decided:* add a `; VENDOR-SPECIFIC = 100-199` body line beside
  `; RESERVED`, with parser, formatter, linter overlap check and a model
  field the generator can allow.
- **O. Stand in for RFC 4590.** RFC 4590 is a RADIUS document and types
  nothing; RFC 4740 imports its nineteen Digest AVPs and SIP-AOR by name
  only. *Decided:* a hand-written stand-in `.dad` (like the TISPAN
  transcriptions) typing all twenty UTF8String, each with its evidence:
  RFC 4590's "text" fields, TS 29.229 clause 6.3.37-41 for the four it
  re-uses, Wireshark's dictionary for the rest.
- **P. One document extending another's enumeration.** RFC 8581 §7.2.1
  adds `PEER_REPORT = 2` to RFC 7683's OC-Report-Type; the extractor
  drops it with a warning because an Enumerated section's header rule
  claims the definition. It is the only such case in the corpus.
  *Decided:* a correction on RFC 7683 adding the value, its comment citing
  RFC 8581 §7.2.1.
- **Q. Registry documents the corpus lacks.** TS 29.153 (Ns, current to
  Rel-19) and TS 32.296 (Re, current to Rel-19) have current versions and
  can be extracted the usual way. TS 29.211 (last V6.4.0), TS 29.210 (last
  V6.7.0) and TS 29.234 (last V11.2.0) are retired and would be pinned.
  Single rows for TS 29.228 and 29.328 are registry pointers at procedure
  documents. *Decided:* extract 29.153 and 32.296; retired three only if a
  corpus document resolves into them.
- **R. Fill `; Values:` lists pointed elsewhere.** 100 sections in 11
  files. *Decided:* fill from the cited source as a corrections-supplied
  list with the source and its date or version recorded; TS 32.422 trace
  parameters and ICMP types first, IANA RADIUS registries as a dated
  snapshot, OMNA content types last.

## Consumers

- **N. Build the model strictly by default** once the committed corpus
  builds under `strict=True`. What stands in the way, by cause (the pinned
  `_STANDING_HOLES` in `tests/test_model.py`):
  - types no source states: RFC 4590 (see O); TS 29.061's
    `3GPP-Session-Stop-Indicator` row prints only a code, flag cells
    included;
  - names no corpus document defines: RFC 4004's three SPI members, TS
    29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
    `External-Group-Identifier`, TS 32.299's `Submission-Timestamp` and
    `Network-Element`. *Decided:* these stay in the corpus as explicit
    broken names; the model must present them as such and offer the
    consumer resolution options (skip, keep as an untyped placeholder,
    accept a supplied definition). Design pending.
  - a name undefined in the citing document, which another corpus document
    defines under the same name without being cited: TS 32.299's
    `TCP-Source-Port` (TS 29.212; table 7.2.0.1 refers to [215] for
    `UDP-Source-Port` only). *Decided:* a correction adding the re-used
    row.
  - what oneM2M TS-0004's `Service-Information` reaches in TS 32.299
    V11.20.0, the version its reference [31] names: forty-one members
    re-used from Release 11's TS 29.061, 29.173, 29.212, 29.214, 29.229,
    29.272, 29.273 and 29.329, and three OMA-DDS-Charging_Data rows.
    Release 18 defines all forty-four names with the same codes; the three
    OMA ones TS 32.299 itself now defines. *Decided:* resolve to the
    Release 18 copies where code, type and flags agree, marked
    `across_releases`; pin a Release 11 document only where a grouped
    member list or flag rule differs materially. Comparison pending.

## Oracle

- **S. Deliberate renames are not disagreements.** Wireshark's
  disambiguations (`Cx-User-Data`, `Sh-User-Data`, …) count among the 52
  `name-disagrees` findings. *Decided:* an accepted-aliases list; a
  renamed AVP whose code, vendor and type agree is agreement.
