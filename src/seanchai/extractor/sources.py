"""Source declarations: what is declared about reading one source document.

One TOML file per specification, named by its reference ("TS29.272.toml"),
with three kinds of block:

- `[[patch]]` fixes a typo in the normalized source text (paragraph, cell or
  title text, never the raw docx XML) before parsing.
- `[[quirk]]` turns on, by name, a heuristic reading that stays off unless the
  document declares it. A quirk takes no parameters; its behaviour lives in
  extractor code.
- `[[exclude]]` leaves a whole clause of a 3GPP docx unread.

    [[patch]]
    find = "M. V"
    replace = "M, V"
    exact = true            # match the whole text unit, not a substring
    count = 1               # must apply exactly this many times (default 1)
    section = "7.3"         # optional: only inside this section (prefix)
    reason = "flags cell typo in table 7.3.1/1"   # required
    first_version = "18.6.0"   # oldest version known to need this patch
    last_version = "18.6.0"    # newest version known to need this patch

    [[quirk]]
    name = "prose-avp-codes"   # must be one the extractor defines
    reason = "AVP tables carry no Code column; each clause prints its code"

    [[exclude]]
    section = "8"              # the clause and every clause under it
    name = "Sh-ee"             # what the file's note calls it
    reason = "the document leaves the application id to be allocated"
    first_version = "19.1.0"

Every block needs a `reason` and may carry a version range, which selects a
release's declarations and is advisory within it
(`_versions.reviewed_release`). Every block must fire: a patch applied other
than `count` times, a quirk that changed nothing, or an exclusion that left
nothing out fails the extraction. A `reason` may wrap across lines and is read
back as one line (`_prose.collapse`); every other field is exact. Semantic
corrections belong in `edits/corrections/`. See docs/extractor.md.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from .._prose import collapse_fields
from .._versions import VersionRange, applies, reviewed_release
from .errors import ExtractionError

__all__ = [
    "Exclusion",
    "Patch",
    "PatchError",
    "Patcher",
    "Quirk",
    "QuirkError",
    "Quirks",
    "load",
]


class PatchError(ExtractionError):
    pass


class QuirkError(ExtractionError):
    pass


def _in_clause(section: str | None, clause: str) -> bool:
    """Whether `section` is `clause` or a clause under it."""
    if section is None:
        return False
    return section == clause or section.startswith(clause + ".")


@dataclass
class Patch:
    find: str
    replace: str
    count: int = 1
    section: str | None = None
    exact: bool = False
    reason: str | None = None
    versions: VersionRange = dataclass_field(default_factory=VersionRange)
    applied: int = 0

    def __post_init__(self) -> None:
        """Reject declarations that cannot mean what a patch means.

        An empty `find` matches the gaps between characters, so it would rewrite
        "abc" into "XaXbXcX" and could still satisfy its `count`.
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
        return self.section is None or _in_clause(section, self.section)

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


@dataclass
class Exclusion:
    """A clause of the document no reading looks at, and whatever is under it.

    The file will not hold what the clause states, so `reason` says why the
    document cannot be read there, and the file notes the omission
    (`Patcher.exclusion_notes`).
    """

    section: str
    name: str
    reason: str | None = None
    versions: VersionRange = dataclass_field(default_factory=VersionRange)
    skipped: int = 0

    def __post_init__(self) -> None:
        if not self.section or not self.name:
            raise PatchError("an exclusion needs a `section` and a `name`")
        if not self.reason:
            raise PatchError(f"exclusion of clause {self.section} has no `reason`")


class Patcher:
    """Applies one spec's input patches and exclusions, and accounts for every
    application."""

    def __init__(
        self,
        patches: list[Patch],
        version: str | None,
        exclusions: list[Exclusion] | None = None,
    ):
        # `version` is only for messages; None for a version-less document
        # (an RFC), whose patches have no version range to compare against.
        self.patches = patches
        self.version = version
        self.exclusions = exclusions or []

    @classmethod
    def load(cls, path: Path | None, version: str | None) -> Patcher:
        if path is None or not path.is_file():
            return cls([], version)
        data = _read(path)
        try:
            patches = [Patch(**_ranged(entry)) for entry in data.get("patch", ())]
            exclusions = [
                Exclusion(**_ranged(entry)) for entry in data.get("exclude", ())
            ]
        except (TypeError, ValueError) as error:
            # A misspelled or missing key in the TOML is the user's file being
            # wrong, not this program: report it like every other patch problem.
            raise PatchError(f"{path}: {error}") from None
        release = reviewed_release(
            [declared.versions for declared in [*patches, *exclusions]]
            + [_ranged(entry)["versions"] for entry in data.get("quirk", ())],
            version,
        )
        return cls(
            [p for p in patches if applies(p.versions, release)],
            version,
            [e for e in exclusions if applies(e.versions, release)],
        )

    def excludes(self, section: str) -> bool:
        """Whether a declared exclusion leaves out the clause headed `section`;
        asked once per heading, which is what an exclusion's accounting counts."""
        excluded = False
        for exclusion in self.exclusions:
            if _in_clause(section, exclusion.section):
                exclusion.skipped += 1
                excluded = True
        return excluded

    def exclusion_notes(self, file_name: str) -> list[str]:
        """What the file says of each clause it left out, naming the file
        `file_name` of declarations that says why."""
        return [
            f"excluded: clause {exclusion.section} ({exclusion.name}), see {file_name}"
            for exclusion in self.exclusions
        ]

    def apply(self, text: str, section: str | None = None, record: bool = True) -> str:
        """Apply all patches to one text unit. `record=False` applies without
        counting, for views that repeat an already-counted unit (per-line views of a
        cell, merged-cell repeats)."""
        for patch in self.patches:
            text = patch.apply(text, section, record)
        return text

    def finish(self) -> None:
        """Fail if any patch did not apply exactly `count` times.

        This aborts the extraction instead of warning. `first_version` and
        `last_version` only sharpen the message; they never gate whether a patch is
        applied. An exclusion that left nothing out fails the same way, which also
        refuses one declared for an extractor that does not read exclusions
        (`excludes`): only the docx extractor does.
        """
        problems = []
        for patch in self.patches:
            if patch.applied == patch.count:
                continue
            message = (
                f"input patch {patch.find!r} -> {patch.replace!r} applied"
                f" {patch.applied} times, expected {patch.count}"
            )
            if patch.versions != VersionRange() and self.version is not None:
                known = str(patch.versions)
                message += (
                    f"; it was needed on version {known}, currently parsing"
                    f" {self.version} — the source may have changed"
                )
            problems.append(message)
        for exclusion in self.exclusions:
            if exclusion.skipped:
                continue
            message = f"exclusion of clause {exclusion.section} left nothing out"
            if exclusion.versions != VersionRange() and self.version is not None:
                message += (
                    f"; it was needed on version {exclusion.versions}, currently"
                    f" parsing {self.version} — the source may have changed"
                )
            problems.append(message)
        if problems:
            # One per line: each message already contains a semicolon, so
            # joining with another one reads as four clauses at two levels.
            raise PatchError("\n".join(problems))


