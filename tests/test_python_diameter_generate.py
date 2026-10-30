"""The python-diameter generator writes a package the library can run.

The package is generated from the committed corpus once per module and then
imported in a fresh interpreter against the real library, so a rendering
slip shows up as an import error rather than as text that merely looks
right. The pinned lists are what README.md beside the script states.
"""

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from diameter.message.avp import AvpUnsigned32

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


def test_the_output_is_a_function_of_the_corpus(generator, package, tmp_path):
    again = tmp_path / "again"
    assert generator.main(["--all", "-o", str(again)]) == 0
    first = {path.name: path.read_bytes() for path in package.glob("*.py")}
    second = {path.name: path.read_bytes() for path in again.glob("*.py")}
    assert first == second


def test_every_class_imports_and_names_what_its_rules_derive(package):
    """Each annotation the generator writes is an attribute the runtime
    derives from the same rule, in the same order; building `avp_def` also
    builds every grouped value class a command reaches."""
    output = _run(
        package,
        """
        import importlib, pkgutil
        import generated
        count = 0
        for info in pkgutil.iter_modules(generated.__path__):
            module = importlib.import_module(f"generated.{info.name}")
            for name in getattr(module, "__all__", ()):
                cls = getattr(module, name)
                if getattr(cls, "is_request", None) is None:
                    continue
                written = list(cls.__annotations__)
                derived = [d.attr_name for d in cls.avp_def]
                assert written == derived, (info.name, name, written, derived)
                count += 1
        print(count)
        """,
    )
    assert int(output) > 300


def test_a_command_round_trips_through_the_library(package):
    """A Cx UAR encoded from the generated class decodes, through the
    library's own command table, back into the generated class."""
    output = _run(
        package,
        """
        from diameter.message import Message
        from generated import avps, ts29_229

        request = ts29_229.UserAuthorizationRequest()
        request.session_id = "scscf.example;1;2"
        request.auth_session_state = 1
        request.origin_host = b"scscf.example"
        request.origin_realm = b"example"
        request.destination_realm = b"example"
        request.user_name = "user@example"
        request.public_identity = "sip:user@example"
        request.visited_network_identifier = b"visited"
        request.vendor_specific_application_id = (
            avps.VENDOR_SPECIFIC_APPLICATION_ID.grouped_class(
                vendor_id=10415, auth_application_id=16777216
            )
        )
        decoded = Message.from_bytes(request.as_bytes())
        header = decoded.header
        cls = ts29_229.UserAuthorization.type_factory(header)
        again = cls(header, decoded.avps)
        print(header.application_id, type(again).__name__)
        print(again.public_identity, again.vendor_specific_application_id.vendor_id)
        print(type(again.to_answer()).__name__)
        """,
    )
    assert output.split("\n")[:3] == [
        "16777216 UserAuthorizationRequest",
        "sip:user@example 10415",
        "UserAuthorizationAnswer",
    ]


def test_holes_stay_in_the_rule_tables(package):
    """A hole with an identity is an `AvpDef` that says so, one without is
    an `AvpHole`, and every rule naming either carries the reason."""
    avps = (package / "avps.py").read_text(encoding="utf-8")
    assert 'LINE_IDENTIFIER = AvpHole(\n    "Line-Identifier",' in avps
    assert (
        "Rule(LINE_IDENTIFIER, max=None),"
        "  # hole: TS29.229 Line-Identifier: resolves nowhere"
    ) in avps
    sta = (package / "ts29_273_7.py").read_text(encoding="utf-8")
    assert (
        "Rule(avps.EAP_PAYLOAD, REQUIRED),  # hole: RFC4072 EAP-Payload: no flag_rules"
    ) in sta


def test_readings_that_differ_stay_apart_and_agreeing_ones_merge(package):
    avps = (package / "avps.py").read_text(encoding="utf-8")
    # TS 29.273's SIP-Auth-Data-Item body differs from TS 29.229's.
    assert "SIP_AUTH_DATA_ITEM__TS29_229 = AvpDef(" in avps
    assert "SIP_AUTH_DATA_ITEM__TS29_273 = AvpDef(" in avps
    # TS 29.272 re-prints TS 29.212's Allocation-Retention-Priority.
    assert 'defined_in=("TS29.212", "TS29.272"),\n)' in avps
    # RFC 8506 drops the P flag RFC 4006 allows on CC-Time.
    assert "CC_TIME__RFC4006 = AvpDef(" in avps
    assert "CC_TIME__RFC8506 = AvpDef(" in avps
    # TS 29.329 re-prints TS 29.229's Public-Identity.
    assert (
        'PUBLIC_IDENTITY = AvpDef(\n    "Public-Identity", 601, 10415, AvpUtf8String,'
        ' FlagRules(must="MV"),\n    defined_in=("TS29.229", "TS29.329"),\n)'
    ) in avps


