"""The python-diameter generator writes modules in the library's own shape.

The package is generated from the committed corpus once per module and then
imported in a fresh interpreter against the real library, so a rendering
slip shows up as an import error rather than as text that merely looks
right, and the encoding checks run through the library's own codec. The
pinned lists are what README.md beside the script states.
"""

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from seanchai import model
from seanchai.dad import ast

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "integrations" / "python_diameter" / "generate.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("generate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through the module's entry.
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture(scope="module")
def package(tmp_path_factory, generator) -> Path:
    output = tmp_path_factory.mktemp("generated") / "generated"
    assert generator.main(["--all", "-o", str(output)]) == 0
    return output


def _run(package: Path, code: str) -> str:
    """`code` in a fresh interpreter that can import the package as
    `generated`, its stdout returned."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=package.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _read(package: Path, module: str) -> str:
    return (package / f"{module}.py").read_text(encoding="utf-8")


def test_the_output_is_a_function_of_the_corpus(generator, package, tmp_path):
    again = tmp_path / "again"
    assert generator.main(["--all", "-o", str(again)]) == 0
    first = {path.name: path.read_bytes() for path in package.glob("*.py")}
    second = {path.name: path.read_bytes() for path in again.glob("*.py")}
    assert first == second


def test_every_module_imports_as_library_classes_and_registers_nothing(package):
    """Every class is a `DefinedMessage` whose annotations name its
    `AvpGenDef` attributes in order. Importing the package leaves the
    library's dictionaries and command table as they were; once
    `additions.register()` has run, every `AvpGenDef` in every class,
    grouped classes included, has a dictionary entry to encode by."""
    output = _run(
        package,
        """
        import importlib, inspect, pkgutil
        from diameter.message import DefinedMessage
        from diameter.message.avp.avp import get_avp_dictionary_entry
        from diameter.message.avp import dictionary
        from diameter.message.avp.generator import AvpGenDef
        from diameter.message.commands import all_commands

        def snapshot():
            vendors = dictionary.AVP_VENDOR_DICTIONARY.items()
            return (
                dict(dictionary.AVP_DICTIONARY),
                {vendor: dict(entries) for vendor, entries in vendors},
                dict(all_commands),
            )

        before = snapshot()
        import generated
        modules = [
            importlib.import_module(f"generated.{info.name}")
            for info in pkgutil.iter_modules(generated.__path__)
        ]
        assert snapshot() == before
        holders = []
        directions = 0
        for module in modules:
            for name, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ != module.__name__:
                    continue
                holders.append(cls)
                if module.__name__ == "generated.additions":
                    continue
                assert issubclass(cls, DefinedMessage), name
                assert name in module.__all__, name
                if "avp_def" in vars(cls):
                    written = list(vars(cls)["__annotations__"])
                    assert written.pop() == "avp_def"
                    derived = [d.attr_name for d in cls.avp_def]
                    assert written == derived, (module.__name__, name)
                    assert all(isinstance(d, AvpGenDef) for d in cls.avp_def)
                    directions += 1
        from generated import additions
        additions.register()
        unknown = [
            (cls.__name__, d.attr_name)
            for cls in holders
            for d in getattr(cls, "avp_def", ()) or ()
            if get_avp_dictionary_entry(d.avp_code, d.vendor_id) is None
        ]
        assert not unknown, unknown
        print(len(modules), directions)
        """,
    )
    modules, directions = map(int, output.split())
    assert modules == 60
    assert directions > 300


def test_a_cx_uar_round_trips_through_the_librarys_codec(package):
    """A UAR built from the generated class encodes with the library's
    `Avp.new`, decodes through `Message.from_bytes` into the library's own
    merged class, which reads the same values, and into the generated class
    through its `type_factory`, which re-encodes it byte for byte."""
    output = _run(
        package,
        """
        from diameter.message import Message, MessageHeader
        from diameter.message.avp.grouped import VendorSpecificApplicationId
        from diameter.message.constants import APP_3GPP_CX, VENDOR_TGPP
        from generated import ts29_229

        request = ts29_229.UserAuthorizationRequest()
        request.header.application_id = ts29_229.APPLICATION_ID
        request.session_id = "scscf.example;1;2"
        request.auth_session_state = 1
        request.origin_host = b"scscf.example"
        request.origin_realm = b"example"
        request.destination_realm = b"example"
        request.user_name = "user@example"
        request.public_identity = "sip:user@example"
        request.visited_network_identifier = b"visited"
        request.uar_flags = 1
        request.vendor_specific_application_id = VendorSpecificApplicationId(
            vendor_id=VENDOR_TGPP, auth_application_id=APP_3GPP_CX
        )
        sent = request.as_bytes()

        merged = Message.from_bytes(sent)
        print(type(merged).__module__, type(merged).__name__, merged.public_identity)
        plain = Message.from_bytes(sent, plain_msg=True)
        cls = ts29_229.UserAuthorization.type_factory(plain.header)
        again = cls(plain.header, plain.avps)
        print(cls.__module__, cls.__name__, again.header.application_id)
        print(again.public_identity, again.vendor_specific_application_id.vendor_id)
        print(again.as_bytes() == sent, type(again.to_answer()).__name__)
        answer = MessageHeader(command_code=300)
        print(ts29_229.UserAuthorization.type_factory(answer).__name__)
        # TS 29.229 forbids the M flag on UAR-Flags, which the library's
        # dictionary defaults on: `is_mandatory` follows the document.
        (flags,) = [avp for avp in again.avps if avp.name == "UAR-Flags"]
        print(flags.is_mandatory)
        """,
    )
    assert output.splitlines() == [
        "diameter.message.commands.user_authorization UserAuthorizationRequest"
        " sip:user@example",
        "generated.ts29_229 UserAuthorizationRequest 16777216",
        "sip:user@example 10415",
        "True UserAuthorizationAnswer",
        "UserAuthorizationAnswer",
        "False",
    ]


def test_a_library_grouped_class_with_other_m_bits_is_not_reused(package):
    """TS 29.229's table forbids the M flag on Feature-List-ID and
    Feature-List, which the library's `SupportedFeatures` sets, so a Cx UAR
    carries Supported-Features in a class of its own and sends both inner
    AVPs with M clear."""
    output = _run(
        package,
        """
        from diameter.message import Message
        from diameter.message.avp.grouped import SupportedFeatures
        from generated import ts29_229

        (rule,) = [
            d for d in ts29_229.UserAuthorizationRequest.avp_def
            if d.attr_name == "supported_features"
        ]
        print(rule.type_class.__name__, rule.type_class is SupportedFeatures)
        request = ts29_229.UserAuthorizationRequest()
        request.supported_features = [
            rule.type_class(vendor_id=10415, feature_list_id=1, feature_list=3)
        ]
        (features,) = [
            avp
            for avp in Message.from_bytes(request.as_bytes(), plain_msg=True).avps
            if avp.name == "Supported-Features"
        ]
        for inner in features.value:
            print(inner.name, inner.is_mandatory)
        """,
    )
    assert output.splitlines() == [
        "SupportedFeatures_TS29_229 False",
        "Vendor-Id True",
        "Feature-List-ID False",
        "Feature-List False",
    ]


def test_digest_qop_is_the_librarys_ietf_avp(package):
    """TS 29.229's table forbids V on Digest-QoP, so it is RFC 4590's code
    110 in vendor 0, which the library holds as `AVP_DIGEST_QOP`, not an
    addition in vendor 10415. Its table's M in Must outranks RFC 4590's
    stand-in May, so `is_mandatory=True`."""
    additions = _read(package, "additions")
    assert "DIGEST_QOP =" not in additions
    holder = additions.split("\nclass SipDigestAuthenticate_TS29_229:\n")[1]
    assert (
        '        AvpGenDef("digest_qop", AVP_DIGEST_QOP, is_required=True,'
        " is_mandatory=True),\n"
    ) in holder.split("\n\n\n")[0]


def test_a_citing_documents_flag_rules_share_the_origins_class(package):
    """TS 29.272's re-used table marks TS 32.299's User-CSG-Information "Must
    not set" where TS 32.299 sets M, and says nothing of its members: the
    same body, so TS 32.299's class, named by a rule clearing M."""
    additions = _read(package, "additions")
    holder = additions.split("\nclass MmeLocationInformation_TS29_272:\n")[1]
    assert (
        '        AvpGenDef("user_csg_information", AVP_TGPP_USER_CSG_INFORMATION,'
        " VENDOR_TGPP, is_mandatory=False, type_class=UserCsgInformation_TS32_299),\n"
    ) in holder.split("\n\n\n")[0]
    assert (
        '        AvpGenDef("user_csg_information", AVP_TGPP_USER_CSG_INFORMATION,'
        " VENDOR_TGPP, is_mandatory=True, type_class=UserCsgInformation_TS32_299),"
    ) in _read(package, "ts29_212_5")


