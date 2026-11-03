import hashlib
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


def _pdf_bytes(pages: int = 1) -> bytes:
    """A real PDF, for the same reason `_zip_bytes` builds a real ZIP."""
    writer = pypdf.PdfWriter()
    for _ in range(pages):
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

[[onem2m]]
number = "0004"
title = "Service Layer Core Protocol"
release = 2
version = "2.35.0"
document_id = 36771

[wireshark]
tag = "v9.9.9"
path = "resources/protocols/diameter"
""".strip()
    )

    tgpp, rfcs, wireshark, onem2m, pinned, transcribed = downloader.load_catalog(
        catalog
    )
    assert transcribed == ()

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
    (document,) = onem2m
    assert document.identifier == "oneM2M TS-0004"
    assert document.file_version == "V2_35_0"
    assert pinned == ()


def test_a_pinned_version_names_what_it_claims_to_be_final_in(tmp_path):
    catalog = tmp_path / "specs.toml"
    text = """
[[tgpp]]
number = "29.999"
title = "Test TS"

[[rfc]]
number = 9999
title = "Test RFC"

[[tgpp_pinned]]
number = "29.998"
title = "Ended TS"
version = "7.0.0"
final = "{final}"

[wireshark]
tag = "v9.9.9"
path = "resources/protocols/diameter"
"""
    catalog.write_text(text.format(final="document"))
    (pin,) = downloader.load_catalog(catalog).pinned
    assert (pin.release, pin.spec.archive_stem) == (7, "29998")

    catalog.write_text(text.format(final="yes"))
    with pytest.raises(downloader.DownloadError, match="final must be one of"):
        downloader.load_catalog(catalog)


def _listing(*versions: str) -> dict[tuple[int, int, int], str]:
    return {downloader.parse_version(v): f"https://example/{v}.zip" for v in versions}


def test_a_pinned_final_version_is_checked_against_every_release():
    """TS 29.140 ends at V7.0.0: the pin says so, and a version archived
    after it, in any release, fails the download instead of leaving a
    resolution resting on a claim the archive no longer supports."""
    pin = downloader.PinnedThreeGppSpec("29.140", "MM10", "7.0.0", "document")

    assert downloader.check_final(pin, _listing("6.4.0", "7.0.0")) == _listing("7.0.0")
    with pytest.raises(downloader.DownloadError, match=r"lists 8\.0\.0;"):
        downloader.check_final(pin, _listing("6.4.0", "7.0.0", "8.0.0"))
    with pytest.raises(downloader.DownloadError, match="not archived"):
        downloader.check_final(pin, _listing("6.4.0"))


def test_a_release_final_version_is_checked_against_its_release_only():
    pin = downloader.PinnedThreeGppSpec("29.214", "Rx", "7.12.0", "release")
    listing = _listing("7.11.0", "7.12.0", "8.0.0", "19.4.0")

    assert sorted(downloader.check_final(pin, listing)) == [(7, 11, 0), (7, 12, 0)]
    with pytest.raises(downloader.DownloadError, match="Release 7's final"):
        downloader.check_final(pin, {**listing, **_listing("7.13.0")})


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


def test_validate_pdf_reads_a_pdf_encrypted_for_its_owner(tmp_path):
    """ETSI's TS 129 234 V11.2.0 is AES-encrypted with an empty user password;
    without pypdf's crypto extra it read as unpublished, and the run fell back
    to V11.1.0's rendering."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("", "owner", algorithm="AES-256")
    path = tmp_path / "encrypted.pdf"
    with path.open("wb") as handle:
        writer.write(handle)

    downloader.validate_pdf(path)