@dataclass
class Quirk:
    name: str
    reason: str | None = None
    versions: VersionRange = dataclass_field(default_factory=VersionRange)
    fired: int = 0

    def __post_init__(self) -> None:
        if not self.name:
            raise QuirkError("quirk declaration has an empty `name`")
        if not self.reason:
            # A quirk asserts that this document needs a reading no other
            # document gets. Without the reason, the next reader cannot check
            # that claim against the source.
            raise QuirkError(f"quirk {self.name!r} has no `reason`")


class Quirks:
    """One spec's declared quirks, with the Patcher's accounting contract.

    A name outside the extractor's `QUIRKS` fails at load. A declared quirk
    that never fires fails `finish()`, as a patch whose `find` stopped matching
    does.
    """

    def __init__(self, quirks: list[Quirk], version: str | None):
        self.quirks = {quirk.name: quirk for quirk in quirks}
        if len(self.quirks) != len(quirks):
            raise QuirkError("a quirk is declared twice")
        self.version = version

    def enabled(self, name: str) -> bool:
        return name in self.quirks

    def fire(self, name: str, count: int = 1) -> None:
        self.quirks[name].fired += count

    def finish(self) -> None:
        problems = []
        for quirk in self.quirks.values():
            if quirk.fired:
                continue
            message = f"quirk {quirk.name!r} is declared but changed nothing"
            if quirk.versions != VersionRange() and self.version is not None:
                known = str(quirk.versions)
                message += (
                    f"; it was needed on version {known}, currently parsing"
                    f" {self.version} — the source may have changed"
                )
            problems.append(message)
        if problems:
            raise QuirkError("\n".join(problems))


def _read(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load(
    path: Path | None,
    version: str | None,
    known_quirks: dict[str, str],
    warnings: list[str] | None = None,
) -> tuple[Patcher, Quirks]:
    """Load one specification's source declarations.

    `known_quirks` is the calling extractor's vocabulary (name to one-line
    description); an unknown declaration is rejected with that list.
    """
    patcher = Patcher.load(path, version)
    if path is None or not path.is_file():
        return patcher, Quirks([], version)
    data = _read(path)
    try:
        quirks = [Quirk(**_ranged(entry)) for entry in data.get("quirk", ())]
    except (TypeError, ValueError) as error:
        raise QuirkError(f"{path}: {error}") from None
    declared = Patcher.load(path, None)
    release = reviewed_release(
        [each.versions for each in [*declared.patches, *declared.exclusions]]
        + [quirk.versions for quirk in quirks],
        version,
    )
    # Unknown names are refused in every release's declarations alike.
    for quirk in quirks:
        if quirk.name not in known_quirks:
            known = ", ".join(sorted(known_quirks)) or "none"
            raise QuirkError(
                f"{path}: unknown quirk {quirk.name!r}; this extractor defines: {known}"
            )
    unexpected = set(data) - {"patch", "quirk", "exclude"}
    if unexpected:
        raise PatchError(
            f"{path}: unknown block {', '.join(sorted(unexpected))!r};"
            " a source declaration holds [[patch]], [[quirk]] and [[exclude]] blocks"
        )
    quirks = [quirk for quirk in quirks if applies(quirk.versions, release)]
    if warnings is not None:
        for patch in patcher.patches:
            if warning := patch.versions.warning(
                version, f"{path}: input patch {patch.find!r}"
            ):
                warnings.append(warning)
        for exclusion in patcher.exclusions:
            if warning := exclusion.versions.warning(
                version, f"{path}: exclusion of clause {exclusion.section}"
            ):
                warnings.append(warning)
        for quirk in quirks:
            if warning := quirk.versions.warning(
                version, f"{path}: quirk {quirk.name!r}"
            ):
                warnings.append(warning)
    return patcher, Quirks(quirks, version)


def _ranged(entry: dict) -> dict:
    """Translate the TOML bounds into the type corrections declare, and read
    `reason` as prose. Every other field stays exact."""
    fields = collapse_fields(entry, {"reason"})
    if "versions" in fields:
        raise ValueError("TOML ranges use first_version and last_version")
    versions = VersionRange(
        fields.pop("first_version", None), fields.pop("last_version", None)
    )
    return {**fields, "versions": versions}