def test_a_citing_documents_member_rules_are_the_librarys_class(package):
    """TS 32.299 table 7.2.0.1 sets M on Supported-Features and its members,
    which TS 29.229's table forbids on the members: TS 32.299's reading
    encodes them as the library's `SupportedFeatures` does, so it is that
    class, where TS 29.229's is `SupportedFeatures_TS29_229`."""
    additions = _read(package, "additions")
    assert "class SupportedFeatures_TS29_229:\n" in additions
    assert "SupportedFeatures_TS29_229_2" not in additions
    holder = additions.split("\nclass PsInformation")[1]
    assert (
        '        AvpGenDef("supported_features", AVP_TGPP_SUPPORTED_FEATURES,'
        " VENDOR_TGPP, is_mandatory=True, type_class=SupportedFeatures),\n"
    ) in holder.split("\n\n\n")[0]


def test_classes_take_the_librarys_names_and_constants(package):
    gx = _read(package, "ts29_212_5")
    assert "class CreditControl(DefinedMessage):" in gx
    assert '    name: str = "Credit-Control"' in gx
    assert (
        "class CreditControlRequest(CreditControl):\n"
        '    """A Credit-Control-Request message, clause 5.6.2, printed CC-Request."""'
    ) in gx
    assert "APPLICATION_ID = APP_3GPP_GX  # 16777238\n" in gx
    assert "from diameter.message.constants import *\n" in gx
    cx = _read(package, "ts29_229")
    # TS 29.229 names its application nowhere; TS 29.230 table 4.1 does.
    assert (
        "APPLICATION_ID = APP_3GPP_CX  # 16777216, 3GPP Cx/Px, TS29.230 table 4.1\n"
    ) in cx
    assert (
        '        AvpGenDef("public_identity", AVP_TGPP_PUBLIC_IDENTITY, VENDOR_TGPP,'
        " is_required=True, is_mandatory=True),\n"
    ) in cx
    # The library's own type_factory idiom.
    assert (
        "        if header.is_request:\n"
        "            return UserAuthorizationRequest\n"
        "        return UserAuthorizationAnswer\n"
    ) in cx
    # A command code the library has no class for takes the document's name.
    assert "class Ec(DefinedMessage):" in _read(package, "ts29_154_a_6")


