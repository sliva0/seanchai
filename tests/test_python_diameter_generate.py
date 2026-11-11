"""The python-diameter generator writes modules in the library's own shape.

The package is generated from the committed corpus and imported in a fresh
interpreter against the real library, so a rendering slip is an import error,
and what the classes hold is read back from them and through the library's own
codec. What is checked is what README.md beside the script states.
"""

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from conftest import _CORPUS_DIR

from seanchai import corpus, model

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
    """`code` in a fresh interpreter that can import the package by its
    directory's name, its stdout returned."""
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
    assert modules == 92
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
        "SupportedFeatures_3GPP2_X_S0013_006 False",
        "Vendor-Id True",
        "Feature-List-ID False",
        "Feature-List False",
    ]


def test_register_adds_what_the_library_lacks_and_corrects_only_when_asked(
    package,
):
    """RTR-Flags is absent from 0.9.0's dictionary, and Result-Code is there as
    Integer32 where RFC 6733 says Unsigned32."""
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


_READ_BACK = """
import importlib, json
found = {{}}
for path in {paths!r}:
    module, holder, attribute = path.split(".")
    cls = getattr(importlib.import_module({package!r} + "." + module), holder)
    found[path] = [
        [d.avp_code, d.vendor_id, d.is_required, d.is_mandatory,
         getattr(d.type_class, "__name__", None)]
        for d in cls.avp_def
        if d.attr_name == attribute
    ]
print(json.dumps(found))
"""


def _members(package: Path, *paths: str) -> dict[str, list]:
    """Each `module.Class.attribute`'s `AvpGenDef`s, read from the imported
    class as [code, vendor, is_required, is_mandatory, type_class name]."""
    code = _READ_BACK.format(package=package.name, paths=list(paths))
    return json.loads(_run(package, code))


# (member, its AvpGenDef as [code, vendor, is_required, is_mandatory, class]).
_MEMBERS = {
    "ts29_229.UserAuthorizationRequest.public_identity": [601, 10415, True, True, None],
    # TS 29.229's table forbids V on Digest-QoP: RFC 4590's vendor-0 AVP, its M
    # in Must outranking RFC 4590's May.
    "additions.SipDigestAuthenticate_TS29_229.digest_qop": [110, 0, True, True, None],
    # TS 29.272's re-used table clears M on TS 32.299's User-CSG-Information and
    # says nothing of its members: TS 32.299's class, under a rule clearing M.
    "additions.MmeLocationInformation_TS29_272.user_csg_information": [
        2319,
        10415,
        False,
        False,
        "UserCsgInformation_TS32_299",
    ],
    "ts29_212_5.CreditControlRequest.user_csg_information": [
        2319,
        10415,
        False,
        True,
        "UserCsgInformation_TS32_299",
    ],
    # TS 32.299 sets M on Supported-Features and its members as the library's
    # class does, so it is that class.
    "additions.PsInformation_TS32_299.supported_features": [
        628,
        10415,
        False,
        True,
        "SupportedFeatures",
    ],
    # A hole with an identity stays a member.
    "additions.PsInformation_TS32_299.tgpp_session_stop_indicator": [
        11,
        10415,
        False,
        None,
        None,
    ],
    # TS 29.229's Line-Identifier is ETSI's 500, by clause 6.3.42.
    "additions.SipAuthDataItem_TS29_229.line_identifier": [
        500,
        13019,
        False,
        None,
        None,
    ],
    # RFC 4072 leaves EAP-Payload's M bit to the application: no `is_mandatory`,
    # the dictionary's default.
    "ts29_273_7.DiameterEapRequest.eap_payload": [462, 0, True, None, None],
    # TS 29.345 prints WLAN-Link-Layer-Id-List twice: one list member.
    "additions.WifiP2pAssistanceInfo.wlan_link_layer_id_list": [
        3822,
        10415,
        False,
        True,
        "WlanLinkLayerIdList",
    ],
    # A grouped reading the library's class does not match is an addition.
    "ts29_229.ServerAssignmentAnswer.scscf_restoration_info": [
        639,
        10415,
        False,
        False,
        "ScscfRestorationInfo_TS29_229",
    ],
    # TS 32.299 marks Error-Message "-" under ACA; the ABNF, the wire format,
    # lists it.
    "ts32_299_3.AccountingAnswer.error_message": [281, 0, False, False, None],
}


def test_members_follow_their_documents_tables(package):
    found = _members(package, *_MEMBERS)

    assert found == {path: [expected] for path, expected in _MEMBERS.items()}


def test_each_module_states_its_documents_application_id(package):
    """RFC 6733's RAR, STR and ASR carry the using application's id, and TS
    29.234's Wa, Wd, Wm and Wg modules that of the application they serve;
    every other document states one. TS 29.229's commands are Cx's by TS
    29.230 table 4.1."""
    output = _run(
        package,
        """
        import importlib, pkgutil
        import generated
        ids = {
            info.name: importlib.import_module(f"generated.{info.name}").APPLICATION_ID
            for info in pkgutil.iter_modules(generated.__path__)
            if info.name != "additions"
        }
        print(sorted(name for name, value in ids.items() if value is None))
        print(ids["ts29_229"], ids["ts29_212_5"], ids["ts32_299_4"])
        from generated import additions, ts29_154_a_6, ts29_212_5
        print(ts29_212_5.CreditControl.name, ts29_154_a_6.Ec.__name__)
        print(additions.E_MPS_ACTION_DISABLE_MPS_FOR_DTS)
        """,
    )

    assert output.splitlines() == [
        "['rfc6733_8', 'ts29_234_4', 'ts29_234_5', 'ts29_234_8', 'ts29_234_9']",
        "16777216 16777238 4",
        # The library's name where it has one, the document's otherwise.
        "Credit-Control Ec",
        # An added enumerated AVP gets its values as constants.
        "0",
    ]
    assert "TS29.230 table 4.1" in _read(package, "ts29_229")


