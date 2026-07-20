#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Download the 3GPP and IETF Diameter specification corpus.

3GPP publishes the latest version belonging to each release as a ZIP file.
Those ZIPs normally contain the editable DOC or DOCX specification source.
RFCs are downloaded as canonical plain text from the RFC Editor. Official
3GPP/ETSI PDF renditions can also be downloaded with ``--pdfs``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


THREE_GPP_INDEX = "https://www.3gpp.org/ftp/Specs/latest/Rel-{release}/{series}_series/"
ETSI_DELIVER = "https://www.etsi.org/deliver"
RFC_TEXT_URL = "https://www.rfc-editor.org/rfc/rfc{number}.txt"
USER_AGENT = "diameter-spec-corpus-downloader/1.0"


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


# This is deliberately broader than a title search. Several protocols (for
# example SLg, EPS AAA, ProSe, V2X, and MB2) are Diameter applications without
# saying "Diameter" in their specification titles.
THREE_GPP_SPECS = (
    ThreeGppSpec(
        "29.061",
        "PLMN interworking with packet data networks",
        "Defines Diameter NASREQ/accounting command formats and 3GPP AVPs for Gi/SGi.",
    ),
    ThreeGppSpec("29.109", "GAA; Zh and Zn interfaces based on Diameter"),
    ThreeGppSpec("29.128", "MME/SGSN interfaces to packet data networks and applications"),
    ThreeGppSpec("29.172", "EPC LCS Protocol (ELP) over the SLg interface"),
    ThreeGppSpec("29.173", "Diameter-based SLh interface for Control Plane LCS"),
    ThreeGppSpec(
        "29.201",
        "REST reference point between AF and Protocol Converter",
        "Defines mappings between Diameter AVP base formats and XML/REST representations.",
    ),
    ThreeGppSpec("29.212", "Policy and Charging Control (PCC) reference points"),
    ThreeGppSpec(
        "29.213",
        "PCC signalling flows and QoS parameter mapping",
        "Companion PCC specification containing Diameter AVP usage and parameter mappings.",
    ),
    ThreeGppSpec("29.214", "Policy and charging control over Rx"),
    ThreeGppSpec("29.215", "Policy and Charging Control over S9"),
    ThreeGppSpec("29.217", "PCC congestion reporting over Np"),
    ThreeGppSpec("29.219", "PCC spending-limit reporting over Sy"),
    ThreeGppSpec(
        "29.228",
        "Cx/Dx signalling flows and message contents",
        "Defines application-level AVP presence rules that override the protocol ABNF.",
    ),
    ThreeGppSpec("29.229", "Cx and Dx interfaces based on Diameter"),
    ThreeGppSpec(
        "29.230",
        "Diameter applications; 3GPP-specific codes and identifiers",
        "Registry of 3GPP Diameter application IDs, command codes, and AVP codes.",
    ),
    ThreeGppSpec("29.272", "EPS MME/SGSN interfaces based on Diameter"),
    ThreeGppSpec("29.273", "EPS 3GPP AAA interfaces"),
    ThreeGppSpec("29.283", "Diameter data-management applications"),
    ThreeGppSpec(
        "29.305",
        "Interworking between MAP- and Diameter-based interfaces",
        "Contains mappings between MAP parameters and Diameter AVPs.",
    ),
    ThreeGppSpec(
        "29.328",
        "Sh signalling flows and message contents",
        "Companion Sh specification containing Diameter message and AVP content rules.",
    ),
    ThreeGppSpec("29.329", "Sh interface based on Diameter"),
    ThreeGppSpec("29.330", "IMS Sc interface based on Diameter"),
    ThreeGppSpec("29.336", "HSS Diameter interfaces for packet data networks/applications"),
    ThreeGppSpec("29.337", "Diameter-based T4 interface"),
    ThreeGppSpec("29.338", "Diameter protocols supporting SMS-capable MMEs"),
    ThreeGppSpec("29.343", "ProSe function to ProSe application server over PC2"),
    ThreeGppSpec("29.344", "ProSe function to HSS aspects"),
    ThreeGppSpec("29.345", "Inter-ProSe function signalling"),
    ThreeGppSpec("29.368", "Tsp interface between MTC-IWF and SCS"),
    ThreeGppSpec("29.388", "V2X Control Function to HSS aspects (V4)"),
    ThreeGppSpec("29.389", "Inter-V2X Control Function signalling (V6)"),
    ThreeGppSpec("29.468", "GCSE_LTE MB2 reference point"),
    ThreeGppSpec(
        "29.909",
        "Diameter-based protocol usage and recommendations in 3GPP",
        "Cross-specification guidance for 3GPP Diameter applications.",
        "TR",
    ),
    ThreeGppSpec("32.299", "Diameter charging applications"),
)