def _tree(root: Path, label: bytes) -> None:
    """A published-looking tree whose every file says which run wrote it."""
    for name in ("3gpp/Rel-19/TS_29.999/spec.docx", "rfc/rfc9999.txt", "manifest.json"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(label)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_publish_swaps_the_whole_tree_and_drops_what_staging_lacks(tmp_path):
    destination = tmp_path / "specifications"
    _tree(destination, b"old")
    (destination / "converted" / "dropped.docx").parent.mkdir()
    (destination / "converted" / "dropped.docx").write_bytes(b"old")
    (destination / "archives" / "cache.zip").parent.mkdir()
    (destination / "archives" / "cache.zip").write_bytes(b"cache")
    staging = destination / ".staging"
    _tree(staging, b"new")

    downloader.publish(staging, destination, downloader.PUBLISHED)

    # The cache is not a published entry and stays; `converted/` was not
    # staged this time, so the tree no longer has it.
    assert _snapshot(destination) == {
        "3gpp/Rel-19/TS_29.999/spec.docx": b"new",
        "archives/cache.zip": b"cache",
        "manifest.json": b"new",
        "rfc/rfc9999.txt": b"new",
    }
    assert not (destination / ".previous").exists()


def _replace_failing_on(*suffixes):
    """`Path.replace` that fails for paths named by suffix, so one leg of
    the swap can be broken while the rollback still works."""
    original = Path.replace

    def replace(self, target):
        if str(self).endswith(suffixes):
            raise OSError("cross-device link")
        return original(self, target)

    return replace


def test_a_failed_swap_restores_the_previous_tree_and_manifest(tmp_path, monkeypatch):
    # `rfc` is put in before `3gpp` fails, so the rollback has both a placed
    # entry to take back out and set-aside entries to restore.
    destination = tmp_path / "specifications"
    _tree(destination, b"old")
    staging = destination / ".staging"
    _tree(staging, b"new")
    monkeypatch.setattr(Path, "replace", _replace_failing_on(".staging/3gpp"))

    with pytest.raises(downloader.DownloadError, match="cannot publish"):
        downloader.publish(staging, destination, ("3gpp", "rfc"))

    names = ["3gpp/Rel-19/TS_29.999/spec.docx", "manifest.json", "rfc/rfc9999.txt"]
    assert _snapshot(destination) == {name: b"old" for name in names} | {
        f".staging/{name}": b"new" for name in names
    }


def test_a_failed_rollback_keeps_the_previous_tree_and_blocks_the_next_publish(
    tmp_path, monkeypatch
):
    # Nothing can be done about a rename that fails in both directions, but
    # the old tree must still exist afterwards, and a later run must not
    # delete it as a leftover.
    destination = tmp_path / "specifications"
    _tree(destination, b"old")
    staging = destination / ".staging"
    _tree(staging, b"new")
    monkeypatch.setattr(
        Path, "replace", _replace_failing_on(".staging/3gpp", ".previous/manifest.json")
    )

    with pytest.raises(downloader.DownloadError, match="cannot publish"):
        downloader.publish(staging, destination, ("3gpp", "rfc"))

    assert (destination / ".previous" / "manifest.json").read_bytes() == b"old"
    monkeypatch.undo()
    with pytest.raises(downloader.DownloadError, match="failed swap could not"):
        downloader.publish(staging, destination, ("3gpp", "rfc"))
    assert (destination / ".previous" / "manifest.json").read_bytes() == b"old"


def test_a_directory_the_rollback_cannot_restore_keeps_the_manifest_out(
    tmp_path, monkeypatch
):
    # Every directory is in place when the manifest's rename fails; `rfc`
    # then cannot go back. The old manifest restored beside a tree missing
    # `rfc/` would describe files that are not there.
    destination = tmp_path / "specifications"
    _tree(destination, b"old")
    staging = destination / ".staging"
    _tree(staging, b"new")
    monkeypatch.setattr(
        Path,
        "replace",
        _replace_failing_on(".staging/manifest.json", ".previous/rfc"),
    )

    with pytest.raises(downloader.DownloadError) as raised:
        downloader.publish(staging, destination, ("3gpp", "rfc"))

    assert "could not restore rfc" in str(raised.value)
    assert "holds manifest.json, rfc" in str(raised.value)
    snapshot = _snapshot(destination)
    assert "manifest.json" not in snapshot
    assert snapshot["3gpp/Rel-19/TS_29.999/spec.docx"] == b"old"
    assert snapshot[".previous/manifest.json"] == b"old"
    assert snapshot[".previous/rfc/rfc9999.txt"] == b"old"
    monkeypatch.undo()
    with pytest.raises(downloader.DownloadError, match="failed swap could not"):
        downloader.publish(staging, destination, ("3gpp", "rfc"))


@pytest.mark.parametrize("member", ["../escape", "/absolute"])
def test_safe_extract_rejects_path_traversal(tmp_path, member):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(member, b"bad")

    with pytest.raises(downloader.DownloadError, match="unsafe ZIP member"):
        downloader.safe_extract(archive, tmp_path / "output")


def test_discover_3gpp_archive_urls_matches_release_and_resolves_relative_links(
    local_http_server, monkeypatch
):
    monkeypatch.setattr(
        downloader,
        "THREE_GPP_ARCHIVE",
        f"{local_http_server.base_url}/archive/{{series}}_series/{{number}}/",
    )
    # The newest archive is listed *first*, and the index holds other
    # releases too: selection is by decoded version, never by position.
    local_http_server.route(
        "/archive/29_series/29.999/",
        b'<a href="29999-j10.zip">new</a><a href="../files/29999-j00.zip">old</a>'
        b'<a href="/files/29999-h99.zip">wrong release</a>',
    )

    urls = downloader.discover_3gpp_archive_urls(
        downloader.ThreeGppSpec("29.999", "First"), 19
    )

    base = local_http_server.base_url
    assert urls == {
        (19, 1, 0): f"{base}/archive/29_series/29.999/29999-j10.zip",
        (19, 0, 0): f"{base}/archive/29_series/files/29999-j00.zip",
    }


@pytest.mark.parametrize(
    ("url", "version"),
    [
        ("https://example.test/29272-j00.zip", (19, 0, 0)),
        ("https://example.test/29272-j1a.zip", (19, 1, 10)),
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

    tree = tmp_path / ".staging"
    record = downloader.download_rfc(
        downloader.RfcSpec(9999, "Test RFC"), tmp_path, tree
    )

    assert record.identifier == "RFC 9999"
    assert record.files == ["rfc/rfc9999.txt"]
    assert record.size == len(RFC_TEXT)
    assert record.sha256 == downloader.sha256_file(tree / record.files[0])
    # The fetched file is cached, and the tree holds the same file.
    assert (tmp_path / "archives" / "rfc" / "rfc9999.txt").samefile(
        tree / "rfc" / "rfc9999.txt"
    )


def test_download_3gpp_falls_back_to_latest_earlier_etsi_pdf(
    tmp_path, local_http_server, monkeypatch
):
    base = local_http_server.base_url
    monkeypatch.setattr(downloader, "ETSI_DELIVER", base)
    archive_url = local_http_server.route("/29329-j10.zip", _zip_bytes(spec=b"body"))
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/19.01.00_60/ts_129329v190100p.pdf",
        (404, b"not published"),
    )
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/",
        b"19.00.00_60/ 19.01.00_60/ 19.02.00_60/ 17.09.00_60/ 19.01.00_60/",
    )
    local_http_server.route(
        "/etsi_ts/129300_129399/129329/19.00.00_60/ts_129329v190000p.pdf",
        _pdf_bytes(),
    )
    spec = downloader.ThreeGppSpec("29.329", "Sh")

    directory = f"{base}/etsi_ts/129300_129399/129329"
    assert downloader.discover_etsi_editions(spec) == {
        (17, 9, 0): f"{directory}/17.09.00_60/",
        (19, 0, 0): f"{directory}/19.00.00_60/",
        (19, 1, 0): f"{directory}/19.01.00_60/",
        (19, 2, 0): f"{directory}/19.02.00_60/",
    }

    record = downloader.download_3gpp(
        spec,
        {(19, 1, 0): archive_url},
        release=19,
        output=tmp_path,
        tree=tmp_path / ".staging",
        extract=False,
        pdfs=True,
    )

    assert record.source_version == "19.1.0"
    assert record.pdf_version == "19.0.0"
    assert record.pdf_url is not None
    assert record.pdf_url.endswith("19.00.00_60/ts_129329v190000p.pdf")
    assert record.files == [
        "archives/3gpp-rel-19/29329-j10.zip",
        "3gpp/Rel-19/PDF/ts_129329v190000p.pdf",
    ]
    assert (
        local_http_server.counts[
            "/etsi_ts/129300_129399/129329/19.01.00_60/ts_129329v190100p.pdf"
        ]
        == 1
    )
    assert (
        local_http_server.counts[
            "/etsi_ts/129300_129399/129329/19.00.00_60/ts_129329v190000p.pdf"
        ]
        == 1
    )


def test_the_etsi_link_is_the_pdf_its_edition_directory_lists(
    tmp_path, local_http_server, monkeypatch
):
    base = local_http_server.base_url
    monkeypatch.setattr(downloader, "ETSI_DELIVER", base)
    directory = "/etsi_ts/129200_129299/129272"
    # Shaped like the real listing: absolute upper-case HREFs, every
    # directory named twice. 19.7.0 has a second edition here, which the
    # `_60` derivation cannot reach.
    local_http_server.route(
        f"{directory}/",
        "".join(
            f'<A HREF="{directory}/{name}/">{name}</A><br>'
            for name in ("19.06.00_60", "19.07.00_60", "19.07.00_61")
        ).encode(),
    )
    listed = f"{directory}/19.07.00_61/ts_129272v190700p1.pdf"
    local_http_server.route(
        f"{directory}/19.07.00_61/",
        f'<A HREF="{directory}/">[To Parent Directory]</A><br>'
        f'<A HREF="{listed}">ts_129272v190700p1.pdf</A>'.encode(),
    )
    local_http_server.route(listed, _pdf_bytes())
    spec = downloader.ThreeGppSpec("29.272", "S6a")

    editions = downloader.discover_etsi_editions(spec)

    assert editions == {
        (19, 6, 0): f"{base}{directory}/19.06.00_60/",
        (19, 7, 0): f"{base}{directory}/19.07.00_61/",
    }
    assert downloader.etsi_listed_pdf_url(spec, (19, 7, 0), editions) == (
        f"{base}{listed}"
    )
    # An edition directory that cannot be listed: the derived file name in it.
    assert downloader.etsi_listed_pdf_url(spec, (19, 6, 0), editions) == (
        f"{base}{directory}/19.06.00_60/ts_129272v190600p.pdf"
    )
    # No deliver listing at all: the `_60` derivation.
    derived = f"{base}{directory}/19.07.00_60/ts_129272v190700p.pdf"
    assert downloader.etsi_listed_pdf_url(spec, (19, 7, 0), None) == derived
    assert downloader.etsi_pdf_url(spec, (19, 7, 0)) == derived

    archive_url = local_http_server.route("/29272-j70.zip", _zip_bytes(spec=b"body"))
    record = downloader.download_3gpp(
        spec,
        {(19, 7, 0): archive_url},
        release=19,
        output=tmp_path,
        tree=tmp_path / ".staging",
        extract=False,
        pdfs=True,
    )

    # The manifest's `pdf_url` is what `regenerate` writes as `; Link:`.
    assert record.pdf_url == f"{base}{listed}"
    assert record.pdf_version == "19.7.0"
    assert record.files[-1] == "3gpp/Rel-19/PDF/ts_129272v190700p1.pdf"


def test_a_new_edition_of_a_cached_pdf_is_fetched_not_served_from_the_cache(
    tmp_path, local_http_server, monkeypatch
):
    # ETSI names both editions' PDF the same; the `_60` bytes cached by an
    # earlier run must not be recorded under the `_61` URL.
    base = local_http_server.base_url
    monkeypatch.setattr(downloader, "ETSI_DELIVER", base)
    directory = "/etsi_ts/129200_129299/129272"
    name = "ts_129272v190700p.pdf"
    first, second = _pdf_bytes(), _pdf_bytes(pages=2)
    assert first != second
    for edition, body in (("19.07.00_60", first), ("19.07.00_61", second)):
        local_http_server.route(f"{directory}/{edition}/{name}", body)
    archive_url = local_http_server.route("/29272-j70.zip", _zip_bytes(spec=b"body"))
    spec = downloader.ThreeGppSpec("29.272", "S6a")

    def fetch(*editions):
        local_http_server.route(
            f"{directory}/", "".join(f"{e}/ " for e in editions).encode()
        )
        return downloader.download_3gpp(
            spec,
            {(19, 7, 0): archive_url},
            release=19,
            output=tmp_path,
            tree=tmp_path / ".staging" / editions[-1],
            extract=False,
            pdfs=True,
        )

    fetch("19.07.00_60")
    record = fetch("19.07.00_60", "19.07.00_61")

    assert record.pdf_url == f"{base}{directory}/19.07.00_61/{name}"
    assert record.pdf_sha256 == hashlib.sha256(second).hexdigest()
    assert local_http_server.counts[f"{directory}/19.07.00_61/{name}"] == 1
    assert (tmp_path / "archives" / "etsi" / "19.07.00_60" / name).read_bytes() == (
        first
    )


def _serve(local_http_server, monkeypatch) -> str:
    """Point every source the downloader reads at the local server, with an
    RFC and a one-file Wireshark dictionary routed. Returns the base URL."""
    base = local_http_server.base_url
    for name, value in {
        "THREE_GPP_ARCHIVE": f"{base}/archive/{{series}}_series/{{number}}/",
        "ETSI_DELIVER": base,
        "RFC_TEXT_URL": f"{base}/rfc{{number}}.txt",
        "WIRESHARK_TREE_URL": f"{base}/tree/{{path}}/{{tag}}",
        "WIRESHARK_RAW_URL": f"{base}/raw/{{tag}}/{{path}}/{{name}}",
    }.items():
        monkeypatch.setattr(downloader, name, value)
    local_http_server.route("/rfc9999.txt", RFC_TEXT)
    local_http_server.route(
        "/tree/protocols%2Fdiameter/v9.9.9",
        b'[{"name": "dictionary.xml", "type": "blob"}]',
    )
    local_http_server.route(
        "/raw/v9.9.9/protocols/diameter/dictionary.xml", b"<dictionary/>"
    )
    return base


SHARK = downloader.WiresharkDictionary(tag="v9.9.9", path="protocols/diameter")


def _archive_listing(local_http_server, number: str, **archives: bytes) -> None:
    """Serve `Specs/archive/` for `number` with the named zips in it."""
    directory = f"/archive/{number[:2]}_series/{number}/"
    local_http_server.route(
        directory,
        "".join(f'<a href="{name}.zip">{name}</a>' for name in archives).encode(),
    )
    for name, content in archives.items():
        local_http_server.route(f"{directory}{name}.zip", content)


def test_download_corpus_writes_a_sorted_manifest_end_to_end(
    tmp_path, local_http_server, monkeypatch
):
    base = _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    archive = _zip_bytes(spec=b"body")
    _archive_listing(local_http_server, "29.999", **{"29999-j00": archive})
    monkeypatch.setattr(downloader.time, "time", lambda: 1234.9)
    progress = []

    manifest_path = downloader.download_corpus(
        output,
        workers=2,
        extract=False,
        catalog=downloader.Catalog(
            (downloader.ThreeGppSpec("29.999", "Test TS"),),
            (downloader.RfcSpec(9999, "Test RFC"),),
            SHARK,
        ),
        report=progress.append,
    )

    assert manifest_path == output / "manifest.json"
    assert any("Downloaded TS 29.999" in line for line in progress)

    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["3gpp_release"] == 19
    assert manifest["generated_at_epoch"] == 1234
    assert manifest["artifact_count"] == 3
    assert [artifact["identifier"] for artifact in manifest["artifacts"]] == [
        "TS 29.999",
        "RFC 9999",
        "Wireshark v9.9.9",
    ]
    # The archive URL, which stays valid after a newer version lands.
    assert manifest["artifacts"][0]["url"] == (
        f"{base}/archive/29_series/29.999/29999-j00.zip"
    )
    assert (output / "wireshark" / "dictionary.xml").read_bytes() == b"<dictionary/>"
    assert (
        output / "archives" / "3gpp-rel-19" / "29999-j00.zip"
    ).read_bytes() == archive
    assert (output / "rfc" / "rfc9999.txt").read_bytes() == RFC_TEXT
    for artifact in manifest["artifacts"]:
        for name in artifact["files"]:
            assert (output / name).is_file(), name
    assert not (output / ".staging").exists()


def _partial_catalog(onem2m=()):
    return downloader.Catalog(
        (downloader.ThreeGppSpec("29.999", "Test TS"),),
        (downloader.RfcSpec(9999, "Test RFC"),),
        SHARK,
        onem2m,
    )


def _sources_and_identifiers(output) -> tuple[list[str], list[str]]:
    manifest = json.loads((output / "manifest.json").read_text())
    return manifest["sources"], [each["identifier"] for each in manifest["artifacts"]]


def test_a_partial_download_fetches_only_what_it_names(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"

    downloader.download_corpus(
        output, only=["wireshark"], catalog=_partial_catalog(), extract=False
    )

    assert _sources_and_identifiers(output) == (["wireshark"], ["Wireshark v9.9.9"])
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["3gpp_release"] is None
    assert manifest["include_pdfs"] is None
    assert (output / "wireshark" / "dictionary.xml").is_file()
    assert not (output / "3gpp").exists()
    assert not (output / "rfc").exists()
    assert not any("archive" in path for path, _ in local_http_server.requests)
    assert not any("rfc" in path for path, _ in local_http_server.requests)


def _transcribed_catalog(base: str, name: str = "es_283034v020200p.pdf"):
    return downloader.Catalog(
        (),
        (downloader.RfcSpec(9999, "Test RFC"),),
        SHARK,
        transcribed=(
            downloader.TranscribedDocument(
                "ETSI-ES283.034", "Test ES", f"{base}/deliver/{name}"
            ),
        ),
    )


def test_the_transcriptions_pdfs_are_a_source_of_their_own(
    tmp_path, local_http_server, monkeypatch
):
    base = _serve(local_http_server, monkeypatch)
    pdf = _pdf_bytes()
    local_http_server.route("/deliver/es_283034v020200p.pdf", pdf)
    output = tmp_path / "corpus"
    catalog = _transcribed_catalog(base)

    downloader.download_corpus(output, only=["transcribed"], catalog=catalog)

    assert _sources_and_identifiers(output) == (["transcribed"], ["ETSI-ES283.034"])
    (record,) = json.loads((output / "manifest.json").read_text())["artifacts"]
    assert record["family"] == "ETSI"
    assert record["url"] == f"{base}/deliver/es_283034v020200p.pdf"
    assert record["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert record["files"] == ["transcriptions/es_283034v020200p.pdf"]
    assert (output / "transcriptions" / "es_283034v020200p.pdf").read_bytes() == pdf
    assert not (output / "rfc").exists()

    # Kept by a run that fetches something else, and served from the cache after.
    downloader.download_corpus(output, only=["rfc"], catalog=catalog)
    assert (output / "transcriptions" / "es_283034v020200p.pdf").read_bytes() == pdf
    downloader.download_corpus(output, catalog=catalog)
    assert local_http_server.counts["/deliver/es_283034v020200p.pdf"] == 1
    assert "transcribed" in _sources_and_identifiers(output)[0]


def test_every_transcribed_publisher_is_a_family_a_partial_download_can_keep():
    """A later `--only` reads each record's family back to its source, so a
    publisher the map lacks makes the manifest unreadable."""
    for document in downloader.load_catalog().transcribed:
        assert downloader.SOURCE_OF_FAMILY[document.publisher] == "transcribed"


def test_what_a_transcription_url_serves_must_open_as_a_pdf(
    tmp_path, local_http_server, monkeypatch
):
    base = _serve(local_http_server, monkeypatch)
    local_http_server.route("/deliver/es_283034v020200p.pdf", b"<html>not it</html>")
    output = tmp_path / "corpus"

    with pytest.raises(downloader.DownloadError, match="not a readable PDF"):
        downloader.download_corpus(
            output, only=["transcribed"], catalog=_transcribed_catalog(base)
        )

    assert not (output / "manifest.json").exists()
    assert not (output / "transcriptions").exists()


def test_a_partial_download_leaves_pdfs_placed_by_hand_until_it_fetches_them(
    tmp_path, local_http_server, monkeypatch
):
    """Before the source existed `export --include-pdfs` took them from
    `transcriptions/`, placed by hand and in no manifest."""
    base = _serve(local_http_server, monkeypatch)
    pdf = _pdf_bytes()
    local_http_server.route("/deliver/es_283034v020200p.pdf", pdf)
    output = tmp_path / "corpus"
    placed = output / "transcriptions" / "es_283034v020200p.pdf"
    placed.parent.mkdir(parents=True)
    placed.write_bytes(b"placed by hand")
    catalog = _transcribed_catalog(base)

    downloader.download_corpus(output, only=["rfc"], catalog=catalog)
    assert placed.read_bytes() == b"placed by hand"

    downloader.download_corpus(output, only=["transcribed"], catalog=catalog)
    assert placed.read_bytes() == pdf


def test_a_partial_download_keeps_the_other_sources_and_a_full_one_refetches_nothing(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    _archive_listing(
        local_http_server, "29.999", **{"29999-j00": _zip_bytes(spec=b"body")}
    )
    catalog = _partial_catalog()

    downloader.download_corpus(output, only=["wireshark"], catalog=catalog)
    downloader.download_corpus(output, only=["rfc"], catalog=catalog)

    assert _sources_and_identifiers(output) == (
        ["rfc", "wireshark"],
        ["RFC 9999", "Wireshark v9.9.9"],
    )
    assert (output / "wireshark" / "dictionary.xml").is_file()
    assert (output / "rfc" / "rfc9999.txt").is_file()

    fetched = dict(local_http_server.counts)
    downloader.download_corpus(output, catalog=catalog, extract=False)

    assert _sources_and_identifiers(output) == (
        ["3gpp", "onem2m", "rfc", "transcribed", "wireshark"],
        ["TS 29.999", "RFC 9999", "Wireshark v9.9.9"],
    )
    for path, count in fetched.items():
        assert local_http_server.counts[path] == count, path
    assert (output / "archives" / "3gpp-rel-19" / "29999-j00.zip").is_file()
    assert (output / "rfc" / "rfc9999.txt").is_file()


def test_a_partial_download_keeps_another_sources_conversions(
    tmp_path, local_http_server, monkeypatch
):
    """`converted/` is one directory shared by two sources, so fetching one of
    them must leave the other's half standing."""
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    kept = {
        "3gpp/Rel-19/TS_29.999/29999-j00.doc": b"doc",
        "converted/3gpp/Rel-19/TS_29.999/29999-j00.docx": b"docx",
        "onem2m/Release-2/TS-0004/TS-0004.doc": b"onem2m doc",
        "converted/onem2m/Release-2/TS-0004/TS-0004.docx": b"onem2m docx",
    }
    for name, content in kept.items():
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        (output / name).write_bytes(content)
    conversion = {
        "file": "converted/3gpp/Rel-19/TS_29.999/29999-j00.docx",
        "source": "3gpp/Rel-19/TS_29.999/29999-j00.doc",
        "source_sha256": "0",
        "converter": "soffice",
        "command": ["soffice"],
        "sha256": "0",
        "size": 4,
    }
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "3gpp_release": 17,
                "include_pdfs": False,
                "artifacts": [
                    {
                        "family": "3GPP",
                        "identifier": "TS 29.999",
                        "title": "Test TS",
                        "url": "http://example.com",
                        "sha256": "0",
                        "size": 3,
                        "files": ["3gpp/Rel-19/TS_29.999/29999-j00.doc"],
                        "source_version": "19.0.0",
                        "conversions": [conversion],
                    },
                    {
                        "family": "oneM2M",
                        "identifier": "oneM2M TS-0004",
                        "title": "Test",
                        "url": "http://example.com",
                        "sha256": "0",
                        "size": 3,
                        "files": ["onem2m/Release-2/TS-0004/TS-0004.doc"],
                    },
                ],
            }
        )
    )

    downloader.download_corpus(output, only=["rfc"], catalog=_partial_catalog())

    for name, content in kept.items():
        assert (output / name).read_bytes() == content
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["sources"] == ["3gpp", "onem2m", "rfc"]
    # What the kept 3GPP documents were fetched under stays what it was.
    assert manifest["3gpp_release"] == 17
    assert manifest["include_pdfs"] is False
    (kept_3gpp,) = (a for a in manifest["artifacts"] if a["family"] == "3GPP")
    assert kept_3gpp["conversions"] == [conversion]


def test_a_partial_download_refuses_a_manifest_whose_files_have_gone(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    catalog = _partial_catalog()
    downloader.download_corpus(output, only=["wireshark"], catalog=catalog)
    (output / "wireshark" / "dictionary.xml").unlink()
    before = (output / "manifest.json").read_bytes()

    with pytest.raises(downloader.DownloadError, match=r"--only wireshark"):
        downloader.download_corpus(output, only=["rfc"], catalog=catalog)

    assert (output / "manifest.json").read_bytes() == before
    assert not (output / "rfc").exists()

    # A converted DOCX is in its record's `conversions` and not its `files`.
    document = "3gpp/Rel-19/TS_29.999/29999-j00.doc"
    converted = "converted/3gpp/Rel-19/TS_29.999/29999-j00.docx"
    (output / document).parent.mkdir(parents=True)
    (output / document).write_bytes(b"doc")
    before = json.dumps(
        {
            "artifacts": [
                {
                    "family": "3GPP",
                    "identifier": "TS 29.999",
                    "title": "Test TS",
                    "url": "http://example.com",
                    "sha256": "0",
                    "size": 3,
                    "files": [document],
                    "conversions": [
                        {
                            "file": converted,
                            "source": document,
                            "source_sha256": "0",
                            "converter": "soffice",
                            "command": ["soffice"],
                            "sha256": "0",
                            "size": 4,
                        }
                    ],
                }
            ]
        }
    )
    (output / "manifest.json").write_text(before)

    with pytest.raises(
        downloader.DownloadError, match=rf"{converted}, which is gone.*--only 3gpp"
    ):
        downloader.download_corpus(output, only=["rfc"], catalog=catalog)

    assert (output / "manifest.json").read_text() == before
    assert not (output / "rfc").exists()


def test_a_partial_download_refuses_a_manifest_it_cannot_read(tmp_path):
    output = tmp_path / "corpus"
    output.mkdir()
    (output / "manifest.json").write_text("not json")

    with pytest.raises(downloader.DownloadError, match="cannot read"):
        downloader.download_corpus(output, only=["rfc"], catalog=_partial_catalog())


def test_a_partial_download_names_a_source_it_does_not_know(tmp_path):
    with pytest.raises(downloader.DownloadError, match="no such source: pdfs"):
        downloader.download_corpus(tmp_path, only=["pdfs"], catalog=_partial_catalog())


def test_a_manifest_older_than_partial_downloads_keeps_what_its_records_say(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    catalog = _partial_catalog()
    downloader.download_corpus(output, only=["wireshark"], catalog=catalog)
    manifest = json.loads((output / "manifest.json").read_text())
    del manifest["sources"]
    (output / "manifest.json").write_text(json.dumps(manifest))

    downloader.download_corpus(output, only=["rfc"], catalog=catalog)

    assert _sources_and_identifiers(output)[0] == ["rfc", "wireshark"]


def test_a_failed_run_leaves_the_previous_tree_and_manifest_as_they_were(
    tmp_path, local_http_server, monkeypatch
):
    # The manifest is what downstream reads to learn what the corpus holds.
    # Publishing entry by entry, a run that failed partway left some
    # specifications at the new version and others at the old; staged, a run
    # publishes nothing until every entry has succeeded.
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    catalog = downloader.Catalog(
        (
            downloader.ThreeGppSpec("29.998", "Fine"),
            downloader.ThreeGppSpec("29.999", "Broken"),
        ),
        (downloader.RfcSpec(9999, "Test RFC"),),
        SHARK,
    )
    for number in ("29.998", "29.999"):
        stem = number.replace(".", "")
        _archive_listing(
            local_http_server, number, **{f"{stem}-j00": _zip_bytes(old_docx=b"old")}
        )
    downloader.download_corpus(output, catalog=catalog)
    before = _snapshot(output)

    # Both move to 19.1.0; 29.998's download succeeds, 29.999's is truncated.
    _archive_listing(
        local_http_server, "29.998", **{"29998-j10": _zip_bytes(new_docx=b"new")}
    )
    _archive_listing(local_http_server, "29.999", **{"29999-j10": b"PK\x03\x04 cut"})

    with pytest.raises(downloader.DownloadError, match="not a readable ZIP"):
        downloader.download_corpus(output, catalog=catalog)

    # Only the cache grew: 29.998's new archive is kept for the next run.
    assert _snapshot(output) == before | {
        "archives/3gpp-rel-19/29998-j10.zip": _zip_bytes(new_docx=b"new")
    }
    assert not (output / ".staging").exists()


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
    _serve(local_http_server, monkeypatch)
    # ETSI has published only the 19.0.0 rendering.
    local_http_server.route("/etsi_ts/129300_129399/129388/", b"19.00.00_60/")
    local_http_server.route(
        "/etsi_ts/129300_129399/129388/19.00.00_60/ts_129388v190000p.pdf",
        _pdf_bytes(),
    )
    _archive_listing(
        local_http_server,
        "29.388",
        **{"29388-j10": _zip_bytes(spec=b"new"), "29388-j00": _zip_bytes(spec=b"old")},
    )
    spec = downloader.ThreeGppSpec("29.388", "V2X")

    record = downloader.download_3gpp(
        spec,
        downloader.discover_3gpp_archive_urls(spec, 19),
        release=19,
        output=tmp_path,
        tree=tmp_path / ".staging",
        extract=False,
        pdfs=True,
    )

    assert record.source_version == "19.0.0"
    assert record.pdf_version == "19.0.0"
    assert record.newer_source_version == "19.1.0"
    assert record.url.endswith("/archive/29_series/29.388/29388-j00.zip")
    assert record.files == [
        "archives/3gpp-rel-19/29388-j00.zip",
        "3gpp/Rel-19/PDF/ts_129388v190000p.pdf",
    ]
    # The newest archive was never fetched.
    assert (
        local_http_server.counts.get("/archive/29_series/29.388/29388-j10.zip", 0) == 0
    )


@pytest.mark.parametrize(
    "exact",
    [(403, b"refused"), b"not a pdf"],
    ids=["refused", "broken"],
)
def test_a_failed_fetch_of_the_exact_pdf_takes_no_earlier_rendering(
    tmp_path, local_http_server, monkeypatch, exact
):
    # TS 129 329 V11.7.0 is published; a fetch failing once recorded V11.6.0's PDF.
    monkeypatch.setattr(downloader, "ETSI_DELIVER", local_http_server.base_url)
    archive_url = local_http_server.route("/29329-b70.zip", _zip_bytes(spec=b"body"))
    directory = "/etsi_ts/129300_129399/129329"
    local_http_server.route(f"{directory}/", b"11.06.00_60/ 11.07.00_60/")
    local_http_server.route(f"{directory}/11.07.00_60/ts_129329v110700p.pdf", exact)
    earlier = f"{directory}/11.06.00_60/ts_129329v110600p.pdf"
    local_http_server.route(earlier, _pdf_bytes())

    with pytest.raises(downloader.DownloadError) as raised:
        downloader.download_3gpp(
            downloader.ThreeGppSpec("29.329", "Sh"),
            {(11, 7, 0): archive_url},
            release=11,
            output=tmp_path,
            tree=tmp_path / ".staging",
            extract=False,
            pdfs=True,
        )

    assert not isinstance(raised.value, downloader.NotPublishedError)
    assert local_http_server.counts.get(earlier, 0) == 0


def test_a_pinned_version_is_published_in_its_releases_tree_beside_the_catalogs(
    tmp_path, local_http_server, monkeypatch
):
    """TS 29.999 at Release 19 and its pinned Release 7 last version share
    an identifier and live in two trees, the manifest listing both, the
    pinned one with what it claims."""
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    _archive_listing(
        local_http_server,
        "29.999",
        **{
            "29999-7b0": _zip_bytes(**{"29999-7b0.docx": b"eleventh"}),
            "29999-7c0": _zip_bytes(**{"29999-7c0.docx": b"last"}),
            "29999-j00": _zip_bytes(**{"29999-j00.docx": b"now"}),
        },
    )
    local_http_server.route(
        "/etsi_ts/129900_129999/129999/", b"07.12.00_60/ 19.00.00_60/"
    )
    for name in (
        "07.12.00_60/ts_129999v071200p.pdf",
        "19.00.00_60/ts_129999v190000p.pdf",
    ):
        local_http_server.route(f"/etsi_ts/129900_129999/129999/{name}", _pdf_bytes())
    spec = downloader.ThreeGppSpec("29.999", "Test TS")
    pin = downloader.PinnedThreeGppSpec("29.999", "Test TS", "7.12.0", "release")

    downloader.download_corpus(
        output,
        pdfs=True,
        catalog=downloader.Catalog((spec,), (), SHARK, (), (pin,)),
    )

    manifest = json.loads((output / "manifest.json").read_text())
    tgpp = [a for a in manifest["artifacts"] if a["family"] == "3GPP"]
    assert [(a["source_version"], a["final"]) for a in tgpp] == [
        ("7.12.0", "release"),
        ("19.0.0", None),
    ]
    assert tgpp[0]["files"] == [
        "archives/3gpp-rel-7/29999-7c0.zip",
        "3gpp/Rel-7/TS_29.999/29999-7c0.docx",
        "3gpp/Rel-7/PDF/ts_129999v071200p.pdf",
    ]
    released = output / "3gpp" / "Rel-7" / "TS_29.999" / "29999-7c0.docx"
    assert released.read_bytes() == b"last"

    # Release 7 gains a version: the pin's claim fails, and nothing is
    # published.
    before = _snapshot(output)
    _archive_listing(
        local_http_server,
        "29.999",
        **{
            "29999-7c0": _zip_bytes(**{"29999-7c0.docx": b"last"}),
            "29999-7d0": _zip_bytes(**{"29999-7d0.docx": b"later"}),
            "29999-j00": _zip_bytes(**{"29999-j00.docx": b"now"}),
        },
    )
    with pytest.raises(downloader.DownloadError, match=r"lists 7\.13\.0"):
        downloader.download_corpus(
            output,
            pdfs=True,
            catalog=downloader.Catalog((spec,), (), SHARK, (), (pin,)),
        )
    assert _snapshot(output) == before


def test_download_version_fetches_one_older_version_into_its_own_tree(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "specifications"
    _archive_listing(
        local_http_server,
        "29.999",
        **{
            "29999-j60": _zip_bytes(**{"29999-j60.docx": b"old"}),
            "29999-j70": _zip_bytes(**{"29999-j70.docx": b"new"}),
        },
    )
    local_http_server.route(
        "/etsi_ts/129900_129999/129999/", b"19.06.00_60/ 19.07.00_60/"
    )
    local_http_server.route(
        "/etsi_ts/129900_129999/129999/19.06.00_60/ts_129999v190600p.pdf",
        _pdf_bytes(),
    )
    catalog = downloader.Catalog(
        (downloader.ThreeGppSpec("29.999", "Test TS"),), (), SHARK
    )

    manifest_path = downloader.download_version(
        "TS29.999", "19.6.0", output, catalog=catalog
    )

    tree = output / "versions" / "TS29.999" / "19.6.0"
    assert manifest_path == tree / "manifest.json"
    (record,) = json.loads(manifest_path.read_text())["artifacts"]
    assert record["source_version"] == "19.6.0"
    assert record["newer_source_version"] is None
    assert record["files"] == [
        "archives/3gpp-rel-19/29999-j60.zip",
        "3gpp/Rel-19/TS_29.999/29999-j60.docx",
        "3gpp/Rel-19/PDF/ts_129999v190600p.pdf",
    ]
    # Self-contained, so `regenerate --manifest` reads it, and the archive is
    # the cache's own file.
    assert all((tree / name).is_file() for name in record["files"])
    cached = output / "archives" / "3gpp-rel-19" / "29999-j60.zip"
    assert cached.samefile(tree / record["files"][0])
    # The corpus itself is not touched, and 19.7.0 was never fetched.
    assert sorted(path.name for path in output.iterdir()) == ["archives", "versions"]
    assert not (tree.parent / ".staging").exists()
    assert "/archive/29_series/29.999/29999-j70.zip" not in local_http_server.counts

    # Asked again, the archive comes from the cache.
    downloader.download_version("29.999", "19.6.0", output, catalog=catalog)
    assert local_http_server.counts["/archive/29_series/29.999/29999-j60.zip"] == 1

    with pytest.raises(
        downloader.DownloadError,
        match=r"TS 29\.999 19\.5\.0 is not archived; Release 19 has 19\.6\.0, 19\.7\.0",
    ):
        downloader.download_version("TS 29.999", "19.5.0", output, catalog=catalog)
    with pytest.raises(downloader.DownloadError, match="not a catalogued"):
        downloader.download_version("TS29.000", "19.6.0", output, catalog=catalog)
    with pytest.raises(downloader.DownloadError, match="not a 3GPP version"):
        downloader.download_version("TS29.999", "19.36.0", output, catalog=catalog)
    assert (tree / "manifest.json").is_file()


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
    url = "https://example.test/29999-j00.zip"
    archive = tmp_path / "archives" / "3gpp-rel-19" / "29999-j00.zip"
    archive.parent.mkdir(parents=True)
    # The Temp/Promotion/Upgraded/ nesting is real (TS 29.215, 29.217).
    archive.write_bytes(
        _zip_bytes(**{"Temp/Upgraded/29999-j00.doc": b"\xd0\xcf\x11\xe0"})
    )
    spec = downloader.ThreeGppSpec("29.999", "Test TS")
    tree = tmp_path / ".staging"

    record = downloader.download_3gpp(
        spec,
        {(19, 0, 0): url},
        release=19,
        output=tmp_path,
        tree=tree,
        extract=True,
        pdfs=False,
    )

    source = "3gpp/Rel-19/TS_29.999/Temp/Upgraded/29999-j00.doc"
    assert record.conversions is not None
    (conversion,) = record.conversions
    assert conversion.source == source
    assert conversion.file == (
        "converted/3gpp/Rel-19/TS_29.999/Temp/Upgraded/29999-j00.docx"
    )
    assert conversion.converter == "LibreOffice 9.9.9.9 0123abc"
    assert conversion.source_sha256 == downloader.sha256_file(tree / source)
    assert conversion.sha256 == downloader.sha256_file(tree / conversion.file)
    assert conversion.command[-3:] == ["--outdir", "{outdir}", "{source}"]
    # The derived file is not one of the archive's files.
    assert conversion.file not in record.files
    # Each conversion runs in a private profile, never the user's own.
    (_, convert) = calls
    assert convert[1].startswith("-env:UserInstallation=file:///")
    assert convert[-1] == str(tree / source)


def test_an_archive_with_its_own_docx_is_not_converted(tmp_path, monkeypatch):
    calls = _fake_soffice(monkeypatch)
    extracted = [tmp_path / "spec" / "29999-j00.docx", tmp_path / "spec" / "a.doc"]

    conversions = downloader.convert_legacy_documents(
        "TS 29.999", extracted, tmp_path / "spec", tmp_path
    )

    assert conversions == []
    assert calls == []


@pytest.mark.parametrize(
    ("soffice", "message"),
    [
        (
            "absent",
            r"TS 29\.999 ships a legacy \.doc; .*LibreOffice \(`.*soffice`\)"
            r".*; `seanchai download --no-convert` downloads without converting",
        ),
        ("failing", r"TS 29\.999: `.*` exited 1: Error: source file could not be"),
        ("silent", r"TS 29\.999: LibreOffice wrote no 29999-j00\.docx"),
        ("broken", r"29999-j00\.docx is not a readable \.docx"),
    ],
)
def test_a_failed_conversion_fails_the_run_and_publishes_nothing(
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
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    output.mkdir()
    (output / "manifest.json").write_text('{"artifact_count": 99}')
    _archive_listing(
        local_http_server,
        "29.999",
        **{"29999-j00": _zip_bytes(**{"29999-j00.doc": b"word"})},
    )

    with pytest.raises(downloader.DownloadError, match=message):
        downloader.download_corpus(
            output,
            catalog=downloader.Catalog(
                (downloader.ThreeGppSpec("29.999", "Test TS"),), (), SHARK
            ),
        )

    # The previous manifest still describes the previous tree, which the
    # failed run did not touch.
    assert (output / "manifest.json").read_text() == '{"artifact_count": 99}'
    assert not list(output.rglob("*.docx"))
    assert not (output / ".staging").exists()


@pytest.mark.parametrize("convert", [True, False], ids=["convert", "no-convert"])
def test_download_corpus_converts_a_legacy_doc_unless_asked_not_to(
    tmp_path, local_http_server, monkeypatch, convert
):
    if convert:
        calls = _fake_soffice(monkeypatch)
    else:
        # Not installed at all: without conversion it is never looked for.
        calls = []
        monkeypatch.setattr(downloader, "SOFFICE", str(tmp_path / "bin" / "soffice"))
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    _archive_listing(
        local_http_server,
        "29.999",
        **{"29999-j00": _zip_bytes(**{"29999-j00.doc": b"word"})},
    )
    progress = []

    downloader.download_corpus(
        output,
        catalog=downloader.Catalog(
            (downloader.ThreeGppSpec("29.999", "Test TS"),), (), SHARK
        ),
        report=progress.append,
        convert=convert,
    )

    manifest = json.loads((output / "manifest.json").read_text())
    record = manifest["artifacts"][0]
    assert record["identifier"] == "TS 29.999"
    # The `.doc` is extracted and listed either way.
    assert "3gpp/Rel-19/TS_29.999/29999-j00.doc" in record["files"]
    assert (output / "3gpp" / "Rel-19" / "TS_29.999" / "29999-j00.doc").is_file()
    if convert:
        assert [conversion["file"] for conversion in record["conversions"]] == [
            "converted/3gpp/Rel-19/TS_29.999/29999-j00.docx"
        ]
        assert (output / record["conversions"][0]["file"]).is_file()
        assert len(calls) == 2
    else:
        # Empty, not absent: the record says a conversion was skipped.
        assert record["conversions"] == []
        assert not list(output.rglob("*.docx"))
        assert any(line.endswith("(legacy .doc not converted)") for line in progress), (
            progress
        )


def _is_running(pid: int) -> bool:
    """False once the process is gone or a zombie: a zombie is already dead,
    waiting on a PID 1 that in a job container may never reap it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        # No procfs here, or it exited just now: the next look settles it.
        return True
    return stat.rpartition(")")[2].split()[0] != "Z"


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
    # From before the call: waiting the 30 s sleep out would also end the child.
    deadline = time.monotonic() + 5

    with pytest.raises(downloader.DownloadError, match=r"timed out after 0\.5 s"):
        downloader.run_soffice(
            "TS 29.999", ["-c", f"sleep 30 >/dev/null 2>&1 & echo $! > {pidfile}; wait"]
        )

    assert [sig for _, sig in killed] == [downloader.signal.SIGKILL]
    child = int(pidfile.read_text())
    while _is_running(child):
        if time.monotonic() >= deadline:
            pytest.fail(f"the launcher's child {child} outlived the timeout")
        time.sleep(0.05)
    assert time.monotonic() < deadline, "the child was waited out, not killed"


ONEM2M = downloader.OneM2MSpec(
    number="0004",
    title="Service Layer Core Protocol",
    release=2,
    version="2.35.0",
    document_id=36771,
)


def _onem2m_zip(version: str = "V2_35_0") -> bytes:
    """oneM2M's zip as published: the clean and revision-marked documents,
    each with macOS resource-fork metadata beside it."""
    stem = f"TS-0004-Service_Layer_Core_Protocol-{version}"
    return _zip_bytes(
        **{
            f"{stem}(cl).doc": b"clean",
            f"__MACOSX__._{stem}(cl).doc": b"fork",
            f"{stem}(rm).doc": b"marked",
            f"__MACOSX__._{stem}(rm).doc": b"fork",
        }
    )


def _serve_onem2m(local_http_server, monkeypatch, *served: bytes) -> str:
    base = _serve(local_http_server, monkeypatch)
    monkeypatch.setattr(
        downloader, "ONEM2M_DOWNLOAD_URL", f"{base}/onem2m/{{document_id}}"
    )
    local_http_server.route("/onem2m/36771", *served)
    return f"{base}/onem2m/36771"


@pytest.mark.parametrize("convert", [True, False], ids=["convert", "no-convert"])
def test_a_onem2m_document_is_fetched_pinned_and_its_clean_copy_converted(
    tmp_path, local_http_server, monkeypatch, convert
):
    calls = _fake_soffice(monkeypatch)
    url = _serve_onem2m(local_http_server, monkeypatch, _onem2m_zip())
    output = tmp_path / "corpus"
    progress = []

    downloader.download_corpus(
        output,
        catalog=downloader.Catalog((), (), SHARK, (ONEM2M,)),
        report=progress.append,
        convert=convert,
    )

    manifest = json.loads((output / "manifest.json").read_text())
    (record,) = [a for a in manifest["artifacts"] if a["family"] == "oneM2M"]
    document = (
        "onem2m/Release-2/TS-0004/TS-0004-Service_Layer_Core_Protocol-V2_35_0(cl).doc"
    )
    assert record["identifier"] == "oneM2M TS-0004"
    assert record["url"] == url
    assert record["source_version"] == "2.35.0"
    # Cached under its version, and only the clean document extracted.
    assert record["files"] == ["archives/onem2m/TS-0004-V2_35_0.zip", document]
    assert [path.name for path in (output / "onem2m").rglob("*.doc")] == [
        "TS-0004-Service_Layer_Core_Protocol-V2_35_0(cl).doc"
    ]
    if convert:
        (conversion,) = record["conversions"]
        assert conversion["source"] == document
        assert conversion["file"] == (
            "converted/onem2m/Release-2/TS-0004/"
            "TS-0004-Service_Layer_Core_Protocol-V2_35_0(cl).docx"
        )
        assert (output / conversion["file"]).is_file()
        assert len(calls) == 2
        assert any("Downloaded oneM2M TS-0004 2.35.0 (converted" in p for p in progress)
    else:
        assert record["conversions"] == []
        assert calls == []


def test_a_newer_onem2m_revision_fails_the_download_rather_than_replace_the_pin(
    tmp_path, local_http_server, monkeypatch
):
    """The endpoint serves the latest revision. Once the pinned one is cached
    it is read from disk; a fresh fetch serving another version fails."""
    _fake_soffice(monkeypatch)
    _serve_onem2m(local_http_server, monkeypatch, _onem2m_zip(), _onem2m_zip("V2_36_0"))
    output = tmp_path / "corpus"
    catalog = downloader.Catalog((), (), SHARK, (ONEM2M,))
    downloader.download_corpus(output, catalog=catalog)
    downloader.download_corpus(output, catalog=catalog)
    assert local_http_server.counts["/onem2m/36771"] == 1
    before = _snapshot(output)

    (output / "archives" / "onem2m" / "TS-0004-V2_35_0.zip").unlink()
    with pytest.raises(
        downloader.DownloadError,
        match=r"oneM2M TS-0004: oneM2M now serves .*V2_36_0\(cl\)\.doc, but the"
        r" catalog pins 2\.35\.0",
    ):
        downloader.download_corpus(output, catalog=catalog)

    assert _snapshot(output) == {
        name: content
        for name, content in before.items()
        if name != "archives/onem2m/TS-0004-V2_35_0.zip"
    }


def test_a_onem2m_zip_must_hold_exactly_one_clean_document(tmp_path):
    archive = tmp_path / "TS-0004.zip"
    archive.write_bytes(_zip_bytes(**{"TS-0004-Core-V2_35_0(rm).doc": b"marked"}))

    with pytest.raises(downloader.DownloadError, match="holds 0 clean TS-0004"):
        downloader.check_onem2m_archive(ONEM2M, archive)


def test_catalog_titles_and_reasons_read_as_prose_and_the_rest_exactly(tmp_path):
    catalog = tmp_path / "specs.toml"
    wrapped = '"""\n    Two\n      lines\n    """'
    catalog.write_text(
        f"""
[[tgpp]]
number = "29.999"
title = {wrapped}
reason = {wrapped}

[[tgpp_pinned]]
number = "29.998"
title = {wrapped}
version = "7.0.0"
final = "document"
reason = {wrapped}

[[rfc]]
number = 9999
title = {wrapped}

[[onem2m]]
number = "0004"
title = {wrapped}
release = 2
version = "2.35.0"
document_id = 36771
reason = {wrapped}

[wireshark]
tag = "v9.9.9"
path = "resources/protocols/ diameter"
"""
    )

    loaded = downloader.load_catalog(catalog)

    (tgpp,), (rfc,), (onem2m,), (pin,) = (
        loaded.tgpp,
        loaded.rfc,
        loaded.onem2m,
        loaded.pinned,
    )
    assert {
        tgpp.title,
        tgpp.reason,
        rfc.title,
        onem2m.title,
        onem2m.reason,
        pin.title,
        pin.reason,
    } == {"Two lines"}
    assert loaded.wireshark.path == "resources/protocols/ diameter"


def test_a_catalog_entry_that_is_no_table_is_a_download_error(tmp_path):
    catalog = tmp_path / "specs.toml"
    catalog.write_text(
        'tgpp = ["29.999"]\nrfc = []\n[wireshark]\ntag = "t"\npath = "p"\n'
    )

    with pytest.raises(downloader.DownloadError, match="cannot read"):
        downloader.load_catalog(catalog)
