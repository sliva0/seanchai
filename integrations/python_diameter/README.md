# python-diameter

Two scripts over the [model](../../docs/consumers.md) for
[python-diameter](https://github.com/mensonen/diameter): `validate.py`
checks the library's merged command classes against one document at a
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
`--all`, `--corpus` for a corpus other than the installed one,
`--dictionary` for Wireshark's AVP names, and `--undefined` with `--supply`
for the names the corpus declares defined nowhere
([below](#undefined-names)). It reads the installed library for the names
it references, replaces the output directory only if every file in it is
one it wrote, and prints how many additions each document needs. The
output is a function of the corpus, the Wireshark dictionary, the library
version and the options alone, byte for byte, so regenerating after a
change gives a reviewable diff.

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
`ts29_212_5` (Gx), `_5a` (Gxx), `_5b` (Sd), `_5c` (St) and `_e_6` (S15);
RFC 6733 gives `rfc6733_5` (CER, DWR, DPR), `_8` (RAR, STR, ASR) and `_9`
(ACR); TS 32.299's clause 6 gives `ts32_299_3` (Rf) and `_4` (Ro).

Each module is written the way `diameter/message/commands/*.py` is: a
`DefinedMessage` base class per command code, and a Request and an Answer
subclass per direction with one annotation and one `AvpGenDef` per member.
Class names, `name` and attribute spellings are the library's wherever it
has them, and the document's otherwise. The `AvpGenDef`s reference the
library's `AVP_*` and `VENDOR_*` constants and its `grouped.py` classes,
with `is_required` from the brackets and `is_mandatory` wherever the flag
rules fix the M bit:

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
imports it from `additions`. The imports are absolute, so a module works
both where it was generated and inside the library.

## The additions

`additions.py` holds, in the shapes of `dictionary.py`, `constants.py` and
`grouped.py`:

- **New entries**, for AVPs the dictionary lacks, under new constants named
  the library's way (`AVP_TGPP_RTR_FLAGS = 659`), one `AvpInfo` per line
  with the defining clause as a comment. A new enumerated AVP gets `E_`
  constants for its values, and a comment for each range its document
  leaves to vendors.
- **Corrections**, for entries whose value class carries something other
  than the document's type, keyed by the library's own constant
  (`AVP_RESULT_CODE` is AvpInteger32 where RFC 6733 says Unsigned32). An
  Enumerated held as AvpInteger32 and the string types held as either
  string class are not corrected, since the library uses both.
- **Grouped classes**, `grouped.py` dataclasses for every grouped reading
  the library's class does not carry as the document says. The library's
  class is reused only when its members' identities, their nesting and
  their M bits all agree with the reading; otherwise the class is suffixed
  with its first document (`SupportedFeatures_3GPP2_X_S0013_006`, since the
  library's `SupportedFeatures` sets M on two members the tables of 3GPP2
  X.S0013-006 and TS 29.229 forbid).
  Readings of one AVP with one body share a class.

Importing `additions` changes nothing in the library. `register()` merges
the new entries into the library's global dictionaries, which the command
modules need before they encode an AVP only `additions` defines;
`register(corrections=True)` also replaces the corrected entries.

## Adopting it in the library

The generated modules are additive, and nothing in them registers
anything: `all_commands` is built once, when `diameter.message.commands`
is imported. A maintainer would:

1. Put the modules in a package of their own beside the merged classes,
   leaving the existing modules untouched.
2. Merge `additions.py`: its constants into `constants.py`, its entries
   into `dictionary.py`, its dataclasses into `grouped.py`, and drop the
   import from the modules.
3. Not import the new package from `commands/__init__.py` above the
   `all_commands` table, since new base classes loaded first would replace
   the merged classes for every code they share.
4. Add the opt-in dispatch: a lookup from the header's application id and
   command code to a module's base class, built from each module's
   `APPLICATION_ID`, with configuration where an id is shared or absent.
   The tests do it by hand: `Message.from_bytes(data, plain_msg=True)`,
   then `ts29_229.UserAuthorization.type_factory(header)(header, avps)`.

## What the library's shape cannot carry

- **Occurrence bounds.** `AvpGenDef` has `is_required` and no minimum or
  maximum. Bounds the two convey (`[ X ]`, `{ X }`, `*[ X ]`, `1*{ X }`)
  are written as such; any other is the ABNF line as a trailing comment,
  and nothing enforces it.
- **A member printed twice.** The library decodes by identity, so a member
  printed twice gets one list attribute with a comment naming both lines.
- **Wireshark's names.** With `--dictionary`, Wireshark's name is a
  trailing comment where it differs (`# Wireshark: Cx-User-Data`).
- **Enumerated values** of AVPs the library already holds: `additions`
  writes `E_` constants only for the AVPs it adds.
- **The application id on the wire.** The library's classes leave
  `header.application_id` to the caller; `APPLICATION_ID` is the value to
  set and the dispatcher's key.
- **An M bit the flag rules leave open** takes the dictionary's default.
- **Holes.** An AVP the corpus knows the identity of but cannot complete is
  an `AvpGenDef` with the reason as a comment (`# hole: TS29.061
  3GPP-Session-Stop-Indicator: no data_type, no flag_rules`). A name that
  resolves to no identity, like `* [ AVP ]`, is a comment in its place.

## Undefined names

Nine members the corpus's documents use are defined nowhere
([consumers.md](../../docs/consumers.md#undefined-names)). `--undefined` is
the model's policy for them, and `__init__.py`'s docstring records it with
what became of each name:

- **`hole`**, the default: a comment in its place, as for any hole.
- **`drop`**: no `AvpGenDef` and no comment; the class's docstring says
  what it dropped and whether the ABNF required it.
- **`placeholder`**: a comment in its place, labelled as the consumer's
  choice. The library's shape allows no more, since a placeholder has no
  code.
- **`supply`**, with one or more `--supply PATH.dad`: hand-authored `.dad`
  sidecars stating the definitions. A supplied AVP is an ordinary
  definition, with an `additions.py` entry where the library lacks the
  identity, noted with its source. A sidecar claiming the identity of an
  AVP the corpus defines is refused.

An `Alias` is the model's, through `generate()` with a model built with
one; the member takes the named AVP's constant, with a comment saying what
it was read as.

## What the tables mark

The ABNF decides a class's members, being the wire format; a document's
table marks ([consumers.md](../../docs/consumers.md#the-model)) are
comments on them, read for each command from the document's tables as
printed. TS 32.299's tables mark per command whether an AVP is used; where
the mark is the dash clause 7.1.0 reads as "not used", the comment says so
and the member stays. Every other mark comes from the command's interface
clause: TS 29.212's Gxx module reads table 5a.4.0.1 where its Gx module
reads 5.3.0.1. An `Acc-Type` of plain `All` restricts nothing and is not
repeated.

## What the documents leave to the reader

**Application ids.** The id comes from the command header, or, where the
headers print none, from the `Application Scope` block recording the
document's statement in prose; such a module's docstring names the clause.
Where no block names the application, the `APPLICATION_ID` comment gives
TS 29.230 table 4.1's name for the id. `rfc6733_8` and TS 29.234's Wa, Wd,
Wm and Wg modules have `APPLICATION_ID = None`: RFC 6733 clause 2.5 says
RAR, STR and ASR carry the application they serve, and TS 29.234 says each
command advertises "the EAP, NASREQ or Diameter Base Protocol
Application-Id, depending on the command".

**Commands printed twice.** A document that prints one command twice in
one interface clause gets one class when the bodies agree and a second
class named with its clause when they differ (TS 29.273's clause 9 AAR,
`AaRequest_9_2_2_5_1`). `type_factory` returns the first.

**Header flags.** A class's `header.is_request` is its header's REQ flag.
Where a header's flag disagrees with the command's name the class says so
in a comment; the corpus corrects the two misprints known.