# Diameter-titled RFCs plus RFCs referenced by IANA's Diameter AVP registries
# whose titles do not contain the word "Diameter". Obsoleted RFCs are retained:
# they are useful input when extracting historical ABNF and AVP definitions.
RFC_SPECS = (
    RfcSpec(3588, "Diameter Base Protocol (obsoleted by RFC 6733)"),
    RfcSpec(3589, "Diameter command codes for 3GPP Release 5"),
    RfcSpec(4004, "Diameter Mobile IPv4 Application"),
    RfcSpec(4005, "Diameter NAS Application (obsoleted by RFC 7155)"),
    RfcSpec(4006, "Diameter Credit-Control Application (obsoleted by RFC 8506)"),
    RfcSpec(4072, "Diameter EAP Application"),
    RfcSpec(4740, "Diameter SIP Application"),
    RfcSpec(4849, "RADIUS Filter Rule Attribute (includes Diameter NAS-Filter-Rule)"),
    RfcSpec(5224, "Diameter Policy Processing Application"),
    RfcSpec(5431, "Diameter ITU-T Rw Policy Enforcement Interface Application"),
    RfcSpec(5447, "Diameter Mobile IPv6 NAS-to-server interaction"),
    RfcSpec(5516, "Diameter command-code registration for 3GPP EPS"),
    RfcSpec(5580, "Carrying Location Objects in RADIUS and Diameter"),
    RfcSpec(5624, "QoS parameters for use with Diameter"),
    RfcSpec(5719, "Updated IANA considerations for Diameter command codes"),
    RfcSpec(5729, "Diameter request routing by username and realm"),
    RfcSpec(5777, "Traffic classification and QoS attributes for Diameter"),
    RfcSpec(5778, "Diameter Mobile IPv6 home-agent interaction"),
    RfcSpec(5779, "Diameter Proxy Mobile IPv6 MAG/LMA interaction"),
    RfcSpec(5866, "Diameter QoS Application"),
    RfcSpec(6159, "Session-specific explicit Diameter request routing"),
    RfcSpec(6408, "Diameter S-NAPTR usage"),
    RfcSpec(6572, "RADIUS support for PMIPv6 (includes Diameter AVP mapping)"),
    RfcSpec(6733, "Diameter Base Protocol"),
    RfcSpec(6734, "Diameter AVPs for cryptographic-key transport"),
    RfcSpec(6735, "Diameter priority AVPs"),
    RfcSpec(6736, "Diameter NAT Control Application"),
    RfcSpec(6737, "Diameter Capabilities Update Application"),
    RfcSpec(6738, "Diameter IKEv2 shared-key application"),
    RfcSpec(6942, "Diameter support for EAP Re-authentication Protocol"),
    RfcSpec(7068, "Diameter overload-control requirements"),
    RfcSpec(7075, "Realm-based redirection in Diameter"),
    RfcSpec(7155, "Diameter NAS Application"),
    RfcSpec(7156, "Diameter support for PMIPv6 localized routing"),
    RfcSpec(7423, "Diameter application design guidelines"),
    RfcSpec(7660, "Diameter congestion and filter attributes"),
    RfcSpec(7678, "AVPs for IPv4-over-IPv6 transition provisioning"),
    RfcSpec(7683, "Diameter overload indication conveyance"),
    RfcSpec(7944, "Diameter routing-message priority"),
    RfcSpec(7966, "AVP-level security scenarios and requirements"),
    RfcSpec(8506, "Diameter Credit-Control Application"),
    RfcSpec(8581, "Diameter agent and peer overload reports"),
    RfcSpec(8582, "Diameter overload rate control"),
    RfcSpec(8583, "Diameter load-information conveyance"),
    RfcSpec(9390, "Diameter group signaling"),
)


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


