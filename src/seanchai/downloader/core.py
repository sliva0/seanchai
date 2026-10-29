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
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import docx
import pypdf

THREE_GPP_INDEX = "https://www.3gpp.org/ftp/Specs/latest/Rel-{release}/{series}_series/"
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
USER_AGENT = "diameter-spec-corpus-downloader/1.0"
# LibreOffice, for the archives that still ship a legacy binary `.doc` (TS
# 32.299, TR 29.909 and seven more): the extractor reads only `.docx`.
SOFFICE = "soffice"
SOFFICE_TIMEOUT = 600


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


CATALOG_PATH = Path(__file__).resolve().parent / "specs.toml"


class DownloadError(RuntimeError):
    """Anything that stops the corpus being fetched as asked."""


def load_catalog(
    path: Path | None = None,
) -> tuple[tuple[ThreeGppSpec, ...], tuple[RfcSpec, ...], WiresharkDictionary]:
    """Read the curated specification catalog from specs.toml.

    Called on demand rather than at import: reading a file as a side effect of
    importing makes the module hard to use from anything but the CLI.
    """
    path = path or CATALOG_PATH
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        tgpp = tuple(ThreeGppSpec(**entry) for entry in data["tgpp"])
        rfc = tuple(RfcSpec(**entry) for entry in data["rfc"])
        wireshark = WiresharkDictionary(**data["wireshark"])
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise DownloadError(
            f"cannot read the specification catalog {path}:"
            f" {type(error).__name__}: {error}"
        ) from error
    return tgpp, rfc, wireshark


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
    # The `.docx` conversions of a legacy `.doc` archive; None when the
    # archive was not extracted or holds a `.docx` of its own.
    conversions: list[Conversion] | None = None


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


def discover_3gpp_urls(
    release: int, specs: tuple[ThreeGppSpec, ...] | None = None
) -> dict[str, str]:
    marker = release_marker(release)
    specs = load_catalog()[0] if specs is None else specs
    by_number: dict[str, str] = {}
    for series in sorted({spec.series for spec in specs}):
        index_url = THREE_GPP_INDEX.format(release=release, series=series)
        page = request_bytes(index_url).decode("utf-8", errors="replace")
        for spec in (item for item in specs if item.series == series):
            # The first filename character after '-' encodes the 3GPP release.
            pattern = re.compile(
                rf"""href=["']([^"']*/?{re.escape(spec.archive_stem)}-"""
                rf"""{re.escape(marker)}[0-9a-z]{{2}}\.zip)["']""",
                re.IGNORECASE,
            )
            matches = pattern.findall(html.unescape(page))
            if not matches:
                continue
            # The highest version, decoded from the file name — not the last
            # link on the page. An index that lists 18.5.0 after 18.6.0 is a
            # presentation detail; picking by it silently downloads the older
            # specification.
            href = max(matches, key=decode_3gpp_version)
            by_number[spec.number] = urllib.parse.urljoin(index_url, href)
    return by_number


