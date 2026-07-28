import re
from pathlib import Path

import docx
import pytest

from seanchai.dad import ast
from seanchai.extractor import tgpp_docx
from seanchai.extractor.patches import Patch, Patcher, PatchError

_PATCHES = Path(__file__).parent.parent / "edits" / "patches"


def test_patches_apply_by_substring_exact_match_and_section_scope():
    patcher = Patcher(
        [
            Patch(find="M. V", replace="M, V", exact=True, reason="flags cell"),
            Patch(
                find="Name With Spaces::=",
                replace="Name-With-Spaces ::=",
                section="7.3",
                reason="rule name with spaces",
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
                reason="a fix the source no longer needs",
                first_version="18.0.0",
                last_version="18.2.0",
            ),
            Patch(find="common", replace="rare", count=1, reason="too common"),
        ],
        version="18.6.0",
    )
    patcher.apply("common common")

    with pytest.raises(PatchError) as failure:
        patcher.finish()

    assert str(failure.value).splitlines() == [
        "input patch 'gone' -> 'fixed' applied 0 times, expected 1;"
        " it was needed on version 18.0.0..18.2.0, currently parsing 18.6.0"
        " — the source may have changed",
        "input patch 'common' -> 'rare' applied 2 times, expected 1",
    ]


def test_an_empty_find_cannot_be_declared():
    # `"abc".replace("", "X")` is "XaXbXcX" and `"abc".count("")` is 4, so an
    # empty `find` rewrites every gap between characters *and* satisfies its own
    # accounting — the one way a patch can rot without `finish()` noticing.
    with pytest.raises(PatchError, match="empty `find`"):
        Patch(find="", replace="X", count=4, reason="wrecks the text")


_WRONG = "the source is wrong"


@pytest.mark.parametrize(
    ("declare", "message"),
    [
        (lambda: Patch("old", "new", count=0, reason=_WRONG), "is not applied"),
        (lambda: Patch("old", "new", count=-1, reason=_WRONG), "is not applied"),
        (lambda: Patch("old", "old", reason=_WRONG), "the text with itself"),
        (lambda: Patch("old", "new"), "has no `reason`"),
        (lambda: Patch("old", "new", reason=""), "has no `reason`"),
    ],
    ids=["zero-count", "negative-count", "no-op", "no-reason", "empty-reason"],
)
def test_patch_declarations_that_cannot_mean_anything_are_rejected(declare, message):
    with pytest.raises(PatchError, match=message):
        declare()


def test_a_malformed_patch_file_is_a_patch_error_not_a_traceback(tmp_path):
    # A misspelled key is the user's TOML being wrong, and has to arrive at the
    # CLI's error boundary like every other patch problem.
    path = tmp_path / "TS29.999.toml"
    path.write_text(
        """
[[patch]]
find = "old"
replace = "new"
reason = "the source is wrong"
sektion = "6.1"
"""
    )

    with pytest.raises(PatchError, match="sektion"):
        Patcher.load(path, version="1.2.3")


def test_patch_failures_are_extraction_failures():
    # A batch over a corpus asks one question — did this document fail? — and a
    # rotted patch is the same answer as a malformed table.
    assert issubclass(PatchError, tgpp_docx.ExtractionError)


def test_unrecorded_application_still_replaces_without_counting():
    patch = Patch(find="a", replace="b", reason="a is wrong")

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
reason = "a fix the source no longer needs"
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


@pytest.mark.parametrize(
    ("reference", "version", "units"),
    [
        (
            "TS29.109",
            "18.1.0",
            [("OctedString", "6.3")] * 6,
        ),
        (
            "TS29.128",
            "18.0.0",
            [("OctetSstring", "6.4.1")],
        ),
        (
            "TS29.336",
            "18.2.0",
            [
                ("Maximum Latency", "8.4.1"),
                ("Maximum Response Time", "8.4.1"),
                ("Visited PLMN Id", "8.4.1"),
                ("<AVP header: xxxx 10415>", "8.4.85"),
            ],
        ),
        (
            "TS29.337",
            "18.0.0",
            [("Old-Rference-Number", "6.2.3")],
        ),
        (
            "TS29.338",
            "18.2.0",
            # The header-line units carry only the substring the patch targets;
            # the full rule lines around it belong to the source document, and
            # transcribing them here would pin text the patch never asserts.
            [
                ("SGSN-Absent-User-Diagnostic SM", "5.3.3.1"),
                ("10415>>", "5.3.3.15"),
                ("10415>>", "5.3.3.27"),
                ("10415>>", "5.3.3.28"),
            ],
        ),
        (
            "TS29.345",
            "18.0.0",
            [
                ("M. V", "6.3.1"),
                ("M. V", "6.3.1"),
                ("Group", "6.3.1"),
            ],
        ),
    ],
)
def test_real_source_patches_are_fully_accounted(reference, version, units):
    """Pin every application count even when the ignored real docx is absent."""
    patcher = Patcher.load(_PATCHES / f"{reference}.toml", version)

    outputs = [patcher.apply(text, section) for text, section in units]

    patcher.finish()
    assert all(output != text for output, (text, _) in zip(outputs, units, strict=True))
