# Interpreted constraints

A `.dad` file says what a document prints as structure: an AVP is an
`OctetString`, an `Unsigned32`. The clause defining the AVP says more, in
prose: "encoded as a TBCD-string", "in the range of 0 to 255", "shall only be
present when Non-IP-PDN-Type-Indicator is set to TRUE (1)". No extractor reads
that reliably, so a person reads the clause and writes down what it says,
pinned to the sentences read. The corpus calls the result interpreted
constraints.

## What "interpreted" means

Everything else in the corpus is what a document prints, or a correction of
it with its reason. An interpreted constraint is a reading of prose: someone
decided that "It should consist of 14 digits ... It may also include a 15th
digit" means `length 14..15 digits` of `digits`. The corpus keeps that apart
from the printed facts, so a consumer can weigh it:

- The blocks are written by hand, one file per document, in the document's
  interpretations file, `edits/interpretations/TS29.272.dadx`, in the block
  syntax itself ([below](#the-interpretations-file)). Only a corrected file
  holds them, `; Type: Interpreted Constraints`; the raw file is what the
  extractor read. A note on each block's `; Type:` line cites the block it
  was merged from (`;; interpreted: (TS29.272.dadx#imei-digits)`).
- Each rule stands after the sentences it was read from, verbatim. Rebuilding
  the corpus from the documents checks every sentence against its clause, and
  fails when the document no longer prints it, as a correction does when the
  document is fixed. The block's page is the clause's in that copy's PDF.
- `; Versions:` is the range of the document's versions the reading was
  checked against. A reading is carried to another release's copy only once
  its sentences are found there, and is otherwise left out of that copy: of
  TS 29.272's 157, Release 18's copy holds 152
  ([below](#the-interpretations-file)).
- The model's `Constraint`, the dictionary's and the export's say
  `interpreted`; the Wireshark plugin reports a breach as a note, whatever
  the quote's wording, its line ending in `interpreted`
  ([wireshark-plugin.md](wireshark-plugin.md#findings)).
- What no kind below expresses is recorded as `text-only`: the quote, and no
  rule a checker could run. A checker reports it unknown, never a guess.

Trust a rule as far as you trust its quote. Where the quote says "should", or
is a NOTE, the rule is the reader's; read the quote before rejecting traffic
on it.

## The block

[grammar.md](grammar.md#interpreted-constraints) defines it. Each kind, as
TS 29.272's file prints it:

```dad
; Type: Interpreted Constraints ;; interpreted: (TS29.272.dadx#imei-digits)
; AVP: IMEI
; Section: 7.3.4
; Page: 100
; Versions: 19.6.0
"It should consist of 14 digits, including the 8-digit Type Allocation Code (TAC) and the 6-digit Serial Number (SNR). It may also include a 15th digit."
    encoding digits
    length 14..15 digits


; Type: Interpreted Constraints ;; interpreted: (TS29.272.dadx#ue-usage-type-range)
; AVP: UE-Usage-Type
; Section: 7.3.202
; Page: 166
; Versions: 19.6.0
"The allowed values of UE-Usage-Type shall be in the range of 0 to 255."
    range 0..255


; Type: Interpreted Constraints ;; interpreted: (TS29.272.dadx#apn-configuration-non-ip-delivery)
; AVP: Non-IP-Data-Delivery-Mechanism
; Within: APN-Configuration
; Section: 7.3.35
; Page: 128
; Versions: 19.6.0
"The Non-IP-Data-Delivery-Mechanism shall only be present when Non-IP-PDN-Type-Indicator is set to TRUE (1)."
    requires Non-IP-PDN-Type-Indicator = TRUE
```

| Kind | Example | Holds when |
|---|---|---|
| `length` | `length 3 octets`, `length 14..15 digits`, `length 1..* characters` | the payload's octets, the digits its encoding carries, or its UTF-8 characters are within the bounds |
| `range` | `range 0..255`, `range -1..*` | the integer value is within the bounds |
| `exclude` | `exclude 0` | the integer value is none of these |
| `encoding` | `encoding plmn-id`, `encoding element TS29.002 17.7.8 "E-UTRAN-CGI"` | the payload is laid out as the codec, or the element registry's entry, says |
| `present-if` | `present-if Result-Code = DIAMETER_SUCCESS` | the AVP is present when a condition holds |
| `absent-if` | `absent-if Emergency-Services bit Emergency-Indication` | the AVP is absent when a condition holds |
| `requires` | `requires DSR-Flags bit "Trace Data Withdrawal"` | a condition holds when the AVP is present |
| `excludes` | `excludes Other-AVP` | no condition holds when the AVP is present |
| `default` | `default FALSE`, `default 0` | (what an absent AVP is read as) |
| `bits` | `bits at-most-one 3 6`, `bits at-least-one 0 1`, `bits set 1`, `bits clear 4 5 6 7`, `bits only 9` | of these bits of the AVP's own value, at most one is set, at least one, each is set, each is clear, or none but these is set |
| `members` | `members at-least-one SCEF-Reference-ID SCEF-Reference-ID-Ext`, `members only IMEI Software-Version` | of the grouped AVP's members, at least one of these is present (one name: it is), or none but these |
| `unique` | `unique` | no two of the `; Within:` grouped AVPs beside each other hold the AVP with the same value |
| `values` | `values 1 if Monitoring-Type = 1` | the integer value is one of these when a condition holds |
| `text-only` | `text-only` | (a reader decides) |

A predicate's conditions, and a `values` rule's, are alternatives (`or`), each
on a sibling in the block's `; Command:` or `; Within:` grouped AVP: present,
holding a value (a number, or a name its values or result codes give it), or
with a bit set (a number, or its bit table's name). Several predicates in one
block must all hold. `absent-if` and `excludes` say the same of a presence
condition, read from the other side; the kinds follow the clause's wording.
Without a scope the rules hold wherever the document reads the AVP, and a
predicate there has no siblings to test.

A `bits` rule numbers bits as the AVP's bit table does, bit 0 the least
significant; an OctetString's bits are those of its octets read as one
big-endian number, so `bits clear 4 5 6 7` is a one-octet AVP's four most
significant bits. `members` says of a grouped AVP what `bits` says of a flags
AVP, by member name. `unique` holds across the grouped AVPs one body holds, and
needs `; Within:`: TS 29.272's Service-Selection within APN-Configuration
differs from one APN-Configuration of an APN-Configuration-Profile to the next.
There is no kind for "should": a rule read from "should" is a rule like any
other, its quote saying how far to trust it.

## Codecs

The set is closed, and holds the layouts TS 29.272's clauses name. A layout
no clause states is not here.

| Codec | Layout | Defined in |
|---|---|---|
| `e164-tbcd` | an international number, ITU-T E.164 (1 to 15 decimal digits), as a TBCD-string: two digits an octet, the first in bits 1-4, "1111" filling bits 5-8 of the last octet after an odd count; no octet for the nature of address and numbering plan | TS 29.002 clause 17.7.8, as TS 29.272 clauses 7.3.39, 7.3.85, 7.3.91, 7.3.102, 7.3.157 and 7.3.159 say |
| `plmn-id` | MCC and MNC in 3 octets: MCC digits 2 and 1, then MNC digit 3 (or "1111" for a 2-digit MNC) and MCC digit 3, then MNC digits 2 and 1 | TS 29.272 table 7.3.9/1, after TS 24.008 clause 10.5.1.13 |
| `plmn-id-prefix` | a `plmn-id` in the first 3 octets, more octets after it | TS 29.272 table 7.3.64/1 (Trace-Reference) |
| `digits` | decimal digits as text, a character each | TS 29.272 clauses 7.3.4, 7.3.5, 7.3.50 |
| `labels` | one or more non-empty labels separated by dots | TS 29.272 clause 7.3.32 |
| `apn` | `labels`, or the wild card `*` | TS 29.272 clause 7.3.36 |
| `plmn-domain` | `mnc<MNC>.mcc<MCC>.3gppnetwork.org`, MNC 2 or 3 digits, MCC 3, in any case | TS 29.272 clause 7.3.105 |
| `epc-plmn-domain` | `epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org` | TS 29.272 clause 7.3.43 |
| `ip-address` | an Address of family 1 (IPv4, 4 octets) or 2 (IPv6, 16) | RFC 6733 clause 4.3.1, as TS 29.272 clauses 7.3.98 and 7.3.109 restrict it |
| `time-zone` | a sign and decimal digits, the offset from UTC in 15 minutes: `+8` | TS 29.272 clause 7.3.163 |
| `element` | another document's information element, carried whole: its document, and the clause and name of the element | the cited document, as the element registry reads it ([below](#elements)) |

A clause pointing at another document without stating a layout ("Octets are
coded according to TS 29.002 [24]") is an `element` of that document, named
as specifically as the clause allows: the MAP type an AVP's name and clause
mean (`TS29.002 17.7.5 "SS-Code"`), the parameter of TS 32.422 it takes its
values from (`TS32.422 5.10.19 "Positioning Method"`).

`seanchai.constraints` checks a payload in Python: `codec_problem(codec,
payload)` says why a payload is no such layout, `digit_count` counts its
digits, `element_problem(rule, payload, data_type)` why it is not the element
an `encoding element` rule names, and `check(rule, payload, data_type, codec)`
tells whether a length, range, exclude, encoding or bits rule holds, None
where the payload alone cannot tell (a predicate, a `values`, `members` or
`unique` rule, an element the registry does not have or checks nothing of, a
`default`, `text-only`). A `bits` rule holds of an unsigned integer's payload
or an OctetString's (`bits_value`, `bits_problem`).

## Elements

What an element looks like is not written in the `.dadx` file, which only
names it, but in the library's element registry, `seanchai.elements`: one
`Element` per document, clause and name, read from the defining document and
built from a closed set of declarative shapes, so that no file carries code:

| Shape | Holds when |
|---|---|
| `Octets` | the payload has so many octets, or a range of them |
| `Plmn` | three octets from a given one are a PLMN identity, as `plmn-id` |
| `Field` | bits of an octet, or running across octets, numbered 8 to 1 as the documents number them, take one of a set or range of values; a spare field takes the value it is coded with |
| `OneBit` | at most one bit of an octet is set |
| `Integer` | an integer-typed payload's value is within bounds |
| `Tbcd` | the octets from a given one are TBCD digits, "1111" filling only the last octet's bits 8-5 |
| `Fqdn` | the text is one of a few domain-name templates, `mmec<MMEC:hex:2>.mmegi<MMEGI:hex:4>.mme.epc...`, in any case |

Each entry cites every clause its layout was read from, with the edition read
(`Source`: TS 29.002 V19.1.0 clause 17.7.8, `E-UTRAN-CGI ::= OCTET STRING
(SIZE (7))`), following the references as far as they are concrete: MAP's
E-UTRAN-CGI to TS 29.118 clause 9.4.3a and on to TS 29.274's ECGI field. The
editions are Release 19's latest of each document TS 29.272 cites
non-specifically, as its references clause means; 3GPP2 publishes A.S0022-0
v2.0 as its newest. Release 18's copy of TS 29.272 is held to the same
entries, though its references mean Release 18's editions, which were not
read: where an element differs between the releases (a trace bitmap of TS
32.422 with fewer octets), a Release 18 sender draws a note it does not
deserve. Each says how deep its check goes, its `depth`:

- `full`: everything the document lets a sender get wrong is checked;
- `partial`: some of it, the entry saying what is not and why;
- `length`: the octet count alone;
- `none`: nothing, the entry saying why.

A spare bit is checked to be what the document codes it as, unless the
document tells the receiver to ignore it, as TS 24.008 clause 10.5 and TS
29.274 clause 8.1 do: such a bit is no error of the message. A reserved
code point is checked only where the document says it is not sent; one a
receiver reads as another (TS 24.008's "All other values shall be
interpreted as 0000") is not. Where the AVP alone does not say which
variant applies, a RAT's table of bits or a measurement quantity's range,
only what every variant shares is checked.

A finding is a note like any other interpreted rule's, `constraint-element`,
its line citing TS 29.272's clause and, beneath it, the element and the
documents read ([wireshark-plugin.md](wireshark-plugin.md#findings)).
`elements.problem(entry, payload, data_type)` checks a payload against an
entry, `elements.lookup(document, clause, name)` finds one, `sample` and
`breaking` give the payloads `seanchai vectors` sends, and the dictionary's
and the export's rules carry the entry as `element_entry`
([consumers.md](consumers.md#the-dictionary), [website.md](website.md#blocks)).
The linter notes an element the registry has no entry for as
`constraint-element-unknown`: another document's interpretations may name
one before the registry learns it, and nothing checks it meanwhile.

TS 29.272's 43 `encoding element` rules name 40 entries, of which 34 check
something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| 3GPP2-MEID | 3GPP2 A.S0022 A Mobile Identity (MEID) | 3GPP2 A.S0022-0 v2.0 Annex A | 8 octets; octet 1 bits 4-1 (odd/even indicator 0, type of identity 001) 0001; octet 8 bits 8-5 (fill) 1111 | full | the 14 MEID hex digits take any value 0H to FH. 3gpp2.org publishes A.S0022-0 v2.0 (April 2010) as the newest revision; later revisions TIA republishes were not read |
| Destination-Host | TS 29.303 4.3.2 | TS 29.303 V19.1.0 4.3.2 | nothing | none | the clause binds the operator provisioning host names to the form, and tells implementations to treat a host name not of the form as valid, so a breach is no error of the message; the host name itself is checked as a DiameterIdentity |
| Regional-Subscription-Zone-Code | TS 23.003 4.4 Zone Code | TS 23.003 V19.8.0 4.4 | 2 octets | full | the code is in full hexadecimal representation: any value |
| RAND | TS 33.401 RAND | TS 33.401 V19.2.0 6.1.2; TS 33.102 V19.1.0 6.3.7 | 16 octets | full | a random number: any value |
| XRES | TS 33.401 XRES | TS 33.401 V19.2.0 6.1.2; TS 33.102 V19.1.0 6.3.7 | 4 to 16 octets | full | a function's output: any value |
| AUTN | TS 33.401 AUTN | TS 33.401 V19.2.0 6.1.2; TS 33.102 V19.1.0 6.3.2; TS 33.102 V19.1.0 6.3.7 | 16 octets | full | its fields take any value: the AMF's bits are the operator's |
| KASME | TS 33.401 K_ASME | TS 33.401 V19.2.0 6.2 | 32 octets | full | a key: any value |
| SRES | TS 33.102 SRES | TS 33.102 V19.1.0 6.8.1.2 | 4 octets | full | a function's output: any value |
| Trace-NE-Type-List | TS 32.422 5.4 List of NE Types | TS 32.422 V19.7.0 5.4 | 3 octets; octet 3 bits 8-7 (spare) 00 | full | every other bit is an NE type, set or not |
| Trace-Interface-List | TS 32.422 5.5 List of Interfaces | TS 32.422 V19.7.0 5.5 | 23 octets | length | the spare bits in each network element's bitmap are not checked: several of the bitmaps print fewer cells than bits, so which bits a spare cell spans is not certain, and NOTE 5 says the bitmaps may number bits otherwise than the signalling specifications do |
| Trace-Event-List | TS 32.422 5.1 Triggering Events | TS 32.422 V19.7.0 5.1 | 17 octets | length | the spare bits in each network element's bitmap are not checked: several of the bitmaps print fewer cells than bits, so which bits a spare cell spans is not certain |
| OMC-Id | TS 29.002 17.7.8 AddressString | TS 29.002 V19.1.0 17.7.2; TS 29.002 V19.1.0 17.7.8 | 1 to 20 octets; octet 1 bit 8 (extension, 1 for no extension) 1; octets 2 on TBCD digits (0-9, *, #, a, b, c), '1111' filling only the last octet's bits 8-5 | full | the nature of address and numbering plan values the type marks reserved are not refused, since it does not say they are not sent |
| PDP-Type | TS 29.002 17.7.1 PDP-Type | TS 29.002 V19.1.0 17.7.1; TS 29.060 V19.0.0 7.7.27 | 2 octets; octet 1 bits 8-5 (spare) 1111; octet 1 bit 4 to octet 2 bit 1 (PDP type organisation and number) PPP (0x001), Non-IP (0x002), IPv4 (0x121) or IPv6 (0x157) | full |  |
| QoS-Subscribed | TS 29.002 17.7.1 QoS-Subscribed | TS 29.002 V19.1.0 17.7.1; TS 24.008 V19.5.0 10.5.6.5 | 3 to 18 octets | length | the octets' fields are not checked: TS 24.008 has the receiver map a reserved value to another rather than refuse it, and its spare bits are ignored by the receiving side (clause 10.5) |
| CSG-Id | TS 23.003 4.7 CSG-ID | TS 23.003 V19.8.0 4.7 | nothing | none | the document fixes only the identity's 27 bits; where they sit in the Unsigned32 AVP is TS 29.272's own sentence, read as a bits rule beside it |
| SS-Code | TS 29.002 17.7.5 SS-Code | TS 29.002 V19.1.0 17.7.5 | 1 octet; octet 1 (SS-Code) a code clause 17.7.5 defines | full |  |
| SS-Status | TS 29.002 17.7.4 SS-Status | TS 29.002 V19.1.0 17.7.4 | 1 octet; octet 1 bits 8-5 (unused) 0000 | full |  |
| ServiceTypeIdentity | TS 29.002 17.7.8 LCSServiceTypeID | TS 29.002 V19.1.0 17.7.8 | an integer 0 to 127 | full | a standard type the clause has not yet named is reserved for one, not refused |
| TS-Code | TS 29.002 17.7.9 TeleserviceCode | TS 29.002 V19.1.0 17.7.9 | 1 octet; octet 1 (TeleserviceCode) a code clause 17.7.9 defines | full | Ext-TeleserviceCode's octets 2 to 5, reserved for future use, are not the type named |
| E-UTRAN-Cell-Global-Identity | TS 29.002 17.7.8 E-UTRAN-CGI | TS 29.002 V19.1.0 17.7.8; TS 29.118 V19.1.0 9.4.3a; TS 29.274 V19.6.0 8.21.5 | 7 octets; a PLMN identity in octets 1 to 3 | full | octet 4's bits 8-5 are the spare bits TS 29.274 clause 8.1 says are sent as 0 and not evaluated by the receiver; the ECI takes any value |
| Tracking-Area-Identity | TS 29.002 17.7.8 TA-Id | TS 29.002 V19.1.0 17.7.8; TS 29.118 V19.1.0 9.4.21a; TS 29.274 V19.6.0 8.21.4 | 5 octets; a PLMN identity in octets 1 to 3 | full | the tracking area code takes any value, its coding being each administration's |
| Cell-Global-Identity | TS 29.002 17.7.8 CellGlobalIdOrServiceAreaIdFixedLength | TS 29.002 V19.1.0 17.7.8 | 7 octets; a PLMN identity in octets 1 to 3 | full | the location area code and the cell identity or service area code take any value |
| Routing-Area-Identity | TS 29.002 17.7.8 RAIdentity | TS 29.002 V19.1.0 17.7.8; TS 29.060 V19.0.0 7.7.3 | 6 octets; a PLMN identity in octets 1 to 3 | full | the location and routing area codes take any value |
| Location-Area-Identity | TS 29.002 17.7.8 LAIFixedLength | TS 29.002 V19.1.0 17.7.8 | 5 octets; a PLMN identity in octets 1 to 3 | full | the location area code takes any value |
| Service-Area-Identity | TS 29.002 17.7.8 CellGlobalIdOrServiceAreaIdFixedLength | TS 29.002 V19.1.0 17.7.8 | 7 octets; a PLMN identity in octets 1 to 3 | full | the location area code and the cell identity or service area code take any value |
| Geographical-Information | TS 29.002 17.7.1 GeographicalInformation | TS 29.002 V19.1.0 17.7.1; TS 23.032 V19.0.0 7.3.2; TS 23.032 V19.0.0 7.2 | 8 octets; octet 1 bits 8-5 (type of shape) 0001; octet 1 bits 4-1 (spare) 0000; octet 8 bit 8 (spare) 0 | full | the latitude, longitude and uncertainty code take any value |
| Geodetic-Information | TS 29.002 17.7.1 GeodeticInformation | TS 29.002 V19.1.0 17.7.1; ITU-T Q.763 (12/1999) 3.88 | 10 octets; octet 1 bits 8-5 (spare) 0000; octet 2 bits 7-1 (type of shape) 0000001; octet 9 bit 8 (spare) 0; octet 10 bit 8 (spare) 0; octet 10 bits 7-1 (confidence) 0 to 100 | full | the extension bit's value for a parameter of one octet of shape is not stated; the LPRI's spare code 11 is one for future use, not refused |
| List-Of-Measurements | TS 32.422 5.10.3 List of Measurements | TS 32.422 V19.7.0 5.10.3 | octet 2 bit 8 (spare) 0; octets 3 to 4 (spare) all 0 | partial | only the bits spare in every RAT's table are checked: the AVP does not say which RAT its bits are read for, and octet 2's other spare bits are measurements in another RAT |
| Reporting-Trigger | TS 32.422 5.10.4 Reporting Trigger | TS 32.422 V19.7.0 5.10.4 | nothing | none | the document defines one octet, TS 29.272 an Unsigned32 whose most significant bit is bit 8 of its first octet, so which of the four octets holds the bitmap is said by neither |
| Event-Threshold-RSRP | TS 32.422 5.10.7 Event Threshold for Event A2 | TS 32.422 V19.7.0 5.10.7 | an integer 0 to 127 | partial | an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not checked: the AVP does not say which RAT it is for |
| Event-Threshold-RSRQ | TS 32.422 5.10.7 Event Threshold for Event A2 | TS 32.422 V19.7.0 5.10.7 | an integer 0 to 127 | partial | an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not checked: the AVP does not say which RAT it is for |
| Positioning-Method | TS 32.422 5.10.19 Positioning Method | TS 32.422 V19.7.0 5.10.19 | octet 1 bits 8-3 (spare) 000000 | partial | bit 2, spare in NR, is E-Cell ID in LTE, and the AVP does not say which RAT it is for |
| Measurement-Quantity | TS 32.422 5.10.15 Measurement Quantity | TS 32.422 V19.7.0 5.10.15 | at most one bit of octet 1 set | full | bits 8-4 are reserved, not refused, since the clause does not say they are not sent |
| Event-Threshold-Event-1F | TS 32.422 5.10.13 Event Threshold for Event 1f | TS 32.422 V19.7.0 5.10.13 | an integer -120 to 165 | partial | the narrower range of the measurement quantity (CPICH RSCP -120..-25, Ec/No -24..0, pathloss 30..165) is not checked: it is another AVP's |
| Event-Threshold-Event-1I | TS 32.422 5.10.14 Event Threshold for Event 1i | TS 32.422 V19.7.0 5.10.14 | an integer -120 to -25 | full |  |
| SGs-MME-Identity | TS 23.003 19.4.2.4 MME node FQDN | TS 23.003 V19.8.0 19.4.2.4; TS 23.003 V19.8.0 19.2 | mmec<MMEC>.mmegi<MMEGI>.mme.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org (MMEC 2 hexadecimal digits, MMEGI 4 hexadecimal digits, MNC 3 digits, MCC 3 digits), in any case | full |  |
| Coupled-Node-Diameter-ID | TS 23.003 19.4.2 MME or SGSN node FQDN | TS 23.003 V19.8.0 19.4.2.4; TS 23.003 V19.8.0 19.4.2.6; TS 23.003 V19.8.0 19.2 | mmec<MMEC>.mmegi<MMEGI>.mme.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org or nri-sgsn<NRI>.rac<RAC>.lac<LAC>.rac.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org (MMEC 2 hexadecimal digits, MMEGI 4 hexadecimal digits, MNC 3 digits, MCC 3 digits, NRI 4 hexadecimal digits, RAC 4 hexadecimal digits, LAC 4 hexadecimal digits), in any case | full |  |
| eDRX-Cycle-Length-Value | TS 24.008 10.5.5.32 eDRX value | TS 24.008 V19.5.0 10.5.5.32 | nothing | full | every 4-bit value is received, those undefined read as 0000, so nothing is refused; the octet carrying the field is TS 29.272's own length and bits rules |
| Paging-Time-Window-Length | TS 24.008 10.5.5.32 Paging Time Window | TS 24.008 V19.5.0 10.5.5.32 | nothing | full | every 4-bit value is defined, so nothing is refused; the octet carrying the field is TS 29.272's own length and bits rules |
| 5QI | TS 23.501 5QI | TS 23.501 V19.9.0 5.7.2.1 | nothing | none | the document gives no range: beside the standardized values a 5QI may be a pre-configured or dynamically assigned one |
| Event-Threshold-SINR | TS 32.422 5.10.7 Event Threshold for Event A2 | TS 32.422 V19.7.0 5.10.7 | an integer 0 to 127 | partial | an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not checked: the AVP does not say which RAT it is for |
| Collection-Period-M7-NR | TS 32.422 5.10.35 Collection Period M7 in NR | TS 32.422 V19.7.0 5.10.35 | an integer 1 to 60 | full |  |
| NR-Cell-Global-Identity | TS 29.002 17.7.8 NR-CGI | TS 29.002 V19.1.0 17.7.8; TS 38.413 V19.4.0 9.3.1.7 | 8 octets; a PLMN identity in octets 1 to 3 | partial | where the 36 bits of the NR cell identity sit in the last five octets, and what the other four are, neither document says |


## Reading them

- The model: `Avp.constraints` holds what the reading document read of the
  AVP wherever it appears, or else its origin's, as value tables are;
  `Grouped.member_constraints` what it read of the grouped AVP's members;
  `Message.constraints` what it read of the command's members.
  `Model.constraints(reference)` lists a document's. Each is a
  `model.Constraint` with its `readings` (`ast.Reading`: quotes and rules),
  clause, page, table and `versions`
  ([consumers.md](consumers.md#interpreted-constraints)).
- The dictionary: `constraints[]` holds those on the AVPs the selection
  reaches, each naming the readings carrying it in `avp_ids`; a command's own
  `constraints` its members'
  ([consumers.md](consumers.md#the-dictionary)).
- The export: an Interpreted Constraints block has `interpreted`, the
  `avp_target` its `; AVP:` line links to, and `readings`, each quote and
  rule at its line ([website.md](website.md#blocks)).
- The linter's `constraint-*` rules report a block naming what the file does
  not hold, a rule the AVP's type cannot meet, a value or bit no table names,
  and rules that cannot all hold
  ([linter.md](linter.md#interpreted-constraints)).
- The Wireshark plugin checks lengths, ranges, exclusions, the codecs, an
  `element` as far as its registry entry does, `bits`, `members` and `unique`
  rules, and the predicates and `values` rules whose names resolve; a
  `default` breaks nothing on the wire
  ([wireshark-plugin.md](wireshark-plugin.md#what-it-checks)).

## The interpretations file

A document's interpretations are written in `edits/interpretations/`, one
file per document named by its reference with the suffix `.dadx`:
`TS29.272.dadx`. The syntax is the `.dad` syntax
([grammar.md](grammar.md#interpretations-files)); the suffix keeps the corpus
loaders and `--with`, which read `*.dad`, from taking the file for a
document. It holds a `; Interprets:` header naming the document as its
`; Specification:` does, then the blocks, in the document's clause order, so
a reviewer reads it beside the specification:

```dad
; Interprets: 3GPP TS 29.272


; Type: Interpreted Constraints
; Id: apn-configuration-non-ip-delivery
; AVP: Non-IP-Data-Delivery-Mechanism
; Within: APN-Configuration
; Section: 7.3.35
; Versions: 18.7.0..19.6.0
"The Non-IP-Data-Delivery-Mechanism shall only be present when Non-IP-PDN-Type-Indicator is set to TRUE (1)."
    requires Non-IP-PDN-Type-Indicator = TRUE
```

- A person writes the scope (`; AVP:`, `; Within:` or `; Command:` with
  `; Application-ID:`, `; Section:`, `; Table:`), the quotes and the rules,
  and `; Versions:`, the range the quotes were checked against.
- `; Id:` names the block: a kebab-case name, unique in the file, naming what
  is read (`imei-digits`), not where. The corrected file's note and the
  corrections record cite it as `TS29.272.dadx#imei-digits`, so it stays put
  when the clause is renumbered or the block moves.
- `; Page:` is not written: it is the clause's page in each copy, read from
  that copy's source as the block is merged, so one block serves the copies
  of several releases.
- `;;` comments are the author's notes; they stay in the file and do not
  reach the corrected one.

`seanchai corpus regenerate` merges the file into each corrected copy after
the document's corrections:

- Each block whose range spans the copy's release is placed after the last
  block whose clause sorts at or before its own, in the order written: a
  block reading clause 7.3.9 follows clause 7.3.8's, and one reading an
  information element's description follows its table.
- Every quote must be within one paragraph or table cell of its clause once
  whitespace is collapsed, as the extractor reads it; an RFC's quote within
  one paragraph, its lines joined. A miss fails the document, naming the
  file and line of the quote:
  `edits/interpretations/TS29.272.dadx:435: imei-digits: clause 7.3.4 does
  not print 'It should consist of 16 digits, ...'`. A transcription has no
  source text to check against, so a file for one is refused.
- Merging expects the corrected file to hold every AVP a block names, one
  command of its scope's name, the AVP in the command's or the grouped AVP's
  printed body, and no other block for the same AVP, scope and clause.
- A block applies only to copies of the releases its range spans, since
  whether a clause prints a sentence is a fact of each copy. Another
  release's are offered: `regenerate` counts them in a warning, and with
  `--expand-ranges`, on a copy of a release no block of the file spans, it
  holds the quotes of each of the nearest reviewed release's (the oldest
  above, else the newest below) to the copy's text. Each it finds is merged
  and its `; Versions:` line widened to the copy in the file; each it does
  not is reported as `not carried:` with the sentence the clause lacks, and
  stays out. Release 18's copy holds 152 of TS 29.272's 157; the five it
  does not read sentences Release 19 added.
- `corrections.json` records each block by its citation, kind `interpret`,
  with its clause and quotes
  ([corrections.md](corrections.md#the-corrections-record)).

`seanchai format` keeps the file in canonical form, comments included, and
`seanchai lint FILE.dadx` checks it: its syntax, rules, ids and clause order
as it is read, and with a corpus the `constraint-*` rules in each copy of the
document a block's range spans, as the copy would read the block merged in
place of its own ([linter.md](linter.md#interpreted-constraints)).
`seanchai corpus correct` and `corpus extract` take `--interpretations DIR`
to merge a file without its source: no quote is checked and no block is
paged.

A file of your own beside a private `--with` document is not read: write
that document's Interpreted Constraints blocks in its `.dad` itself, as any
file may hold them, with no source to hold their quotes to.

## Adding them for another document

1. Read every AVP clause of the document, and the descriptions of its
   information-element tables' C rows. Keep the source text at hand:
   `seanchai.extractor.tgpp_docx.clause_texts(docx, Path("edits/sources"))`
   gives each clause's paragraphs and cells as the quote check reads them.
2. Create `edits/interpretations/<SpecRef>.dadx` with its `; Interprets:`
   line, and for each rule a clause states write a block, in clause order:
   an `; Id:`, the AVP, its scope where the clause speaks of the AVP in a
   command or grouped AVP, the clause and table, the version read as
   `; Versions:`, and readings of the shortest quotes that state the rule.
3. Prefer `text-only` to a rule the quote does not settle. A rule depending
   on an earlier message, a feature, the node, the interface or the
   subscriber is `text-only`; so is a NOTE outside a table, which states no
   requirement. A clause pointing at another document for a layout is an
   `element`, named by its clause and name in that document.
4. Run `uv run seanchai format edits/interpretations/<SpecRef>.dadx` and
   `uv run seanchai lint edits/interpretations/<SpecRef>.dadx`, then
   `uv run seanchai corpus regenerate --spec <SpecRef>`. A quote the clause
   does not print fails the document at the quote's line.
5. A layout no codec describes needs a codec, defined with its clause in
   `ast.Codec`, `seanchai.constraints`, the plugin's `core.lua` and this
   page, with byte vectors in `tests/test_constraints.py`.
6. An element the registry lacks (`constraint-element-unknown`) needs an
   entry in `seanchai.elements`, read from the defining document, a copy
   fetched for the purpose: its sources with the edition read, its checks in
   the shapes above, its depth and what it leaves unchecked, and an example
   payload. `tests/test_elements.py` holds every entry to its example, to the
   payloads breaking it and to `core.lua`, which reads the shapes the plugin
   is generated with.

## TS 29.272

TS 29.272 V19.6.0 is read completely: every AVP clause of clause 7.3 and every
C row of its information-element tables.

| | |
|---|---|
| AVP clauses (clause 7.3, not its General and Void clauses) | 247 |
| with something to declare | 99, in 122 blocks |
| with nothing to declare | 148 |
| information-element C rows | 45, of which 35 state a condition, 10 of them typed |
| blocks | 157: 87 on an AVP wherever read, 33 within a grouped AVP, 37 within a command |
| readings | 176 |

| Rules | |
|---|---|
| `encoding`, a codec | 20: `e164-tbcd` 6, `plmn-id` 3, `digits` 3, `ip-address` 2, `plmn-id-prefix`, `labels`, `apn`, `plmn-domain`, `epc-plmn-domain`, `time-zone` |
| `encoding element` | 43, naming 40 entries of the registry; 37 rules checked, 6 not ([above](#elements)) |
| `length` | 8: 6 in octets, 2 in digits |
| `range` | 7 |
| `exclude` | 4 |
| `requires`, `present-if`, `absent-if`, `excludes` | 17, 2, 2, 1 |
| `default` | 9 |
| `bits` | 10: `at-most-one` 3 (DSR-Flags), `at-least-one` (Preferred-Data-Mode), `clear` 4 (Reachability-Type, eDRX-Cycle-Length-Value, Paging-Time-Window-Length, CSG-Id), `set` (Reachability-Type), `only` (DSR-Flags on S7a) |
| `members` | 3: `at-least-one` 2 (AESE-Communication-Pattern, Monitoring-Event-Configuration), `only` (Terminal-Information in NOR) |
| `unique` | 2: Context-Identifier and Service-Selection in APN-Configuration |
| `values` | 1: Reachability-Information in Monitoring-Event-Report |
| `text-only` | 54 |

The text-only rules are mostly conditions on the node, the interface, an
earlier message or a feature (an information element's "shall be present if
the MME supports SMS in MME"), what an absent AVP means where that is no
value or differs between commands (MDT-User-Consent's in ULA and IDR), and
conditions on an OctetString's value (PDP-Type's, whose octets the clauses
do not spell out). The rest a single message could show but no kind says
without a member's member, a negation or a mapping between two bit tables:
Visited-Network-Identifier present when MIP6-Agent-Info holds no FQDN,
Maximum-Number-of-Reports bounded by MONTE-Location-Type inside
Location-Information-Configuration, PLMN-RAT-Usage-Control's bits against
Access-Restriction-Data's. Access-Restriction-Data's "Bits 11 and 12 are only
used when bit 4 is not set" says what they mean, not that they are clear.