def test_what_the_library_lacks_is_an_addition_in_its_shape(package):
    """RTR-Flags is absent from 0.9.0's dictionary, and Result-Code is there
    as Integer32 where RFC 6733 says Unsigned32. Neither is registered on
    import; `register()` adds the new entry and leaves the library's own,
    and only `corrections=True` replaces it."""
    additions = _read(package, "additions")
    assert "AVP_TGPP_RTR_FLAGS = 659  # TS29.229 clause 6.3.69\n" in additions
    assert (
        '    AVP_TGPP_RTR_FLAGS: {"name": "RTR-Flags", "type": AvpUnsigned32,'
        ' "vendor": 10415},  # TS29.229 clause 6.3.69\n'
    ) in additions
    assert (
        '    AVP_RESULT_CODE: {"name": "Result-Code", "type": AvpUnsigned32,'
        ' "mandatory": True},  # RFC6733 clause 7.1; the library holds it as'
        " AvpInteger32\n"
    ) in additions
    cx = _read(package, "ts29_229")
    assert "    AVP_TGPP_RTR_FLAGS,\n" in cx.split("from .additions import (")[1]
    assert (
        "AVP_RESULT_CODE, is_mandatory=True),  # additions.py corrects the"
        " library's AvpInteger32 to AvpUnsigned32\n"
    ) in cx
    output = _run(
        package,
        """
        from diameter.message.avp import Avp
        from diameter.message.constants import AVP_RESULT_CODE
        from generated import additions

        try:
            Avp.new(additions.AVP_TGPP_RTR_FLAGS, 10415)
        except ValueError as error:
            print(error)
        additions.register()
        print(type(Avp.new(additions.AVP_TGPP_RTR_FLAGS, 10415, 1)).__name__)
        print(type(Avp.new(AVP_RESULT_CODE)).__name__)
        additions.register(corrections=True)
        print(type(Avp.new(AVP_RESULT_CODE, value=2**31)).__name__)
        """,
    )
    assert output.splitlines() == [
        "AVP code 659 with vendor 10415 is unknown",
        "AvpUnsigned32",
        "AvpInteger32",
        "AvpUnsigned32",
    ]


