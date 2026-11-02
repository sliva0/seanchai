"""Corpus downloader implementation. See the package docstring for what it is.

Two rules hold throughout this module.

Every failure is a `DownloadError`. An HTTP error, an unreadable catalog, a
truncated ZIP and a PDF that is only the first few bytes of one are all the
same answer to "did the corpus download?", and a caller should not have to
know which layer noticed.

Nothing is trusted because it exists. A file left by an interrupted run is a
plausible-looking, wrong artifact; so is a proxy's error page saved under a
`.zip` name. Both fresh downloads and cached files are therefore opened and
checked by the format they claim to be, and a replacement is validated in a
temporary file *before* it is put in place.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import docx
import pypdf

from ..prose import collapse_fields

THREE_GPP_ARCHIVE = "https://www.3gpp.org/ftp/Specs/archive/{series}_series/{number}/"
ETSI_DELIVER = "https://www.etsi.org/deliver"
RFC_TEXT_URL = "https://www.rfc-editor.org/rfc/rfc{number}.txt"
# Wireshark's repository, via GitLab's API: the tree listing enumerates the
# dictionary directory at the pinned tag, and the raw endpoint serves each
# file. The API is what makes "fetch that directory" expressible at all —
# git offers no shallow single-directory fetch, and the repository is 1.2 GB
# for the 824 KB that matter.
WIRESHARK_TREE_URL = (
    "https://gitlab.com/api/v4/projects/wireshark%2Fwireshark/repository/tree"
    "?path={path}&ref={tag}&per_page=100"
)
WIRESHARK_RAW_URL = "https://gitlab.com/wireshark/wireshark/-/raw/{tag}/{path}/{name}"
# oneM2M's document library: no login, served as application/octet-stream.
# The endpoint always serves a document's latest revision, so the catalog pins
# the version and the download checks the file it got (`OneM2MSpec`).
ONEM2M_DOWNLOAD_URL = (
    "https://member.onem2m.org/Application/documentapp/downloadLatestRevision/"
    "default.aspx?docID={document_id}"
)
USER_AGENT = "diameter-spec-corpus-downloader/1.0"
# LibreOffice, for the archives that still ship a legacy binary `.doc` (TS
# 32.299 and nine more): the extractor reads only `.docx`.
SOFFICE = "soffice"
SOFFICE_TIMEOUT = 600

# The layout under the output directory. `archives/` is the download cache:
# every file ever fetched, version-named and never pruned, so an older
# version is re-extracted from disk. The published tree is what
# `manifest.json` describes; each run builds it afresh in `.staging/` and
# swaps it in whole (`publish`). `versions/<SpecRef>/<version>/` holds an
# older version fetched on request, as a tree of the same shape.
CACHE = "archives"
PUBLISHED = ("3gpp", "converted", "onem2m", "rfc", "wireshark")
MANIFEST = "manifest.json"
STAGING = ".staging"
PREVIOUS = ".previous"
VERSIONS = "versions"


@dataclass(frozen=True)
class ThreeGppSpec:
    number: str
    title: str
    reason: str = "Defines Diameter commands, command ABNF, AVPs, or AVP mappings."
    document_type: str = "TS"

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

    oneM2M publishes the Word original, which ETSI's TS 118 1xx mirror does
    not (PDF only), as a zip of a clean `(cl)` and a revision-marked `(rm)`
    legacy `.doc`. Its download endpoint serves whatever revision is latest
    for the document id, with no archive of earlier ones to select from, so
    the version is the catalog's and the downloaded file must carry it
    (`check_onem2m_archive`): a newer upload fails the run rather than
    replacing the document under a committed corpus.
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

    A citing document may mean another release than the corpus's: TS 32.299
    cites TS 29.140, whose last version is V7.0.0, and ETSI TS 183 017 cites
    "3GPP TS 29.214 Release 7". Each such version is pinned here and
    fetched into its own release's tree (`3gpp/Rel-7/TS_29.140/`), and
    `final` says what the pin claims about it, checked against the archive
    listing on every download (`check_final`): `"document"`, the
    document's final version, no later one archived in any release, or
    `"release"`, its release's last, no later one archived in that release.
    A version archived later breaks the claim, and the download fails
    rather than leave a resolution resting on it (docs/consumers.md).
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
    transcriptions/`), which no download fetches: only its title is here."""

    reference: str  # "ETSI-ES283.034"
    title: str


class Catalog(NamedTuple):
    """`specs.toml`, read."""

    tgpp: tuple[ThreeGppSpec, ...]
    rfc: tuple[RfcSpec, ...]
    wireshark: WiresharkDictionary
    onem2m: tuple[OneM2MSpec, ...] = ()
    pinned: tuple[PinnedThreeGppSpec, ...] = ()
    transcribed: tuple[TranscribedDocument, ...] = ()


CATALOG_PATH = Path(__file__).resolve().parent / "specs.toml"


class DownloadError(RuntimeError):
    """Anything that stops the corpus being fetched as asked."""


def _prose(entry: dict) -> dict:
    """A catalog entry with `title` and `reason` read as prose; its numbers,
    versions and the Wireshark tag and path are exact."""
    return collapse_fields(entry, {"title", "reason"})


