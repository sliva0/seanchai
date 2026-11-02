"""Inclusive version ranges shared by all declaration layers: each scopes its
declaration to the releases it spans, and is advisory within them."""

import re
from dataclasses import dataclass


def _parts(version: str) -> tuple[int, ...]:
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]+)*", version
    ):
        raise ValueError(f"invalid version {version!r}: expected dotted integers")
    parts = tuple(int(part) for part in version.split("."))
    # A missing trailing component means zero, so 18.6 equals 18.6.0.
    while parts and parts[-1] == 0:
        parts = parts[:-1]
    return parts


class RangeWarning(str):
    """A warning about a stale range, told apart from the extractor's own
    warnings so `regenerate --expand-ranges` can retire it once widened."""


@dataclass(frozen=True)
class VersionRange:
    """Inclusive bounds; an absent bound is open, and both absent mean any version."""

    first: str | None = None
    last: str | None = None

    def __post_init__(self) -> None:
        first = _parts(self.first) if self.first is not None else None
        last = _parts(self.last) if self.last is not None else None
        if first is not None and last is not None and first > last:
            raise ValueError(f"reversed version range {self}")

    @classmethod
    def exact(cls, version: str) -> VersionRange:
        """A declaration reviewed against one version."""
        return cls(version, version)

    @classmethod
    def parse(cls, text: str | VersionRange) -> VersionRange:
        """`"18.6.0"` for one version, `"18.0.0..18.2.0"` for a range, either
        bound `*` for open — the spelling `__str__` produces."""
        if isinstance(text, VersionRange):
            return text
        first, dots, last = text.partition("..")
        if not dots:
            return cls.exact(text)
        return cls(None if first == "*" else first, None if last == "*" else last)

    def covers(self, version: str) -> bool:
        """Compare numeric components, including both endpoints."""
        parsed = _parts(version)
        return (self.first is None or _parts(self.first) <= parsed) and (
            self.last is None or parsed <= _parts(self.last)
        )

    def expanded(self, version: str) -> VersionRange:
        """The smallest widening of this range that covers `version`."""
        if self.covers(version):
            return self
        if self.first is not None and _parts(version) < _parts(self.first):
            return VersionRange(version, self.last)
        return VersionRange(self.first, version)

    def warning(self, version: str | None, declaration: str) -> RangeWarning | None:
        """Report an unreviewed version; this never decides whether an edit applies."""
        if version is None or self.covers(version):
            return None
        return RangeWarning(
            f"{declaration}: declared version range {self} does not cover parsed"
            f" version {version}; application is not gated"
        )

    def __str__(self) -> str:
        if self.first == self.last and self.first is not None:
            return self.first
        return f"{self.first or '*'}..{self.last or '*'}"


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def _releases(versions: VersionRange) -> tuple[int | None, int | None]:
    """The majors `versions` spans, either bound None for open."""
    return (
        None if versions.first is None else _major(versions.first),
        None if versions.last is None else _major(versions.last),
    )


def reviewed_release(ranges: list[VersionRange], version: str | None) -> int | None:
    """The release whose declarations apply to `version`, or None for all.

    A document's declarations are reviewed per release: a 3GPP release is
    where a template, and with it every quirk and typo, may change, so a
    declaration made for Release 18 says nothing about Release 7 (TS 29.214
    V7.12.0 beside V18.4.0). Within a release a range is advisory, so the
    next version of a release still gets every declaration and a warning
    (docs/development.md#version-upgrades). The release is `version`'s own
    when some range spans it, else the newest declared release below it,
    which is a release upgrade: Release 19 is first read with Release 18's
    declarations, as within a release. A version below every declared
    release gets none. None, meaning every declaration, for a version-less
    document (an RFC) and for a file whose ranges are all open.
    """
    if version is None:
        return None
    wanted = _major(version)
    spans = [_releases(versions) for versions in ranges]
    if not spans or all(first is None and last is None for first, last in spans):
        return None
    if any(
        (first is None or first <= wanted) and (last is None or wanted <= last)
        for first, last in spans
    ):
        return wanted
    below = [last for first, last in spans if last is not None and last < wanted]
    return max(below) if below else -1


def applies(versions: VersionRange, release: int | None) -> bool:
    """Whether a declaration ranged `versions` applies in `release`, which
    `reviewed_release` chose; None applies everything."""
    if release is None:
        return True
    first, last = _releases(versions)
    return (first is None or first <= release) and (last is None or release <= last)