def release_marker(release: int) -> str:
    """Return the first version-code character used in 3GPP ZIP names."""
    if 4 <= release <= 9:
        return str(release)
    if 10 <= release <= 35:
        return chr(ord("a") + release - 10)
    raise ValueError("3GPP release must be between 4 and 35")


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
                raise RuntimeError(f"failed to fetch {url}: HTTP {error.code}") from error
            if attempt + 1 == retries:
                raise RuntimeError(f"failed to fetch {url}: {error}") from error
            time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt + 1 == retries:
                raise RuntimeError(f"failed to fetch {url}: {error}") from error
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def discover_3gpp_urls(release: int) -> dict[str, str]:
    marker = release_marker(release)
    by_number: dict[str, str] = {}
    for series in sorted({spec.series for spec in THREE_GPP_SPECS}):
        index_url = THREE_GPP_INDEX.format(release=release, series=series)
        page = request_bytes(index_url).decode("utf-8", errors="replace")
        for spec in (item for item in THREE_GPP_SPECS if item.series == series):
            # The first filename character after '-' encodes the 3GPP release.
            pattern = re.compile(
                rf'''href=["']([^"']*/?{re.escape(spec.archive_stem)}-'''
                rf'''{re.escape(marker)}[0-9a-z]{{2}}\.zip)["']''',
                re.IGNORECASE,
            )
            matches = pattern.findall(html.unescape(page))
            if not matches:
                continue
            href = matches[-1]
            by_number[spec.number] = urllib.parse.urljoin(index_url, href)
    return by_number


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_download(url: str, destination: Path, expected_prefix: bytes | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size:
        if expected_prefix is None:
            return
        with destination.open("rb") as stream:
            if stream.read(len(expected_prefix)) == expected_prefix:
                return
    data = request_bytes(url)
    if expected_prefix is not None and not data.startswith(expected_prefix):
        raise RuntimeError(f"downloaded content from {url} is not the expected file type")
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=destination.parent, prefix=destination.name, suffix=".part", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def safe_extract(archive: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(f"unsafe ZIP member in {archive}: {member.filename}")
            target = destination.joinpath(*member_path.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    return extracted


def relative_paths(paths: Iterable[Path], root: Path) -> list[str]:
    return [str(path.relative_to(root)) for path in paths]


def decode_3gpp_version(archive_url: str) -> tuple[int, int, int]:
    name = Path(urllib.parse.urlparse(archive_url).path).name
    match = re.search(r"-([0-9a-z]{3})\.zip$", name, re.IGNORECASE)
    if not match:
        raise RuntimeError(f"cannot determine 3GPP version from {archive_url}")
    return tuple(int(character, 36) for character in match.group(1).lower())


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
    versions = {
        tuple(int(part) for part in match)
        for match in re.findall(r"([0-9]{2})\.([0-9]{2})\.([0-9]{2})_60/?", page)
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
    archive_name = Path(urllib.parse.urlparse(url).path).name
    archive = output / "archives" / f"3gpp-rel-{release}" / archive_name
    atomic_download(url, archive)
    files = [archive]
    if extract:
        spec_dir = output / "3gpp" / f"Rel-{release}" / f"{spec.document_type}_{spec.number}"
        files.extend(safe_extract(archive, spec_dir))
    pdf_url = None
    pdf_sha256 = None
    pdf_size = None
    source_version_tuple = decode_3gpp_version(url)
    source_version = version_string(source_version_tuple)
    pdf_version = None
    if pdfs:
        exact_pdf_url = etsi_pdf_url(spec, source_version_tuple)
        pdf = output / "3gpp" / f"Rel-{release}" / "PDF" / Path(exact_pdf_url).name
        try:
            atomic_download(exact_pdf_url, pdf, expected_prefix=b"%PDF-")
            pdf_url = exact_pdf_url
            pdf_version = source_version
        except RuntimeError as exact_error:
            fallback_versions = discover_etsi_pdf_versions(spec, source_version_tuple)
            fallback_versions = [
                version for version in fallback_versions if version != source_version_tuple
            ]
            if not fallback_versions:
                raise RuntimeError(
                    f"no Release {release} ETSI PDF is published for {spec.document_type} "
                    f"{spec.number} (source {source_version}): {exact_error}"
                ) from exact_error
            fallback_version = fallback_versions[0]
            pdf_url = etsi_pdf_url(spec, fallback_version)
            pdf = output / "3gpp" / f"Rel-{release}" / "PDF" / Path(pdf_url).name
            atomic_download(pdf_url, pdf, expected_prefix=b"%PDF-")
            pdf_version = version_string(fallback_version)
        files.append(pdf)
        pdf_sha256 = sha256_file(pdf)
        pdf_size = pdf.stat().st_size
    return DownloadRecord(
        family="3GPP",
        identifier=f"{spec.document_type} {spec.number}",
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
    )


def download_rfc(spec: RfcSpec, output: Path) -> DownloadRecord:
    url = RFC_TEXT_URL.format(number=spec.number)
    destination = output / "rfc" / f"rfc{spec.number}.txt"
    atomic_download(url, destination)
    return DownloadRecord(
        family="IETF",
        identifier=f"RFC {spec.number}",
        title=spec.title,
        url=url,
        sha256=sha256_file(destination),
        size=destination.stat().st_size,
        files=relative_paths([destination], output),
    )


def print_catalog() -> None:
    print(f"3GPP specifications ({len(THREE_GPP_SPECS)}):")
    for spec in THREE_GPP_SPECS:
        print(f"  {spec.document_type} {spec.number}: {spec.title}")
    print(f"\nRFCs ({len(RFC_SPECS)}):")
    for spec in RFC_SPECS:
        print(f"  RFC {spec.number}: {spec.title}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=int, default=18, help="3GPP release (default: 18)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("specifications"),
        help="corpus directory (default: specifications)",
    )
    parser.add_argument("--workers", type=int, default=6, help="parallel downloads (default: 6)")
    parser.add_argument(
        "--no-extract", action="store_true", help="keep 3GPP ZIPs without extracting DOC/DOCX files"
    )
    parser.add_argument(
        "--pdfs", action="store_true", help="also download official 3GPP/ETSI PDFs"
    )
    parser.add_argument("--list", action="store_true", help="print the curated catalog and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list:
        print_catalog()
        return 0
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    try:
        release_marker(args.release)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(f"Resolving 3GPP Release {args.release} artifacts...", flush=True)
    urls = discover_3gpp_urls(args.release)
    missing = [spec.number for spec in THREE_GPP_SPECS if spec.number not in urls]
    if missing:
        raise SystemExit(
            f"No Release {args.release} artifact found for: {', '.join(missing)}. "
            "The release may not contain every catalogued specification."
        )

    jobs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for spec in THREE_GPP_SPECS:
            jobs.append(
                executor.submit(
                    download_3gpp,
                    spec,
                    urls[spec.number],
                    args.release,
                    output,
                    not args.no_extract,
                    args.pdfs,
                )
            )
        for spec in RFC_SPECS:
            jobs.append(executor.submit(download_rfc, spec, output))

        records: list[DownloadRecord] = []
        for future in concurrent.futures.as_completed(jobs):
            try:
                record = future.result()
            except Exception as error:
                for job in jobs:
                    job.cancel()
                raise SystemExit(str(error)) from error
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
            print(f"Downloaded {record.identifier}{version_note}", flush=True)

    records.sort(key=lambda item: (item.family, item.identifier))
    manifest = {
        "3gpp_release": args.release,
        "generated_at_epoch": int(time.time()),
        "include_pdfs": args.pdfs,
        "artifact_count": len(records),
        "artifacts": [asdict(record) for record in records],
    }
    manifest_path = output / "manifest.json"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output, prefix="manifest", suffix=".part", delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    try:
        os.replace(temporary, manifest_path)
    finally:
        temporary.unlink(missing_ok=True)

    print(f"\nWrote {len(records)} artifacts and {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