def load_catalog(path: Path | None = None) -> Catalog:
    """Read the curated specification catalog from specs.toml.

    Called on demand rather than at import: reading a file as a side effect of
    importing makes the module hard to use from anything but the CLI.
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


@dataclass
class Conversion:
    """A `.docx` LibreOffice made from an archived legacy `.doc`.

    The converted file is not reproducible byte for byte: two runs over the
    same `.doc` with the same LibreOffice differ in the zip timestamps and in
    the random OLE `ObjectID`s Writer assigns (TS 32.299's embedded
    figures). Its `sha256` therefore identifies this run's file and nothing
    more; what says whether a conversion should read the same is the pair
    `source_sha256` and `converter`, and `command` is how to repeat it.
    """

    file: str
    source: str
    source_sha256: str
    # `soffice --version`, e.g. "LibreOffice 26.8.1.1 bf8adb135da2…".
    converter: str
    # The argument vector, with the run's temporary directories as
    # `{profile}` and `{outdir}` and the `.doc` as `{source}`.
    command: list[str]
    sha256: str
    size: int


@dataclass
class DownloadRecord:
    family: str
    identifier: str
    title: str
    url: str
    sha256: str
    size: int
    files: list[str]
    reason: str | None = None
    pdf_url: str | None = None
    pdf_sha256: str | None = None
    pdf_size: int | None = None
    source_version: str | None = None
    pdf_version: str | None = None
    # The newer archive version that was passed over because ETSI has not
    # published its PDF rendering; None when the newest version was taken.
    newer_source_version: str | None = None
    # The `.docx` conversions of a legacy `.doc` archive; empty when the run
    # was asked not to convert; None when the archive was not extracted or
    # holds a `.docx` of its own.
    conversions: list[Conversion] | None = None
    # A pinned version's claim, checked against the archive listing:
    # "document" (no later version in any release) or "release" (none later
    # in its own). None for the catalog's release.
    final: str | None = None


def release_marker(release: int) -> str:
    """Return the first version-code character used in 3GPP ZIP names."""
    if 4 <= release <= 9:
        return str(release)
    if 10 <= release <= 35:
        return chr(ord("a") + release - 10)
    raise DownloadError("3GPP release must be between 4 and 35")


def request_bytes(url: str, retries: int = 4) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in {408, 429, 500, 502, 503, 504}:
                raise DownloadError(
                    f"failed to fetch {url}: HTTP {error.code}"
                ) from error
            if attempt + 1 == retries:
                raise DownloadError(f"failed to fetch {url}: {error}") from error
            time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if attempt + 1 == retries:
                raise DownloadError(f"failed to fetch {url}: {error}") from error
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def discover_3gpp_archive_urls(
    spec: ThreeGppSpec, release: int | None
) -> dict[tuple[int, int, int], str]:
    """Every archived version of `spec` in `release`, from `Specs/archive/`;
    with None, in every release.

    The archive, not `Specs/latest/Rel-N/`, because `latest` lists one zip per
    specification and drops it when the next version lands: a manifest
    recording a `latest` URL names a file that stops existing, and choosing
    any version but the newest (an unpublished ETSI PDF, `--version`) needs
    the list of all of them anyway.
    """
    marker = "[0-9a-z]" if release is None else re.escape(release_marker(release))
    index_url = THREE_GPP_ARCHIVE.format(series=spec.series, number=spec.number)
    page = request_bytes(index_url).decode("utf-8", errors="replace")
    # The first filename character after '-' encodes the 3GPP release.
    pattern = re.compile(
        rf"""href=["']([^"']*/?{re.escape(spec.archive_stem)}-"""
        rf"""{marker}[0-9a-z]{{2}}\.zip)["']""",
        re.IGNORECASE,
    )
    # Keyed by the decoded version, so the newest is `max()` of the keys and
    # never the last link on the page: an index that lists 18.5.0 after
    # 18.6.0 is a presentation detail.
    return {
        decode_3gpp_version(href): urllib.parse.urljoin(index_url, href)
        for href in pattern.findall(html.unescape(page))
    }


