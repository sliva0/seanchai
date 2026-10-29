import io
import json
import os
import time
import zipfile
from pathlib import Path

import docx
import pypdf
import pytest

# The implementation, not the package's public surface: these tests exercise
# the HTTP, cache and archive helpers behind `download_corpus`.
from seanchai.downloader import core as downloader


@pytest.mark.parametrize(
    ("release", "marker"),
    [(4, "4"), (9, "9"), (10, "a"), (18, "i"), (35, "z"), (3, None), (36, None)],
)
def test_release_marker_uses_3gpp_base36_encoding(release, marker):
    if marker is None:
        with pytest.raises(downloader.DownloadError, match="between 4 and 35"):
            downloader.release_marker(release)
    else:
        assert downloader.release_marker(release) == marker


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

[wireshark]
tag = "v9.9.9"
path = "resources/protocols/diameter"
""".strip()
    )

    tgpp, rfcs, wireshark = downloader.load_catalog(catalog)

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
    assert wireshark == downloader.WiresharkDictionary(
        tag="v9.9.9", path="resources/protocols/diameter"
    )


@pytest.mark.parametrize("status", [503, 404], ids=["transient", "permanent"])
def test_request_bytes_retries_transient_http_errors(
    local_http_server, monkeypatch, status
):
    sleeps = []
    monkeypatch.setattr(downloader.time, "sleep", sleeps.append)
    url = local_http_server.route(
        "/retry", (status, b"unavailable"), (200, b"response")
    )
    if status == 404:
        with pytest.raises(RuntimeError, match="HTTP 404"):
            downloader.request_bytes(url)
    else:
        assert downloader.request_bytes(url) == b"response"
    assert local_http_server.counts["/retry"] == (1 if status == 404 else 2)
    assert local_http_server.requests[0][1]["User-Agent"] == downloader.USER_AGENT
    assert sleeps == ([] if status == 404 else [1])


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


@pytest.mark.parametrize("existing", [True, False], ids=["replace", "install"])
def test_replace_extracted_removes_the_previous_versions_files(tmp_path, existing):
    destination = tmp_path / "TS_29.999"
    if existing:
        destination.mkdir()
        (destination / "dropped-in-this-version.docx").write_bytes(b"old")
    archive = tmp_path / "new.zip"
    archive.write_bytes(_zip_bytes(spec_docx=b"new"))

    extracted = downloader.replace_extracted(archive, destination)

    assert extracted == [destination / "spec_docx"]
    assert not (destination / "dropped-in-this-version.docx").exists()
    assert not list(tmp_path.glob(".*staging"))
    assert not list(tmp_path.glob(".*previous"))


def _replace_failing_on(*suffixes):
    """`Path.replace` that fails for directories named by suffix, so one leg of
    the swap can be broken while the rollback still works."""
    original = Path.replace

    def replace(self, target):
        if self.name.endswith(suffixes):
            raise OSError("cross-device link")
        return original(self, target)

    return replace


def test_a_failed_install_leaves_the_previous_version_in_place(tmp_path, monkeypatch):
    # The docstring promises "either the old version or the new one". Removing
    # the old directory before the swap broke that for the one failure it
    # exists to survive: an install that fails after the delete left neither.
    destination = tmp_path / "TS_29.999"
    destination.mkdir()
    (destination / "spec_docx").write_bytes(b"old")
    archive = tmp_path / "new.zip"
    archive.write_bytes(_zip_bytes(spec_docx=b"new"))

    monkeypatch.setattr(Path, "replace", _replace_failing_on(".staging"))

    with pytest.raises(downloader.DownloadError, match="cannot install"):
        downloader.replace_extracted(archive, destination)

    assert (destination / "spec_docx").read_bytes() == b"old"
    assert not list(tmp_path.glob(".*staging"))


def test_a_failed_rollback_keeps_the_previous_version_beside_the_destination(
    tmp_path, monkeypatch
):
    # Nothing can be done about a rename that fails in both directions, but the
    # old corpus must still exist somewhere afterwards rather than be deleted.
    destination = tmp_path / "TS_29.999"
    destination.mkdir()
    (destination / "spec_docx").write_bytes(b"old")
    archive = tmp_path / "new.zip"
    archive.write_bytes(_zip_bytes(spec_docx=b"new"))

    monkeypatch.setattr(Path, "replace", _replace_failing_on(".staging", ".previous"))

    with pytest.raises(downloader.DownloadError, match="cannot install"):
        downloader.replace_extracted(archive, destination)

    backup = tmp_path / ".TS_29.999.previous"
    assert (backup / "spec_docx").read_bytes() == b"old"


def test_a_failed_extraction_leaves_the_previous_version_untouched(tmp_path):
    destination = tmp_path / "TS_29.999"
    destination.mkdir()
    (destination / "spec_docx").write_bytes(b"old")
    archive = tmp_path / "truncated.zip"
    archive.write_bytes(b"PK\x03\x04 not really a zip")

    with pytest.raises(downloader.DownloadError, match="cannot extract"):
        downloader.replace_extracted(archive, destination)

    assert (destination / "spec_docx").read_bytes() == b"old"
    assert not list(tmp_path.glob(".*staging"))
    assert not list(tmp_path.glob(".*previous"))


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
        ("https://example.test/spec.zip", None),
    ],
)
def test_decodes_3gpp_archive_versions(url, version):
    if version is None:
        with pytest.raises(downloader.DownloadError, match="cannot determine"):
            downloader.decode_3gpp_version(url)
    else:
        assert downloader.decode_3gpp_version(url) == version
        assert downloader.version_string(version) == ".".join(map(str, version))


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
        b"18.00.00_60/ 18.01.00_60/ 18.02.00_60/ 17.09.00_60/ 18.01.00_60/",
    )
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/18.00.00_60/ts_129329v180000p.pdf",
        _pdf_bytes(),
    )

    assert downloader.discover_etsi_pdf_versions(
        downloader.ThreeGppSpec("29.329", "Sh"), (18, 1, 5)
    ) == [(18, 1, 0), (18, 0, 0)]

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
    shark = downloader.WiresharkDictionary(tag="v9.9.9", path="protocols/diameter")
    output = tmp_path / "corpus"
    local_http_server.route(
        "/Rel-18/29_series/",
        b'<a href="29999-i00.zip">source</a>',
    )
    archive = _zip_bytes(spec=b"body")
    local_http_server.route("/Rel-18/29_series/29999-i00.zip", archive)
    local_http_server.route("/rfc9999.txt", RFC_TEXT)
    local_http_server.route(
        "/tree/protocols%2Fdiameter/v9.9.9",
        b'[{"name": "dictionary.xml", "type": "blob"}]',
    )
    local_http_server.route(
        "/raw/v9.9.9/protocols/diameter/dictionary.xml",
        b"<dictionary/>",
    )
    monkeypatch.setattr(
        downloader,
        "WIRESHARK_TREE_URL",
        f"{local_http_server.base_url}/tree/{{path}}/{{tag}}",
    )
    monkeypatch.setattr(
        downloader,
        "WIRESHARK_RAW_URL",
        f"{local_http_server.base_url}/raw/{{tag}}/{{path}}/{{name}}",
    )

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
        catalog=((tgpp,), (rfc,), shark),
        report=progress.append,
    )

    assert manifest_path == output / "manifest.json"
    assert any("Downloaded TS 29.999" in line for line in progress)

    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["3gpp_release"] == 18
    assert manifest["generated_at_epoch"] == 1234
    assert manifest["artifact_count"] == 3
    assert [artifact["identifier"] for artifact in manifest["artifacts"]] == [
        "TS 29.999",
        "RFC 9999",
        "Wireshark v9.9.9",
    ]
    assert (output / "wireshark" / "dictionary.xml").read_bytes() == b"<dictionary/>"
    assert (
        output / "archives" / "3gpp-rel-18" / "29999-i00.zip"
    ).read_bytes() == archive
    assert (output / "rfc" / "rfc9999.txt").read_bytes() == RFC_TEXT
    assert not list(output.glob("*.part"))


def test_a_failed_run_does_not_leave_the_previous_manifest_behind(
    tmp_path, local_http_server, monkeypatch
):
    # The manifest is what downstream reads to learn what the corpus holds. A
    # run that fails partway has already replaced some artifacts, so the old
    # manifest now describes something that is no longer on disk.
    output = tmp_path / "corpus"
    output.mkdir()
    (output / "manifest.json").write_text('{"artifact_count": 99}')
    local_http_server.route("/Rel-18/29_series/", b"<a>no artifacts here</a>")
    monkeypatch.setattr(
        downloader,
        "THREE_GPP_INDEX",
        f"{local_http_server.base_url}/Rel-{{release}}/{{series}}_series/",
    )

    with pytest.raises(downloader.DownloadError, match="No Release 18 artifact"):
        downloader.download_corpus(
            output,
            catalog=(
                (downloader.ThreeGppSpec("29.999", "Test TS"),),
                (),
                downloader.WiresharkDictionary(tag="v9.9.9", path="p"),
            ),
        )

    assert not (output / "manifest.json").exists()


def test_download_corpus_validates_its_arguments_before_downloading(tmp_path):
    with pytest.raises(downloader.DownloadError, match="workers must be at least 1"):
        downloader.download_corpus(tmp_path, workers=0)

    with pytest.raises(downloader.DownloadError, match="release must be between"):
        downloader.download_corpus(tmp_path, release=99)

    assert not list(tmp_path.iterdir())


def test_download_3gpp_prefers_the_highest_version_with_a_published_pdf(
    tmp_path, local_http_server, monkeypatch
):
    """Page attachment needs the exact-version ETSI PDF, so when the newest
    archive version's rendering is unpublished, the downloader walks back to
    the highest archived version whose PDF exists rather than pairing the
    newest source with a mismatched fallback PDF."""
    monkeypatch.setattr(downloader, "ETSI_DELIVER", local_http_server.base_url)
    monkeypatch.setattr(
        downloader,
        "THREE_GPP_ARCHIVE",
        f"{local_http_server.base_url}/archive/{{series}}_series/{{number}}/",
    )
    latest_url = local_http_server.route("/29388-i10.zip", _zip_bytes(spec=b"new"))
    # ETSI has published only the 18.0.0 rendering.
    local_http_server.route("/etsi_ts/129300_129399/129388/", b"18.00.00_60/")
    local_http_server.route(
        "/etsi_ts/129300_129399/129388/18.00.00_60/ts_129388v180000p.pdf",
        _pdf_bytes(),
    )
    local_http_server.route(
        "/archive/29_series/29.388/",
        b'<a href="29388-i10.zip">new</a><a href="29388-i00.zip">old</a>',
    )
    archive = _zip_bytes(spec=b"old")
    local_http_server.route("/archive/29_series/29.388/29388-i00.zip", archive)

    record = downloader.download_3gpp(
        downloader.ThreeGppSpec("29.388", "V2X"),
        latest_url,
        release=18,
        output=tmp_path,
        extract=False,
        pdfs=True,
    )

    assert record.source_version == "18.0.0"
    assert record.pdf_version == "18.0.0"
    assert record.newer_source_version == "18.1.0"
    assert record.url.endswith("/archive/29_series/29.388/29388-i00.zip")
    assert record.files == [
        "archives/3gpp-rel-18/29388-i00.zip",
        "3gpp/Rel-18/PDF/ts_129388v180000p.pdf",
    ]
    # The newest archive was never fetched.
    assert local_http_server.counts.get("/29388-i10.zip", 0) == 0


def _docx_bytes() -> bytes:
    """A real, empty `.docx`: the downloader opens a conversion with
    python-docx, so a ZIP that only names `word/document.xml` is rejected."""
    buffer = io.BytesIO()
    docx.Document().save(buffer)
    return buffer.getvalue()


def _fake_soffice(monkeypatch, *, returncode=0, package: bytes | None = None):
    """Stand in for LibreOffice: `--version` answers, a conversion writes
    `package` (a real `.docx` by default; nothing with a failing exit status)
    into `--outdir`. Returns the argument vectors it ran."""
    calls = []
    package = _docx_bytes() if package is None else package

    class Popen:
        pid = 0

        def __init__(self, command, **options):
            calls.append(command)
            self.returncode = returncode
            self.output = ("", "Error: source file could not be loaded\n")
            if command[1:] == ["--version"]:
                self.returncode = 0
                self.output = ("LibreOffice 9.9.9.9 0123abc\n", "")
            elif returncode == 0 and package:
                outdir = Path(command[command.index("--outdir") + 1])
                name = Path(command[-1]).with_suffix(".docx").name
                (outdir / name).write_bytes(package)

        def communicate(self, timeout=None):
            return self.output

    monkeypatch.setattr(downloader.subprocess, "Popen", Popen)
    return calls


def test_download_3gpp_converts_a_legacy_doc_archive(tmp_path, monkeypatch):
    calls = _fake_soffice(monkeypatch)
    url = "https://example.test/29999-i00.zip"
    archive = tmp_path / "archives" / "3gpp-rel-18" / "29999-i00.zip"
    archive.parent.mkdir(parents=True)
    # The Temp/Promotion/Upgraded/ nesting is real (TS 29.215, TR 29.909).
    archive.write_bytes(
        _zip_bytes(**{"Temp/Upgraded/29999-i00.doc": b"\xd0\xcf\x11\xe0"})
    )
    stale = tmp_path / "converted" / "3gpp" / "Rel-18" / "TS_29.999" / "old.docx"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"a previous version's conversion")
    spec = downloader.ThreeGppSpec("29.999", "Test TS")

    record = downloader.download_3gpp(
        spec, url, release=18, output=tmp_path, extract=True, pdfs=False
    )

    source = "3gpp/Rel-18/TS_29.999/Temp/Upgraded/29999-i00.doc"
    assert record.conversions is not None
    (conversion,) = record.conversions
    assert conversion.source == source
    assert conversion.file == (
        "converted/3gpp/Rel-18/TS_29.999/Temp/Upgraded/29999-i00.docx"
    )
    assert conversion.converter == "LibreOffice 9.9.9.9 0123abc"
    assert conversion.source_sha256 == downloader.sha256_file(tmp_path / source)
    assert conversion.sha256 == downloader.sha256_file(tmp_path / conversion.file)
    assert conversion.command[-3:] == ["--outdir", "{outdir}", "{source}"]
    # The derived file is not one of the archive's files, and the converted
    # tree holds this run's conversion and nothing else.
    assert conversion.file not in record.files
    assert not stale.exists()
    assert not list((tmp_path / "converted").rglob("*.staging"))
    # Each conversion runs in a private profile, never the user's own.
    (_, convert) = calls
    assert convert[1].startswith("-env:UserInstallation=file:///")
    assert convert[-1] == str(tmp_path / source)


def test_an_archive_with_its_own_docx_is_not_converted(tmp_path, monkeypatch):
    calls = _fake_soffice(monkeypatch)
    extracted = [tmp_path / "spec" / "29999-i00.docx", tmp_path / "spec" / "a.doc"]

    conversions = downloader.convert_legacy_documents(
        "TS 29.999", extracted, tmp_path / "spec", tmp_path
    )

    assert conversions == []
    assert calls == []


@pytest.mark.parametrize(
    ("soffice", "message"),
    [
        ("absent", r"TS 29\.999 ships a legacy \.doc; .*LibreOffice \(`.*soffice`\)"),
        ("failing", r"TS 29\.999: `.*` exited 1: Error: source file could not be"),
        ("silent", r"TS 29\.999: LibreOffice wrote no 29999-i00\.docx"),
        ("broken", r"29999-i00\.docx is not a readable \.docx"),
    ],
)
def test_a_failed_conversion_fails_the_run_without_a_manifest(
    tmp_path, local_http_server, monkeypatch, soffice, message
):
    if soffice == "absent":
        monkeypatch.setattr(downloader, "SOFFICE", str(tmp_path / "bin" / "soffice"))
    else:
        _fake_soffice(
            monkeypatch,
            returncode=1 if soffice == "failing" else 0,
            # Exit 0 and a ZIP naming the main part, which is not XML.
            package=(
                _zip_bytes(**{"word/document.xml": b"not XML"})
                if soffice == "broken"
                else b""
            ),
        )
    output = tmp_path / "corpus"
    output.mkdir()
    (output / "manifest.json").write_text('{"artifact_count": 99}')
    local_http_server.route("/Rel-18/29_series/", b'<a href="29999-i00.zip">s</a>')
    local_http_server.route(
        "/Rel-18/29_series/29999-i00.zip", _zip_bytes(**{"29999-i00.doc": b"word"})
    )
    local_http_server.route("/tree/p/v9.9.9", b'[{"name": "d.xml", "type": "blob"}]')
    local_http_server.route("/raw/v9.9.9/p/d.xml", b"<dictionary/>")
    base = local_http_server.base_url
    monkeypatch.setattr(
        downloader, "WIRESHARK_TREE_URL", f"{base}/tree/{{path}}/{{tag}}"
    )
    monkeypatch.setattr(
        downloader, "WIRESHARK_RAW_URL", f"{base}/raw/{{tag}}/{{path}}/{{name}}"
    )
    monkeypatch.setattr(
        downloader, "THREE_GPP_INDEX", f"{base}/Rel-{{release}}/{{series}}_series/"
    )

    with pytest.raises(downloader.DownloadError, match=message):
        downloader.download_corpus(
            output,
            catalog=(
                (downloader.ThreeGppSpec("29.999", "Test TS"),),
                (),
                downloader.WiresharkDictionary(tag="v9.9.9", path="p"),
            ),
        )

    assert not (output / "manifest.json").exists()
    assert not list((output / "converted").rglob("*.docx"))


def test_a_timed_out_conversion_kills_the_whole_process_group(tmp_path, monkeypatch):
    # `soffice` is a launcher whose `soffice.bin` child does the converting;
    # a shell that backgrounds a sleep stands in for the pair.
    pidfile = tmp_path / "child.pid"
    killed = []
    killpg = downloader.os.killpg

    def recording_killpg(group, sig):
        killed.append((group, sig))
        killpg(group, sig)

    monkeypatch.setattr(downloader.os, "killpg", recording_killpg)
    monkeypatch.setattr(downloader, "SOFFICE", "sh")
    monkeypatch.setattr(downloader, "SOFFICE_TIMEOUT", 0.5)

    with pytest.raises(downloader.DownloadError, match=r"timed out after 0\.5 s"):
        downloader.run_soffice(
            "TS 29.999", ["-c", f"sleep 30 >/dev/null 2>&1 & echo $! > {pidfile}; wait"]
        )

    assert [sig for _, sig in killed] == [downloader.signal.SIGKILL]
    child = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"the launcher's child {child} outlived the timeout")
