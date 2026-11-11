"""The downloader against a local HTTP server standing in for 3GPP, ETSI, the RFC
Editor, oneM2M and GitLab: what docs/downloader.md promises of a run."""

import hashlib
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import docx
import pypdf
import pytest

from seanchai.downloader import core as downloader
from seanchai.errors import MissingExtraError

RFC_TEXT = b"Internet Engineering Task Force\nRequest for Comments: 9999\n\nBody.\n"
SHARK = downloader.WiresharkDictionary(tag="v9.9.9", path="protocols/diameter")
TS = downloader.ThreeGppSpec("29.999", "Test TS")
RFC = downloader.RfcSpec(9999, "Test RFC")


def _zip_bytes(**members: bytes) -> bytes:
    """A real ZIP archive, `__` standing for `/` in member names: the downloader
    opens what it fetches."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        for name, content in members.items():
            zipped.writestr(name.replace("__", "/"), content)
    return buffer.getvalue()


def _pdf_bytes(pages: int = 1) -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    buffer = io.BytesIO()
    docx.Document().save(buffer)
    return buffer.getvalue()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _manifest(output: Path) -> dict:
    return json.loads((output / "manifest.json").read_text())


def _serve(local_http_server, monkeypatch) -> str:
    """Point every source at the local server, with an RFC and a one-file
    Wireshark dictionary routed. Returns the base URL."""
    base = local_http_server.base_url
    for name, value in {
        "THREE_GPP_ARCHIVE": f"{base}/archive/{{series}}_series/{{number}}/",
        "ETSI_DELIVER": base,
        "RFC_TEXT_URL": f"{base}/rfc{{number}}.txt",
        "WIRESHARK_TREE_URL": f"{base}/tree/{{path}}/{{tag}}",
        "WIRESHARK_RAW_URL": f"{base}/raw/{{tag}}/{{path}}/{{name}}",
        "ONEM2M_DOWNLOAD_URL": f"{base}/onem2m/{{document_id}}",
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


def _archive_listing(local_http_server, number: str, **archives: bytes) -> None:
    """Serve `Specs/archive/` for `number` with the named zips in it."""
    directory = f"/archive/{number[:2]}_series/{number}/"
    local_http_server.route(
        directory,
        "".join(f'<a href="{name}.zip">{name}</a>' for name in archives).encode(),
    )
    for name, content in archives.items():
        local_http_server.route(f"{directory}{name}.zip", content)


def _etsi(local_http_server, directory: str, **pdfs: bytes) -> None:
    """Serve an ETSI deliver listing of the editions `pdfs` names, with the PDF
    in each, keyed `<edition>/<file>` as `19.00.00_60__ts_129999v190000p.pdf`."""
    editions = sorted({name.split("__")[0] for name in pdfs})
    local_http_server.route(
        f"{directory}/", "".join(f"{e}/ " for e in editions).encode()
    )
    for name, content in pdfs.items():
        local_http_server.route(f"{directory}/{name.replace('__', '/')}", content)


# --- the catalog ---------------------------------------------------------------


def test_the_catalog_reads_each_kind_of_entry_with_its_prose_collapsed(tmp_path):
    catalog = tmp_path / "specs.toml"
    wrapped = '"""\n    Two\n      lines\n    """'
    catalog.write_text(
        f"""
[[tgpp]]
number = "29.999"
title = {wrapped}
document_type = "TR"
reason = {wrapped}

[[tgpp_pinned]]
number = "29.998"
title = "Ended TS"
version = "7.0.0"
final = "document"

[[rfc]]
number = 9999
title = "Test RFC"

[[onem2m]]
number = "0004"
title = "Service Layer Core Protocol"
release = 2
version = "2.35.0"
document_id = 36771

[[transcribed]]
reference = "ETSI-ES283.034"
title = "Test ES"
url = "https://example.test/deliver/es_283034v020200p.pdf"

[wireshark]
tag = "v9.9.9"
path = "resources/protocols/ diameter"
"""
    )

    loaded = downloader.load_catalog(catalog)

    (tgpp,), (pin,), (rfc,), (onem2m,), (transcribed,) = (
        loaded.tgpp,
        loaded.pinned,
        loaded.rfc,
        loaded.onem2m,
        loaded.transcribed,
    )
    assert (tgpp.title, tgpp.reason, tgpp.document_type) == ("Two lines",) * 2 + ("TR",)
    assert (tgpp.series, tgpp.archive_stem) == (29, "29999")
    assert (pin.release, pin.final, pin.spec.archive_stem) == (7, "document", "29998")
    assert rfc == downloader.RfcSpec(9999, "Test RFC")
    assert (onem2m.identifier, onem2m.file_version) == ("oneM2M TS-0004", "V2_35_0")
    assert (transcribed.publisher, transcribed.file_name) == (
        "ETSI",
        "es_283034v020200p.pdf",
    )
    # Exact fields keep their whitespace.
    assert loaded.wireshark.path == "resources/protocols/ diameter"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            'tgpp = []\n[[tgpp_pinned]]\nnumber = "29.998"\ntitle = "T"\n'
            'version = "7.0.0"\nfinal = "yes"\n',
            "final must be one of",
        ),
        ('tgpp = ["29.999"]\n', "cannot read"),
    ],
    ids=["final", "not-a-table"],
)
def test_a_malformed_catalog_is_a_download_error(tmp_path, text, message):
    catalog = tmp_path / "specs.toml"
    catalog.write_text(f'rfc = []\n{text}[wireshark]\ntag = "t"\npath = "p"\n')

    with pytest.raises(downloader.DownloadError, match=message):
        downloader.load_catalog(catalog)


def test_the_shipped_catalog_names_a_source_for_every_publisher():
    """A later `--only` reads each record's family back to its source."""
    catalog = downloader.load_catalog()

    assert catalog.tgpp and catalog.rfc and catalog.transcribed
    for document in catalog.transcribed:
        assert downloader.SOURCE_OF_FAMILY[document.publisher] == "transcribed"