def test_an_externally_defined_enumeration_names_its_source(package):
    avps = (package / "avps.py").read_text(encoding="utf-8")
    assert (
        "# Values: TS 32.422 [23] for Trace Depth (TS29.272 clause 7.3.67).\n"
        "TRACE_DEPTH = AvpDef(\n"
    ) in avps
    assert "# Values: OMNA WSP Content Type Numbers [210] (TS32.299 clause" in avps


def test_only_commands_no_document_gives_an_id_generate_none(package):
    """RFC 6733's RAR, STR and ASR carry the using application's id (clause
    2.5); every other module's document states one, in a header or in an
    application scope."""
    without = sorted(
        path.stem
        for path in package.glob("*.py")
        if "APPLICATION_ID: int | None = None\n" in path.read_text(encoding="utf-8")
    )
    assert without == ["rfc6733_8"]
    gx = (package / "ts29_212_5.py").read_text(encoding="utf-8")
    assert "APPLICATION_ID: int | None = 16777238\n" in gx
    assert (
        "The command headers print no application id; clause 5.1 states Gx's."
    ) in gx
    ro = (package / "ts32_299_4.py").read_text(encoding="utf-8")
    assert "APPLICATION_ID: int | None = 4\n" in ro


def test_a_directory_it_did_not_write_is_refused(generator, tmp_path):
    (tmp_path / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"notes\.txt"):
        generator.main(["TS29.229", "-o", str(tmp_path)])
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_a_dictionary_adds_wireshark_aliases(generator, tmp_path):
    """Where Wireshark spells an AVP differently, the definition carries
    its spelling and `BY_WIRESHARK_NAME` finds it; without a dictionary the
    map is empty and nothing else changes."""
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

    avps = (named / "avps.py").read_text(encoding="utf-8")
    session_id = avps.split("\nSESSION_ID = ")[1].split("\n)\n")[0]
    assert 'wireshark_name="Session-ID"' in session_id
    origin_host = avps.split("\nORIGIN_HOST = ")[1].split("\n)\n")[0]
    assert "wireshark_name" not in origin_host
    assert '    "Session-ID": (SESSION_ID,),' in avps
    plain_avps = (plain / "avps.py").read_text(encoding="utf-8")
    assert "BY_WIRESHARK_NAME: dict[str, tuple[AvpDef, ...]] = {\n}" in plain_avps
    output = _run(
        named,
        """
        from named import avps
        print(avps.BY_WIRESHARK_NAME["Session-ID"][0].name)
        """,
    )
    assert output == "Session-Id\n"


@pytest.mark.sources
def test_the_pinned_dictionary_aliases_import_cleanly(generator, tmp_path):
    output = tmp_path / "aliased"
    dictionary = _ROOT / "specifications" / "wireshark"
    arguments = ["--all", "-o", str(output), "--dictionary", str(dictionary)]
    assert generator.main(arguments) == 0
    found = _run(
        output,
        """
        from aliased import avps
        (info,) = avps.BY_WIRESHARK_NAME["Call-Barring-Infor-List"]
        print(info.name, info.wireshark_name)
        print(avps.BY_WIRESHARK_NAME["Cx-User-Data"][0].name)
        """,
    )
    assert found == "Call-Barring-Info Call-Barring-Infor-List\nUser-Data\n"


def test_avps_are_built_and_read_as_their_generated_types(package):
    """TS 29.214's `Codec-Data` is OctetString and RFC 6733's
    `Authorization-Lifetime` Unsigned32, whatever the library's dictionary
    holds under their codes (UTF8String and Integer32 in 0.9.0), so values
    only the generated types can hold survive a round trip."""
    output = _run(
        package,
        """
        from diameter.message import Message
        from diameter.message.avp import Avp
        from generated import avps, rfc4005

        codec = avps.CODEC_DATA.build(b"\\xff")
        back = avps.CODEC_DATA.read(Avp.from_bytes(codec.as_bytes()))
        print(type(codec).__name__, back)

        request = rfc4005.AaRequest()
        request.session_id = "nas.example;1"
        request.auth_application_id = 1
        request.origin_host = b"nas.example"
        request.origin_realm = b"example"
        request.destination_realm = b"example"
        request.auth_request_type = 1
        request.authorization_lifetime = 2147483648
        received = Message.from_bytes(request.as_bytes(), plain_msg=True)
        again = rfc4005.AaRequest(received.header, received.avps)
        print(again.authorization_lifetime)
        """,
    )
    assert output == "AvpOctetString b'\\xff'\n2147483648\n"


