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
| `equals` | `equals request/User-Name` | the AVP holds, octet for octet, the value of the one named, where both are present |
| `absent` | `absent` | the AVP is not present in the block's scope |
| `text-only` | `text-only` | (a reader decides) |

A predicate's conditions, and a `values` rule's, are alternatives (`or`), each
one or more conditions that must all hold (`and`, which binds tighter; there
are no parentheses), each on a sibling in the block's `; Command:` or
`; Within:` grouped AVP: present, holding a value (a number, or a name its
values or result codes give it), or with a bit set (a number, or its bit
table's name), or with `not` none of these (`present-if MIP6-Agent-Info and
not MIP6-Agent-Info/MIP-Home-Agent-Host`). A condition resting on a value
that cannot be read is unknown, and so is what it decides: `not` of an
unknown is unknown, an `and` of a false one is false. Several predicates in one
block must all hold. `absent-if` and `excludes` say the same of a presence
condition, read from the other side; the kinds follow the clause's wording.
Without a scope the rules hold wherever the document reads the AVP, and a
predicate there has no siblings to test, only the AVP's own members through
a path. A scope's AVP is a member its body prints or one its `* [ AVP ]`
admits, so a block may hold a command to a
sentence about an AVP its ABNF leaves to the wildcard; `absent` says such
an AVP is never sent there. A member of a grouped AVP the command holds is
the grouped AVP's scope, not the command's.

A name may be a path through grouped AVPs, `/` between the names, relative
to the block's scope: `MIP6-Agent-Info/MIP-Home-Agent-Host` tests the
MIP-Home-Agent-Host member of the command's MIP6-Agent-Info, which a sibling
condition cannot, and reaches a member of a grouped AVP the document re-uses
from another, as the defining document prints its body. With no scope a
path starts at the block's AVP itself, present wherever the rule is checked,
so the predicate is a grouped AVP's on its own members. Of the AVPs a path
names, any one meeting the condition does. A `members` rule may name a
member of a grouped
AVP another document defines (IMEI in TS 29.272's Terminal-Information, as
TS 29.273 re-uses it).

In a block scoped to an answer, a name after `request/` is a member of the
request the answer answers: the same command code with the R bit under the
same application, printed at the block's `; Request-Section:` where the
document prints that request more than once there, as TS 29.273 prints
Diameter-EAP-Request for STa and SWd under one application. A condition may
test it as it tests a sibling (`absent-if request/Emergency-Services bit
Emergency-Indication`), or compare a sibling's value with it
(`Result-Code = request/Result-Code`), and `equals` holds the AVP to it. Of
the request's members of a name, any one meeting the condition does. A rule
reading the request is checked only where the request is at hand: what
reads the answer alone reports it unchecked, never broken. A rule across
more than one exchange (an earlier answer, a session's state) has no form:
it is `text-only`.

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

The set is closed, and holds the layouts the interpreted documents' clauses
name. A layout no clause states is not here.

| Codec | Layout | Defined in |
|---|---|---|
| `e164-tbcd` | an international number, ITU-T E.164 (1 to 15 decimal digits), as a TBCD-string: two digits an octet, the first in bits 1-4, "1111" filling bits 5-8 of the last octet after an odd count; no octet for the nature of address and numbering plan | TS 29.002 clause 17.7.8, as TS 29.272 clauses 7.3.39, 7.3.85, 7.3.91, 7.3.102, 7.3.157 and 7.3.159 and TS 29.329 clause 6.3.2 say |
| `plmn-id` | MCC and MNC in 3 octets: MCC digits 2 and 1, then MNC digit 3 (or "1111" for a 2-digit MNC) and MCC digit 3, then MNC digits 2 and 1 | TS 29.272 table 7.3.9/1, after TS 24.008 clause 10.5.1.13 |
| `plmn-id-prefix` | a `plmn-id` in the first 3 octets, more octets after it | TS 29.272 table 7.3.64/1 (Trace-Reference) |
| `digits` | decimal digits as text, a character each | TS 29.272 clauses 7.3.4, 7.3.5, 7.3.50 |
| `labels` | one or more non-empty labels separated by dots | TS 29.272 clause 7.3.32 |
| `apn` | `labels`, or the wild card `*` | TS 29.272 clause 7.3.36 |
| `plmn-domain` | `mnc<MNC>.mcc<MCC>.3gppnetwork.org`, MNC 2 or 3 digits, MCC 3, in any case | TS 29.272 clause 7.3.105 |
| `epc-plmn-domain` | `epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org` | TS 29.272 clause 7.3.43 |
| `ip-address` | an Address of family 1 (IPv4, 4 octets) or 2 (IPv6, 16) | RFC 6733 clause 4.3.1, as TS 29.272 clauses 7.3.98 and 7.3.109 restrict it |
| `time-zone` | a sign and decimal digits, the offset from UTC in 15 minutes: `+8` | TS 29.272 clause 7.3.163 |
| `mac-address` | a 6-octet MAC address as text, each octet two upper-case hexadecimal digits, joined by dashes: `00-10-A4-23-19-C0` | TS 29.273 clauses 5.2.3.23 and 5.2.3.30 |
| `ip-filter` | an IPFilterRule as TS 29.212 restricts it: `permit`, `in` or `out`, a protocol number or `ip`, `from` a source and `to` a destination, each `any`, `assigned` or an IPv4 or IPv6 number with an optional mask width, then optional ports and port ranges; no options, no `!` | RFC 6733 clause 4.3.1, as TS 29.212 clause 5.3.34 restricts it |
| `ip-filter-out` | an `ip-filter` of the direction `out`: `permit out 17 from 192.0.2.10/32 5060 to assigned` | TS 29.212 clauses 5.3.13, 5.3.54 and 5.4.2 |
| `element` | another document's information element, carried whole: its document, and the clause and name of the element | the cited document, as the element registry reads it ([below](#elements)) |

A clause pointing at another document without stating a layout ("Octets are
coded according to TS 29.002 [24]") is an `element` of that document, named
as specifically as the clause allows: the MAP type an AVP's name and clause
mean (`TS29.002 17.7.5 "SS-Code"`), the parameter of TS 32.422 it takes its
values from (`TS32.422 5.10.19 "Positioning Method"`).

`seanchai.constraints` checks a payload in Python: `codec_problem(codec,
payload)` says why a payload is no such layout, `digit_count` counts its
digits, `element_problem(rule, payload, data_type)` why it is not the element
an `encoding element` rule names, and `check(rule, payload, data_type, codec,
request)` tells whether a length, range, exclude, encoding or bits rule
holds, and a rule reading only the request where `request`, the request's
AVPs, is given; None where the payload alone cannot tell (another predicate,
a `values`, `members` or `unique` rule, an element the registry does not
have or checks nothing of, a `default`, `text-only`). `holds(rule, avp,
scope, request)` tells whether a predicate, a `values` or an `equals` rule
holds of the AVP named `avp` in `scope`, its run of AVPs (`Avp`: a name, a
type, a payload or members, and the numbers its names stand for). A rule
reading the request with no request given is not evaluated: its `Check` is
None with `needs_request`, neither a pass nor a breach. A `bits` rule holds
of an unsigned integer's payload or an OctetString's (`bits_value`,
`bits_problem`).

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
editions are Release 19's latest of each document the interpreted documents
cite non-specifically, as their references clauses mean; 3GPP2 publishes
A.S0022-0 v2.0 as its newest. Release 18's copies are held to the same
entries, though their references mean Release 18's editions, which were not
read: where an element differs between the releases (a trace bitmap of TS
32.422 with fewer octets), a Release 18 sender draws a note it does not
deserve. Each says how deep its check goes, its `depth`:

- `full`: everything the document lets a sender get wrong is checked; an
  entry whose every value is defined checks nothing and says so (TS 24.008's
  4-bit eDRX fields);
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
| eDRX-Cycle-Length-Value | TS 24.008 10.5.5.32 eDRX value | TS 24.008 V19.5.0 10.5.5.32 | every 4-bit value is valid, an undefined one read as 0000; nothing to refuse | full | the octet carrying the field is held to TS 29.272's own length and bits rules instead |
| Paging-Time-Window-Length | TS 24.008 10.5.5.32 Paging Time Window | TS 24.008 V19.5.0 10.5.5.32 | every 4-bit value is defined; nothing to refuse | full | the octet carrying the field is held to TS 29.272's own length and bits rules instead |
| 5QI | TS 23.501 5QI | TS 23.501 V19.9.0 5.7.2.1 | nothing | none | the document gives no range: beside the standardized values a 5QI may be a pre-configured or dynamically assigned one |
| Event-Threshold-SINR | TS 32.422 5.10.7 Event Threshold for Event A2 | TS 32.422 V19.7.0 5.10.7 | an integer 0 to 127 | partial | an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not checked: the AVP does not say which RAT it is for |
| Collection-Period-M7-NR | TS 32.422 5.10.35 Collection Period M7 in NR | TS 32.422 V19.7.0 5.10.35 | an integer 1 to 60 | full |  |
| NR-Cell-Global-Identity | TS 29.002 17.7.8 NR-CGI | TS 29.002 V19.1.0 17.7.8; TS 38.413 V19.4.0 9.3.1.7 | 8 octets; a PLMN identity in octets 1 to 3 | partial | where the 36 bits of the NR cell identity sit in the last five octets, and what the other four are, neither document says |

TS 29.329's 3 name 3 entries, of which 2 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| User-Data | TS 29.328 C Sh-Data | TS 29.328 V19.2.0 Annex C; TS 29.328 V19.2.0 Annex D | nothing | none | an XML document the schema of Annex D defines: no shape of the registry reads XML |
| Call-Reference-Number | TS 29.002 17.7.3 CallReferenceNumber | TS 29.002 V19.1.0 17.7.3 | 1 to 8 octets | full | the octets take any value: the type says nothing more of them |
| AS-Number | TS 29.002 17.7.8 ISDN-AddressString | TS 29.002 V19.1.0 17.7.3; TS 29.002 V19.1.0 17.7.8 | 1 to 9 octets; octet 1 bit 8 (extension, 1 for no extension) 1; octets 2 on TBCD digits (0-9, *, #, a, b, c), '1111' filling only the last octet's bits 8-5 | full | the nature of address and numbering plan values the type marks reserved are not refused, since it does not say they are not sent |

TS 29.273's 6 name 6 entries, of which 4 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| ANID | TS 24.302 8.1.1 Access Network Identity | TS 24.302 V19.0.0 8.1.1.1; TS 24.302 V19.0.0 8.1.1.2 | nothing | none | no shape of the registry bounds a text's octets, and a prefix the tables do not name is 'Not defined', not refused: NOTE 6 leaves further prefixes to be defined |
| Full-Network-Name | TS 24.302 8.2.5.1 Full name value | TS 24.302 V19.0.0 8.2.5.1; TS 24.008 V19.5.0 10.5.3.5a | at least 1 octet; octet 1 bit 8 (ext) 1 | partial | the coding scheme's reserved values 010 to 111 are not refused, since the clause does not say they are not sent, and the text string, with the spare bits its last octet holds, is not decoded |
| Short-Network-Name | TS 24.302 8.2.5.2 Short name value | TS 24.302 V19.0.0 8.2.5.2; TS 24.008 V19.5.0 10.5.3.5a | at least 1 octet; octet 1 bit 8 (ext) 1 | partial | as Full-Network-Name's |
| MIP-FA-RK | TS 33.402 9.2.1.2.2 FA-RK | TS 33.402 V19.0.0 9.2.1.2.2 | 20 octets | full | a key: any value |
| MIP-FA-RK-SPI | TS 33.402 9.2.1.2.2 FA-RK-SPI | TS 33.402 V19.0.0 9.2.1.2.2 | nothing | none | a derived index: the clause steps it clear of the other active SPIs and of the top of the range, which a single message cannot show |
| WLCP-Key | TS 33.402 A.3 WLCP key | TS 33.402 V19.0.0 A.3; TS 33.402 V19.0.0 A.1; TS 33.220 V19.1.0 B.2.0 | 32 octets | full | a key: any value |

TS 29.212's 4 name 4 entries, all of which check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| RAN-NAS-Release-Cause | TS 29.274 8.103 RAN/NAS Cause | TS 29.274 V19.6.0 8.103 | at least 2 octets | partial | that a Diameter or IKEv2 cause takes two octets is not checked: no shape ties a length to a field's value; the protocol types 6 to 15 are spare, not refused, since the clause does not say they are not sent, and the cause type and value take any value |
| Presence-Reporting-Area-Elements-List | TS 29.274 8.108 Presence Reporting Area Action | TS 29.274 V19.6.0 8.108 | at least 6 octets | partial | that the elements' octets add up to the counts is not checked: no shape sums them; the spare bits of octets 10 to 14 are the ones TS 29.274 clause 8.1 says are sent as 0 and not evaluated by the receiver, and each count's own bits bound it at 15 or 63 |
| Presence-Reporting-Area-Identifier | TS 29.274 8.109 PRA Identifier | TS 29.274 V19.6.0 8.109; TS 23.003 V19.8.0 19.10 | 3 octets | full | the identifier takes any value, its most significant bit telling a UE-dedicated area from a core network predefined one |
| Framed-IPv6-Prefix | RFC 3162 2.3 Framed-IPv6-Prefix | RFC 3162 (August 2001) 2.3 | 2 to 18 octets; octet 1 (Reserved) 00000000; octet 2 (Prefix-Length) 00000000 to 10000000 | partial | that the bits beyond the prefix length are zero is not checked: no shape reads a length from a field |


## Reading them

- The model: `Avp.constraints` holds what the reading document read of the
  AVP wherever it appears, or else its origin's, as value tables are; a
  document's rules on an AVP it re-uses make its reading one of its own,
  read through it, so they hold where that document reads the AVP;
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
  rules, and the predicates, `values` and `equals` rules whose names
  resolve, those reading the request against the request the capture holds;
  a `default` breaks nothing on the wire
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
  `; Application-ID:`, `; Command-Section:` and `; Request-Section:`,
  `; Section:`, `; Table:`),
  the quotes and the rules, and `; Versions:`, the range the quotes were
  checked against. `; Application-ID:` names the application of the
  command's print: its header's id, or where the header names none, the
  one the application scope covering its clause gives it, as TS 29.212's
  Gx and Gxx prints of CC-Request take theirs. `; Command-Section:` names
  the clause of the command's block where the document prints the command
  more than once for one application: TS 29.273 prints Diameter-EAP-Answer
  for STa and SWd under STa's application.
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
  command of its scope's name, application and clause, the AVP in the
  command's or the grouped AVP's printed body, and no other block for the
  same AVP, scope and clause.
- A block applies only to copies of the releases its range spans, since
  whether a clause prints a sentence is a fact of each copy. Every block
  whose range does not span a copy's release is offered to it, whatever the
  other blocks' ranges, unless a copy of the document in another release
  the corpus holds lies between the two, which the widened range would
  claim without the block being held to it. `regenerate` counts those
  whose quotes the copy prints in a warning, and with `--expand-ranges`
  merges each and widens its `; Versions:` line to the copy in the file;
  each whose quotes it does not print is reported as `not carried:` with
  the sentence the clause lacks, and stays out. Such a run reads a
  document's copies newest first, so that going back widens a block one
  release at a time. A copy of a release the corpus holds only for
  citations (TS 29.212's Release 11) is offered nothing unless the run is
  given `--offer-cited`. Release 18's copy holds 152 of TS 29.272's 157;
  the five it does not read sentences Release 19 added.
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
| information-element C rows | 45, of which 35 state a condition, 17 of them typed |
| blocks | 157: 87 on an AVP wherever read, 33 within a grouped AVP, 37 within a command |
| readings | 176 |

| Rules | |
|---|---|
| `encoding`, a codec | 20: `e164-tbcd` 6, `plmn-id` 3, `digits` 3, `ip-address` 2, `plmn-id-prefix`, `labels`, `apn`, `plmn-domain`, `epc-plmn-domain`, `time-zone` |
| `encoding element` | 43, naming 40 entries of the registry; 37 rules checked, 6 not ([above](#elements)) |
| `length` | 8: 6 in octets, 2 in digits |
| `range` | 7 |
| `exclude` | 4 |
| `requires`, `present-if`, `absent-if`, `excludes` | 17, 9, 2, 2 |
| `default` | 9 |
| `bits` | 10: `at-most-one` 3 (DSR-Flags), `at-least-one` (Preferred-Data-Mode), `clear` 4 (Reachability-Type, eDRX-Cycle-Length-Value, Paging-Time-Window-Length, CSG-Id), `set` (Reachability-Type), `only` (DSR-Flags on S7a) |
| `members` | 3: `at-least-one` 2 (AESE-Communication-Pattern, Monitoring-Event-Configuration), `only` (Terminal-Information in NOR) |
| `unique` | 2: Context-Identifier and Service-Selection in APN-Configuration |
| `values` | 2: Reachability-Information in Monitoring-Event-Report, Maximum-Number-of-Reports for a last known location |
| reading the request | 6: the IDA's EPS-User-State, EPS-Location-Information and Local-Time-Zone where the IDR's IDR-Flags asks for them, its Monitoring-Event-Config-Status beside the IDR's Monitoring-Event-Configuration, and the ULA's and UVA's subscription data unless the request skips it |
| `text-only` | 45 |

The text-only rules are mostly conditions on the node, the interface, an
earlier message or a feature (an information element's "shall be present if
the MME supports SMS in MME"), what an absent AVP means where that is no
value or differs between commands (MDT-User-Consent's in ULA and IDR), and
conditions on an OctetString's value (PDP-Type's, whose octets the clauses
do not spell out). A row read as an answer's rule on its request is held to
a success's answer, `Result-Code = DIAMETER_SUCCESS`, where the row says
nothing of an error's: an IDA reporting one carries no EPS-User-State
though the IDR asked for it. The rest a single message could show but no
kind says: a text value (Specific-APN-Info only for the wild card APN `*`),
a mapping between two bit tables (PLMN-RAT-Usage-Control's bits against
Access-Restriction-Data's), the address type of Ext-PDP-Address against
PDP-Address's, and MIP6-Home-Link-Prefix "not used in S6a/S6d", which a
`; Within:` scope would hold to every interface reading MIP6-Agent-Info as
TS 29.272 does, SWx's APN-Configuration among them.
Access-Restriction-Data's "Bits 11 and 12 are only used when bit 4 is not
set" says what they mean, not that they are clear.

## TS 29.329

TS 29.329 V19.1.0 is read completely: every AVP clause of clause 6.3, the
notes under the commands of clause 6.1 and clause 6.2's sentence on its
result codes. Its commands' information-element tables and its procedures
are TS 29.328's, whose clauses are not read here. Release 18's copy,
V18.0.0, prints every sentence read and holds all 15 blocks.

| | |
|---|---|
| AVP clauses (clause 6.3, not its overview) | 36 |
| with something to declare | 9, in 9 blocks |
| with nothing to declare | 27 |
| notes under the commands | 2, both on a feature |
| the result codes' clause, 6.2 | 1 sentence, a block per answer |
| blocks | 15: 8 on an AVP wherever read, 7 within a command |
| readings | 15 |

| Rules | |
|---|---|
| `encoding`, a codec | 1: `e164-tbcd` (MSISDN) |
| `encoding element` | 3, naming 3 entries of the registry; 2 rules checked, 1 not ([above](#elements)) |
| `requires` | 1: One-Time-Notification in SNR, on Data-Reference |
| `absent-if` | 4: Result-Code in UDA, PUA, SNA and PNA, beside one of clause 6.2's codes in Experimental-Result's Experimental-Result-Code |
| `default` | 1: Pre-paging-Supported |
| `bits` | 1: `only` (UDR-Flags) |
| `members` | 1: `at-least-one` (User-Identity) |
| `text-only` | 3 |

The text-only rules are the two notes making a second Data-Reference in PUR,
and any in PUA, depend on both nodes supporting Update-Eff-Enhance, and
Wildcarded-Public-Identity's "only contains a Wildcarded PSI", which a
Wildcarded IMPU's text does not differ from. User-Identity's "either ... or"
is read as at least one of its three members: that no two are present has no
`members` form. Clause 6.2's "Result-Code AVP shall be absent" is read of
each answer as a path into its Experimental-Result, the codes the clause
lists, those it takes from TS 29.229 among them. Left unread:
Data-Reference's value 20, which the clause marks reserved without saying it
is not sent; and Server-Name's "SIP-URL", for which no codec exists.

## TS 29.273

TS 29.273 V19.2.0 is read completely: every AVP clause of clauses 5.2.3,
7.2.3, 8.2.3 and 9.2.3, and every C row of the information-element tables
of clauses 4.1.2, 5.1.2, 6.1.2, 7.1.2, 8.1.2, 9.1.2 and 11.1.2, and the
procedure and session-handling clauses for what they state of one message.
Release 18's copy, V18.6.0, prints every sentence read and holds all 258
blocks: it prints a reference to another 3GPP document as "3GPP TS" where
Release 19 prints "TS", so a quote ends before such a reference.

The document prints Diameter-EAP-Request and -Answer for SWa with no
application and for STa and SWd under 16777250, and S6b's AA-Request and
-Answer twice under 16777272, each print with a body of its own; a block
names the print its table describes with `; Command-Section:`, as the
corrections attaching the tables do. A re-authentication's answer is the
first exchange's print: a row there allowing DIAMETER_SUCCESS alone, where
the first exchange's allows DIAMETER_MULTI_ROUND_AUTH too, is text-only,
since reading it would refuse the first exchange's answer.

| | |
|---|---|
| AVP clauses (clauses 5.2.3, 7.2.3, 8.2.3 and 9.2.3, not their General, Void and grouping clauses) | 81 |
| with something to declare | 36, in 51 blocks |
| with nothing to declare | 45 |
| information-element C rows | 157, of which 147 state a condition, a block each |
| procedure clauses | 9.1.2.1.3's relocated PDN GW and 8.2.4's Auth-Session-State, in 9 blocks |
| session-handling clauses | 5.2.4's, 7.2.4's and 9.2.4's Auth-Session-State and 8.2.4's Authorization-Lifetime and Session-Timeout, never sent, in 51 blocks |
| blocks | 258: 37 on an AVP wherever read, 21 within a grouped AVP, 200 within a command |
| readings | 284 |

| Rules | |
|---|---|
| `encoding`, a codec | 5: `mac-address` 2 (HESSID, TWAG-UP-Address), `labels`, `ip-address`, `plmn-domain` |
| `encoding element` | 6, naming 6 entries of the registry; 4 rules checked, 2 not ([above](#elements)) |
| `length` | 3, in octets |
| `range` | 13: Auth-Session-State NO_STATE_MAINTAINED in SWx's 8 commands, Feature-List-ID 1 in each of the 4 applications, AN-Trusted TRUSTED in STa's answer |
| `exclude` | 1: Subscription-Id-Type, MSISDN and External Identifier only |
| `requires`, `present-if`, `absent-if` | 35, 30, 7 |
| `absent` | 51: Auth-Session-State in every STa, SWm and S6b command but the ASR, whose Auth-Session-State a 3GPP AAA Proxy may set (clauses 5.1.2.2.3, 7.1.2.4.3, 9.1.2.4.4), Authorization-Lifetime and Session-Timeout in SWx's 8 commands |
| reading the request | 7: SAA's Non-3GPP-User-Data as the SAR's Server-Assignment-Type asks, S6b answers' QoS-Resources only after a QoS-Capability, MIP-Session-Key after an MIP-MN-HA-SPI and no APN-Configuration for an emergency, STa's AA-Answer's MIP6-Feature-Vector only after the request's |
| `default` | 1: Access-Authorization-Flags in TWAN-Access-Info |
| `bits` | 12, each `only`: a flags AVP's NOTE that undefined bits are cleared |
| `members` | 9: `only` 6 (Trace-Info in an answer), `at-least-one` 3 (Trace-Info, Access-Network-Info's SSID, IMEI in STa's Terminal-Information, a member of TS 29.272's AVP) |
| `unique` | 1: WLAN-Identifier in TWAN-Access-Info |
| `text-only` | 116 |

Most text-only rules are conditions on the node, the subscription, the
operator's policy, the procedure or an earlier message ("shall be sent to
the 3GPP AAA Server if the UE has access priority", "if this information is
available in the user subscription", "was not set in the initial
Authentication and Authorization Answer"). A row whose condition is partly
the node's keeps the part a message shows where that part alone holds of
every message the row allows: "shall contain the MSISDN of the UE and shall
be sent if it is available" is read as the Subscription-Id's type, and
"shall be included only if the QoS-Capability AVP was received in the
authorization request and the authorization succeeded" as the request's
QoS-Capability. The rest a single message could show but the format cannot
say: a text value (the authentication scheme in SIP-Auth-Data-Item,
EAP-AKA', ANID's "HRPD"), a byte of a variable-length payload
(Location-Information's Code, Operator-Name's Namespace ID), a flag of
MIP6-Feature-Vector, whose flags clause 5.2.3.3 lists in prose and RFC
5447's bit table names two of, and five rows whose AVP the command's ABNF
leaves to its `* [ AVP ]` and whose condition is the node's
(Transport-Access-Type in STa's and SWd's request,
IMEI-Check-In-VPLMN-Result, AMBR in STa's AA-Answer, AN-Trusted in S6b's
Diameter-EAP-Answer), read where the document reads the AVP.
ME-Identity-Check-Answer's Equipment-Status row is TS 29.272's command,
which this file does not print, and TS 29.272's file reads it.

The session-handling clauses' "shall not include the Auth-Session-State
AVP" (clauses 5.2.4, 7.2.4, 9.2.4) and "Neither the Authorization-Lifetime
AVP nor the Session-Timeout AVP shall be present" (clause 8.2.4) are read as
`absent` in each command of the interface, a body admitting the AVP through
its `* [ AVP ]`; Non-3GPP-User-Data's Session-Timeout is that grouped AVP's
member, not the command's. Left unread: DER-Flags' and
DEA-Flags' "This bit is only applicable to the TWAN authentication and
authorization procedure", which says what a bit means, not when it is set;
the detailed-behaviour clauses' result codes, which are what a node answers
with, not a condition on an AVP; and the C rows saying only what an AVP
holds when present ("If present, this IE shall contain the untrusted
non-3GPP access network technology type").

## TS 29.212

TS 29.212 V19.1.0 is read for each of its applications, Gx, Gxx, Sd, St and
S15: every AVP clause of clauses 5.3, 5a.3, 5b.3, 5c.3 and E.6.3, the
re-used AVPs' descriptions of tables 5.4.0.1, 5a.4.0.1, 5b.4.0.1, 5c.4.1.1
and E.6.4.1.1, the supported-features and result-code clauses, 5.4.2's
Flow-Description, and the procedure clauses for what they state of one
message (4.5.1's IP-CAN session establishment, 4a.5.1's Gateway Control
Session's, 4b.5.1.1's TDF session's). Release 18's copy, V18.2.0, prints
every sentence read and holds all 137 blocks; the Release 11 copy, held for
citations, is offered none. The re-used AVPs' tables of Gxx, Sd, St and S15
mostly repeat Gx's descriptions, which a block on the AVP wherever read, or
within the document's own grouped AVP, already reads.

The document has no information-element tables, and prints CC-Request,
CC-Answer, RA-Request and RA-Answer for Gx, Gxx, Sd and S15 with no
application id in their headers, and TS-Request and TS-Answer for Sd and
St: a block names the print's application with `; Application-ID:`, which
the application scope covering its clause gives it, Gx's in clause 5.6,
Gxx's in 5a.6, Sd's in 5b.6, St's in 5c.6, S15's in E.6.6. A PCC rule's
Charging-Rule-Definition modifies the one installed before it, keeping what
it omits (clause 5.3.4), and an ADC rule's ADC-Rule-Definition likewise
(clause 5b.3.3), so a condition on their members is `text-only`.

| | |
|---|---|
| AVP clauses (clause 5.3, not its General and Void clauses) | 130 |
| with something to declare | 59, in 102 blocks |
| with nothing to declare | 71 |
| Gxx's, Sd's, St's and S15's AVP clauses (5a.3, 5b.3, 5c.3, E.6.3) | 19, 4 with something to declare, in 8 blocks |
| re-used AVPs' descriptions (tables 5.4.0.1, 5b.4.0.1) | 9 blocks |
| supported features, Flow-Description, result codes (5.4.1, 5.4.2, 5.5.1, 5a.4.1, 5b.4.1, 5b.5.1, 5c.4.2, E.6.4.2) | 11 blocks |
| procedure clauses (4.5.1, 4a.5.1, 4b.5.1.1) | 7 blocks |
| blocks | 137: 52 on an AVP wherever read, 35 within a grouped AVP, 50 within a command |
| readings | 168 |

| Rules | |
|---|---|
| `encoding`, a codec | 11: `ip-address` 6 (AN-GW-Address, CoA-IP-Address, Routing-IP-Address, TDF-IP-Address, HeNB-Local-IP-Address, UE-Local-IP-Address), `ip-filter-out` 4 (TFT-Filter, Packet-Filter-Content, Flow-Description wherever read and in Routing-Filter), `ip-filter` (Tunnel-Header-Filter) |
| `encoding element` | 4, naming 4 entries of the registry, all checked ([above](#elements)) |
| `length` | 1: ToS-Traffic-Class, 2 octets |
| `range` | 2: Priority-Level 1 to 15, Routing-Filter's Flow-Direction BIDIRECTIONAL |
| `exclude` | 1: Event-Trigger's obsolete values 8, 9, 10, 38 and 41 |
| `requires`, `present-if`, `absent-if` | 6, 42, 4 |
| reading the request | 3: the initial CCA's Supported-Features beside the CCR's, Sd's and St's TSA's none without the TSR's |
| `default` | 4: QoS-Negotiation, Pre-emption-Capability, Pre-emption-Vulnerability, Usage-Monitoring-Level |
| `bits` | 2: `set` and `clear`, an ADC rule's ToS-Traffic-Class mask 11111100 |
| `members` | 7: `at-least-one` 6 (TDF-Information's realm and host or address, Conditional-APN-Aggregate-Max-Bitrate's bandwidths and conditions, the Flow-Description and Flow-Direction of Application-Detection-Information's Flow-Information), `only` (an ADC rule's QoS-Information, its maximum bandwidths) |
| `text-only` | 87 |

Most checked rules are clause 5.3.7's: an event trigger a CCR reports, of
any of its Event-Trigger AVPs, with the AVP the value's description says it
is sent with (SGSN_CHANGE's 3GPP-SGSN-Address or 3GPP-SGSN-IPv6-Address,
TAI_CHANGE's 3GPP-User-Location-Info, USAGE_REPORT's
Usage-Monitoring-Information), 29 conditions.
Gxx's initial CCR carries the AN-GW-Address (clause 4a.5.1), Sd's TS-Request
the UE's IPv4 address or IPv6 prefix (4b.5.1.1), and each Gx and Sd answer's
Experimental-Result the 3GPP vendor (5.5.1, 5b.5.1). A deletion's
Packet-Filter-Information "only the Packet-Filter-Identifier" is read on the
CCR as the AVP absent where it holds another member, a path
into it, since its own scope does not see the command's
Packet-Filter-Operation.

The text-only rules are mostly conditions on the node, the bearer binding,
the subscription or an earlier message ("For GPRS scenarios where the
bearer binding is performed by the PCRF", "If ... not been previously
provided, its absence shall indicate", "the PCRF supports Rel-8 Gxx
functionality"), the members of a Charging-Rule-Definition or an
ADC-Rule-Definition, Gxx's initial Subscription-Id, which an emergency
session's BBERF without the IMSI replaces by the IMEI(SV) (clause
4a.5.12.1.1), and defaults resting on what was supplied before. St's TSA is
held to its request's Request-Type 0, "0 (initial request)" (clause 5c.2).
The rest a single message could show but the format cannot say: which of a
CCR's Charging-Rule-Reports are a lost bearer's, a text's start (an NBIFOM
Routing-Rule-Identifier's "PCEF" or "PCRF"), digits as text where a
sibling's type says IMEISV, User-Equipment-Info-Extension's members, which
RFC 8506 defines and this document does not print, Granted-Service-Unit's
and Used-Service-Unit's re-used members, which a `members` rule cannot name
beside the Monitoring-Time their `* [ AVP ]` admits, non-GBR QCIs, which
are TS 23.203's, and Max-PLR-DL's and Max-PLR-UL's range 0 to 1000, which
the clauses read of an Unsigned32 and table 5.3.0.1, as the corpus prints
it, types Float32: the document disagrees with itself in V18.2.0, V19.1.0
and Release 20's V20.0.0 alike, and implementations split (Wireshark's
dictionary types the AVPs Float32, freeDiameter's Unsigned32, changing the
table's type), so the corpus keeps the table's type and the range is read
of neither. No linter rule reads the type a plain AVP's clause states, so
the disagreement is recorded here and in the blocks, not as a finding.
Clause 5.3.27's "The Event-Trigger AVP with value IP-CAN-CHANGE shall be
provided together with the IP-CAN-Type AVP" is
text-only, since clause 5.3.7's NBIFOM event triggers carry an IP-CAN-Type
too; clause 5.3.53's unconditional "shall include the Flow-Direction AVP"
is, beside its sentence excusing a Flow-Information holding only a
Packet-Filter-Identifier; and clause 5.3.40 names Extended-APN-AMBR-DL for
the uplink, citing 5.3.135's Extended-APN-AMBR-UL. Left unread: the
sentences saying a value or an AVP is "applicable" or "not applicable" to an
interface or a release, with no "shall" (Session-Release-Cause's values
"to be used by Sd only", Charging-Rule-Install's IP-CAN-Type "Only the
3GPP-EPS and Non-3GPP-EPS IP-CAN type values are applicable in this
release", Max-PLR's "only applicable for PCC rule with QCI=1"); "is
provided" and "may ... when" sentences (the NBIFOM event triggers' IP-CAN
type, Quota-Consumption-Time beside a CC-Time); the M-bit and vendor
settings of table 5.4.0.1, which the AVP table's flags already state; and
the Sd table's sentences on grouped AVPs Gx shares, which a scope of the
grouped AVP would hold to both: Application-Detection-Information's
Flow-Information, where "only Flow-Description AVP and Flow-Direction AVPs
are used", and Usage-Monitoring-Level, where "Only SESSION_LEVEL (0) ... and
ADC-Rule-Level (2) apply", against clause 5.3.61's default PCC_RULE_LEVEL,
which the file reads wherever the AVP is read, Sd's too.
