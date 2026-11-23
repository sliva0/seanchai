"""What the extractors report as unclaimed: the resemblance test and the
baseline it is held to (`extractor.unclaimed`)."""

import pytest

from seanchai.extractor.unclaimed import Baseline, Candidate, classify


@pytest.mark.parametrize(
    ("header", "kind"),
    [
        (["Command-Name", "Abbreviation", "Code", "Clause"], "commands"),
        (
            ["Information element name", "Mapping to Diameter AVP", "Cat."],
            "information-elements",
        ),
        (["AVP", "Category", "Description"], "information-elements"),
        (["Value", "Description"], "values"),
        (["Result-Code AVP value", "Condition"], "values"),
        (["AVP Name", "Reference"], "avp-table"),
        (["Attribute Name", "Code", "Defined in"], "avp-table"),
        (["Application identifier", "First applied"], "application-ids"),
        (["Name", "Description"], None),
        (["Type", "Value"], None),
        (["Date", "TSG #", "TSG Doc.", "CR", "Rev", "Subject/Comment"], None),
    ],
)
def test_a_header_resembles_what_it_lists(header, kind):
    assert classify(header, None) == kind


def test_rows_and_a_caption_say_what_a_header_does_not():
    assert classify(["Reason", "Cause"], None, [["ALPHA (0)", "x"]]) == "enumeration"
    numbered = [["1", "a"], ["2", "b"], ["3", "c"]]
    caption = "Table 5.2.3.35/1: IMEI-Check-In-VPLMN-Result value description"
    assert classify(["Cause value (decimal)", "Meaning"], caption, numbered) == (
        "values"
    )
    assert classify(["Cause value (decimal)", "Meaning"], None, numbered) is None


def test_a_baseline_round_trips_and_matches_without_pages(tmp_path):
    found = Candidate(
        "7.2.2", "commands", 'Table 7.2.2/1: "S6a"', ("Command-Name", "Code"), 98
    )
    path = tmp_path / "unclaimed.json"
    path.write_text(Baseline({}).updated({"TS29.272": [found]}).render())
    baseline = Baseline.load(path)
    assert baseline.documents == {"TS29.272": (found,)}

    moved = Candidate("7.2.2", "commands", found.caption, found.header, 99)
    assert baseline.compare("TS29.272", [moved]) == ([], [])
    renumbered = Candidate("7.2.3", "commands", found.caption, found.header)
    assert baseline.compare("TS29.272", [renumbered]) == ([renumbered], [found])
    assert Baseline.load(tmp_path / "absent.toml").documents == {}
