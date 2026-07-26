import io
import json
import zipfile

import pypdf
import pytest

# The implementation, not the package's public surface: these tests exercise
# the HTTP, cache and archive helpers behind `download_corpus`.
from seanchai.downloader import core as downloader


@pytest.mark.parametrize(
    ("release", "marker"),
    [(4, "4"), (9, "9"), (10, "a"), (18, "i"), (35, "z")],
)
def test_release_marker_uses_3gpp_base36_encoding(release, marker):
    assert downloader.release_marker(release) == marker


@pytest.mark.parametrize("release", [3, 36])
def test_release_marker_rejects_unsupported_releases(release):
    with pytest.raises(downloader.DownloadError, match="between 4 and 35"):
        downloader.release_marker(release)


def _zip_bytes(**members: bytes) -> bytes:
    """A real ZIP archive: the downloader opens what it fetches, so a fixture
    that only looks like an archive is no longer a usable stand-in."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        for name, content in members.items():
            zipped.writestr(name.replace("__", "/"), content)
    return buffer.getvalue()


def _pdf_bytes() -> bytes:
    """A real one-page PDF, for the same reason `_zip_bytes` builds a real ZIP."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


RFC_TEXT = b"Internet Engineering Task Force\nRequest for Comments: 9999\n\nBody.\n"


def test_catalog_loading_and_spec_derived_properties(tmp_path):
    catalog = tmp_path / "specs.toml"
    catalog.write_text(
        """
[[tgpp]]
number = "29.999"
title = "Test TS"
document_type = "TR"
reason = "For tests"

[[rfc]]
number = 9999
title = "Test RFC"
""".strip()
    )

    tgpp, rfcs = downloader.load_catalog(catalog)

    assert tgpp == (
        downloader.ThreeGppSpec(
            number="29.999",
            title="Test TS",
            document_type="TR",
            reason="For tests",
        ),
    )
    assert tgpp[0].series == 29
    assert tgpp[0].archive_stem == "29999"
    assert rfcs == (downloader.RfcSpec(number=9999, title="Test RFC"),)


def test_request_bytes_retries_transient_http_errors(local_http_server, monkeypatch):
    sleeps = []
    monkeypatch.setattr(downloader.time, "sleep", sleeps.append)
    url = local_http_server.route("/retry", (503, b"unavailable"), (200, b"response"))

    assert downloader.request_bytes(url) == b"response"
    assert local_http_server.counts["/retry"] == 2
    assert local_http_server.requests[0][1]["User-Agent"] == downloader.USER_AGENT
    assert sleeps == [1]


def test_request_bytes_does_not_retry_permanent_http_errors(local_http_server):
    url = local_http_server.route("/missing", (404, b"missing"))

    with pytest.raises(RuntimeError, match="HTTP 404"):
        downloader.request_bytes(url)

    assert local_http_server.counts["/missing"] == 1


def test_atomic_download_is_atomic_cached_and_validated(tmp_path, local_http_server):
    destination = tmp_path / "nested" / "archive.zip"
    url = local_http_server.route(
        "/archive.zip", _zip_bytes(spec=b"body"), b"truncated"
    )

    downloader.atomic_download(url, destination, validate=downloader.validate_zip)
    downloader.atomic_download(url, destination, validate=downloader.validate_zip)

    # A valid cached file is served from disk, so only one request so far.
    assert local_http_server.counts["/archive.zip"] == 1

    destination.write_bytes(b"invalid cache")

    with pytest.raises(downloader.DownloadError, match="not a readable ZIP"):
        downloader.atomic_download(url, destination, validate=downloader.validate_zip)

    # The nonempty-but-broken cache was re-fetched rather than trusted, and the
    # file that failed both checks is gone rather than left to be found again.
    assert local_http_server.counts["/archive.zip"] == 2
    assert not destination.exists()
    assert not list(destination.parent.glob("*.part"))


def test_atomic_download_keeps_a_valid_cached_file_when_the_server_is_down(
    tmp_path, local_http_server
):
    destination = tmp_path / "archive.zip"
    url = local_http_server.route("/archive.zip", _zip_bytes(spec=b"body"))
    downloader.atomic_download(url, destination, validate=downloader.validate_zip)
    before = destination.read_bytes()

    downloader.atomic_download(url, destination, validate=downloader.validate_zip)

    assert destination.read_bytes() == before


