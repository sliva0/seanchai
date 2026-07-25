import re

import docx
import pytest

from seanchai.dad import ast
from seanchai.extractor import tgpp_docx
from seanchai.extractor.patches import Patch, Patcher, PatchError


def test_patches_apply_by_substring_exact_match_and_section_scope():
    patcher = Patcher(
        [
            Patch(find="M. V", replace="M, V", exact=True),
            Patch(
                find="Name With Spaces::=",
                replace="Name-With-Spaces ::=",
                section="7.3",
            ),
        ],
        version="18.6.0",
    )

    assert patcher.apply("M. V", "1.2") == "M, V"
    assert patcher.apply("prefix M. V", "1.2") == "prefix M. V"  # exact only
    assert patcher.apply("Name With Spaces::= <x>", "7.3.196") == (
        "Name-With-Spaces ::= <x>"
    )
    assert patcher.apply("Name With Spaces::= <x>", "6.1") == (
        "Name With Spaces::= <x>"  # out of scope
    )

    patcher.finish()  # every patch applied exactly once


def test_unapplied_and_overapplied_patches_fail_with_the_version_range():
    patcher = Patcher(
        [
            Patch(
                find="gone",
                replace="fixed",
                first_version="18.0.0",
                last_version="18.2.0",
            ),
            Patch(find="common", replace="rare", count=1),
        ],
        version="18.6.0",
    )
    patcher.apply("common common")

    with pytest.raises(PatchError) as failure:
        patcher.finish()

    assert str(failure.value) == (
        "input patch 'gone' -> 'fixed' applied 0 times, expected 1;"
        " it was needed on version 18.0.0..18.2.0, currently parsing 18.6.0"
        " — the source may have changed;"
        " input patch 'common' -> 'rare' applied 2 times, expected 1"
    )


def test_unrecorded_application_still_replaces_without_counting():
    patch = Patch(find="a", replace="b")

    assert patch.apply("a a", None, record=False) == "b b"
    assert patch.applied == 0


def test_extract_applies_input_patches_before_parsing(tmp_path, synthetic_spec_docx):
    malformed = tmp_path / "lowercase-flag.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[1].cell(3, 4).text = "v"
    document.save(malformed)

    patches_dir = tmp_path / "patches"
    patches_dir.mkdir()
    (patches_dir / "TS29.999.toml").write_text(
        """
[[patch]]
find = "v"
replace = "V"
exact = true
reason = "lowercase flags cell"
first_version = "1.2.3"
"""
    )

    spec = tgpp_docx.extract(malformed, patches_dir=patches_dir)

    table = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    assert table.rows[1].flag_rules.must == {ast.AvpFlag.VENDOR}


def test_extract_fails_when_a_patch_no_longer_applies(tmp_path, synthetic_spec_docx):
    # A patch that stops matching is a fix silently dropped from the output,
    # so it must not be possible to miss it in a stderr warning.
    patches_dir = tmp_path / "patches"
    patches_dir.mkdir()
    (patches_dir / "TS29.999.toml").write_text(
        """
[[patch]]
find = "no longer present"
replace = "irrelevant"
first_version = "1.0.0"
last_version = "1.1.0"
"""
    )

    with pytest.raises(PatchError, match=re.escape("needed on version 1.0.0..1.1.0")):
        tgpp_docx.extract(synthetic_spec_docx, patches_dir=patches_dir)


def test_extract_without_patch_file_rejects_malformed_input(
    tmp_path, synthetic_spec_docx
):
    malformed = tmp_path / "lowercase-flag.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[1].cell(3, 4).text = "v"
    document.save(malformed)

    with pytest.raises(
        tgpp_docx.ExtractionError,
        match="malformed flags cell 'v'",
    ):
        tgpp_docx.extract(malformed, patches_dir=tmp_path)
