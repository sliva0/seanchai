"""Source declarations: everything declared about reading one source document.

One TOML file per specification, named by its reference ("TS29.272.toml"),
holding three kinds of block. `[[patch]]` fixes a genuine typo in the source
*text* before parsing — a 3GPP docx's "M. V" flag cell, "Monitoring Event
Report" with spaces for hyphens — by patching the normalized
paragraph/cell/title text, not the raw docx XML, which has arbitrary run
splits and is hopeless as a patch target. `[[quirk]]` enables, by name, an
extractor reading that is heuristic enough to misfire on a document it was
not written for — harvesting AVP codes out of defining prose, indexing a
document that prints no AVP table at all — and that therefore stays off
unless the document declares it. Exact-match structural vocabulary (table
header spellings, rule grammars) stays in extractor code, where unrecognized
input fails loudly on its own; semantic corrections to data that parses fine
stay in `edits/corrections/`. `[[exclude]]` leaves a whole clause of a 3GPP docx
unread, which is the only way a file says less than its document.

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

All block kinds carry the same declaration contract: a required `reason`
(a declaration asserts something about the source document, and without the
reason the next reader cannot check that claim), a version range scoping it
to the releases it spans and advisory within them (`versions.reviewed_release`),
and must-fire accounting — a patch that applies more or fewer times than
`count`, a declared quirk that never changed anything, or an exclusion that
left nothing out fails the extraction rather than rotting silently when the
source changes between versions. A quirk carries no parameters by design: it is
a named boolean with a reason, and the behavior it names lives in extractor code
— TOML that carried logic would make the extractor an interpreter and the
declaration unreviewable.

A `reason` is prose and may wrap in a multi-line string, read back as one line
(`prose.collapse`). Every other field is exact, `find` and `replace` above all.
"""

import tomllib
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from ..prose import collapse_fields
from ..versions import VersionRange, applies, reviewed_release
from .errors import ExtractionError


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

    It says more than a patch does: the file will not hold what the clause
    states, so `reason` has to say why the document cannot be read there, and
    the file says that it left the clause out (`Patcher.exclusion_notes`).
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
        it is applied. An exclusion that left nothing out fails the same way,
        which also refuses one declared for a document whose reading does not
        ask (`excludes`): only the docx extractor does.
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

    Each extractor owns a vocabulary of quirk names (its `QUIRKS` mapping);
    declaring a name outside it fails at load, so a typo cannot silently
    leave a quirk off. A declared quirk that never fires fails `finish()`,
    so a reading the source stopped needing is loud, exactly like a patch
    whose `find` stopped matching.
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

    `known_quirks` is the calling extractor's vocabulary: name → one-line
    description, used to reject an unknown declaration with the list of what
    this extractor can be told.
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
    """Translate the TOML bounds into the same type corrections declare, and
    read `reason` as prose. Nothing else collapses: `find` and `replace` are
    matched and written character for character, `section` and `name` compared
    exactly."""
    fields = collapse_fields(entry, {"reason"})
    if "versions" in fields:
        raise ValueError("TOML ranges use first_version and last_version")
    versions = VersionRange(
        fields.pop("first_version", None), fields.pop("last_version", None)
    )
    return {**fields, "versions": versions}
