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
    reason = "flags cell typo in table 7.3.1/1"
    first_version = "18.6.0"   # oldest version known to need this patch
    last_version = "18.6.0"    # newest version known to need this patch

A patch that applies more or fewer times than `count` produces a warning
including the known-needed version range, so patches cannot silently rot when
the source document changes between versions.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path


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

    def __init__(self, patches: list[Patch], version: str):
        self.patches = patches
        self.version = version

    @classmethod
    def load(cls, path: Path | None, version: str) -> "Patcher":
        if path is None or not path.is_file():
            return cls([], version)
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        return cls([Patch(**entry) for entry in data.get("patch", ())], version)

    def apply(self, text: str, section: str | None = None, record: bool = True) -> str:
        """Apply all patches to one text unit. `record=False` applies without
        counting — for text views that duplicate an already-counted unit
        (per-line views of a cell, merged-cell repeats)."""
        for patch in self.patches:
            text = patch.apply(text, section, record)
        return text

    def finish(self, warnings: list[str]) -> None:
        """Report every patch that did not apply exactly `count` times."""
        for patch in self.patches:
            if patch.applied == patch.count:
                continue
            message = (
                f"input patch {patch.find!r} -> {patch.replace!r} applied"
                f" {patch.applied} times, expected {patch.count}"
            )
            if patch.first_version is not None:
                known = patch.first_version
                if patch.last_version not in (None, patch.first_version):
                    known += f"..{patch.last_version}"
                message += (
                    f"; it was needed on version {known}, currently parsing"
                    f" {self.version} — the source may have changed"
                )
            warnings.append(message)
