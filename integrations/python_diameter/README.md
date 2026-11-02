# python-diameter

Two scripts over the [model](../../docs/consumers.md) for
[python-diameter](https://github.com/mensonen/diameter): `validate.py`
checks the library's merged command classes against one specification at a
time, and `generate.py` writes per-application command modules in the
library's own shape, for the library to carry beside its merged classes.
Both carry PEP 723 metadata, so uv supplies seanchai and the library.

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 TS29.272 -o out/cx_s6a
uv run integrations/python_diameter/generate.py --all -o out/protocols \
    --dictionary specifications/wireshark
uv run integrations/python_diameter/generate.py --all -o out/protocols \
    --undefined supply --supply acme.dad
```

`generate.py` takes references (`TS29.229`, `29.229`, `RFC6733`) or
`--all`, `--corpus` for a corpus other than the repository's `dad/`,
`--dictionary` for Wireshark's AVP names, and `--undefined` with `--supply`
for the names the corpus declares defined nowhere ([below](#undefined-names)).
It reads the installed library
for the names it references, replaces the output directory only if every
file in it is one it wrote, and prints how many additions each
specification needs (`TS29.229: 19 additions`). The output is a function
of the corpus, the Wireshark dictionary, the library version and the
options alone, byte for byte: regenerating after a change to any of them
gives a reviewable diff.

## Output layout

```
out/protocols/
  __init__.py            module list, the documents generated from, additions per module
  additions.py           what the library's dictionary and grouped classes lack
  ts29_229.py            one module per application and interface
  ts29_212_5a.py         ...interface clause appended where a document has several
  ts29_272_16777308.py   ...application id where several share one clause
```

A module groups what `Model.applications` groups: one document's commands
for one application id under one interface clause. TS 29.212 gives
`ts29_212_5` (Gx), `_5a` (Gxx), `_5b` (Sd), `_5c` (St) and `_e_6` (S15); TS
29.273 gives one module per reference point, three of them sharing
16777250; RFC 6733 gives `rfc6733_5` (CER, DWR, DPR), `_8` (RAR, STR, ASR)
and `_9` (ACR); TS 32.299's clause 6 gives `ts32_299_3` (Rf) and `_4`
(Ro), and RFC 5778's clause 5 `rfc5778_7` and `_8`.

Each module is written the way `diameter/message/commands/*.py` is: a
`DefinedMessage` base class per command code with `code`, `name` and the
library's `type_factory`, and a Request and an Answer subclass per
direction with one annotation and one `AvpGenDef` per member, the list
members initialised in `__post_init__` and the received AVPs assigned with
the library's `assign_attr_from_defs`. Class names, `name` and attribute
spellings are the library's wherever it has them — TS 29.212's
`CC-Request` is `CreditControlRequest`, RFC 4005's AAR `AaRequest` — and
the document's otherwise. The `AvpGenDef`s reference the library's `AVP_*`
and `VENDOR_*` constants and its `grouped.py` classes, with `is_required`
from the brackets and `is_mandatory` wherever the flag rules fix the M bit:

```python
APPLICATION_ID = APP_3GPP_CX  # 16777216, 3GPP Cx/Px, TS29.230 table 4.1


class RegistrationTermination(DefinedMessage):
    code: int = 304
    name: str = "Registration-Termination"
    avp_def: AvpGenType
    ...


class RegistrationTerminationRequest(RegistrationTermination):
    """A Registration-Termination-Request message, clause 6.1.9."""
    session_id: str
    ...
    rtr_flags: int
    proxy_info: list[ProxyInfo]
    route_record: list[bytes]

    avp_def: AvpGenType = (
        AvpGenDef("session_id", AVP_SESSION_ID, is_required=True, is_mandatory=True),
        ...
        AvpGenDef("rtr_flags", AVP_TGPP_RTR_FLAGS, VENDOR_TGPP, is_mandatory=False),
        # * [ AVP ]
        AvpGenDef("proxy_info", AVP_PROXY_INFO, is_mandatory=True, type_class=ProxyInfo),
        AvpGenDef("route_record", AVP_ROUTE_RECORD, is_mandatory=True),
    )
```

`AVP_TGPP_RTR_FLAGS` is not one of the library's constants: the module
imports it from `additions`. The imports are absolute
(`diameter.message.constants`, not `..constants`), so a module works both
where it was generated and inside the library.

## The additions

The library's dictionary is not papered over. `additions.py` holds, in the
shapes of `dictionary.py`, `constants.py` and `grouped.py`:

- **New entries**, for AVPs the dictionary lacks, under new constants named
  the library's way (`AVP_TGPP_RTR_FLAGS = 659`), in
  `AVP_DICTIONARY_ADDITIONS` and `AVP_VENDOR_DICTIONARY_ADDITIONS[10415]`,
  one `AvpInfo` per line with the defining clause as a comment. Where the
  dictionary has the name under another identity, the comment says so. A
  new enumerated AVP gets `E_` constants for its values, those a
  correction supplies included, a comment naming the document its clause
  defers them to where it does, and a comment for each
  range its document leaves to vendors (`; VENDOR-SPECIFIC`), whose values
  are legal with no constant. The library checks no enumerated value, so
  nothing else stands in their way.
- **Corrections**, for entries whose value class carries something other
  than the document's type, keyed by the library's own constant:
  `AVP_RESULT_CODE` is AvpInteger32 in 0.9.0 where RFC 6733 says
  Unsigned32. An Enumerated held as AvpInteger32 (AvpEnumerated's base)
  and the string-derived types held as either string class are not
  corrected, since the library uses both for them. A rule naming a
  corrected AVP says so in a comment. An identity whose documents disagree
  on its type, one of them as the library holds it, is listed in a closing
  comment instead (RFC 4005 and RFC 7155 on `Framed-IPX-Network`).
- **Grouped classes**, `grouped.py` dataclasses for every grouped reading the
  library's class does not carry as the document says. The library's class is
  reused only when its members' identities, their nesting and their M bits all
  agree with the reading: it must hold every member the reading names, each
  grouped member in a class that itself agrees, and encode each member's M bit
  as the reading's flag rules fix it (its `is_mandatory`, or failing that the
  dictionary default; a member whose rules leave M open accepts either). TS
  29.229's `Supported-Features` gets `SupportedFeatures_TS29_229`, since the
  library's `SupportedFeatures` sets M on Feature-List-ID and Feature-List,
  which TS 29.229's table forbids. The docstring says which of these failed. A
  class never takes a name the library binds: a second reading of one AVP, or a
  reading the library's class does not serve, is suffixed with its first
  document (`ScscfRestorationInfo_TS29_229`, `SipAuthDataItem_TS29_229` beside
  the library's IETF `SipAuthDataItem`). Readings of one AVP with one body share
  a class, the defining document's own reading naming it: TS 29.272's re-used
  table clears M on TS 32.299's `User-CSG-Information`, which is the
  `is_mandatory=False` on the rule naming `UserCsgInformation_TS32_299`, not a
  class of its own. A citing document's rules for the members make another body:
  TS 32.299's `Supported-Features` sets M on Feature-List-ID and Feature-List,
  so its reading is the library's `SupportedFeatures`.

Importing `additions` changes nothing in the library. `register()` merges
the new entries into the library's global dictionaries, which the command
modules need before they encode an AVP only `additions` defines
(`Avp.new` refuses an unknown one); `register(corrections=True)` also
replaces the corrected entries, which changes how the library's own merged
classes read those AVPs.

The count a specification reports is the new entries, corrections and
grouped classes its modules and its dictionary view reach; the module list
in `__init__.py` counts per module.

## Adopting it in the library

The generated modules are additive, and nothing in them registers
anything: a class subclassing `DefinedMessage` outside the library's
package has no side effect, since `all_commands` is built once, when
`diameter.message.commands` is imported, and `commands.register` is never
called. A maintainer would:

1. Put the modules in a package of their own beside the merged classes,
   such as `diameter/message/commands/<application>/` or
   `diameter/message/protocols/`, leaving the existing modules untouched.
2. Merge `additions.py`: its constants into `constants.py`, its entries into
   `dictionary.py` (reviewing each correction for the merged classes'
   users), its dataclasses into `grouped.py`, and drop the import from the
   modules. `register()` is then unnecessary.
3. Not import the new package from `commands/__init__.py` above the
   `all_commands` table. That table is `DefinedMessage.__subclasses__()`
   keyed by code, so new base classes loaded first would replace the
   merged classes for every code they share, which is exactly the switch
   the library should make opt-in.
4. Add the opt-in dispatch: a lookup from the header's application id and
   command code to a module's base class, built from each module's
   `APPLICATION_ID` and classes, with configuration where an id is shared
   (TS 29.273's SWa, STa and SWd) or absent (`rfc6733_8`). The tests do it
   by hand: `Message.from_bytes(data, plain_msg=True)`, then
   `ts29_229.UserAuthorization.type_factory(header)(header, avps)`.

Until then the merged classes serve every received message, and the
generated ones are built by hand, as the library's are.

## What the library's shape cannot carry

- **Occurrence bounds.** `AvpGenDef` has `is_required` and no minimum or
  maximum; a list attribute says the member repeats. Bounds the two convey
  (`[ X ]`, `{ X }`, `*[ X ]`, `1*{ X }`) are written as such; any other is
  the ABNF line as a trailing comment (`# *2 [ AN-GW-Address ]`), and
  nothing enforces it. An unset required member is only logged at encode
  time, as for the library's classes.
- **A member printed twice.** The library decodes by identity, so TS
  29.345's `WiFi-P2P-Assistance-Info`, which prints
  `[ WLAN-Link-Layer-Id-List ]` twice, gets one list attribute with a
  comment naming both lines.
- **Wireshark's names.** The library has no slot for another spelling;
  with `--dictionary`, Wireshark's name is a trailing comment where it
  differs (`# Wireshark: Cx-User-Data`).
- **Enumerated values** of AVPs the library already holds, and where a
  clause defers its values to another document, except for new entries:
  the library keeps `E_` constants per AVP, and `additions` writes them only
  for the AVPs it adds.
- **The application id on the wire.** The library's classes leave
  `header.application_id` to the caller, and so do these; `APPLICATION_ID`
  is the value to set and the dispatcher's key.
- **An M bit the flag rules leave open** (M under May, or an IETF AVP's
  M that RFC 6733 section 4.1 leaves to the application using it,
  RFC 4072's `EAP-Payload` among them) takes the dictionary's default, as
  there is no `is_mandatory` to state.
- **The library's grouped classes, where they serve.** A grouped AVP whose
  library class agrees with the reading on member identities, nesting and
  M bits is carried by that class, with its own `is_required` flags rather
  than the document's.
- **Holes.** An AVP the corpus knows the identity of but cannot complete
  is an `AvpGenDef` with the reason as a comment (`# hole: TS29.061
  3GPP-Session-Stop-Indicator: no data_type, no flag_rules`), or, absent
  from the dictionary, an entry
  typed `Avp` when no document states its type. A name that resolves to no
  identity, like `* [ AVP ]`, is a comment in its place; the library keeps
  such AVPs in the additional AVPs.
- **A member without a code.** `AvpGenDef` needs one, so an undefined
  name kept as a placeholder is a comment in its place, as a hole without
  an identity is, labelled as the choice it is (below).

## Undefined names

Nine members the corpus's documents use are defined nowhere: RFC 4004's three
SPIs, TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
`External-Group-Identifier`, TS 32.299's `Submission-Timestamp` and
`Network-Element`, TS 29.234's `Error-Cause`
([consumers.md](../../docs/consumers.md#undefined-names)). `--undefined` is the
model's policy for them, and `__init__.py`'s docstring records it with what
became of each name the generated set reaches
(`Undefined names, --undefined drop: dropped: RFC4004 MIP-HA-to-MN-SPI, …`):

- **`hole`**, the default: as any hole, a comment in its place
  (`# { MIP-HA-to-MN-SPI }  # hole: RFC4004 MIP-HA-to-MN-SPI: undefined
  (clause 9.4)`), and a grouped class's docstring says `Hole:`.
- **`drop`**: no `AvpGenDef` and no comment; the command or grouped class
  the script writes says in its docstring what it dropped (`Dropped,
  undefined in the corpus: { External-Group-Identifier } (TS29.154 clause
  A.6.6.2), required by the ABNF.`). A grouped AVP the library's class
  carries gets no class and so no such line; `__init__.py` lists every
  dropped name. Nothing goes to `additions.py`; on decode the library puts
  such an AVP in `additional_avps`. Four of the nine are required
  members, so a command built so no longer carries what its ABNF requires.
- **`placeholder`**: a comment in its place, as for `hole`, but labelled
  as the consumer's choice (`# [ ProSe-Query-Code ]  # placeholder:
  undefined in TS29.345 clause 6.3.53`). The library's shape allows no
  more: a placeholder has no code. Nothing goes to `additions.py`.
- **`supply`**, with one or more `--supply PATH.dad`: hand-authored `.dad`
  sidecars stating the definitions, each complete in its file (an AVP
  table row with code, type and flags, and a grouped or enumerated section
  for a body or values; `model.supplied_from`). A supplied AVP is an
  ordinary definition: an `AvpGenDef` with its constant, an
  `additions.py` entry where the library lacks the identity, noted
  `supplied: ACME ProSe dictionary (acme.dad)` there and on the member,
  and the sidecar among the sources. A name no sidecar supplies stays a
  hole. A sidecar claiming the identity of an AVP the corpus defines is
  refused. `--supply` without `--undefined supply`, or the reverse, is
  refused too.

An `Alias` (TS 29.154's `External-Group-Identifier` read as TS 29.336's
`External-Identifier`) is the model's, through `generate()` with a model
built with one; the member takes the named AVP's constant, commented
`{ External-Group-Identifier } read as TS29.336 External-Identifier:
<source>`. No sidecar spells one.

## What the tables mark

A document's AVP tables may mark where each row applies
([consumers.md](../../docs/consumers.md#the-model) has the labels). The
ABNF decides a class's members, being the wire format; the marks are
comments on them, read for each command from the document generating it,
as printed. The first row for a member printing a column with a mark or a
dash speaks for it; a blank cell says nothing.

- **Use in the command.** TS 32.299's tables mark per command whether an
  AVP is used in ACR, ACA, CCR and CCA, from any of its tables. Where the
  mark is the dash clause 7.1.0 reads as "not used", the comment says so;
  the member stays, as the ABNF lists it. In the committed corpus that is
  ACA's `Error-Message` and `Failed-AVP` (table 7.1.0.1, against clause
  6.2.3's ABNF; the linter's `member-marked-unused` reports it):

  ```python
  (
      AvpGenDef("error_message", AVP_ERROR_MESSAGE, is_mandatory=False),
  )  # ACA: - (unused, table 7.1.0.1)
  ```

- **Every other mark, from the command's interface clause.** Access types,
  functions and supported features say when an AVP is used within an
  interface, not on which: the documents give each interface its own
  tables. So TS 29.212's Gxx module reads table 5a.4.0.1 where its Gx
  module reads 5.3.0.1 (`Applicability: EPC-routed (See NOTE 8)` beside
  Gx's `Both, Rel8, EPC-routed`). An `Acc-Type` of plain `All` restricts
  nothing and is not repeated; `All (NOTE 5)` is.

TS 29.061's reference points (`Gi`, `Sgi`) are on AVPs no 29.061 command
carries, Gi/SGi using RFC 7155's commands (clauses 16a.1, 16a.2), so no
module shows them.

## What the documents leave to the reader

**Application ids.** The application id comes from the command header the
document prints, or, where the headers print none, from the `Application Scope`
block that records the document's statement in prose; such a module's docstring
names the clause
(`The command headers print no application id; clause 5.1 states Gx's.`). Where
no block names the application, the `APPLICATION_ID` comment gives TS 29.230
table 4.1's name for the id, which the id itself never comes from. The 3GPP
blocks are read from the documents (TS 29.153, 29.154, 29.212, 29.214, 29.215,
29.217, 29.219, 29.343, 29.368, 29.468); those for RFC 4004, 4005, 4006, 4072,
5778, 6733, 7155, 8506, TS 32.299 and oneM2M TS-0004 are corrections citing the
clause, since each words it differently. Two readings are worth knowing: RFC
4005 clause 1.3 gives the commands it takes from the base protocol "the Base
application id value", and the block follows clause 11.3 and RFC 7155 in giving
all of clause 3 the NASREQ id 1; RFC 6733's ACR is the base accounting
application's 3, the split accounting model of clause 9.3, where coupled
accounting carries the using application's id. `APPLICATION_ID` is the library's
`APP_` constant for the id where it has one.

`rfc6733_8` alone has `APPLICATION_ID = None`: clause 2.5 says RAR, STR and
ASR "MUST carry the Application Id of the application" they serve.

**Commands printed twice.** A document that prints one command twice in one
interface clause gets one class when the bodies agree (TS 29.273's STa STR,
clauses 5.2.2.2.3 and 5.2.2.4.1, whose docstring cites both) and a second
class named with its clause when they differ (TS 29.273's clause 9 AAR,
application 16777272: `AaRequest_9_2_2_5_1`). `type_factory` returns the
first, and the library's `to_answer`, which pairs classes by the
`Request`/`Answer` suffix, does not pair the second.

**Header flags.** A class's `header.is_request` is its header's REQ flag.
Where a header's flag disagrees with the command's name the class says so
in a comment; the corpus corrects the two misprints known (TS 29.336 clause
8.2.5's RIR printed without REQ, TS 29.273 clause 7.2.2.1.4's AAA with it),
so the committed corpus generates no such class.