def check_final(
    pin: PinnedThreeGppSpec, archived: dict[tuple[int, int, int], str]
) -> dict[tuple[int, int, int], str]:
    """Check `pin`'s `final` claim against its archive listing in every
    release, and return the listing of the pinned version's release.

    The listing is the archive's, which keeps every version, so a version
    published after the pin was made shows up here and fails the download,
    naming it: the catalog then states what the corpus should hold.
    """
    identifier = f"{pin.document_type} {pin.number}"
    selected = parse_version(pin.version)
    if selected not in archived:
        listed = ", ".join(version_string(v) for v in sorted(archived)) or "nothing"
        raise DownloadError(
            f"{identifier} {pin.version} is not archived; the archive lists {listed}"
        )
    later = sorted(
        version
        for version in archived
        if version > selected and (pin.final == "document" or version[0] == selected[0])
    )
    if later:
        scope = "document" if pin.final == "document" else f"Release {selected[0]}"
        raise DownloadError(
            f"{identifier}: the catalog pins {pin.version} as the {scope}'s final"
            f" version, but the archive lists"
            f" {', '.join(version_string(v) for v in later)}; a later version is"
            " one to adopt in specs.toml, not one to pass over"
        )
    return {
        version: url for version, url in archived.items() if version[0] == selected[0]
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


Validator = Callable[[Path], None]


def validate_zip(path: Path) -> None:
    """Open the archive and check every member's CRC.

    A nonempty file is not an archive: an interrupted download and a proxy
    error page both leave one, and both survive to the extraction step as a
    confusing failure somewhere else.
    """
    try:
        with zipfile.ZipFile(path) as zipped:
            corrupt = zipped.testzip()
    except (OSError, zipfile.BadZipFile) as error:
        raise DownloadError(f"{path} is not a readable ZIP archive: {error}") from error
    if corrupt is not None:
        raise DownloadError(f"{path} has a corrupt member: {corrupt}")


def validate_pdf(path: Path) -> None:
    """Open the PDF and require at least one page.

    A `%PDF-` prefix says only that the first five bytes arrived, which is
    exactly what a truncated download has.
    """
    try:
        pages = len(pypdf.PdfReader(str(path)).pages)
    except Exception as error:
        raise DownloadError(f"{path} is not a readable PDF: {error}") from error
    if not pages:
        raise DownloadError(f"{path} is a PDF with no pages")


def validate_rfc_text(path: Path) -> None:
    """Check that the file is the RFC Editor's plain text, not an error page.

    Every RFC's text rendering carries the "Request for Comments:" header line,
    which no HTML error body does.
    """
    try:
        head = path.read_bytes()[:4096].decode("utf-8", errors="replace")
    except OSError as error:
        raise DownloadError(f"cannot read {path}: {error}") from error
    if "Request for Comments:" not in head:
        raise DownloadError(f"{path} does not look like an RFC text rendering")


def atomic_download(
    url: str, destination: Path, validate: Validator | None = None
) -> None:
    """Fetch `url` to `destination` unless a valid file is already there.

    The replacement is written to a temporary file and validated there, so a
    bad download never becomes the cached artifact. A cached file that fails
    validation is removed even when its replacement also fails: leaving it
    would mean the next run finds the same broken file and reports the same
    error, having quietly rejected it twice.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    stale = False
    if destination.is_file() and destination.stat().st_size:
        if validate is None:
            return
        try:
            validate(destination)
        except DownloadError:
            stale = True
        else:
            return
    try:
        data = request_bytes(url)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=destination.name,
            suffix=".part",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            if validate is not None:
                validate(temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    except DownloadError:
        if stale:
            destination.unlink(missing_ok=True)
        raise


def safe_extract(archive: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    try:
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                member_path = PurePosixPath(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise DownloadError(
                        f"unsafe ZIP member in {archive}: {member.filename}"
                    )
                target = destination.joinpath(*member_path.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                extracted.append(target)
    except (OSError, zipfile.BadZipFile) as error:
        raise DownloadError(f"cannot extract {archive}: {error}") from error
    return extracted


def link_file(source: Path, target: Path) -> None:
    """Put the cached file `source` at `target` in a tree being staged.

    A hard link, since the cache is never modified in place; a copy where the
    filesystem refuses one.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def publish(staging: Path, destination: Path, names: Iterable[str]) -> None:
    """Swap the entries `names` and the manifest from `staging` into `destination`.

    All of them or none: a run that published entry by entry would leave a
    mix of two corpus versions whenever it failed partway, which is the state
    staging exists to rule out. The current entries are renamed aside into
    `.previous/` first and moved back if any rename fails. The manifest is
    the first entry taken aside and the last put in, so an interruption
    mid-swap leaves no manifest rather than one describing a half-swapped
    tree. An entry `destination` has and `staging` lacks is removed: the tree
    holds what the manifest lists and nothing else.

    A `.previous/` already present is a rollback that failed and holds the
    last published tree; it is refused rather than deleted.
    """
    refuse_failed_swap(destination)
    previous = destination / PREVIOUS
    entries = [MANIFEST, *names]
    aside: list[str] = []
    placed: list[str] = []
    try:
        previous.mkdir(parents=True)
        for name in entries:
            if (destination / name).exists():
                (destination / name).replace(previous / name)
                aside.append(name)
        for name in reversed(entries):
            if (staging / name).exists():
                (staging / name).replace(destination / name)
                placed.append(name)
    except OSError as error:
        # Best effort: a rollback rename can only fail for the reason the
        # swap did, and the original error is the one worth reporting. What
        # cannot be moved back stays in `.previous/`, which the next run
        # refuses to touch.
        for name in reversed(placed):
            with contextlib.suppress(OSError):
                (destination / name).replace(staging / name)
        # The manifest goes back last and only over a whole tree: restored
        # beside a directory still stuck in `.previous/`, it would describe
        # files that are not there.
        stuck = []
        for name in (*(n for n in aside if n != MANIFEST), MANIFEST):
            if name not in aside or (name == MANIFEST and stuck):
                continue
            try:
                (previous / name).replace(destination / name)
            except OSError:
                stuck.append(name)
        with contextlib.suppress(OSError):
            previous.rmdir()
        if stuck:
            kept = ", ".join(sorted(path.name for path in previous.iterdir()))
            raise DownloadError(
                f"cannot publish {staging} into {destination}: {error}; the"
                f" rollback could not restore {', '.join(stuck)}, so {previous}"
                f" holds {kept} and {destination} has no manifest"
            ) from error
        raise DownloadError(
            f"cannot publish {staging} into {destination}: {error}"
        ) from error
    shutil.rmtree(previous, ignore_errors=True)


def validate_docx(path: Path) -> None:
    """Open the file with python-docx, as the extractor will.

    A conversion LibreOffice reports as successful can still leave a package
    with an unparsable part; checking only that the archive holds
    `word/document.xml` would put it in the manifest and fail in
    `regenerate` instead.
    """
    validate_zip(path)
    try:
        docx.Document(str(path))
    except Exception as error:
        raise DownloadError(f"{path} is not a readable .docx: {error}") from error


def run_soffice(identifier: str, arguments: list[str]) -> str:
    """Run LibreOffice and return its standard output.

    The `.doc` belongs to a catalogued entry, so an absent LibreOffice is a
    failed download rather than a skipped one: whether a run's manifest can
    rebuild the whole corpus depends on what it was asked, never on what
    happens to be installed. Skipping is `convert=False`, which records it.
    """
    command = [SOFFICE, *arguments]
    try:
        # A session of its own, so a timeout can kill the whole group:
        # `soffice` is a launcher script whose `soffice.bin` child does the
        # work, and killing only the launcher (what `subprocess.run` does)
        # leaves the converter running into a profile directory the caller
        # is about to delete.
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise DownloadError(
            f"{identifier} ships a legacy .doc; converting it needs LibreOffice"
            f" (`{SOFFICE}`), which is not installed or not on PATH: {error};"
            " `seanchai download --no-convert` downloads without converting"
        ) from error
    except (OSError, subprocess.SubprocessError) as error:
        raise DownloadError(
            f"{identifier}: `{shlex.join(command)}` failed: {error}"
        ) from error
    try:
        stdout, stderr = process.communicate(timeout=SOFFICE_TIMEOUT)
    except subprocess.TimeoutExpired as error:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        # Reaps the launcher; the pipes close only once every process in the
        # group holding them is gone.
        process.communicate()
        raise DownloadError(
            f"{identifier}: `{shlex.join(command)}` timed out after {SOFFICE_TIMEOUT} s"
        ) from error
    if process.returncode != 0:
        output = (stderr.strip() or stdout.strip()).splitlines()
        raise DownloadError(
            f"{identifier}: `{shlex.join(command)}` exited {process.returncode}"
            + (f": {output[-1]}" if output else "")
        )
    return stdout


def legacy_documents(extracted: list[Path]) -> list[Path]:
    """The extracted `.doc` files to convert: none when the archive holds a
    `.docx` of its own."""
    if any(path.suffix == ".docx" for path in extracted):
        return []
    return [path for path in extracted if path.suffix == ".doc"]


def convert_legacy_documents(
    identifier: str, extracted: list[Path], spec_dir: Path, tree: Path
) -> list[Conversion]:
    """Convert an archive's legacy `.doc` files to `.docx` with LibreOffice.

    Only an archive with no `.docx` of its own is converted. The results go
    to `converted/` beside the extracted archive in the staged `tree`
    (`converted/3gpp/Rel-18/TS_32.299/32299-i00.docx`), not into it, so the
    extracted directory holds the archive's contents and nothing else. They
    are rebuilt on every run, like the extraction they derive from, and the
    manifest is the only way `regenerate` finds them; a run that fails here
    publishes nothing.
    """
    legacy = legacy_documents(extracted)
    if not legacy:
        return []
    converter = run_soffice(identifier, ["--version"]).strip()
    if not converter:
        raise DownloadError(f"{identifier}: `{SOFFICE} --version` printed nothing")
    destination = tree / "converted" / spec_dir.relative_to(tree)
    conversions = []
    try:
        # A private profile per run: with the user's own, a LibreOffice that
        # is already open receives the request and the headless process
        # exits without converting anything; concurrent conversions would
        # also contend for the one profile's lock.
        with tempfile.TemporaryDirectory(prefix="soffice-profile-") as profile:
            for document in legacy:
                relative = document.relative_to(spec_dir)
                outdir = destination / relative.parent
                outdir.mkdir(parents=True, exist_ok=True)
                # `--infilter` pins the Word 97 import: left to detection,
                # LibreOffice reads a file that is not a Word document as
                # plain text and exits 0 with a docx of its bytes.
                arguments = [
                    "-env:UserInstallation={profile}",
                    "--headless",
                    "--infilter=MS Word 97",
                    "--convert-to",
                    "docx:Office Open XML Text",
                    "--outdir",
                    "{outdir}",
                    "{source}",
                ]
                run_soffice(
                    identifier,
                    [
                        argument.format(
                            profile=Path(profile).as_uri(),
                            outdir=outdir,
                            source=document,
                        )
                        for argument in arguments
                    ],
                )
                converted = outdir / f"{document.stem}.docx"
                if not converted.is_file():
                    raise DownloadError(
                        f"{identifier}: LibreOffice wrote no {converted.name}"
                        f" for {document.name}"
                    )
                validate_docx(converted)
                conversions.append(
                    Conversion(
                        file=str(
                            destination.relative_to(tree)
                            / relative.with_suffix(".docx")
                        ),
                        source=str(document.relative_to(tree)),
                        source_sha256=sha256_file(document),
                        converter=converter,
                        command=[SOFFICE, *arguments],
                        sha256=sha256_file(converted),
                        size=converted.stat().st_size,
                    )
                )
    except OSError as error:
        raise DownloadError(
            f"{identifier}: cannot convert its legacy .doc: {error}"
        ) from error
    return conversions


def relative_paths(paths: Iterable[Path], root: Path) -> list[str]:
    return [str(path.relative_to(root)) for path in paths]


def decode_3gpp_version(archive_url: str) -> tuple[int, int, int]:
    name = Path(urllib.parse.urlparse(archive_url).path).name
    match = re.search(r"-([0-9a-z]{3})\.zip$", name, re.IGNORECASE)
    if not match:
        raise DownloadError(f"cannot determine 3GPP version from {archive_url}")
    major, minor, patch = (int(character, 36) for character in match.group(1).lower())
    return major, minor, patch


def version_string(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


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


def etsi_pdf_location(spec: ThreeGppSpec) -> tuple[str, str, str]:
    etsi_number = f"1{spec.archive_stem}"
    range_start = int(etsi_number) // 100 * 100
    number_range = f"{range_start:06d}_{range_start + 99:06d}"
    kind = spec.document_type.lower()
    base_url = f"{ETSI_DELIVER}/etsi_{kind}/{number_range}/{etsi_number}"
    return kind, etsi_number, base_url


def etsi_pdf_url(spec: ThreeGppSpec, version: tuple[int, int, int]) -> str:
    """The ETSI PDF URL for `version`, derived without listing anything.

    Assumes the `_60` edition, which every catalogued TS has today. The
    fallback for when the deliver directory cannot be listed;
    `etsi_listed_pdf_url` is the one to call.
    """
    major, minor, patch = version
    kind, etsi_number, base_url = etsi_pdf_location(spec)
    version_directory = f"{major:02d}.{minor:02d}.{patch:02d}_60"
    filename = f"{kind}_{etsi_number}v{major:02d}{minor:02d}{patch:02d}p.pdf"
    return f"{base_url}/{version_directory}/{filename}"


def discover_etsi_editions(spec: ThreeGppSpec) -> dict[tuple[int, int, int], str]:
    """Every version ETSI has published for `spec`, with its directory's URL.

    A version directory carries an edition suffix (`18.07.00_60`) that the
    version does not determine, so it is read off the deliver listing rather
    than assumed. Where one version has several editions the highest is
    taken, as the latest publication of it.
    """
    _, _, base_url = etsi_pdf_location(spec)
    page = request_bytes(f"{base_url}/").decode("utf-8", errors="replace")
    editions: dict[tuple[int, int, int], int] = {}
    for *parts, edition in re.findall(
        r"([0-9]{2})\.([0-9]{2})\.([0-9]{2})_([0-9]{2})/", page
    ):
        major, minor, patch = (int(part) for part in parts)
        version = (major, minor, patch)
        editions[version] = max(editions.get(version, 0), int(edition))
    return {
        version: f"{base_url}/{'.'.join(f'{part:02d}' for part in version)}"
        f"_{edition:02d}/"
        for version, edition in editions.items()
    }


def etsi_listed_pdf_url(
    spec: ThreeGppSpec,
    version: tuple[int, int, int],
    editions: dict[tuple[int, int, int], str] | None,
) -> str:
    """The ETSI PDF URL for `version`: the PDF its edition directory lists.

    `editions` is `discover_etsi_editions`'s answer, None when the listing was
    unreachable. A version it lacks gets `etsi_pdf_url`'s derivation; an
    edition directory that cannot be listed, or lists no PDF of this version,
    gets the derived file name inside it.
    """
    if editions is None or version not in editions:
        return etsi_pdf_url(spec, version)
    directory = editions[version]
    kind, etsi_number, _ = etsi_pdf_location(spec)
    major, minor, patch = version
    stem = f"{kind}_{etsi_number}v{major:02d}{minor:02d}{patch:02d}"
    try:
        page = request_bytes(directory).decode("utf-8", errors="replace")
    except DownloadError:
        page = ""
    hrefs = re.findall(
        rf"""href=["']([^"']*{re.escape(stem)}[0-9a-z]*\.pdf)["']""",
        html.unescape(page),
        re.IGNORECASE,
    )
    if hrefs:
        return urllib.parse.urljoin(directory, min(hrefs))
    return f"{directory}{stem}p.pdf"


def url_name(url: str) -> str:
    return Path(urllib.parse.urlparse(url).path).name


def etsi_cache_path(output: Path, url: str) -> Path:
    """Where the ETSI PDF at `url` is cached: under its edition directory
    (`etsi/18.07.00_60/ts_129272v180700p.pdf`). The file name alone repeats
    across editions, so a cache keyed by it would serve the `_60` bytes once
    `_61` is the edition the manifest records."""
    path = PurePosixPath(urllib.parse.urlparse(url).path)
    return output / CACHE / "etsi" / path.parent.name / path.name


def download_3gpp(
    spec: ThreeGppSpec,
    archived: dict[tuple[int, int, int], str],
    release: int,
    output: Path,
    tree: Path,
    extract: bool,
    pdfs: bool,
    version: tuple[int, int, int] | None = None,
    link_archive: bool = False,
    convert: bool = True,
) -> DownloadRecord:
    """Fetch one specification into the cache under `output`, staged in `tree`.

    `archived` is the specification's `discover_3gpp_archive_urls` listing.
    Without `version` the newest archived version is taken, or with `pdfs`
    the newest whose ETSI PDF is published; with it, exactly that one. The
    record's paths are relative to `tree`. Its archive path names the cache
    entry, which is where it is once `tree` is published into `output`;
    `link_archive` puts a link to it in `tree` instead, for a tree published
    anywhere else. Without `convert`, a legacy `.doc` is extracted but not
    converted, and the record's `conversions` is empty rather than None.
    """
    identifier = f"{spec.document_type} {spec.number}"
    if not archived:
        raise DownloadError(f"no Release {release} version of {identifier} is archived")
    if version is not None:
        if version not in archived:
            listed = ", ".join(version_string(v) for v in sorted(archived))
            raise DownloadError(
                f"{identifier} {version_string(version)} is not archived;"
                f" Release {release} has {listed}"
            )
        selected = version
    else:
        selected = max(archived)
    newer_source_version = None
    editions = None
    if pdfs:
        # Degrade to the newest-version-plus-fallback-PDF path rather than
        # fail: the listing being unreachable is the situation the fallback
        # below already handles, with its own error message.
        with contextlib.suppress(DownloadError):
            editions = discover_etsi_editions(spec)
        # Page attachment needs the exact-version ETSI PDF, so when the newest
        # archive version's rendering is not published yet, prefer the highest
        # version whose PDF exists over the newest version with a mismatched
        # fallback PDF. Only when no version of this release has a PDF at all
        # does the newest archive plus a fallback rendering remain the answer.
        # An explicit `version` is never walked back: it was asked for.
        if version is None and editions is not None and selected not in editions:
            matched = max((v for v in archived if v in editions), default=None)
            if matched is not None:
                newer_source_version = version_string(selected)
                selected = matched
    url = archived[selected]
    relative_archive = Path(CACHE) / f"3gpp-rel-{release}" / url_name(url)
    archive = output / relative_archive
    atomic_download(url, archive, validate=validate_zip)
    if link_archive:
        link_file(archive, tree / relative_archive)
    files = [str(relative_archive)]
    conversions = None
    if extract:
        spec_dir = (
            tree / "3gpp" / f"Rel-{release}" / f"{spec.document_type}_{spec.number}"
        )
        # `tree` is staged afresh, so a plain extraction leaves no previous
        # version's files behind; sorted, so the manifest lists them stably.
        extracted = sorted(safe_extract(archive, spec_dir))
        files.extend(relative_paths(extracted, tree))
        if not legacy_documents(extracted):
            conversions = None
        elif convert:
            conversions = convert_legacy_documents(
                identifier, extracted, spec_dir, tree
            )
        else:
            conversions = []
    pdf_url = None
    pdf_sha256 = None
    pdf_size = None
    source_version = version_string(selected)
    pdf_version = None
    if pdfs:
        exact_pdf_url = etsi_listed_pdf_url(spec, selected, editions)
        cached = etsi_cache_path(output, exact_pdf_url)
        try:
            atomic_download(exact_pdf_url, cached, validate=validate_pdf)
            pdf_url = exact_pdf_url
            pdf_version = source_version
        except DownloadError as exact_error:
            if editions is None:
                editions = discover_etsi_editions(spec)
            fallback_versions = sorted(
                (v for v in editions if v[0] == selected[0] and v < selected),
                reverse=True,
            )
            if not fallback_versions:
                raise DownloadError(
                    f"no Release {release} ETSI PDF is published for"
                    f" {identifier} (source {source_version}): {exact_error}"
                ) from exact_error
            fallback_version = fallback_versions[0]
            pdf_url = etsi_listed_pdf_url(spec, fallback_version, editions)
            cached = etsi_cache_path(output, pdf_url)
            atomic_download(pdf_url, cached, validate=validate_pdf)
            pdf_version = version_string(fallback_version)
        pdf = tree / "3gpp" / f"Rel-{release}" / "PDF" / cached.name
        link_file(cached, pdf)
        files.append(str(pdf.relative_to(tree)))
        pdf_sha256 = sha256_file(pdf)
        pdf_size = pdf.stat().st_size
    return DownloadRecord(
        family="3GPP",
        identifier=identifier,
        title=spec.title,
        url=url,
        sha256=sha256_file(archive),
        size=archive.stat().st_size,
        files=files,
        reason=spec.reason,
        pdf_url=pdf_url,
        pdf_sha256=pdf_sha256,
        pdf_size=pdf_size,
        source_version=source_version,
        pdf_version=pdf_version,
        newer_source_version=newer_source_version,
        conversions=conversions,
    )


def download_pinned(
    pin: PinnedThreeGppSpec,
    archived: dict[tuple[int, int, int], str],
    output: Path,
    tree: Path,
    extract: bool,
    pdfs: bool,
    convert: bool = True,
) -> DownloadRecord:
    """Fetch a pinned version into its release's tree, as `download_3gpp`
    fetches an asked-for `version`: never walked back, its PDF the exact
    rendering when published. `archived` is `check_final`'s answer."""
    record = download_3gpp(
        pin.spec,
        archived,
        pin.release,
        output,
        tree,
        extract,
        pdfs,
        version=parse_version(pin.version),
        convert=convert,
    )
    record.final = pin.final
    return record


def check_onem2m_archive(spec: OneM2MSpec, path: Path) -> str:
    """Validate a oneM2M zip and return the name of its clean `.doc`.

    The zip holds `TS-0004-Service_Layer_Core_Protocol-V2_35_0(cl).doc`, its
    revision-marked `(rm)` twin and macOS `__MACOSX/` metadata; the `(cl)`
    file at the top level is the document. Its version must be the one
    catalogued: the endpoint serves the latest revision, and one that moved
    on is a decision to make in `specs.toml`, not a silent upgrade.
    """
    validate_zip(path)
    with zipfile.ZipFile(path) as zipped:
        names = zipped.namelist()
    pattern = re.compile(
        rf"TS-{re.escape(spec.number)}-[^/]*-(?P<version>V\d+_\d+_\d+)\(cl\)\.doc"
    )
    found = [(name, match) for name in names if (match := pattern.fullmatch(name))]
    if len(found) != 1:
        raise DownloadError(
            f"{path} holds {len(found)} clean TS-{spec.number} documents"
            f" ('(cl).doc' at its top level), not one: {', '.join(names)}"
        )
    ((name, match),) = found
    if match["version"] != spec.file_version:
        raise DownloadError(
            f"{spec.identifier}: oneM2M now serves {name}, but the catalog pins"
            f" {spec.version} ({spec.file_version}); a newer revision is a"
            " version to adopt in specs.toml, not one to take silently"
        )
    return name


def download_onem2m(
    spec: OneM2MSpec,
    output: Path,
    tree: Path,
    extract: bool,
    convert: bool = True,
) -> DownloadRecord:
    """Fetch one pinned oneM2M specification into the cache, staged in `tree`.

    Cached by the version-bearing name (`archives/onem2m/TS-0004-V2_35_0.zip`),
    so once fetched the pinned version is read from disk even after oneM2M
    publishes the next. Only the clean `(cl)` document is extracted, to
    `onem2m/Release-2/TS-0004/`, and converted like a 3GPP legacy `.doc`;
    without `convert` its `conversions` is empty, as there.
    """

    def validate(path: Path) -> None:
        check_onem2m_archive(spec, path)

    url = ONEM2M_DOWNLOAD_URL.format(document_id=spec.document_id)
    relative_archive = (
        Path(CACHE) / "onem2m" / f"TS-{spec.number}-{spec.file_version}.zip"
    )
    archive = output / relative_archive
    atomic_download(url, archive, validate=validate)
    files = [str(relative_archive)]
    conversions = None
    if extract:
        member = check_onem2m_archive(spec, archive)
        spec_dir = tree / "onem2m" / f"Release-{spec.release}" / f"TS-{spec.number}"
        document = spec_dir / member
        try:
            spec_dir.mkdir(parents=True, exist_ok=True)
            with (
                zipfile.ZipFile(archive) as zipped,
                zipped.open(member) as source,
                document.open("wb") as target,
            ):
                shutil.copyfileobj(source, target)
        except (OSError, zipfile.BadZipFile) as error:
            raise DownloadError(
                f"cannot extract {member} from {archive}: {error}"
            ) from error
        files.append(str(document.relative_to(tree)))
        conversions = (
            convert_legacy_documents(spec.identifier, [document], spec_dir, tree)
            if convert
            else []
        )
    return DownloadRecord(
        family="oneM2M",
        identifier=spec.identifier,
        title=spec.title,
        url=url,
        sha256=sha256_file(archive),
        size=archive.stat().st_size,
        files=files,
        reason=spec.reason,
        source_version=spec.version,
        conversions=conversions,
    )


def download_rfc(spec: RfcSpec, output: Path, tree: Path) -> DownloadRecord:
    url = RFC_TEXT_URL.format(number=spec.number)
    relative = Path("rfc") / f"rfc{spec.number}.txt"
    cached = output / CACHE / relative
    atomic_download(url, cached, validate=validate_rfc_text)
    link_file(cached, tree / relative)
    return DownloadRecord(
        family="IETF",
        identifier=f"RFC {spec.number}",
        title=spec.title,
        url=url,
        sha256=sha256_file(cached),
        size=cached.stat().st_size,
        files=[str(relative)],
    )


def validate_wireshark_file(path: Path) -> None:
    """The dictionary files are XML documents and XML entity fragments; an
    entity fragment has no prolog, so well-formedness cannot be required.
    What every one of them has is markup."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DownloadError(f"{path.name} is not readable text: {error}") from error
    if "<" not in text:
        raise DownloadError(f"{path.name} contains no markup")


def download_wireshark(
    dictionary: WiresharkDictionary, output: Path, tree: Path
) -> DownloadRecord:
    """Fetch every file of the pinned dictionary directory.

    One record for the whole directory: the files only mean anything
    together (dictionary.xml includes the vendor files as XML entities), so
    the manifest treats them as one artifact whose hash is the hash of the
    per-file hashes in name order. The cache keeps one directory per tag, and
    the published `wireshark/` holds the pinned tag's files and no other's.
    """
    tree_url = WIRESHARK_TREE_URL.format(
        path=urllib.parse.quote(dictionary.path, safe=""), tag=dictionary.tag
    )
    try:
        entries = json.loads(request_bytes(tree_url).decode("utf-8"))
        names = sorted(
            entry["name"] for entry in entries if entry.get("type") == "blob"
        )
    except (ValueError, KeyError, TypeError) as error:
        raise DownloadError(
            f"cannot read the Wireshark dictionary listing: {error}"
        ) from error
    if not names:
        raise DownloadError(
            f"the Wireshark dictionary listing at {dictionary.tag} is empty"
        )
    files = []
    digest = hashlib.sha256()
    total = 0
    for name in names:
        url = WIRESHARK_RAW_URL.format(
            tag=dictionary.tag, path=dictionary.path, name=name
        )
        cached = output / CACHE / "wireshark" / dictionary.tag / name
        atomic_download(url, cached, validate=validate_wireshark_file)
        destination = tree / "wireshark" / name
        link_file(cached, destination)
        digest.update(f"{name}\n{sha256_file(destination)}\n".encode())
        total += destination.stat().st_size
        files.append(destination)
    return DownloadRecord(
        family="Wireshark",
        identifier=f"Wireshark {dictionary.tag}",
        title="Wireshark Diameter dictionary",
        url=tree_url,
        sha256=digest.hexdigest(),
        size=total,
        files=relative_paths(files, tree),
        reason="Independent oracle for extracted codes, vendor-ids and types.",
    )


def describe(record: DownloadRecord) -> str:
    """The progress line for one finished download."""
    note = ""
    if (
        record.source_version is not None
        and record.pdf_version is not None
        and record.source_version != record.pdf_version
    ):
        note = (
            f" (PDF {record.pdf_version}; source {record.source_version}, "
            "ETSI publication lag)"
        )
    elif record.newer_source_version is not None:
        note = (
            f" (source {record.source_version}; newer"
            f" {record.newer_source_version} skipped, its ETSI PDF is"
            " unpublished)"
        )
    elif record.source_version is not None:
        note = f" {record.source_version}"
    for conversion in record.conversions or ():
        note += (
            f" (converted {PurePosixPath(conversion.source).name}"
            f" with {conversion.converter})"
        )
    if record.conversions == []:
        note += " (legacy .doc not converted)"
    if record.final == "document":
        note += " (pinned: the final version, none later archived)"
    elif record.final == "release":
        note += " (pinned: its release's last, none later archived in it)"
    return f"Downloaded {record.identifier}{note}"


def write_manifest(
    tree: Path, release: int, pdfs: bool, records: list[DownloadRecord]
) -> Path:
    """Write `tree`'s manifest.json. `tree` is staged, so no temporary file:
    a half-written manifest is never published."""
    # A pinned version shares its identifier with the catalog's release of
    # the same document; the version keeps the order stable.
    records = sorted(
        records,
        key=lambda item: (
            item.family,
            item.identifier,
            parse_version(item.source_version)
            if item.family == "3GPP" and item.source_version
            else (),
        ),
    )
    manifest = {
        "3gpp_release": release,
        "generated_at_epoch": int(time.time()),
        "include_pdfs": pdfs,
        "artifact_count": len(records),
        "artifacts": [asdict(record) for record in records],
    }
    path = tree / MANIFEST
    try:
        with path.open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except OSError as error:
        raise DownloadError(f"cannot write {path}: {error}") from error
    return path


def refuse_failed_swap(destination: Path) -> None:
    """Refuse a `destination` whose `.previous/` a failed `publish` left.

    Checked before downloading too, so the refusal does not come only after
    the whole catalog has been fetched.
    """
    if (destination / PREVIOUS).exists():
        raise DownloadError(
            f"{destination / PREVIOUS} holds the tree a failed swap could not"
            f" restore; move its entries back into {destination} or delete it"
        )


@contextlib.contextmanager
def staged(directory: Path) -> Iterator[Path]:
    """A fresh staging directory, removed afterwards whatever happened.

    One left by an interrupted run was never published, so nothing reads it.
    """
    staging = directory / STAGING
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
    except OSError as error:
        raise DownloadError(f"cannot create {staging}: {error}") from error
    try:
        yield staging
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def download_corpus(
    output: Path,
    release: int = 18,
    workers: int = 6,
    extract: bool = True,
    pdfs: bool = False,
    catalog: Catalog | None = None,
    report: Callable[[str], None] = lambda message: None,
    convert: bool = True,
) -> Path:
    """Download the catalog into `output` and publish it with `manifest.json`.

    Every entry is staged in `output/.staging/`, and the staged tree replaces
    the published one only once every entry succeeded: a run that fails
    anywhere leaves the previous tree and the manifest describing it exactly
    as they were, rather than a mix of old and new specifications. Returns
    the manifest path. Progress goes to `report`, so the caller decides what
    printing means; anything that stops the download raises `DownloadError`.
    `convert=False` leaves legacy `.doc` archives unconverted, so LibreOffice
    is not needed; see `download_3gpp`.
    """
    if workers < 1:
        raise DownloadError("workers must be at least 1")
    release_marker(release)

    catalog = catalog if catalog is not None else load_catalog()
    tgpp_specs, rfc_specs, wireshark, onem2m_specs = catalog[:4]
    pinned_specs = catalog.pinned
    try:
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DownloadError(f"cannot create the corpus directory: {error}") from error
    refuse_failed_swap(output)
    with (
        staged(output) as tree,
        concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor,
    ):
        report(f"Resolving 3GPP Release {release} artifacts...")
        # Discovery is inside the boundary too: one archive listing per
        # specification, all of them before any download starts, so a
        # release missing several catalogued specifications names them all.
        listings = [
            executor.submit(discover_3gpp_archive_urls, spec, release)
            for spec in tgpp_specs
        ]
        # A pinned version's listing covers every release, for its `final`.
        pinned_listings = [
            executor.submit(discover_3gpp_archive_urls, pin.spec, None)
            for pin in pinned_specs
        ]
        archived = {
            spec.number: listing.result()
            for spec, listing in zip(tgpp_specs, listings, strict=True)
        }
        missing = [number for number, versions in archived.items() if not versions]
        if missing:
            raise DownloadError(
                f"No Release {release} artifact found for: {', '.join(missing)}. "
                "The release may not contain every catalogued specification."
            )

        pinned_archived = [
            check_final(pin, listing.result())
            for pin, listing in zip(pinned_specs, pinned_listings, strict=True)
        ]

        jobs = [
            executor.submit(
                download_3gpp,
                spec,
                archived[spec.number],
                release,
                output,
                tree,
                extract,
                pdfs,
                convert=convert,
            )
            for spec in tgpp_specs
        ]
        jobs.extend(
            executor.submit(
                download_pinned, pin, archived, output, tree, extract, pdfs, convert
            )
            for pin, archived in zip(pinned_specs, pinned_archived, strict=True)
        )
        jobs.extend(
            executor.submit(download_rfc, spec, output, tree) for spec in rfc_specs
        )
        jobs.extend(
            executor.submit(download_onem2m, spec, output, tree, extract, convert)
            for spec in onem2m_specs
        )
        jobs.append(executor.submit(download_wireshark, wireshark, output, tree))

        records: list[DownloadRecord] = []
        for future in concurrent.futures.as_completed(jobs):
            try:
                record = future.result()
            except Exception as error:
                for job in jobs:
                    job.cancel()
                raise DownloadError(str(error)) from error
            records.append(record)
            report(describe(record))
        write_manifest(tree, release, pdfs, records)
        publish(tree, output, PUBLISHED)
    manifest_path = output / MANIFEST
    report(f"Wrote {len(records)} artifacts and {manifest_path}")
    return manifest_path


def download_version(
    reference: str,
    version: str,
    output: Path,
    extract: bool = True,
    pdfs: bool = True,
    catalog: Catalog | None = None,
    report: Callable[[str], None] = lambda message: None,
    convert: bool = True,
) -> Path:
    """Fetch one catalogued 3GPP specification at `version` into `output/versions/`.

    For diffing against what the corpus holds: the tree is
    `versions/<SpecRef>/<version>/` (`versions/TS29.272/18.6.0/`), shaped
    like the published one and with a one-record `manifest.json` of its own,
    so `seanchai regenerate --manifest` reads it the way it reads the corpus.
    The release is the version's major. The archive comes from the cache
    when an earlier run fetched it; nothing else under `output` changes.
    Returns the manifest path.
    """
    catalog = catalog if catalog is not None else load_catalog()
    # A pinned document's other versions are fetched the same way: TS
    # 29.140, which the catalog's release lacks, at 6.4.0 for a diff.
    tgpp_specs = catalog.tgpp + tuple(pin.spec for pin in catalog.pinned)
    wanted = reference.replace(" ", "").upper()
    spec = next(
        (
            item
            for item in tgpp_specs
            if wanted in (item.number, f"{item.document_type}{item.number}")
        ),
        None,
    )
    if spec is None:
        raise DownloadError(
            f"{reference} is not a catalogued 3GPP specification"
            " (`seanchai download --list` shows the catalog)"
        )
    selected = parse_version(version)
    release = selected[0]
    release_marker(release)
    try:
        output = output.resolve()
        parent = output / VERSIONS / f"{spec.document_type}{spec.number}"
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DownloadError(f"cannot create the versions directory: {error}") from error
    refuse_failed_swap(parent)
    name = version_string(selected)
    with staged(parent) as staging:
        tree = staging / name
        report(f"Resolving {spec.document_type} {spec.number} {name}...")
        record = download_3gpp(
            spec,
            discover_3gpp_archive_urls(spec, release),
            release,
            output,
            tree,
            extract,
            pdfs,
            version=selected,
            link_archive=True,
            convert=convert,
        )
        report(describe(record))
        write_manifest(tree, release, pdfs, [record])
        publish(staging, parent, [name])
    manifest_path = parent / name / MANIFEST
    report(f"Wrote {manifest_path}")
    return manifest_path