def discover_3gpp_archive_urls(
    spec: ThreeGppSpec, release: int
) -> dict[tuple[int, int, int], str]:
    """Every archived version of `spec` in `release`, from `Specs/archive/`.

    The `Specs/latest/Rel-N/` index lists exactly one zip per specification,
    so choosing any version other than the newest needs the archive, which
    keeps them all.
    """
    marker = release_marker(release)
    index_url = THREE_GPP_ARCHIVE.format(series=spec.series, number=spec.number)
    page = request_bytes(index_url).decode("utf-8", errors="replace")
    pattern = re.compile(
        rf"""href=["']([^"']*/?{re.escape(spec.archive_stem)}-"""
        rf"""{re.escape(marker)}[0-9a-z]{{2}}\.zip)["']""",
        re.IGNORECASE,
    )
    return {
        decode_3gpp_version(href): urllib.parse.urljoin(index_url, href)
        for href in pattern.findall(html.unescape(page))
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


def replace_extracted(archive: Path, destination: Path) -> list[Path]:
    """Extract `archive` so that `destination` holds its contents and nothing else.

    Extracting in place would leave the previous version's files behind
    whenever a specification renames or drops one, and a directory holding two
    versions at once is a corpus that silently extracts the wrong document.
    The new contents are staged in a sibling directory and swapped in, so an
    interrupted run leaves either the old version or the new one. Deleting the
    old directory before the swap would break that promise for the one failure
    it exists to survive — a failed install would leave no version at all — so
    the old directory is renamed aside first and moved back if the swap fails.
    """
    staging = destination.parent / f".{destination.name}.staging"
    backup = destination.parent / f".{destination.name}.previous"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    try:
        safe_extract(archive, staging)
        replaced = destination.exists()
        if replaced:
            destination.replace(backup)
        try:
            staging.replace(destination)
        except OSError as error:
            if replaced:
                # Best effort: the rollback can only fail for the same reason
                # the install did, and the original error is the one worth
                # reporting. The backup directory is left behind either way.
                with contextlib.suppress(OSError):
                    backup.replace(destination)
            raise DownloadError(
                f"cannot install {archive} into {destination}: {error}"
            ) from error
    except OSError as error:
        raise DownloadError(
            f"cannot install {archive} into {destination}: {error}"
        ) from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if destination.exists():
            # Only once the new version is in place: a surviving backup is the
            # old corpus, and deleting it after a failed install is the whole
            # thing this function promises not to do.
            shutil.rmtree(backup, ignore_errors=True)
    return sorted(path for path in destination.rglob("*") if path.is_file())


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
    failed download rather than a skipped one: skipping would publish a
    manifest without the document, which `regenerate` reports only later and
    as "not in manifest".
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
            f" (`{SOFFICE}`), which is not installed or not on PATH: {error}"
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


def convert_legacy_documents(
    identifier: str, extracted: list[Path], spec_dir: Path, output: Path
) -> list[Conversion]:
    """Convert an archive's legacy `.doc` files to `.docx` with LibreOffice.

    Only an archive with no `.docx` of its own is converted. The results go
    to `converted/` beside the extracted tree (`converted/3gpp/Rel-18/
    TS_32.299/32299-i00.docx`), not into it, because `replace_extracted`
    promises that directory holds the archive's contents and nothing else.
    They are rebuilt on every run, like the extraction they derive from, and
    the manifest is the only way `regenerate` finds them: a run that fails
    here writes no manifest, so a half-converted directory is never read.
    """
    legacy = [path for path in extracted if path.suffix == ".doc"]
    if not legacy or any(path.suffix == ".docx" for path in extracted):
        return []
    converter = run_soffice(identifier, ["--version"]).strip()
    if not converter:
        raise DownloadError(f"{identifier}: `{SOFFICE} --version` printed nothing")
    destination = output / "converted" / spec_dir.relative_to(output)
    staging = destination.parent / f".{destination.name}.staging"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    conversions = []
    try:
        # A private profile per run: with the user's own, a LibreOffice that
        # is already open receives the request and the headless process
        # exits without converting anything; concurrent conversions would
        # also contend for the one profile's lock.
        with tempfile.TemporaryDirectory(prefix="soffice-profile-") as profile:
            for document in legacy:
                relative = document.relative_to(spec_dir)
                outdir = staging / relative.parent
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
                            destination.relative_to(output)
                            / relative.with_suffix(".docx")
                        ),
                        source=str(document.relative_to(output)),
                        source_sha256=sha256_file(document),
                        converter=converter,
                        command=[SOFFICE, *arguments],
                        sha256=sha256_file(converted),
                        size=converted.stat().st_size,
                    )
                )
        # Not swapped with a rollback as `replace_extracted` is: nothing reads
        # this directory except through the manifest, and a failure from here
        # on fails the run, which then writes none.
        shutil.rmtree(destination, ignore_errors=True)
        staging.replace(destination)
    except OSError as error:
        raise DownloadError(
            f"{identifier}: cannot convert its legacy .doc: {error}"
        ) from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
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


def etsi_pdf_location(spec: ThreeGppSpec) -> tuple[str, str, str]:
    etsi_number = f"1{spec.archive_stem}"
    range_start = int(etsi_number) // 100 * 100
    number_range = f"{range_start:06d}_{range_start + 99:06d}"
    kind = spec.document_type.lower()
    base_url = f"{ETSI_DELIVER}/etsi_{kind}/{number_range}/{etsi_number}"
    return kind, etsi_number, base_url


