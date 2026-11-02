"""Definition citations must survive extraction, resolution and export."""

import pytest

from seanchai.corpus import Corpus
from seanchai.dad import ast
from seanchai.extractor import tgpp_docx
from seanchai.extractor.errors import ExtractionError
from seanchai.extractor.sources import Quirk, Quirks
from seanchai.model import Enumerated, Grouped, Model


@pytest.fixture(scope="module")
def built():
    return Model.build(Corpus.installed())


@pytest.mark.parametrize(
    ("reference", "version", "name", "origin", "section"),
    [
        ("TS29.329", None, "Server-Name", "TS29.229", "6.3.3"),
        ("TS29.329", None, "Supported-Features", "TS29.229", "6.3.29"),
        ("TS29.329", None, "Feature-List-ID", "TS29.229", "6.3.30"),
        ("TS29.329", None, "Feature-List", "TS29.229", "6.3.31"),
        ("TS29.329", None, "Supported-Applications", "TS29.229", "6.3.32"),
        ("TS29.329", None, "Public-Identity", "TS29.229", "6.3.2"),
        ("TS29.329", None, "Wildcarded-Public-Identity", "TS29.229", "6.3.35"),
        ("TS29.329", None, "Wildcarded-IMPU", "TS29.229", "6.3.43"),
        ("TS29.329", None, "Session-Priority", "TS29.229", "6.3.56"),
        ("TS29.273", None, "QoS-Capability", "RFC5777", "6"),
        ("TS29.273", None, "QoS-Resources", "RFC5777", "3.1"),
        ("TS29.273", None, "MIP-MN-HA-SPI", "RFC5778", "6.4"),
        ("TS29.273", None, "MIP-Session-Key", "RFC4004", "9.7"),
        ("TS29.140", None, "MSISDN", "TS29.329", "6.3.2"),
        ("TS29.140", None, "3GPP-IMSI", "TS29.061", "16.4.7"),
        ("TS32.299", "11.20.0", "Rating-Group", "RFC4006", "8.29"),
        ("TS32.299", "11.20.0", "Service-Context-Id", "RFC4006", "8.42"),
        ("TS32.299", "11.20.0", "Service-Identifier", "RFC4006", "8.28"),
        ("RFC8583", None, "SourceID", "RFC8581", "7.3"),
    ],
)
def test_prose_citations_resolve_to_the_defining_clause(
    built, reference, version, name, origin, section
):
    if version is not None:
        built = Model.build(
            Corpus(
                e
                for e in Corpus.installed()
                if e.reference != reference or e.spec.version == version
            ),
            strict=False,
        )
    avp = built.resolve(reference, name)
    assert avp is not None
    assert (avp.defined_in, avp.section) == (origin, section)
    # Resolving through the origin must retain this interface's flag rules.
    for row in built.table_rows(reference, name):
        for flag in ("must", "may", "should_not", "must_not"):
            assert getattr(row.flag_rules, flag) <= getattr(avp.flag_rules, flag)


def test_citations_recover_the_body_and_values(built):
    priority = built.resolve("TS29.329", "Session-Priority")
    assert isinstance(priority, Enumerated)
    assert priority.values == tuple(
        ast.EnumValue(name=f"PRIORITY-{i}", value=i) for i in range(5)
    )
    resources = built.resolve("TS29.273", "QoS-Resources")
    assert isinstance(resources, Grouped)
    assert resources.members


def test_an_erroneous_citation_does_not_change_the_wire_identity(built):
    mc = built.resolve("TS29.283", "Sequence-Number")
    sh = built.resolve("TS29.329", "Sequence-Number")
    assert mc is not None and sh is not None
    assert (mc.identity, mc.defined_in) == ((10415, 4512), "TS29.283")
    assert (sh.identity, sh.defined_in) == ((10415, 716), "TS29.329")


def _read_origins(*texts):
    table = ast.AvpTable(
        table="6.3.1",
        source=ast.SourceRef(section="6.3"),
        columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.SECTION),
        rows=(ast.AvpTableRow(name="Thing", code=1, section="6.3.1"),),
    )
    collected = tgpp_docx._Collected(
        own_reference="TS29.999",
        avp_tables=[tgpp_docx._CollectedAvpTable(table, "6.3", [])],
    )
    section = tgpp_docx._Section(
        number="6.3.1",
        title="Thing AVP",
        paragraphs=[tgpp_docx._Para(text=t, style="", lines=[]) for t in texts],
    )
    tgpp_docx._prose_avp_origins(
        collected,
        [section],
        Quirks([Quirk(name="prose-avp-origins", reason="rejection")], None),
    )
    return collected.avp_tables[0].note_reused


@pytest.mark.parametrize(
    "text",
    [
        "The coding is specified in TS 29.229 [6].",
        "See TS 24.008 [31] clause 10.5.1.13 for the coding of MCC and MNC.",
        "The values are those defined in TS 32.422 [23].",
        "The Other AVP is defined in TS 29.229 [6].",
        "The Thing AVP uses an encoding. See TS 24.008 [31] clause 10.5.5.32.",
    ],
)
def test_encoding_values_and_other_avps_do_not_set_the_origin(text):
    assert _read_origins(text) == []


def test_conflicting_prose_origins_fail_instead_of_picking_one():
    with pytest.raises(ExtractionError, match="conflicting prose origins"):
        _read_origins(
            "The Thing AVP is defined in TS 29.229 [6].",
            "This AVP is defined in TS 29.329 [7].",
        )
