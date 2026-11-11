import re

import pytest

from seanchai._versions import VersionRange
from seanchai.extractor import rfc_text, tgpp_docx
from seanchai.extractor.sources import Patch, Patcher, PatchError, load


def test_unapplied_and_overapplied_patches_fail_with_the_version_range():
    patcher = Patcher(
        [
            Patch(
                find="gone",
                replace="fixed",
                reason="a fix the source no longer needs",
                versions=VersionRange("18.0.0", "18.2.0"),
            ),
            Patch(find="common", replace="rare", count=1, reason="too common"),
        ],
        version="18.6.0",
    )
    patcher.apply("common common")

    with pytest.raises(PatchError) as failure:
        patcher.finish()

    unapplied, overapplied = str(failure.value).splitlines()
    assert "'gone'" in unapplied and "applied 0 times" in unapplied
    assert "18.0.0..18.2.0" in unapplied and "18.6.0" in unapplied
    assert "'common'" in overapplied and "applied 2 times" in overapplied


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
        (lambda: Patch("old", "old", reason=_WRONG), "the text with itself"),
        (lambda: Patch("old", "new"), "has no `reason`"),
    ],
    ids=["zero-count", "no-op", "no-reason"],
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


@pytest.mark.parametrize("kind", ["docx", "rfc"])
def test_extract_fails_when_a_patch_no_longer_applies(
    tmp_path, synthetic_spec_docx, kind
):
    if kind == "docx":
        source, reference, extract = synthetic_spec_docx, "TS29.999", tgpp_docx.extract
    else:
        source = tmp_path / "rfc9999.txt"
        source.write_text("Request for Comments: 9999\n\n1.  Introduction\n")
        reference, extract = "RFC9999", rfc_text.extract
    # A patch that stops matching is a fix silently dropped from the output,
    # so it must not be possible to miss it in a stderr warning.
    patches_dir = tmp_path / "patches"
    patches_dir.mkdir()
    (patches_dir / f"{reference}.toml").write_text(
        """
[[patch]]
find = "no longer present"
replace = "irrelevant"
reason = "a fix the source no longer needs"
first_version = "1.0.0"
last_version = "1.1.0"
"""
    )

    message = "needed on version 1.0.0..1.1.0" if kind == "docx" else "applied 0 times"
    with pytest.raises(PatchError, match=re.escape(message)):
        extract(source, sources_dir=patches_dir)


def test_a_reason_reads_as_prose_and_a_find_exactly(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text(
        '''
[[patch]]
find = "two  spaces"
replace = "two\\tspaces "
reason = """
    flags cell typo
      in   table 7.3.1/1
    """

[[quirk]]
name = "prose-avp-codes"
reason = """
    the AVP tables
    print no Code column
    """
'''
    )

    patcher, quirks = load(path, None, {"prose-avp-codes": ""})

    (patch,) = patcher.patches
    assert patch.reason == "flags cell typo in table 7.3.1/1"
    assert (patch.find, patch.replace) == ("two  spaces", "two\tspaces ")
    assert quirks.quirks["prose-avp-codes"].reason == (
        "the AVP tables print no Code column"
    )


def test_an_exclusion_holds_its_clause_and_what_is_under_it(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text(
        '[[exclude]]\nsection = "8"\nname = "Sh-ee"\nreason = """\n    not\n'
        '    finished\n    """\nfirst_version = "19.1.0"\n'
    )

    patcher, _ = load(path, "19.1.0", {})

    assert patcher.exclusions[0].reason == "not finished"
    assert [patcher.excludes(each) for each in ("8", "8.3.1", "80", "8A", "7.8")] == [
        True,
        True,
        False,
        False,
        False,
    ]
    assert patcher.exclusion_notes("TS29.999.toml") == [
        "excluded: clause 8 (Sh-ee), see TS29.999.toml"
    ]
    patcher.finish()


def test_an_exclusion_stays_with_the_release_of_its_lower_bound(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text(
        '[[exclude]]\nsection = "8"\nname = "A"\nreason = "x"\n'
        'first_version = "19.1.0"\n'
    )

    assert Patcher.load(path, "18.0.0").exclusions == []
    assert len(Patcher.load(path, "19.2.0").exclusions) == 1
    assert len(Patcher.load(path, "20.0.0").exclusions) == 1


def test_an_exclusion_that_left_nothing_out_fails(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text(
        '[[exclude]]\nsection = "8"\nname = "A"\nreason = "x"\n'
        'first_version = "19.1.0"\n'
    )

    with pytest.raises(PatchError, match=r"clause 8 left nothing out.*19\.1\.0"):
        Patcher.load(path, "19.1.0").finish()


@pytest.mark.parametrize(
    ("declaration", "complaint"),
    [
        ('section = "8"\nname = "A"\n', "no `reason`"),
        ('section = "8"\nreason = "x"\n', "name"),
        ('name = "A"\nreason = "x"\n', "section"),
        ('section = ""\nname = "A"\nreason = "x"\n', "needs a `section`"),
        ('section = "8"\nname = "A"\nreason = "x"\nfind = "y"\n', "find"),
    ],
)
def test_an_exclusion_declares_what_it_leaves_out_and_why(
    tmp_path, declaration, complaint
):
    path = tmp_path / "TS29.999.toml"
    path.write_text(f"[[exclude]]\n{declaration}")

    with pytest.raises(PatchError, match=complaint):
        Patcher.load(path, None)


def test_a_reason_of_only_whitespace_is_no_reason(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text('[[patch]]\nfind = "a"\nreplace = "b"\nreason = """\n    """\n')

    with pytest.raises(PatchError, match="no `reason`"):
        Patcher.load(path, None)
