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