@pytest.mark.parametrize(
    ("validator", "content", "message"),
    [
        ("validate_zip", b"not an archive", "not a readable ZIP"),
        ("validate_pdf", b"%PDF-but truncated", "not a readable PDF"),
        ("validate_rfc_text", b"<html>404</html>", "does not look like an RFC"),
    ],
    ids=["zip", "pdf", "rfc"],
)
def test_artifact_validators_reject_plausible_looking_files(
    tmp_path, validator, content, message
):
    # Each of these is nonempty, and the PDF even carries the right prefix.
    path = tmp_path / "artifact"
    path.write_bytes(content)

    with pytest.raises(downloader.DownloadError, match=message):
        getattr(downloader, validator)(path)


def test_replace_extracted_removes_the_previous_versions_files(tmp_path):
    destination = tmp_path / "TS_29.999"
    destination.mkdir()
    (destination / "dropped-in-this-version.docx").write_bytes(b"old")
    archive = tmp_path / "new.zip"
    archive.write_bytes(_zip_bytes(spec_docx=b"new"))

    extracted = downloader.replace_extracted(archive, destination)

    assert extracted == [destination / "spec_docx"]
    assert not (destination / "dropped-in-this-version.docx").exists()
    assert not list(tmp_path.glob(".*staging"))


def test_safe_extract_returns_files_and_creates_directories(tmp_path):
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("nested/", b"")
        zipped.writestr("nested/spec.docx", b"document")

    extracted = downloader.safe_extract(archive, tmp_path / "output")

    assert extracted == [tmp_path / "output" / "nested" / "spec.docx"]
    assert extracted[0].read_bytes() == b"document"


@pytest.mark.parametrize("member", ["../escape", "/absolute"])
def test_safe_extract_rejects_path_traversal(tmp_path, member):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(member, b"bad")

    with pytest.raises(downloader.DownloadError, match="unsafe ZIP member"):
        downloader.safe_extract(archive, tmp_path / "output")


def test_discover_3gpp_urls_matches_release_and_resolves_relative_links(
    local_http_server, monkeypatch
):
    specs = (
        downloader.ThreeGppSpec("29.999", "First"),
        downloader.ThreeGppSpec("32.123", "Second"),
    )
    # The newest archive is listed *first*: selection is by decoded version,
    # not by where the index happens to put the link.
    local_http_server.route(
        "/Rel-18/29_series/",
        b'<a href="29999-i10.zip">new</a><a href="../files/29999-i00.zip">old</a>',
    )
    local_http_server.route(
        "/Rel-18/32_series/",
        b'<a href="/files/32123-h99.zip">wrong release</a>',
    )

    monkeypatch.setattr(
        downloader,
        "THREE_GPP_INDEX",
        f"{local_http_server.base_url}/Rel-{{release}}/{{series}}_series/",
    )

    urls = downloader.discover_3gpp_urls(18, specs)

    assert urls == {
        "29.999": (f"{local_http_server.base_url}/Rel-18/29_series/29999-i10.zip")
    }


@pytest.mark.parametrize(
    ("url", "version"),
    [
        ("https://example.test/29272-i00.zip", (18, 0, 0)),
        ("https://example.test/29272-i1a.zip", (18, 1, 10)),
    ],
)
def test_decodes_3gpp_archive_versions(url, version):
    assert downloader.decode_3gpp_version(url) == version
    assert downloader.version_string(version) == ".".join(map(str, version))


def test_decode_3gpp_version_rejects_unknown_names():
    with pytest.raises(downloader.DownloadError, match="cannot determine"):
        downloader.decode_3gpp_version("https://example.test/spec.zip")


def test_builds_etsi_pdf_location_and_url():
    spec = downloader.ThreeGppSpec("29.329", "Sh")

    assert downloader.etsi_pdf_location(spec) == (
        "ts",
        "129329",
        "https://www.etsi.org/deliver/etsi_ts/129300_129399/129329",
    )
    assert downloader.etsi_pdf_url(spec, (18, 1, 0)).endswith(
        "/18.01.00_60/ts_129329v180100p.pdf"
    )


def test_discovers_matching_etsi_versions_newest_first(local_http_server, monkeypatch):
    monkeypatch.setattr(downloader, "ETSI_DELIVER", local_http_server.base_url)
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/",
        (b"18.00.00_60/ 18.01.00_60/ 18.02.00_60/ 17.09.00_60/ 18.01.00_60/"),
    )

    versions = downloader.discover_etsi_pdf_versions(
        downloader.ThreeGppSpec("29.329", "Sh"), (18, 1, 5)
    )

    assert versions == [(18, 1, 0), (18, 0, 0)]