def test_a_grouped_class_the_library_cannot_use_is_an_addition(package):
    """In `grouped.py`'s shape, named so it shadows nothing the star imports
    bring in, and saying why the library's class does not serve."""
    additions = _read(package, "additions")
    assert (
        "@dataclasses.dataclass\n"
        "class FailedPcscf:\n"
        '    """A data container that represents the "Failed-PCSCF" (664) grouped'
        " AVP.\n\n"
        "    TS29.229 clause 6.3.74: the library has no class for it.\n"
    ) in additions
    restoration = additions.split("\nclass ScscfRestorationInfo_TS29_229:\n")[1]
    why = " ".join(restoration.split('    """', 2)[1].split())
    assert why.endswith(
        "TS29.229 clause 6.3.46: `ScscfRestorationInfo` lacks"
        " Registration-Time-Out, SIP-Authentication-Scheme;"
        " `ScscfRestorationInfo` holds Restoration-Info in a class this"
        " reading's does not match; `ScscfRestorationInfo` encodes"
        " Restoration-Info with M set, which this reading's flag rules forbid."
    )
    cx = _read(package, "ts29_229")
    assert "    ScscfRestorationInfo_TS29_229,\n" in cx
    assert "type_class=ScscfRestorationInfo_TS29_229)" in cx


def test_holes_stay_in_the_tables_with_their_reason(package):
    """A hole with an identity is an `AvpGenDef` that says so; one without,
    like `* [ AVP ]`, is a comment in its place."""
    additions = _read(package, "additions")
    assert (
        '        AvpGenDef("tgpp_session_stop_indicator",'
        " AVP_TGPP_3GPP_SESSION_STOP_INDICATOR, VENDOR_TGPP),  # hole: TS29.061"
        " 3GPP-Session-Stop-Indicator: no data_type, no flag_rules\n"
    ) in additions
    assert (
        "        # [ Submission-Timestamp ]  # hole: TS32.299 Submission-Timestamp:"
        " resolves nowhere\n"
    ) in additions
    # TS 29.229's Line-Identifier, ETSI's 500 by clause 6.3.42, resolves.
    assert (
        '        AvpGenDef("line_identifier", AVP_ETSI_LINE_IDENTIFIER, VENDOR_ETSI),\n'
    ) in additions


def test_an_application_defined_m_bit_takes_the_dictionary_default(package):
    """RFC 4072 states no M rule for EAP-Payload, which RFC 6733 section 4.1
    leaves to the application, and TS 29.273's STa table leaves blank: no
    `is_mandatory`, as for an M under May."""
    sta = _read(package, "ts29_273_7")
    assert (
        '        AvpGenDef("eap_payload", AVP_EAP_PAYLOAD, is_required=True),\n'
    ) in sta


def _member(presence, minimum, maximum):
    rule = ast.AvpRule(
        name="Session-Id", presence=presence, min_occurs=minimum, max_occurs=maximum
    )
    flag_rules = ast.AvpFlagRules(must=frozenset({ast.AvpFlag.MANDATORY}))
    utf8 = ast.DataType.UTF8_STRING
    target = model.Avp("Session-Id", 0, 263, utf8, flag_rules, "RFC6733", None, None)
    return model.Member(rule=rule, avp=target), target


_SESSION_ID = 'AvpGenDef("session_id", AVP_SESSION_ID, '