def etsi_pdf_url(spec: ThreeGppSpec, version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    kind, etsi_number, base_url = etsi_pdf_location(spec)
    version_directory = f"{major:02d}.{minor:02d}.{patch:02d}_60"
    filename = f"{kind}_{etsi_number}v{major:02d}{minor:02d}{patch:02d}p.pdf"
    return f"{base_url}/{version_directory}/{filename}"


def discover_etsi_pdf_versions(
    spec: ThreeGppSpec, source_version: tuple[int, int, int]
) -> list[tuple[int, int, int]]:
    _, _, base_url = etsi_pdf_location(spec)
    page = request_bytes(f"{base_url}/").decode("utf-8", errors="replace")
    versions: set[tuple[int, int, int]] = {
        (int(major), int(minor), int(patch))
        for major, minor, patch in re.findall(
            r"([0-9]{2})\.([0-9]{2})\.([0-9]{2})_60/?", page
        )
    }
    return sorted(
        (
            version
            for version in versions
            if version[0] == source_version[0] and version <= source_version
        ),
        reverse=True,
    )


def download_3gpp(
    spec: ThreeGppSpec,
    url: str,
    release: int,
    output: Path,
    extract: bool,
    pdfs: bool,
) -> DownloadRecord:
    source_version_tuple = decode_3gpp_version(url)
    newer_source_version = None
    if pdfs:
        # Page attachment needs the exact-version ETSI PDF, so when the newest
        # archive version's rendering is not published yet, prefer the highest
        # version whose PDF exists over the newest version with a mismatched
        # fallback PDF. Only when no version of this release has a PDF at all
        # does the newest archive plus a fallback rendering remain the answer.
        # Degrade to the newest-version-plus-fallback-PDF path rather than
        # fail: either listing being unreachable is the situation the existing
        # fallback already handles, with its own error message.
        try:
            published = set(discover_etsi_pdf_versions(spec, source_version_tuple))
            if source_version_tuple not in published:
                archived = discover_3gpp_archive_urls(spec, release)
                matched = max((v for v in archived if v in published), default=None)
                if matched is not None:
                    newer_source_version = version_string(source_version_tuple)
                    url = archived[matched]
                    source_version_tuple = matched
        except DownloadError:
            pass
    archive_name = Path(urllib.parse.urlparse(url).path).name
    archive = output / "archives" / f"3gpp-rel-{release}" / archive_name
    atomic_download(url, archive, validate=validate_zip)
    files = [archive]
    identifier = f"{spec.document_type} {spec.number}"
    conversions = None
    if extract:
        spec_dir = (
            output / "3gpp" / f"Rel-{release}" / f"{spec.document_type}_{spec.number}"
        )
        extracted = replace_extracted(archive, spec_dir)
        files.extend(extracted)
        conversions = (
            convert_legacy_documents(identifier, extracted, spec_dir, output) or None
        )
    pdf_url = None
    pdf_sha256 = None
    pdf_size = None
    source_version = version_string(source_version_tuple)
    pdf_version = None
    if pdfs:
        exact_pdf_url = etsi_pdf_url(spec, source_version_tuple)
        pdf = output / "3gpp" / f"Rel-{release}" / "PDF" / Path(exact_pdf_url).name
        try:
            atomic_download(exact_pdf_url, pdf, validate=validate_pdf)
            pdf_url = exact_pdf_url
            pdf_version = source_version
        except DownloadError as exact_error:
            fallback_versions = discover_etsi_pdf_versions(spec, source_version_tuple)
            fallback_versions = [
                version
                for version in fallback_versions
                if version != source_version_tuple
            ]
            if not fallback_versions:
                raise DownloadError(
                    f"no Release {release} ETSI PDF is published for"
                    f" {spec.document_type} {spec.number}"
                    f" (source {source_version}): {exact_error}"
                ) from exact_error
            fallback_version = fallback_versions[0]
            pdf_url = etsi_pdf_url(spec, fallback_version)
            pdf = output / "3gpp" / f"Rel-{release}" / "PDF" / Path(pdf_url).name
            atomic_download(pdf_url, pdf, validate=validate_pdf)
            pdf_version = version_string(fallback_version)
        files.append(pdf)
        pdf_sha256 = sha256_file(pdf)
        pdf_size = pdf.stat().st_size
    return DownloadRecord(
        family="3GPP",
        identifier=identifier,
        title=spec.title,
        url=url,
        sha256=sha256_file(archive),
        size=archive.stat().st_size,
        files=relative_paths(files, output),
        reason=spec.reason,
        pdf_url=pdf_url,
        pdf_sha256=pdf_sha256,
        pdf_size=pdf_size,
        source_version=source_version,
        pdf_version=pdf_version,
        newer_source_version=newer_source_version,
        conversions=conversions,
    )


def download_rfc(spec: RfcSpec, output: Path) -> DownloadRecord:
    url = RFC_TEXT_URL.format(number=spec.number)
    destination = output / "rfc" / f"rfc{spec.number}.txt"
    atomic_download(url, destination, validate=validate_rfc_text)
    return DownloadRecord(
        family="IETF",
        identifier=f"RFC {spec.number}",
        title=spec.title,
        url=url,
        sha256=sha256_file(destination),
        size=destination.stat().st_size,
        files=relative_paths([destination], output),
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


def download_wireshark(dictionary: WiresharkDictionary, output: Path) -> DownloadRecord:
    """Fetch every file of the pinned dictionary directory.

    One record for the whole directory: the files only mean anything
    together (dictionary.xml includes the vendor files as XML entities), so
    the manifest treats them as one artifact whose hash is the hash of the
    per-file hashes in name order.
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
        destination = output / "wireshark" / name
        atomic_download(url, destination, validate=validate_wireshark_file)
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
        files=relative_paths(files, output),
        reason="Independent oracle for extracted codes, vendor-ids and types.",
    )


def download_corpus(
    output: Path,
    release: int = 18,
    workers: int = 6,
    extract: bool = True,
    pdfs: bool = False,
    catalog: tuple[tuple[ThreeGppSpec, ...], tuple[RfcSpec, ...], WiresharkDictionary]
    | None = None,
    report: Callable[[str], None] = lambda message: None,
) -> Path:
    """Download the catalog into `output` and write `manifest.json`.

    Returns the manifest path. Progress goes to `report`, so the caller
    decides what printing means; anything that stops the download raises
    `DownloadError`.
    """
    if workers < 1:
        raise DownloadError("workers must be at least 1")
    release_marker(release)

    tgpp_specs, rfc_specs, wireshark = (
        catalog if catalog is not None else load_catalog()
    )
    try:
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        # A run that fails partway leaves some artifacts replaced and others
        # not, so the previous manifest now describes a corpus that no longer
        # exists — and it is the file everything downstream reads to find out
        # what is here. Removing it first makes a failed run look like what it
        # is rather than like the state it interrupted.
        (output / "manifest.json").unlink(missing_ok=True)
    except OSError as error:
        raise DownloadError(f"cannot create the corpus directory: {error}") from error
    report(f"Resolving 3GPP Release {release} artifacts...")
    # Discovery is inside the boundary too: it runs before the worker pool, so
    # nothing else would translate a failure here.
    urls = discover_3gpp_urls(release, tgpp_specs)
    missing = [spec.number for spec in tgpp_specs if spec.number not in urls]
    if missing:
        raise DownloadError(
            f"No Release {release} artifact found for: {', '.join(missing)}. "
            "The release may not contain every catalogued specification."
        )

    jobs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for spec in tgpp_specs:
            jobs.append(
                executor.submit(
                    download_3gpp,
                    spec,
                    urls[spec.number],
                    release,
                    output,
                    extract,
                    pdfs,
                )
            )
        for spec in rfc_specs:
            jobs.append(executor.submit(download_rfc, spec, output))
        jobs.append(executor.submit(download_wireshark, wireshark, output))

        records: list[DownloadRecord] = []
        for future in concurrent.futures.as_completed(jobs):
            try:
                record = future.result()
            except Exception as error:
                for job in jobs:
                    job.cancel()
                raise DownloadError(str(error)) from error
            records.append(record)
            version_note = ""
            if (
                record.source_version is not None
                and record.pdf_version is not None
                and record.source_version != record.pdf_version
            ):
                version_note = (
                    f" (PDF {record.pdf_version}; source {record.source_version}, "
                    "ETSI publication lag)"
                )
            elif record.newer_source_version is not None:
                version_note = (
                    f" (source {record.source_version}; newer"
                    f" {record.newer_source_version} skipped, its ETSI PDF is"
                    " unpublished)"
                )
            for conversion in record.conversions or ():
                version_note += (
                    f" (converted {PurePosixPath(conversion.source).name}"
                    f" with {conversion.converter})"
                )
            report(f"Downloaded {record.identifier}{version_note}")

    records.sort(key=lambda item: (item.family, item.identifier))
    manifest = {
        "3gpp_release": release,
        "generated_at_epoch": int(time.time()),
        "include_pdfs": pdfs,
        "artifact_count": len(records),
        "artifacts": [asdict(record) for record in records],
    }
    manifest_path = output / "manifest.json"  # `output` is resolved by now
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output,
            prefix="manifest",
            suffix=".part",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")
        try:
            os.replace(temporary, manifest_path)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as error:
        raise DownloadError(f"cannot write {manifest_path}: {error}") from error
    report(f"Wrote {len(records)} artifacts and {manifest_path}")
    return manifest_path