def test_download_rfc_records_hash_size_and_relative_path(
    tmp_path, local_http_server, monkeypatch
):
    monkeypatch.setattr(
        downloader,
        "RFC_TEXT_URL",
        f"{local_http_server.base_url}/rfc{{number}}.txt",
    )
    local_http_server.route("/rfc9999.txt", RFC_TEXT)

    record = downloader.download_rfc(downloader.RfcSpec(9999, "Test RFC"), tmp_path)

    assert record.identifier == "RFC 9999"
    assert record.files == ["rfc/rfc9999.txt"]
    assert record.size == len(RFC_TEXT)
    assert record.sha256 == downloader.sha256_file(tmp_path / record.files[0])


def test_download_3gpp_falls_back_to_latest_earlier_etsi_pdf(
    tmp_path, local_http_server, monkeypatch
):
    monkeypatch.setattr(downloader, "ETSI_DELIVER", local_http_server.base_url)
    archive_url = local_http_server.route("/29329-i10.zip", _zip_bytes(spec=b"body"))
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/18.01.00_60/ts_129329v180100p.pdf",
        (404, b"not published"),
    )
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/",
        b"18.01.00_60/ 18.00.00_60/",
    )
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/18.00.00_60/ts_129329v180000p.pdf",
        _pdf_bytes(),
    )

    record = downloader.download_3gpp(
        downloader.ThreeGppSpec("29.329", "Sh"),
        archive_url,
        release=18,
        output=tmp_path,
        extract=False,
        pdfs=True,
    )

    assert record.source_version == "18.1.0"
    assert record.pdf_version == "18.0.0"
    assert record.pdf_url is not None
    assert record.pdf_url.endswith("18.00.00_60/ts_129329v180000p.pdf")
    assert record.files == [
        "archives/3gpp-rel-18/29329-i10.zip",
        "3gpp/Rel-18/PDF/ts_129329v180000p.pdf",
    ]
    assert (
        local_http_server.counts[
            "/etsi_ts/129300_129399/129329/18.01.00_60/ts_129329v180100p.pdf"
        ]
        == 1
    )
    assert (
        local_http_server.counts[
            "/etsi_ts/129300_129399/129329/18.00.00_60/ts_129329v180000p.pdf"
        ]
        == 1
    )


def test_download_corpus_writes_a_sorted_manifest_end_to_end(
    tmp_path, local_http_server, monkeypatch
):
    tgpp = downloader.ThreeGppSpec("29.999", "Test TS")
    rfc = downloader.RfcSpec(9999, "Test RFC")
    output = tmp_path / "corpus"
    local_http_server.route(
        "/Rel-18/29_series/",
        b'<a href="29999-i00.zip">source</a>',
    )
    archive = _zip_bytes(spec=b"body")
    local_http_server.route("/Rel-18/29_series/29999-i00.zip", archive)
    local_http_server.route("/rfc9999.txt", RFC_TEXT)

    monkeypatch.setattr(
        downloader,
        "THREE_GPP_INDEX",
        f"{local_http_server.base_url}/Rel-{{release}}/{{series}}_series/",
    )
    monkeypatch.setattr(
        downloader,
        "RFC_TEXT_URL",
        f"{local_http_server.base_url}/rfc{{number}}.txt",
    )
    monkeypatch.setattr(downloader.time, "time", lambda: 1234.9)
    progress = []

    manifest_path = downloader.download_corpus(
        output,
        workers=2,
        extract=False,
        catalog=((tgpp,), (rfc,)),
        report=progress.append,
    )

    assert manifest_path == output / "manifest.json"
    assert any("Downloaded TS 29.999" in line for line in progress)

    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["3gpp_release"] == 18
    assert manifest["generated_at_epoch"] == 1234
    assert manifest["artifact_count"] == 2
    assert [artifact["identifier"] for artifact in manifest["artifacts"]] == [
        "TS 29.999",
        "RFC 9999",
    ]
    assert (
        output / "archives" / "3gpp-rel-18" / "29999-i00.zip"
    ).read_bytes() == archive
    assert (output / "rfc" / "rfc9999.txt").read_bytes() == RFC_TEXT
    assert not list(output.glob("*.part"))


def test_download_corpus_validates_its_arguments_before_downloading(tmp_path):
    with pytest.raises(downloader.DownloadError, match="workers must be at least 1"):
        downloader.download_corpus(tmp_path, workers=0)

    with pytest.raises(downloader.DownloadError, match="release must be between"):
        downloader.download_corpus(tmp_path, release=99)

    assert not list(tmp_path.iterdir())