@pytest.mark.parametrize(
    ("presence", "spelled", "rendered"),
    [
        (ast.Presence.OPTIONAL, (1, 1), "is_mandatory=True),"),
        (ast.Presence.REQUIRED, (1, None), "is_required=True, is_mandatory=True),"),
        (ast.Presence.OPTIONAL, (0, None), "is_mandatory=True),"),
        # What a list and `is_required` cannot say is a comment.
        (ast.Presence.OPTIONAL, (0, 2), "is_mandatory=True),  # *2 [ Session-Id ]"),
        (ast.Presence.FIXED, (0, 1), "is_mandatory=True),  # *1 < Session-Id >"),
        (
            ast.Presence.REQUIRED,
            (2, None),
            "is_required=True, is_mandatory=True),  # 2* { Session-Id }",
        ),
    ],
)
def test_occurrence_bounds_the_library_cannot_hold_are_comments(
    generator, presence, spelled, rendered
):
    member, target = _member(presence, *spelled)
    definitions = generator.Definitions()
    definition = definitions.add(target)
    resolver = generator.Resolver(generator.Library.load(), definitions)
    (entry,) = generator.gen_defs([(member, definition)], resolver)
    assert entry.text == _SESSION_ID + rendered
    assert entry.repeated == (spelled[1] != 1)


def test_a_member_named_twice_is_one_list(package):
    """TS 29.345's `WiFi-P2P-Assistance-Info` prints
    `[ WLAN-Link-Layer-Id-List ]` twice; the library decodes by identity,
    so both occurrences go to one list attribute."""
    additions = _read(package, "additions")
    holder = additions.split("\nclass WifiP2pAssistanceInfo:\n")[1].split("\n\n\n")[0]
    assert (
        "    wlan_link_layer_id_list: list[WlanLinkLayerIdList] ="
        " dataclasses.field(default_factory=list)\n"
    ) in holder
    assert holder.count('AvpGenDef("wlan_link_layer_id_list"') == 1
    assert (
        "  # printed [ WLAN-Link-Layer-Id-List ] and [ WLAN-Link-Layer-Id-List ],"
        " one list\n"
    ) in holder


def test_members_carry_their_interfaces_marks_as_comments(package):
    """TS 29.212 marks AN-GW-Address for Gx in table 5.3.0.1 and again for
    Gxx in table 5a.4.0.1; each module comments its own clause's marks as
    printed, note references included. `All` access types, which restricts
    nothing, is not repeated unless a note qualifies it."""
    gx, gxx = _read(package, "ts29_212_5"), _read(package, "ts29_212_5a")
    line = (
        '        AvpGenDef("an_gw_address", AVP_TGPP_AN_GW_ADDRESS, VENDOR_TGPP,'
        " is_mandatory=False),  # *2 [ AN-GW-Address ]; Applicability: "
    )
    assert line + "Both, Rel8, EPC-routed\n" in gx
    assert line + "EPC-routed (See NOTE 8)\n" in gxx
    assert "Acc-Type: All;" not in gx and "Acc-Type: All\n" not in gx
    assert "  # Acc-Type: All (NOTE 5); Applicability: PC, Rel8\n" in gx


def test_a_member_its_tables_mark_unused_stays_with_the_mark_as_comment(package):
    """TS 32.299 table 7.1.0.1 marks Error-Message and Failed-AVP "-" under
    ACA, "not used" by clause 7.1.0, while clause 6.2.3's ABNF lists both:
    the class follows the ABNF, which is the wire format, and says what the
    table marks."""
    rf = _read(package, "ts32_299_3")
    aca = rf.split("\nclass AccountingAnswer(")[1]
    assert "    error_message: str\n" in aca
    assert (
        '        AvpGenDef("error_message", AVP_ERROR_MESSAGE, is_mandatory=False),'
        "  # ACA: - (unused, table 7.1.0.1)\n"
    ) in aca
    assert (
        '        AvpGenDef("failed_avp", AVP_FAILED_AVP, is_mandatory=True,'
        " type_class=FailedAvp),  # ACA: - (unused, table 7.1.0.1)\n"
    ) in aca
    assert "  # ACA: OC\n" in aca