# --- 3GPP versions and pins ----------------------------------------------------


def test_3gpp_names_spell_versions_in_base_36():
    assert [downloader.release_marker(r) for r in (4, 9, 10, 18, 35)] == list("49aiz")
    for release in (3, 36):
        with pytest.raises(downloader.DownloadError, match="between 4 and 35"):
            downloader.release_marker(release)
    assert downloader.decode_3gpp_version("https://x/29272-j1a.zip") == (19, 1, 10)
    with pytest.raises(downloader.DownloadError, match="cannot determine"):
        downloader.decode_3gpp_version("https://x/spec.zip")


def test_the_archive_listing_is_read_by_decoded_version_not_position(
    local_http_server, monkeypatch
):
    base = _serve(local_http_server, monkeypatch)
    local_http_server.route(
        "/archive/29_series/29.999/",
        b'<a href="29999-j10.zip">new</a><a href="../files/29999-j00.zip">old</a>'
        b'<a href="/files/29999-h99.zip">wrong release</a>',
    )

    urls = downloader.discover_3gpp_archive_urls(TS, 19)

    assert urls == {
        (19, 1, 0): f"{base}/archive/29_series/29.999/29999-j10.zip",
        (19, 0, 0): f"{base}/archive/29_series/files/29999-j00.zip",
    }


def _listing(*versions: str) -> dict[tuple[int, int, int], str]:
    return {downloader.parse_version(v): f"https://x/{v}.zip" for v in versions}


@pytest.mark.parametrize(
    ("final", "version", "listed", "kept", "refused"),
    [
        ("document", "7.0.0", ("6.4.0", "7.0.0"), ("7.0.0",), None),
        ("document", "7.0.0", ("6.4.0", "7.0.0", "8.0.0"), (), r"lists 8\.0\.0;"),
        ("document", "7.0.0", ("6.4.0",), (), "not archived"),
        (
            "release",
            "7.12.0",
            ("7.11.0", "7.12.0", "8.0.0", "19.4.0"),
            ("7.11.0", "7.12.0"),
            None,
        ),
        ("release", "7.12.0", ("7.12.0", "7.13.0"), (), "Release 7's final"),
    ],
)
def test_a_pinned_version_s_claim_is_checked_against_the_archive(
    final, version, listed, kept, refused
):
    pin = downloader.PinnedThreeGppSpec("29.140", "MM10", version, final)

    if refused:
        with pytest.raises(downloader.DownloadError, match=refused):
            downloader.check_final(pin, _listing(*listed))
    else:
        assert downloader.check_final(pin, _listing(*listed)) == _listing(*kept)


def test_a_pinned_version_is_published_in_its_releases_tree(
    tmp_path, local_http_server, monkeypatch
):
    """TS 29.999 at Release 19 and pinned at Release 7's last version: two trees
    and two records. Once Release 7 gains a version, the run fails whole."""
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
    _etsi(
        local_http_server,
        "/etsi_ts/129900_129999/129999",
        **{
            "07.12.00_60__ts_129999v071200p.pdf": _pdf_bytes(),
            "19.00.00_60__ts_129999v190000p.pdf": _pdf_bytes(),
        },
    )
    pin = downloader.PinnedThreeGppSpec("29.999", "Test TS", "7.12.0", "release")
    catalog = downloader.Catalog((TS,), (), SHARK, (), (pin,))

    downloader.download_corpus(output, pdfs=True, catalog=catalog)

    tgpp = [a for a in _manifest(output)["artifacts"] if a["family"] == "3GPP"]
    assert [(a["source_version"], a["final"]) for a in tgpp] == [
        ("7.12.0", "release"),
        ("19.0.0", None),
    ]
    assert tgpp[0]["files"] == [
        "archives/3gpp-rel-7/29999-7c0.zip",
        "3gpp/Rel-7/TS_29.999/29999-7c0.docx",
        "3gpp/Rel-7/PDF/ts_129999v071200p.pdf",
    ]
    assert (output / "3gpp/Rel-7/TS_29.999/29999-7c0.docx").read_bytes() == b"last"

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
        downloader.download_corpus(output, pdfs=True, catalog=catalog)
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
    _etsi(
        local_http_server,
        "/etsi_ts/129900_129999/129999",
        **{"19.06.00_60__ts_129999v190600p.pdf": _pdf_bytes()},
    )
    catalog = downloader.Catalog((TS,), (), SHARK)

    manifest_path = downloader.download_version(
        "TS29.999", "19.6.0", output, catalog=catalog
    )

    tree = output / "versions" / "TS29.999" / "19.6.0"
    assert manifest_path == tree / "manifest.json"
    (record,) = json.loads(manifest_path.read_text())["artifacts"]
    assert record["source_version"] == "19.6.0"
    assert record["files"] == [
        "archives/3gpp-rel-19/29999-j60.zip",
        "3gpp/Rel-19/TS_29.999/29999-j60.docx",
        "3gpp/Rel-19/PDF/ts_129999v190600p.pdf",
    ]
    # Self-contained for `regenerate --manifest`; the corpus is not touched.
    assert all((tree / name).is_file() for name in record["files"])
    assert sorted(path.name for path in output.iterdir()) == ["archives", "versions"]
    assert "/archive/29_series/29.999/29999-j70.zip" not in local_http_server.counts

    downloader.download_version("29.999", "19.6.0", output, catalog=catalog)
    assert local_http_server.counts["/archive/29_series/29.999/29999-j60.zip"] == 1

    for reference, version, message in [
        ("TS 29.999", "19.5.0", r"19\.5\.0 is not archived; Release 19 has 19\.6\.0"),
        ("TS29.000", "19.6.0", "not a catalogued"),
        ("TS29.999", "19.36.0", "not a 3GPP version"),
    ]:
        with pytest.raises(downloader.DownloadError, match=message):
            downloader.download_version(reference, version, output, catalog=catalog)