def test_a_member_named_twice_keeps_both_occurrences(package):
    """TS 29.345's `WiFi-P2P-Assistance-Info` prints
    `[ WLAN-Link-Layer-Id-List ]` twice: each occurrence decodes into its
    own attribute, in order, and re-encodes to the same bytes."""
    output = _run(
        package,
        """
        from diameter.message.avp import Avp
        from generated import avps

        info = avps.WIFI_P2P_ASSISTANCE_INFO
        listed = avps.WLAN_LINK_LAYER_ID_LIST.grouped_class
        one = avps.WLAN_LINK_LAYER_ID.grouped_class
        value = info.grouped_class(
            wlan_link_layer_id_list=listed(wlan_link_layer_id=[one(mac_address="first")]),
            wlan_link_layer_id_list_2=listed(wlan_link_layer_id=[one(mac_address="second")]),
        )
        sent = info.build(value).as_bytes()
        back = info.read(Avp.from_bytes(sent))
        print(back.wlan_link_layer_id_list.wlan_link_layer_id[0].mac_address)
        print(back.wlan_link_layer_id_list_2.wlan_link_layer_id[0].mac_address)
        print(info.build(back).as_bytes() == sent, back.additional_avps)
        """,
    )
    assert output == "first\nsecond\nTrue []\n"


def test_a_cer_without_host_ip_address_is_refused(package):
    """RFC 6733's CER requires `1* { Host-IP-Address }`."""
    output = _run(
        package,
        """
        from generated import rfc6733_5
        from generated._base import OccurrenceError

        request = rfc6733_5.CapabilitiesExchangeRequest()
        request.origin_host = b"peer.example"
        request.origin_realm = b"example"
        request.vendor_id = 0
        request.product_name = "seanchai"
        request.host_ip_address = []
        try:
            request.as_bytes()
        except OccurrenceError as error:
            print(error)
        """,
    )
    assert output == (
        "CapabilitiesExchangeRequest: Host-IP-Address (host_ip_address) is set"
        " 0 times, outside its 1* bounds\n"
    )


@pytest.fixture(scope="module")
def base():
    """The runtime support module, imported against the real library."""
    path = _ROOT / "integrations" / "python_diameter" / "_base.py"
    spec = importlib.util.spec_from_file_location("python_diameter_base", path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.parametrize(
    ("presence", "spelled", "rendered", "accepted", "refused"),
    [
        # `0*1< X >`: fixed in position, but may be absent.
        (ast.Presence.FIXED, (0, 1), "Rule(X, FIXED, min=0)", [None, 7], [[7, 8]]),
        # `1*2 [ X ]`: RFC 6733 §3.2 makes an optional rule's minimum 0.
        (ast.Presence.OPTIONAL, (1, 2), "Rule(X, max=2)", [[], [7, 8]], [[7, 8, 9]]),
        # `1* { X }`: at least one, an empty list included.
        (ast.Presence.REQUIRED, (1, None), "Rule(X, REQUIRED, max=None)", [[7]], [[]]),
        (ast.Presence.REQUIRED, (0, None), "Rule(X, REQUIRED, max=None)", [[7]], [[]]),
        # `* [ X ]`: any number, none included.
        (ast.Presence.OPTIONAL, (0, None), "Rule(X, max=None)", [[], [7, 8, 9]], []),
    ],
)
def test_occurrence_bounds_are_rendered_and_enforced(
    generator, base, presence, spelled, rendered, accepted, refused
):
    minimum, maximum = spelled
    rule = ast.AvpRule(
        name="X", presence=presence, min_occurs=minimum, max_occurs=maximum
    )
    flag_rules = ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR}))
    target = model.Avp(
        "X", 10415, 1, ast.DataType.UNSIGNED32, flag_rules, "TS29.900", None, None
    )
    definition = generator.Definition(target, [], identifier="X")
    member = model.Member(rule=rule, avp=target)
    (item,) = generator.rule_items([(member, definition)], "")
    assert item.text == rendered

    x = base.AvpDef("X", 1, 10415, AvpUnsigned32, base.FlagRules(must="V"))
    evaluated = eval(rendered, {**vars(base), "X": x})
    assert evaluated.is_required == (member.min_occurs > 0)
    assert (evaluated.min_occurs, evaluated.max) == (
        member.min_occurs,
        member.max_occurs,
    )

    for value in accepted:
        holder = SimpleNamespace(x=value)
        sent = base.encode(holder, (evaluated,), "Holder")
        expected = (
            [] if value is None else value if isinstance(value, list) else [value]
        )
        assert [avp.value for avp in sent] == expected
    for value in refused:
        holder = SimpleNamespace(x=value)
        with pytest.raises(base.OccurrenceError, match=r"Holder: X \(x\)"):
            base.encode(holder, (evaluated,), "Holder")