def test_only_commands_no_document_gives_an_id_generate_none(package):
    """RFC 6733's RAR, STR and ASR carry the using application's id (clause
    2.5); every other module's document states one, in a header or in an
    application scope."""
    without = sorted(
        path.stem
        for path in package.glob("*.py")
        if "\nAPPLICATION_ID = None\n" in path.read_text(encoding="utf-8")
    )
    assert without == ["rfc6733_8"]
    gx = _read(package, "ts29_212_5")
    assert (
        "The command headers print no application id; clause 5.1 states Gx's."
    ) in gx
    ro = _read(package, "ts32_299_4")
    assert "APPLICATION_ID = APP_DIAMETER_CREDIT_CONTROL_APPLICATION  # 4\n" in ro


def test_each_specification_reports_its_additions(generator, tmp_path, capsys):
    assert generator.main(["TS29.229", "-o", str(tmp_path / "cx")]) == 0
    assert capsys.readouterr().out == "TS29.229: 19 additions\n"
    init = (tmp_path / "cx" / "__init__.py").read_text(encoding="utf-8")
    assert (
        "- `ts29_229`: 3GPP TS 29.229 clause 6, application 16777216; 18 additions\n"
    ) in init


def test_an_added_enumeration_carries_its_values_or_their_source(package):
    additions = _read(package, "additions")
    assert "E_MPS_ACTION_DISABLE_MPS_FOR_DTS = 0\n" in additions
    assert "# Values: TS 23.682[243] (TS32.299 clause 7.2.20eA).\n" in additions


def test_a_directory_it_did_not_write_is_refused(generator, tmp_path):
    (tmp_path / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"notes\.txt"):
        generator.main(["TS29.229", "-o", str(tmp_path)])
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_a_dictionary_adds_wireshark_names_as_comments(generator, tmp_path):
    """The library has no place for another spelling, so Wireshark's
    rides on the rule as a comment; without a dictionary there is none."""
    dictionary = tmp_path / "wireshark"
    dictionary.mkdir()
    (dictionary / "dictionary.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<dictionary>
  <base>
    <avp name="Session-ID" code="263" vendor-id="None">
      <type type-name="UTF8String"/>
    </avp>
    <avp name="Origin-Host" code="264" vendor-id="None">
      <type type-name="DiameterIdentity"/>
    </avp>
  </base>
</dictionary>
""",
        encoding="utf-8",
    )
    plain = tmp_path / "plain"
    named = tmp_path / "named"
    assert generator.main(["TS29.229", "-o", str(plain)]) == 0
    arguments = ["TS29.229", "-o", str(named), "--dictionary", str(dictionary)]
    assert generator.main(arguments) == 0

    cx = (named / "ts29_229.py").read_text(encoding="utf-8")
    assert (
        '        AvpGenDef("session_id", AVP_SESSION_ID, is_required=True,'
        " is_mandatory=True),  # Wireshark: Session-ID\n"
    ) in cx
    assert (
        '        AvpGenDef("origin_host", AVP_ORIGIN_HOST, is_required=True,'
        " is_mandatory=True),\n"
    ) in cx
    assert "Wireshark:" not in (plain / "ts29_229.py").read_text(encoding="utf-8")


@pytest.mark.sources
def test_the_pinned_dictionary_names_import_cleanly(generator, tmp_path):
    output = tmp_path / "aliased"
    dictionary = _ROOT / "specifications" / "wireshark"
    arguments = ["--all", "-o", str(output), "--dictionary", str(dictionary)]
    assert generator.main(arguments) == 0
    additions = (output / "additions.py").read_text(encoding="utf-8")
    assert "type_class=CallBarringInfo),  # Wireshark: Call-Barring-Infor-List\n" in (
        additions
    )
    cx = (output / "ts29_229.py").read_text(encoding="utf-8")
    assert (
        '"user_data", AVP_TGPP_CX_USER_DATA, VENDOR_TGPP, is_mandatory=True),'
        "  # Wireshark: Cx-User-Data\n"
    ) in cx
    found = _run(
        output,
        """
        import importlib, pkgutil
        import aliased
        for info in pkgutil.iter_modules(aliased.__path__):
            importlib.import_module(f"aliased.{info.name}")
        print("ok")
        """,
    )
    assert found == "ok\n"
