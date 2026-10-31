# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Sources

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
  - a type no source states: TS 29.061's `3GPP-Session-Stop-Indicator`
    row prints only a code, flag cells included;
  - names no corpus document defines: RFC 4004's three SPI members, TS
    29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
    `External-Group-Identifier`, TS 32.299's `Submission-Timestamp` and
    `Network-Element`. *Decided:* these stay in the corpus as explicit
    broken names; the model must present them as such and offer the
    consumer resolution options (skip, keep as an untyped placeholder,
    accept a supplied definition). Design pending.
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
