import pytest

from seanchai.dad import formatter, parser


def test_canonical_file_round_trips_exactly(canonical_dad_text):
    spec = parser.parse(canonical_dad_text)
    assert formatter.format(spec) == canonical_dad_text
    assert parser.parse(formatter.format(spec)) == spec


def test_malformed_directive_is_rejected(canonical_dad_text):
    broken = canonical_dad_text.replace(
        "; Name: Repository-Data-ID", "; AVP Name: Repository-Data-ID"
    )
    with pytest.raises(parser.DadParseError, match="missing directive 'Name'"):
        parser.parse(broken)