# --- ETSI renderings -----------------------------------------------------------


def _download_3gpp(tmp_path, spec, archives, tree=".staging"):
    return downloader.download_3gpp(
        spec,
        archives,
        release=19,
        output=tmp_path,
        tree=tmp_path / tree,
        extract=False,
        pdfs=True,
    )


def test_the_newest_version_with_an_etsi_pdf_is_taken(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    _etsi(
        local_http_server,
        "/etsi_ts/129300_129399/129388",
        **{"19.00.00_60__ts_129388v190000p.pdf": _pdf_bytes()},
    )
    _archive_listing(
        local_http_server,
        "29.388",
        **{"29388-j10": _zip_bytes(spec=b"new"), "29388-j00": _zip_bytes(spec=b"old")},
    )
    spec = downloader.ThreeGppSpec("29.388", "V2X")

    record = _download_3gpp(
        tmp_path, spec, downloader.discover_3gpp_archive_urls(spec, 19)
    )

    assert (record.source_version, record.pdf_version) == ("19.0.0", "19.0.0")
    assert record.newer_source_version == "19.1.0"
    assert record.url.endswith("/archive/29_series/29.388/29388-j00.zip")
    assert "/archive/29_series/29.388/29388-j10.zip" not in local_http_server.counts


@pytest.mark.parametrize(
    ("exact", "falls_back"),
    [((404, b"not published"), True), ((403, b"refused"), False), (b"no pdf", False)],
    ids=["missing", "refused", "broken"],
)
def test_only_a_404_for_the_exact_pdf_falls_back_to_an_earlier_rendering(
    tmp_path, local_http_server, monkeypatch, exact, falls_back
):
    _serve(local_http_server, monkeypatch)
    archive = local_http_server.route("/29329-j10.zip", _zip_bytes(spec=b"body"))
    directory = "/etsi_ts/129300_129399/129329"
    earlier = f"{directory}/19.00.00_60/ts_129329v190000p.pdf"
    _etsi(
        local_http_server,
        directory,
        **{
            "19.00.00_60__ts_129329v190000p.pdf": _pdf_bytes(),
            "19.01.00_60__ts_129329v190100p.pdf": exact,
        },
    )
    spec = downloader.ThreeGppSpec("29.329", "Sh")

    if not falls_back:
        with pytest.raises(downloader.DownloadError) as raised:
            _download_3gpp(tmp_path, spec, {(19, 1, 0): archive})
        assert not isinstance(raised.value, downloader.NotPublishedError)
        assert earlier not in local_http_server.counts
        return

    record = _download_3gpp(tmp_path, spec, {(19, 1, 0): archive})

    assert (record.source_version, record.pdf_version) == ("19.1.0", "19.0.0")
    assert record.pdf_url == f"{local_http_server.base_url}{earlier}"
    assert record.files == [
        "archives/3gpp-rel-19/29329-j10.zip",
        "3gpp/Rel-19/PDF/ts_129329v190000p.pdf",
    ]


def test_the_etsi_link_is_the_pdf_its_edition_directory_lists(
    tmp_path, local_http_server, monkeypatch
):
    """The real listing's shape: absolute upper-case HREFs, and a second edition
    (`_61`) the `_60` derivation cannot reach."""
    base = _serve(local_http_server, monkeypatch)
    directory = "/etsi_ts/129200_129299/129272"
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
    archive = local_http_server.route("/29272-j70.zip", _zip_bytes(spec=b"body"))

    record = _download_3gpp(
        tmp_path, downloader.ThreeGppSpec("29.272", "S6a"), {(19, 7, 0): archive}
    )

    # The manifest's `pdf_url` is what `regenerate` writes as `; Link:`.
    assert record.pdf_url == f"{base}{listed}"
    assert record.files[-1] == "3gpp/Rel-19/PDF/ts_129272v190700p1.pdf"
    # Unlisted, the `_60` edition's name is derived: in an edition directory
    # that cannot be listed, and for a version the listing lacks.
    spec = downloader.ThreeGppSpec("29.272", "S6a")
    editions = downloader.discover_etsi_editions(spec)
    assert downloader.etsi_listed_pdf_url(spec, (19, 6, 0), editions) == (
        f"{base}{directory}/19.06.00_60/ts_129272v190600p.pdf"
    )
    assert downloader.etsi_listed_pdf_url(spec, (19, 8, 0), None) == (
        f"{base}{directory}/19.08.00_60/ts_129272v190800p.pdf"
    )


def test_a_new_edition_of_a_cached_pdf_is_fetched_not_served_from_the_cache(
    tmp_path, local_http_server, monkeypatch
):
    """ETSI names both editions' PDF the same; the `_60` bytes cached by an
    earlier run must not be recorded under the `_61` URL."""
    base = _serve(local_http_server, monkeypatch)
    directory = "/etsi_ts/129200_129299/129272"
    name = "ts_129272v190700p.pdf"
    first, second = _pdf_bytes(), _pdf_bytes(pages=2)
    archive = local_http_server.route("/29272-j70.zip", _zip_bytes(spec=b"body"))
    spec = downloader.ThreeGppSpec("29.272", "S6a")

    _etsi(local_http_server, directory, **{f"19.07.00_60__{name}": first})
    _download_3gpp(tmp_path, spec, {(19, 7, 0): archive}, tree="first")
    _etsi(
        local_http_server,
        directory,
        **{f"19.07.00_60__{name}": first, f"19.07.00_61__{name}": second},
    )
    record = _download_3gpp(tmp_path, spec, {(19, 7, 0): archive}, tree="second")

    assert record.pdf_url == f"{base}{directory}/19.07.00_61/{name}"
    assert record.pdf_sha256 == hashlib.sha256(second).hexdigest()


# --- a run ---------------------------------------------------------------------


def test_download_corpus_publishes_a_manifest_of_what_it_fetched(
    tmp_path, local_http_server, monkeypatch
):
    base = _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    archive = _zip_bytes(spec=b"body")
    _archive_listing(local_http_server, "29.999", **{"29999-j00": archive})
    monkeypatch.setattr(downloader.time, "time", lambda: 1234.9)

    manifest_path = downloader.download_corpus(
        output,
        workers=2,
        extract=False,
        catalog=downloader.Catalog((TS,), (RFC,), SHARK),
    )

    assert manifest_path == output / "manifest.json"
    manifest = _manifest(output)
    assert manifest["3gpp_release"] == 19
    assert manifest["generated_at_epoch"] == 1234
    assert [a["identifier"] for a in manifest["artifacts"]] == [
        "TS 29.999",
        "RFC 9999",
        "Wireshark v9.9.9",
    ]
    # The archive URL, which stays valid after a newer version lands.
    assert manifest["artifacts"][0]["url"] == (
        f"{base}/archive/29_series/29.999/29999-j00.zip"
    )
    rfc = manifest["artifacts"][1]
    assert (rfc["size"], rfc["sha256"]) == (
        len(RFC_TEXT),
        hashlib.sha256(RFC_TEXT).hexdigest(),
    )
    assert (output / "archives/3gpp-rel-19/29999-j00.zip").read_bytes() == archive
    assert (output / "rfc/rfc9999.txt").read_bytes() == RFC_TEXT
    assert (output / "wireshark/dictionary.xml").read_bytes() == b"<dictionary/>"
    for artifact in manifest["artifacts"]:
        for name in artifact["files"]:
            assert (output / name).is_file(), name
    assert not (output / ".staging").exists()


def test_only_fetches_what_it_names_and_keeps_the_rest_of_the_manifest(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    _archive_listing(
        local_http_server, "29.999", **{"29999-j00": _zip_bytes(spec=b"body")}
    )
    catalog = downloader.Catalog((TS,), (RFC,), SHARK)

    downloader.download_corpus(output, only=["wireshark"], catalog=catalog)

    manifest = _manifest(output)
    assert manifest["sources"] == ["wireshark"]
    assert (manifest["3gpp_release"], manifest["include_pdfs"]) == (None, None)
    assert not any(
        "archive" in path or "rfc" in path for path, _ in local_http_server.requests
    )

    # A manifest written before `sources` existed is read by its records.
    del manifest["sources"]
    (output / "manifest.json").write_text(json.dumps(manifest))
    downloader.download_corpus(output, only=["rfc"], catalog=catalog)

    manifest = _manifest(output)
    assert manifest["sources"] == ["rfc", "wireshark"]
    assert [a["identifier"] for a in manifest["artifacts"]] == [
        "RFC 9999",
        "Wireshark v9.9.9",
    ]
    assert (output / "wireshark/dictionary.xml").is_file()

    fetched = dict(local_http_server.counts)
    downloader.download_corpus(output, catalog=catalog, extract=False)

    assert _manifest(output)["sources"] == list(downloader.SOURCES)
    for path, count in fetched.items():
        assert local_http_server.counts[path] == count, path


_DOC = "3gpp/Rel-19/TS_29.999/29999-j00.doc"
_CONVERTED = "converted/3gpp/Rel-19/TS_29.999/29999-j00.docx"


def _converted_record() -> dict:
    """A manifest's record of TS 29.999 as a `.doc` and its conversion."""
    return {
        "family": "3GPP",
        "identifier": "TS 29.999",
        "title": "Test TS",
        "url": "http://x",
        "sha256": "0",
        "size": 3,
        "files": [_DOC],
        "source_version": "19.0.0",
        "conversions": [
            {
                "file": _CONVERTED,
                "source": _DOC,
                "source_sha256": "0",
                "converter": "soffice",
                "command": ["soffice"],
                "sha256": "0",
                "size": 4,
            }
        ],
    }


def test_a_partial_download_keeps_another_sources_conversions(
    tmp_path, local_http_server, monkeypatch
):
    """`converted/` is shared by 3GPP and oneM2M: fetching RFCs leaves both."""
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    onem2m = "onem2m/Release-2/TS-0004/TS-0004.doc"
    kept = {
        _DOC: b"doc",
        _CONVERTED: b"docx",
        onem2m: b"onem2m doc",
        "converted/onem2m/Release-2/TS-0004/TS-0004.docx": b"onem2m docx",
    }
    for name, content in kept.items():
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        (output / name).write_bytes(content)
    record = _converted_record()
    other = {**record, "family": "oneM2M", "identifier": "oneM2M TS-0004"}
    other |= {"files": [onem2m], "conversions": None}
    (output / "manifest.json").write_text(
        json.dumps(
            {"3gpp_release": 17, "include_pdfs": False, "artifacts": [record, other]}
        )
    )

    downloader.download_corpus(
        output, only=["rfc"], catalog=downloader.Catalog((TS,), (RFC,), SHARK)
    )

    assert {name: (output / name).read_bytes() for name in kept} == kept
    manifest = _manifest(output)
    assert manifest["sources"] == ["3gpp", "onem2m", "rfc"]
    # What the kept 3GPP documents were fetched under stays what it was.
    assert (manifest["3gpp_release"], manifest["include_pdfs"]) == (17, False)
    (kept_3gpp,) = (a for a in manifest["artifacts"] if a["family"] == "3GPP")
    assert kept_3gpp["conversions"] == record["conversions"]


@pytest.mark.parametrize(
    ("gone", "message"),
    [
        ("file", r"--only wireshark"),
        ("conversion", rf"{_CONVERTED}, which is gone.*--only 3gpp"),
        ("unreadable", "cannot read"),
    ],
)
def test_a_partial_download_refuses_a_manifest_it_cannot_keep(
    tmp_path, local_http_server, monkeypatch, gone, message
):
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    catalog = downloader.Catalog((TS,), (RFC,), SHARK)
    downloader.download_corpus(output, only=["wireshark"], catalog=catalog)
    if gone == "file":
        (output / "wireshark" / "dictionary.xml").unlink()
    elif gone == "conversion":
        (output / _DOC).parent.mkdir(parents=True)
        (output / _DOC).write_bytes(b"doc")
        manifest = _manifest(output)
        manifest["artifacts"].append(_converted_record())
        (output / "manifest.json").write_text(json.dumps(manifest))
    else:
        (output / "manifest.json").write_text("not json")
    before = (output / "manifest.json").read_bytes()

    with pytest.raises(downloader.DownloadError, match=message):
        downloader.download_corpus(output, only=["rfc"], catalog=catalog)

    assert (output / "manifest.json").read_bytes() == before
    assert not (output / "rfc").exists()


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"workers": 0}, "workers must be at least 1"),
        ({"release": 99}, "release must be between"),
        ({"only": ["pdfs"]}, "no such source: pdfs"),
    ],
)
def test_a_run_refuses_its_arguments_before_fetching_anything(
    tmp_path, options, message
):
    with pytest.raises(downloader.DownloadError, match=message):
        downloader.download_corpus(tmp_path / "out", **options)

    assert not (tmp_path / "out").exists()


