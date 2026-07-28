"""Input patches: per-spec find/replace fixes for typos in source documents.

Genuine typos in a 3GPP docx ("M. V" flag cells, "Monitoring Event Report"
with spaces for hyphens) are fixed *before* parsing, by patching the
normalized paragraph/cell/title text — not the raw docx XML, which has
arbitrary run splits and is hopeless as a patch target. Recurring document
conventions stay in extractor code; semantic corrections stay in output
`.dad` patches.

Patch files are TOML, one per specification, named by its reference
("TS29.272.toml"):

    [[patch]]
    find = "M. V"
    replace = "M, V"
    exact = true            # match the whole text unit, not a substring
    count = 1               # must apply exactly this many times (default 1)
    section = "7.3"         # optional: only inside this section (prefix)
    reason = "flags cell typo in table 7.3.1/1"   # required
    first_version = "18.6.0"   # oldest version known to need this patch
    last_version = "18.6.0"    # newest version known to need this patch

`find`, `replace` and `reason` are required, `find` must be non-empty and
`count` positive: those are the declarations a patch cannot mean, and a patch
whose `find` is empty would rewrite every gap between characters while still
satisfying its own accounting.

A patch that applies more or fewer times than `count` fails the extraction,
with a message including the known-needed version range, so patches cannot
silently rot when the source document changes between versions. The version
range is advisory: it explains where the patch is known to be needed, and does
not gate whether the patch is applied.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ExtractionError


class PatchError(ExtractionError):
    pass


@dataclass
class Patch:
    find: str
    replace: str
    count: int = 1
    section: str | None = None
    exact: bool = False
    reason: str | None = None
    first_version: str | None = None
    last_version: str | None = None
    applied: int = 0

    def __post_init__(self) -> None:
        """Reject declarations that cannot mean what a patch means.

        An empty `find` is the dangerous one: `str.count("")` and
        `str.replace("", x)` both work on the gaps between characters, so
        `find = ""` rewrites "abc" into "XaXbXcX" and can still satisfy its
        `count`. The accounting that is supposed to catch a rotten patch would
        confirm it instead.
        """
        if not self.find:
            raise PatchError("input patch has an empty `find`")
        if self.count < 1:
            raise PatchError(
                f"input patch {self.find!r} -> {self.replace!r} expects"
                f" {self.count} applications; a patch that is not applied"
                " should be deleted, not declared"
            )
        if self.find == self.replace:
            raise PatchError(f"input patch {self.find!r} replaces the text with itself")
        if not self.reason:
            # A patch asserts that the source document is wrong. Without the
            # reason, the next reader cannot check that claim against the spec,
            # and the patch becomes unreviewable the moment its author forgets.
            raise PatchError(
                f"input patch {self.find!r} -> {self.replace!r} has no `reason`"
            )

    def _in_scope(self, section: str | None) -> bool:
        if self.section is None:
            return True
        if section is None:
            return False
        return section == self.section or section.startswith(self.section + ".")

    def apply(self, text: str, section: str | None, record: bool = True) -> str:
        if not self._in_scope(section):
            return text
        if self.exact:
            if text == self.find:
                if record:
                    self.applied += 1
                return self.replace
            return text
        occurrences = text.count(self.find)
        if occurrences:
            if record:
                self.applied += occurrences
            return text.replace(self.find, self.replace)
        return text


class Patcher:
    """Applies one spec's input patches and accounts for every application."""

    def __init__(self, patches: list[Patch], version: str | None):
        # `version` is only for messages; None for a version-less document
        # (an RFC), whose patches have no version range to compare against.
        self.patches = patches
        self.version = version

    @classmethod
    def load(cls, path: Path | None, version: str | None) -> Patcher:
        if path is None or not path.is_file():
            return cls([], version)
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        try:
            patches = [Patch(**entry) for entry in data.get("patch", ())]
        except TypeError as error:
            # A misspelled or missing key in the TOML is the user's file being
            # wrong, not this program: report it like every other patch problem.
            raise PatchError(f"{path}: {error}") from None
        return cls(patches, version)

    def apply(self, text: str, section: str | None = None, record: bool = True) -> str:
        """Apply all patches to one text unit. `record=False` applies without
        counting — for text views that duplicate an already-counted unit
        (per-line views of a cell, merged-cell repeats)."""
        for patch in self.patches:
            text = patch.apply(text, section, record)
        return text

    def finish(self) -> None:
        """Fail if any patch did not apply exactly `count` times.

        A patch that silently stops matching is a fix quietly dropped from the
        output, which is precisely what this accounting exists to prevent — so
        it aborts the extraction rather than adding to the warning list nobody
        has to act on. `first_version`/`last_version` only sharpen the message:
        they say where the patch is known to be needed, and never gate whether
        it is applied.
        """
        problems = []
        for patch in self.patches:
            if patch.applied == patch.count:
                continue
            message = (
                f"input patch {patch.find!r} -> {patch.replace!r} applied"
                f" {patch.applied} times, expected {patch.count}"
            )
            if patch.first_version is not None and self.version is not None:
                known = patch.first_version
                if patch.last_version not in (None, patch.first_version):
                    known += f"..{patch.last_version}"
                message += (
                    f"; it was needed on version {known}, currently parsing"
                    f" {self.version} — the source may have changed"
                )
            problems.append(message)
        if problems:
            # One per line: each message already contains a semicolon, so
            # joining with another one reads as four clauses at two levels.
            raise PatchError("\n".join(problems))
