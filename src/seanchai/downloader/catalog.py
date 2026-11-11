"""What the downloader fetches: `specs.toml`, read.

Kept apart from `core` so that `seanchai export` can read the catalog's
titles without the download machinery. Stdlib only.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlparse

from .._prose import collapse_fields
from ..errors import SeanchaiError

# What `seanchai corpus download --only` selects, and a manifest says it holds.
SOURCES = ("3gpp", "onem2m", "rfc", "transcribed", "wireshark")

# The 3GPP release the catalog's `[[tgpp]]` entries are fetched at, unless a run
# asks for another. Moving it is a version upgrade (docs/development.md).
RELEASE = 19


class DownloadError(SeanchaiError, RuntimeError):
    """Anything that stops the corpus being fetched as asked."""


def parse_version(text: str) -> tuple[int, int, int]:
    """Read `18.6.0` as (18, 6, 0).

    3GPP spells each component as one base-36 character in archive names, so
    none can exceed 35.
    """
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", text.strip())
    if not match or any(int(part) > 35 for part in match.groups()):
        raise DownloadError(f"not a 3GPP version: {text!r} (expected e.g. 18.6.0)")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


@dataclass(frozen=True)
class ThreeGppSpec:
    number: str
    title: str
    reason: str = "Defines Diameter commands, command ABNF, AVPs, or AVP mappings."
    document_type: str = "TS"
    # Why the extractor has nothing to read in it (docs/extractor.md).
    out_of_scope: str | None = None

    @property
    def series(self) -> int:
        return int(self.number.split(".", 1)[0])

    @property
    def archive_stem(self) -> str:
        return self.number.replace(".", "").replace("-", "")


@dataclass(frozen=True)
class RfcSpec:
    number: int
    title: str


@dataclass(frozen=True)
class WiresharkDictionary:
    """The pinned Wireshark Diameter dictionary directory."""

    tag: str
    path: str


@dataclass(frozen=True)
class OneM2MSpec:
    """A oneM2M Technical Specification, pinned to one version of one release.

    oneM2M publishes the Word original (ETSI's TS 118 1xx mirror is PDF only) as
    a zip of a clean `(cl)` and a revision-marked `(rm)` legacy `.doc`. Its
    endpoint serves only the latest revision, so the version is the catalog's and
    the downloaded file must carry it (`check_onem2m_archive`); a newer upload
    fails the run.
    """

    number: str  # "0004"
    title: str
    release: int
    version: str  # "2.35.0"
    document_id: int
    reason: str = "Defines Diameter commands, command ABNF, AVPs, or AVP mappings."

    @property
    def identifier(self) -> str:
        """The title `ast.spec_ref` reads: "oneM2M TS-0004"."""
        return f"oneM2M TS-{self.number}"

    @property
    def file_version(self) -> str:
        """The version as oneM2M's file names spell it: "V2_35_0"."""
        return "V" + self.version.replace(".", "_")


# What a pinned version's `final` says the archive must list nothing newer
# than it in: any release, or its own.
FINAL_SCOPES = ("document", "release")


@dataclass(frozen=True)
class PinnedThreeGppSpec:
    """A 3GPP specification at one version, beside the catalog's release.

    A citing document may mean another release: TS 32.299 cites TS 29.140,
    whose last version is V7.0.0. Each such version is pinned here and fetched
    into its own release's tree (`3gpp/Rel-7/TS_29.140/`). `final` is what the
    pin claims, checked against the archive listing on every download
    (`check_final`): `"document"`, no later version archived in any release, or
    `"release"`, none later in that release. A version archived later fails the
    download (docs/consumers.md).
    """

    number: str
    title: str
    version: str  # "7.0.0"
    final: str  # one of FINAL_SCOPES
    reason: str = "Defines Diameter commands, command ABNF, AVPs, or AVP mappings."
    document_type: str = "TS"

    def __post_init__(self) -> None:
        if self.final not in FINAL_SCOPES:
            raise TypeError(
                f"{self.document_type} {self.number}: final must be one of"
                f" {', '.join(FINAL_SCOPES)}, not {self.final!r}"
            )
        parse_version(self.version)

    @property
    def spec(self) -> ThreeGppSpec:
        return ThreeGppSpec(self.number, self.title, self.reason, self.document_type)

    @property
    def release(self) -> int:
        return parse_version(self.version)[0]


@dataclass(frozen=True)
class TranscribedDocument:
    """A document the corpus holds as a hand transcription (`edits/
    transcriptions/`), and the PDF it was copied from.

    `regenerate` never reads the PDF; the self-hosted export carries it. `url` is
    the file's `; Transcribed:`, which `tests/test_transcription.py` checks.
    """

    reference: str  # "ETSI-ES283.034"
    title: str
    url: str

    @property
    def publisher(self) -> str:
        """Who publishes it, the manifest's `family`: "ETSI", "3GPP2" or "OMA"."""
        return self.reference.split("-", 1)[0]

    @property
    def file_name(self) -> str:
        """The rendering's name, which is what the export looks it up by."""
        return unquote(urlparse(self.url).path).rsplit("/", 1)[-1]


class Catalog(NamedTuple):
    """`specs.toml`, read."""

    tgpp: tuple[ThreeGppSpec, ...]
    rfc: tuple[RfcSpec, ...]
    wireshark: WiresharkDictionary
    onem2m: tuple[OneM2MSpec, ...] = ()
    pinned: tuple[PinnedThreeGppSpec, ...] = ()
    transcribed: tuple[TranscribedDocument, ...] = ()

    def out_of_scope(self) -> dict[str, str]:
        """Why each document the extractor has nothing to read in is so, by
        `SpecRef`."""
        return {
            f"{spec.document_type}{spec.number}": spec.out_of_scope
            for spec in self.tgpp
            if spec.out_of_scope is not None
        }


CATALOG_PATH = Path(__file__).resolve().parent / "specs.toml"


def _prose(entry: dict) -> dict:
    """A catalog entry with `title`, `reason` and `out_of_scope` read as prose;
    its numbers, versions and the Wireshark tag and path are exact."""
    return collapse_fields(entry, {"title", "reason", "out_of_scope"})


def load_catalog(path: Path | None = None) -> Catalog:
    """Read the curated specification catalog from specs.toml, on demand rather
    than at import.
    """
    path = path or CATALOG_PATH
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        tgpp = tuple(ThreeGppSpec(**_prose(entry)) for entry in data["tgpp"])
        rfc = tuple(RfcSpec(**_prose(entry)) for entry in data["rfc"])
        wireshark = WiresharkDictionary(**data["wireshark"])
        onem2m = tuple(OneM2MSpec(**_prose(entry)) for entry in data.get("onem2m", ()))
        pinned = tuple(
            PinnedThreeGppSpec(**_prose(entry)) for entry in data.get("tgpp_pinned", ())
        )
        transcribed = tuple(
            TranscribedDocument(**_prose(entry))
            for entry in data.get("transcribed", ())
        )
    except (
        OSError,
        tomllib.TOMLDecodeError,
        KeyError,
        TypeError,
        DownloadError,
    ) as error:
        raise DownloadError(
            f"cannot read the specification catalog {path}:"
            f" {type(error).__name__}: {error}"
        ) from error
    return Catalog(tgpp, rfc, wireshark, onem2m, pinned, transcribed)