def test_the_output_is_a_function_of_the_corpus(package, tmp_path):
    """Generated again in another interpreter under another hash seed."""
    again = tmp_path / "generated"
    subprocess.run(
        [sys.executable, str(_SCRIPT), "--all", "-o", str(again)],
        env={**os.environ, "PYTHONHASHSEED": "2"},
        check=True,
        capture_output=True,
    )

    assert {path.name: path.read_bytes() for path in again.glob("*.py")} == {
        path.name: path.read_bytes() for path in package.glob("*.py")
    }


# --- undefined names -----------------------------------------------------------

_UNDEFINED_SPECS = ["RFC4004", "TS29.345", "TS29.154"]

_SIDECAR = """\
; Specification: ACME ProSe dictionary
; Vendor-ID: 10415


; Type: AVP Table
; Section: 1
; Columns: Name              Code  Type         Must  May  S.not  M.not
           ProSe-Query-Code  3899  OctetString  V     -    -      M
"""

_PROSE = "additions.DiscoveryAuthRequest.prose_query_code"
_GROUP = "ts29_154_a_6.EcRequest.external_group_identifier"


@pytest.mark.parametrize(
    ("policy", "prose", "recorded"),
    [
        ("hole", [], "--undefined hole: holes: RFC4004 MIP-HA-to-MN-SPI,"),
        ("drop", [], "--undefined drop: dropped: RFC4004 MIP-HA-to-MN-SPI,"),
        ("placeholder", [], "--undefined placeholder:"),
        (
            "supply",
            [[3899, 10415, False, False, None]],
            "--undefined supply: supplied: TS29.345 ProSe-Query-Code; holes:",
        ),
    ],
)
def test_each_undefined_policy_does_what_it_says_and_records_it(
    generator, tmp_path, policy, prose, recorded
):
    sidecar = tmp_path / "acme.dad"
    sidecar.write_text(_SIDECAR, encoding="utf-8")
    options = ["--undefined", policy]
    if policy == "supply":
        options += ["--supply", str(sidecar)]
    output = tmp_path / "generated"
    assert generator.main([*_UNDEFINED_SPECS, "-o", str(output), *options]) == 0

    found = _members(output, _PROSE, _GROUP)

    assert found == {_PROSE: prose, _GROUP: []}
    init = " ".join(_read(output, "__init__").split())
    assert f"Undefined names, {recorded}" in init
    additions = _read(output, "additions")
    if policy in {"hole", "placeholder"}:
        assert f"# [ ProSe-Query-Code ]  # {policy}" in additions
    if policy == "drop":
        assert "# [ ProSe-Query-Code ]" not in additions
        assert "Dropped, undefined in the corpus: [ ProSe-Query-Code ]" in " ".join(
            additions.split()
        )


def test_an_alias_writes_the_named_avps_constant(generator, tmp_path):
    books = corpus.Corpus.load([_CORPUS_DIR])
    alias = model.Alias("TS29.336", "External-Identifier", "TS 29.154 CR draft")
    built = model.Model.build(
        books,
        undefined=model.UndefinedPolicy.SUPPLY,
        supply={"External-Group-Identifier": alias},
    )

    generated = generator.generate(built, books, ["TS29.154"], generator.Library.load())
    generator.write(tmp_path / "generated", generated.files)

    assert _members(
        tmp_path / "generated", "ts29_154_a_6.EcRequest.external_identifier"
    ) == {
        "ts29_154_a_6.EcRequest.external_identifier": [[3111, 10415, True, True, None]]
    }
    assert "- TS 29.154 CR draft\n" in generated.files["__init__.py"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--supply", "acme.dad"], "--supply goes with --undefined supply"),
        (["--undefined", "supply"], "--supply goes with --undefined supply"),
        # A sidecar claiming ProSe-Restricted-Code's 3846, which the corpus
        # defines.
        (
            ["--undefined", "supply", "--supply", "clash.dad"],
            "ProSe-Restricted-Code; an Alias reads one name",
        ),
    ],
)
def test_a_usage_error_exits_2(
    generator, tmp_path, capsys, monkeypatch, arguments, message
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "clash.dad").write_text(_SIDECAR.replace("3899", "3846"), "utf-8")

    try:
        code = generator.main(["TS29.345", "-o", str(tmp_path / "out"), *arguments])
    except SystemExit as raised:
        code = raised.code

    assert code == 2
    assert message in capsys.readouterr().err


def test_a_directory_it_did_not_write_is_refused(generator, tmp_path):
    (tmp_path / "notes.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(SystemExit, match=r"notes\.txt"):
        generator.main(["TS29.229", "-o", str(tmp_path)])

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "mine"


@pytest.mark.sources
def test_the_pinned_dictionary_names_import_cleanly(generator, tmp_path):
    output = tmp_path / "aliased"
    dictionary = _ROOT / "specifications" / "wireshark"
    arguments = ["--all", "-o", str(output), "--wireshark", str(dictionary)]
    assert generator.main(arguments) == 0
    additions = _read(output, "additions")
    assert "type_class=CallBarringInfo),  # Wireshark: Call-Barring-Infor-List\n" in (
        additions
    )
    cx = _read(output, "ts29_229")
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
        aliased.additions.register()
        print("ok")
        """,
    )
    assert found == "ok\n"
