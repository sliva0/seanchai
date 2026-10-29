"""Ranges outside the reviewed versions do not occur in the committed corpus."""

import pytest

from seanchai.versions import VersionRange


@pytest.mark.parametrize(
    "bounds", [("1.x", None), ("", None), ("2.0", "1.0"), (None, "-1")]
)
def test_invalid_ranges_are_rejected(bounds):
    with pytest.raises(ValueError):
        VersionRange(*bounds)


def test_numeric_inclusive_and_open_bounds():
    bounds = VersionRange("18.2", "18.10.0")
    assert bounds.covers("18.2.0")
    assert bounds.covers("18.10")
    assert not bounds.covers("18.11")
    assert not bounds.covers("18.1.9")
    assert VersionRange(last="2").covers("1.99")
    assert VersionRange(first="2").covers("20")
    assert VersionRange().covers("999")
    assert bounds.warning(None, "RFC patch") is None


@pytest.mark.parametrize(
    ("declared", "version", "expected"),
    [
        ("18.6.0", "18.7.0", "18.6.0..18.7.0"),
        ("18.6.0", "18.5.0", "18.5.0..18.6.0"),
        ("18.0.0..18.2.0", "18.1.0", "18.0.0..18.2.0"),
        ("*..18.2.0", "18.4.0", "*..18.4.0"),
        ("18.2.0..*", "18.0.0", "18.0.0..*"),
    ],
)
def test_expanding_moves_only_the_bound_the_version_is_past(
    declared, version, expected
):
    assert str(VersionRange.parse(declared).expanded(version)) == expected