def test_a_download_that_opens_documents_names_the_extract_extra(
    tmp_path, local_http_server, monkeypatch
):
    _serve(local_http_server, monkeypatch)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    catalog = downloader.Catalog((TS,), (RFC,), SHARK)

    for run in (
        lambda: downloader.download_corpus(tmp_path / "a", catalog=catalog),
        lambda: downloader.download_corpus(tmp_path / "b", only=["transcribed"]),
        lambda: downloader.download_version("TS29.999", "19.6.0", tmp_path / "c"),
    ):
        with pytest.raises(
            MissingExtraError, match=r'pip install "seanchai\[extract\]"'
        ):
            run()
    assert not list(tmp_path.iterdir())

    # Fetching RFCs and the dictionary opens nothing that needs it.
    downloader.download_corpus(
        tmp_path / "d", only=["rfc", "wireshark"], catalog=catalog
    )
    assert _manifest(tmp_path / "d")["sources"] == ["rfc", "wireshark"]


def test_the_transcriptions_pdfs_are_a_source_of_their_own(
    tmp_path, local_http_server, monkeypatch
):
    """Kept by a run that fetches something else, served from the cache after,
    and a PDF placed by hand before the source existed stays until fetched."""
    base = _serve(local_http_server, monkeypatch)
    pdf = _pdf_bytes()
    local_http_server.route("/deliver/es_283034v020200p.pdf", pdf)
    output = tmp_path / "corpus"
    placed = output / "transcriptions" / "es_283034v020200p.pdf"
    placed.parent.mkdir(parents=True)
    placed.write_bytes(b"placed by hand")
    catalog = downloader.Catalog(
        (),
        (RFC,),
        SHARK,
        transcribed=(
            downloader.TranscribedDocument(
                "ETSI-ES283.034", "Test ES", f"{base}/deliver/es_283034v020200p.pdf"
            ),
        ),
    )

    downloader.download_corpus(output, only=["rfc"], catalog=catalog)
    assert placed.read_bytes() == b"placed by hand"

    downloader.download_corpus(output, only=["transcribed"], catalog=catalog)
    manifest = _manifest(output)
    assert manifest["sources"] == ["rfc", "transcribed"]
    (record,) = (a for a in manifest["artifacts"] if a["family"] == "ETSI")
    assert record["identifier"] == "ETSI-ES283.034"
    assert record["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert record["files"] == ["transcriptions/es_283034v020200p.pdf"]
    assert placed.read_bytes() == pdf

    downloader.download_corpus(output, only=["rfc"], catalog=catalog)
    downloader.download_corpus(output, catalog=catalog)
    assert placed.read_bytes() == pdf
    assert local_http_server.counts["/deliver/es_283034v020200p.pdf"] == 1


# --- what is fetched is opened ---------------------------------------------------


def test_a_transient_http_error_is_retried_and_a_refusal_is_not(
    local_http_server, monkeypatch
):
    monkeypatch.setattr(downloader.time, "sleep", lambda seconds: None)
    flaky = local_http_server.route("/flaky", (503, b"busy"), (200, b"body"))
    refused = local_http_server.route("/refused", (403, b"no"), (200, b"body"))

    assert downloader.request_bytes(flaky) == b"body"
    with pytest.raises(downloader.DownloadError, match="HTTP 403"):
        downloader.request_bytes(refused)

    assert local_http_server.counts == {"/flaky": 2, "/refused": 1}
    assert local_http_server.requests[0][1]["User-Agent"] == downloader.USER_AGENT


def test_a_cached_file_is_reused_and_a_broken_one_fetched_again_and_dropped(
    tmp_path, local_http_server
):
    destination = tmp_path / "nested" / "archive.zip"
    url = local_http_server.route(
        "/archive.zip", _zip_bytes(spec=b"body"), b"truncated"
    )

    downloader.atomic_download(url, destination, validate=downloader.validate_zip)
    downloader.atomic_download(url, destination, validate=downloader.validate_zip)
    assert local_http_server.counts["/archive.zip"] == 1

    destination.write_bytes(b"invalid cache")
    with pytest.raises(downloader.DownloadError, match="not a readable ZIP"):
        downloader.atomic_download(url, destination, validate=downloader.validate_zip)

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
def test_a_plausible_looking_file_is_opened_and_refused(
    tmp_path, validator, content, message
):
    path = tmp_path / "artifact"
    path.write_bytes(content)

    with pytest.raises(downloader.DownloadError, match=message):
        getattr(downloader, validator)(path)


def test_a_pdf_encrypted_for_its_owner_is_readable(tmp_path):
    """ETSI's TS 129 234 V11.2.0 is AES-encrypted with an empty user password."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("", "owner", algorithm="AES-256")
    path = tmp_path / "encrypted.pdf"
    with path.open("wb") as handle:
        writer.write(handle)

    downloader.validate_pdf(path)


@pytest.mark.parametrize("member", ["../escape", "/absolute"])
def test_an_archive_member_may_not_leave_its_directory(tmp_path, member):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(member, b"bad")

    with pytest.raises(downloader.DownloadError, match="unsafe ZIP member"):
        downloader.safe_extract(archive, tmp_path / "output")


# --- publishing ----------------------------------------------------------------


def _tree(root: Path, label: bytes) -> None:
    """A published-looking tree whose every file says which run wrote it."""
    for name in ("3gpp/Rel-19/TS_29.999/spec.docx", "rfc/rfc9999.txt", "manifest.json"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(label)


def _replace_failing_on(*suffixes):
    """`Path.replace` failing for paths ending in `suffixes`, so one leg of the
    swap breaks while the others work."""
    original = Path.replace

    def replace(self, target):
        if str(self).endswith(suffixes):
            raise OSError("cross-device link")
        return original(self, target)

    return replace


def test_publish_swaps_the_whole_tree_and_keeps_the_cache(tmp_path):
    destination = tmp_path / "specifications"
    _tree(destination, b"old")
    (destination / "converted").mkdir()
    (destination / "converted" / "dropped.docx").write_bytes(b"old")
    (destination / "archives").mkdir()
    (destination / "archives" / "cache.zip").write_bytes(b"cache")
    _tree(destination / ".staging", b"new")

    downloader.publish(destination / ".staging", destination, downloader.PUBLISHED)

    assert _snapshot(destination) == {
        "3gpp/Rel-19/TS_29.999/spec.docx": b"new",
        "archives/cache.zip": b"cache",
        "manifest.json": b"new",
        "rfc/rfc9999.txt": b"new",
    }


def test_a_failed_swap_restores_the_previous_tree_and_manifest(tmp_path, monkeypatch):
    """`rfc` is placed before `3gpp` fails: the rollback takes one back out and
    restores what it set aside."""
    destination = tmp_path / "specifications"
    _tree(destination, b"old")
    _tree(destination / ".staging", b"new")
    monkeypatch.setattr(Path, "replace", _replace_failing_on(".staging/3gpp"))

    with pytest.raises(downloader.DownloadError, match="cannot publish"):
        downloader.publish(destination / ".staging", destination, ("3gpp", "rfc"))

    names = ["3gpp/Rel-19/TS_29.999/spec.docx", "manifest.json", "rfc/rfc9999.txt"]
    assert _snapshot(destination) == {name: b"old" for name in names} | {
        f".staging/{name}": b"new" for name in names
    }


@pytest.mark.parametrize(
    "failing",
    [
        (".staging/3gpp", ".previous/manifest.json"),
        (".staging/manifest.json", ".previous/rfc"),
    ],
    ids=["manifest-stuck", "directory-stuck"],
)
def test_a_failed_rollback_keeps_the_previous_tree_and_blocks_the_next_run(
    tmp_path, monkeypatch, failing
):
    """What cannot be put back stays in `.previous/`, named, with no manifest
    beside a tree it may not describe, and the next run refuses to start."""
    destination = tmp_path / "specifications"
    _tree(destination, b"old")
    _tree(destination / ".staging", b"new")
    monkeypatch.setattr(Path, "replace", _replace_failing_on(*failing))

    with pytest.raises(downloader.DownloadError, match="cannot publish") as raised:
        downloader.publish(destination / ".staging", destination, ("3gpp", "rfc"))

    assert (destination / ".previous" / "manifest.json").read_bytes() == b"old"
    assert not (destination / "manifest.json").exists()
    if "rfc" in failing[1]:
        assert "could not restore rfc" in str(raised.value)
        assert "holds manifest.json, rfc" in str(raised.value)
    monkeypatch.undo()
    with pytest.raises(downloader.DownloadError, match="failed swap could not"):
        downloader.publish(destination / ".staging", destination, ("3gpp", "rfc"))
    assert (destination / ".previous" / "manifest.json").read_bytes() == b"old"


def test_a_failed_run_leaves_the_previous_tree_and_manifest_as_they_were(
    tmp_path, local_http_server, monkeypatch
):
    """Both documents move to 19.1.0; one download succeeds and one is
    truncated. Only the cache grows."""
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    catalog = downloader.Catalog(
        (downloader.ThreeGppSpec("29.998", "Fine"), TS), (RFC,), SHARK
    )
    for stem in ("29998", "29999"):
        _archive_listing(
            local_http_server,
            f"{stem[:2]}.{stem[2:]}",
            **{f"{stem}-j00": _zip_bytes(old_docx=b"old")},
        )
    downloader.download_corpus(output, catalog=catalog)
    before = _snapshot(output)

    _archive_listing(
        local_http_server, "29.998", **{"29998-j10": _zip_bytes(new_docx=b"new")}
    )
    _archive_listing(local_http_server, "29.999", **{"29999-j10": b"PK\x03\x04 cut"})
    with pytest.raises(downloader.DownloadError, match="not a readable ZIP"):
        downloader.download_corpus(output, catalog=catalog)

    assert _snapshot(output) == before | {
        "archives/3gpp-rel-19/29998-j10.zip": _zip_bytes(new_docx=b"new")
    }
    assert not (output / ".staging").exists()


# --- legacy .doc conversion --------------------------------------------------------


def _fake_soffice(monkeypatch, *, returncode=0, package: bytes | None = None):
    """Stand in for LibreOffice: `--version` answers, a conversion writes
    `package` (a real `.docx` by default) into `--outdir`. Returns the argument
    vectors it ran."""
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


@pytest.mark.parametrize("convert", [True, False], ids=["convert", "no-convert"])
def test_a_legacy_doc_is_converted_unless_asked_not_to(
    tmp_path, local_http_server, monkeypatch, convert
):
    if convert:
        calls = _fake_soffice(monkeypatch)
    else:
        # Not installed: without conversion it is never looked for.
        calls = []
        monkeypatch.setattr(downloader, "SOFFICE", str(tmp_path / "bin" / "soffice"))
    _serve(local_http_server, monkeypatch)
    output = tmp_path / "corpus"
    # The Temp/Upgraded/ nesting is real (TS 29.215, 29.217).
    _archive_listing(
        local_http_server,
        "29.999",
        **{"29999-j00": _zip_bytes(**{"Temp__Upgraded__29999-j00.doc": b"word"})},
    )
    progress = []

    downloader.download_corpus(
        output,
        catalog=downloader.Catalog((TS,), (), SHARK),
        report=progress.append,
        convert=convert,
    )

    (record, _) = _manifest(output)["artifacts"]
    source = "3gpp/Rel-19/TS_29.999/Temp/Upgraded/29999-j00.doc"
    assert source in record["files"]
    assert (output / source).is_file()
    if not convert:
        # Empty, not absent: the record says a conversion was skipped.
        assert record["conversions"] == []
        assert not list(output.rglob("*.docx"))
        assert any(line.endswith("(legacy .doc not converted)") for line in progress)
        return
    (conversion,) = record["conversions"]
    assert conversion["source"] == source
    assert conversion["file"] == (
        "converted/3gpp/Rel-19/TS_29.999/Temp/Upgraded/29999-j00.docx"
    )
    assert conversion["file"] not in record["files"]
    assert conversion["converter"] == "LibreOffice 9.9.9.9 0123abc"
    assert conversion["source_sha256"] == hashlib.sha256(b"word").hexdigest()
    assert conversion["sha256"] == downloader.sha256_file(output / conversion["file"])
    assert conversion["command"][-3:] == ["--outdir", "{outdir}", "{source}"]
    # Each conversion runs in a private profile, never the user's own.
    (_, converted) = calls
    assert converted[1].startswith("-env:UserInstallation=file:///")


@pytest.mark.parametrize(
    ("soffice", "message"),
    [
        (
            "absent",
            r"TS 29\.999 ships a legacy \.doc; .*LibreOffice \(`.*soffice`\)"
            r".*; `seanchai corpus download --no-convert` downloads without converting",
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
                _zip_bytes(**{"word__document.xml": b"not XML"})
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
        downloader.download_corpus(output, catalog=downloader.Catalog((TS,), (), SHARK))

    assert (output / "manifest.json").read_text() == '{"artifact_count": 99}'
    assert not list(output.rglob("*.docx"))
    assert not (output / ".staging").exists()


def _is_running(pid: int) -> bool:
    """False once the process is gone or a zombie, which a job container's PID
    1 may never reap."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True
    return stat.rpartition(")")[2].split()[0] != "Z"


def test_a_timed_out_conversion_kills_the_whole_process_group(tmp_path, monkeypatch):
    """`soffice` is a launcher whose `soffice.bin` child converts; a shell that
    backgrounds a sleep stands in for the pair."""
    pidfile = tmp_path / "child.pid"
    monkeypatch.setattr(downloader, "SOFFICE", "sh")
    monkeypatch.setattr(downloader, "SOFFICE_TIMEOUT", 0.5)
    # From before the call: waiting the 30 s sleep out would also end the child.
    deadline = time.monotonic() + 5

    with pytest.raises(downloader.DownloadError, match=r"timed out after 0\.5 s"):
        downloader.run_soffice(
            "TS 29.999", ["-c", f"sleep 30 >/dev/null 2>&1 & echo $! > {pidfile}; wait"]
        )

    child = int(pidfile.read_text())
    while _is_running(child):
        if time.monotonic() >= deadline:
            pytest.fail(f"the launcher's child {child} outlived the timeout")
        time.sleep(0.05)


# --- oneM2M --------------------------------------------------------------------

ONEM2M = downloader.OneM2MSpec(
    number="0004",
    title="Service Layer Core Protocol",
    release=2,
    version="2.35.0",
    document_id=36771,
)


def _onem2m_zip(version: str = "V2_35_0") -> bytes:
    """oneM2M's zip as published: the clean and revision-marked documents, each
    with macOS resource-fork metadata beside it."""
    stem = f"TS-0004-Service_Layer_Core_Protocol-{version}"
    return _zip_bytes(
        **{
            f"{stem}(cl).doc": b"clean",
            f"__MACOSX__._{stem}(cl).doc": b"fork",
            f"{stem}(rm).doc": b"marked",
            f"__MACOSX__._{stem}(rm).doc": b"fork",
        }
    )


def test_a_onem2m_document_is_fetched_at_its_pinned_version_and_only_its_clean_copy(
    tmp_path, local_http_server, monkeypatch
):
    """The endpoint serves the latest revision. Once the pinned one is cached it
    is read from disk; a fresh fetch serving another version fails the run."""
    _fake_soffice(monkeypatch)
    base = _serve(local_http_server, monkeypatch)
    local_http_server.route("/onem2m/36771", _onem2m_zip(), _onem2m_zip("V2_36_0"))
    output = tmp_path / "corpus"
    catalog = downloader.Catalog((), (), SHARK, (ONEM2M,))

    downloader.download_corpus(output, catalog=catalog)

    (record,) = [a for a in _manifest(output)["artifacts"] if a["family"] == "oneM2M"]
    document = (
        "onem2m/Release-2/TS-0004/TS-0004-Service_Layer_Core_Protocol-V2_35_0(cl).doc"
    )
    assert record["url"] == f"{base}/onem2m/36771"
    assert record["source_version"] == "2.35.0"
    assert record["files"] == ["archives/onem2m/TS-0004-V2_35_0.zip", document]
    assert [path.name for path in (output / "onem2m").rglob("*.doc")] == [
        Path(document).name
    ]
    (conversion,) = record["conversions"]
    assert conversion["source"] == document
    assert (output / conversion["file"]).is_file()

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
