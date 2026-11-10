import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import docx
import pypdf
import pytest
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from seanchai import corpus


def _set_cells(row, values):
    for cell, value in zip(row.cells, values, strict=True):
        cell.text = value


@pytest.fixture
def synthetic_spec_docx(tmp_path):
    path = tmp_path / "spec.docx"
    document = docx.Document()

    cover = document.add_table(rows=1, cols=1)
    cover.cell(0, 0).text = "3GPP TS 29.999 V1.2.3"

    heading = document.add_paragraph(style="Heading 1")
    heading.add_run("6.1\tExample-Request (EXR) Command")
    document.add_paragraph(
        "< Example-Request > ::= < Diameter Header: 321, REQ, PXY, 42 >"
    )
    document.add_paragraph("< Session-Id >")
    bold_rule = document.add_paragraph()
    run = bold_rule.add_run("* [ Local-AVP ]")
    run.bold = True

    heading = document.add_paragraph(style="Heading 1")
    heading.add_run("6.3\tAVP Definitions")
    document.add_paragraph("Table 6.3.1: AVP definitions")
    avp_table = document.add_table(rows=2, cols=9)
    avp_table.cell(0, 0).merge(avp_table.cell(0, 3)).text = "AVP"
    avp_table.cell(0, 4).merge(avp_table.cell(0, 7)).text = "AVP Flag rules"
    avp_table.cell(0, 8).merge(avp_table.cell(1, 8)).text = "May Encrypt"
    _set_cells(
        avp_table.rows[1],
        [
            # The labels a real 3GPP AVP table prints: the extractor reads the
            # columns off this row, so abbreviating them here would test a
            # header shape no specification uses.
            "Attribute Name",
            "AVP Code",
            "Clause defined",
            "Value Type",
            "Must",
            "May",
            "Should not",
            "Must not",
            "May Encrypt",
        ],
    )
    _set_cells(
        avp_table.add_row(),
        [
            "Example-Group",
            "10",
            "6.3.1",
            "Grouped",
            "M, V",
            "",
            "",
            "",
            "No",
        ],
    )
    _set_cells(
        avp_table.add_row(),
        [
            "Example-Mode",
            "11",
            "6.3.2",
            "Enumerated",
            "V",
            "",
            "",
            "M",
            "Yes",
        ],
    )

    document.add_paragraph("Table 6.3.2: Re-used AVPs")
    reused_table = document.add_table(rows=1, cols=3)
    _set_cells(
        reused_table.rows[0],
        ["Attribute Name", "Reference", "M-bit"],
    )
    _set_cells(
        reused_table.add_row(),
        ["Other-AVP", "IETF RFC 6733", "Must not set"],
    )

    heading = document.add_paragraph(style="Heading 2")
    heading.add_run("6.3.1\tExample-Group AVP")
    document.add_paragraph("Example-Group ::= < AVP Header: 10 10415 >")
    document.add_paragraph("{ Example-Mode }")

    heading = document.add_paragraph(style="Heading 2")
    heading.add_run("6.3.2\tExample-Mode AVP")
    document.add_paragraph("The Example-Mode AVP is of type Enumerated.")
    document.add_paragraph("Disabled (0)")
    document.save(path)
    return path


def _write_cover(writer, text):
    """Put one line of extractable text on page 1, the way an ETSI rendering
    prints its cover title. `add_blank_page` gives a page with no content
    stream at all, so both the stream and a font resource are added here.

    `_add_object` is private, but the PDF spec requires stream objects to be
    indirect and pypdf exposes no public equivalent. Assigning the stream
    directly does work — pypdf reads it back — but it produces a file only
    pypdf would accept, and this fixture stands in for a real ETSI rendering.
    If a pypdf upgrade breaks this, the symptom will be a fixture whose cover
    text has vanished.
    """
    page = writer.pages[0]
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )


def _outlined_pdf(path, cover):
    writer = pypdf.PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=612, height=792)
    _write_cover(writer, cover)
    writer.add_outline_item("6.1 Messages", 1)
    parent = writer.add_outline_item("6.3 AVP definitions", 2)
    writer.add_outline_item("6.3.1 Example-Group", 3, parent=parent)
    writer.add_outline_item("6.3.2 Example-Mode", 4, parent=parent)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


@pytest.fixture
def outlined_pdf(tmp_path):
    """Matches `synthetic_spec_docx`: same specification, same version."""
    return _outlined_pdf(
        tmp_path / "rendering.pdf", "3GPP TS 29.999 version 1.2.3 Release 18"
    )


@pytest.fixture
def make_outlined_pdf(tmp_path):
    """Same outline under a caller-chosen cover, for mismatch tests."""

    def make(name, specification="TS 29.999", version="1.2.3"):
        return _outlined_pdf(
            tmp_path / name, f"3GPP {specification} version {version} Release 18"
        )

    return make


@pytest.fixture
def make_bare_pdf(tmp_path):
    """One page, no outline, with or without the cover title."""

    def make(name, cover=None):
        path = tmp_path / name
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=612, height=792)
        if cover is not None:
            _write_cover(writer, cover)
        with path.open("wb") as stream:
            writer.write(stream)
        return path

    return make


@pytest.fixture
def local_http_server():
    routes = {}
    requests = []
    counts = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers))
            responses = routes.get(self.path, [(404, b"not found")])
            index = counts.get(self.path, 0)
            counts[self.path] = index + 1
            status, body = responses[min(index, len(responses) - 1)]
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class LocalServer:
        def __init__(self):
            self.base_url = f"http://127.0.0.1:{server.server_port}"
            self.requests = requests
            self.counts = counts

        def route(self, path, *responses):
            routes[path] = [
                response if isinstance(response, tuple) else (200, response)
                for response in responses
            ]
            return f"{self.base_url}{path}"

    try:
        yield LocalServer()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


_ROOT = Path(__file__).parent.parent
# The workspace copy. The tests pin this one, whatever else is installed.
_CORPUS_DIR = _ROOT / "packages" / "seanchai-corpus" / "src" / "seanchai_corpus" / "dad"
# The committed corpus's rules, for a fixture corpus to resolve by as the
# committed one does.
_RULES = corpus.Rules.load(_CORPUS_DIR / corpus.CORPUS_FILE)


def _corpus(*, raw: bool):
    """Committed files of one kind. `rglob("*.dad")` matches `.raw.dad` too,
    so the two are told apart by suffix rather than by glob."""
    paths = [
        path
        for path in sorted(_CORPUS_DIR.rglob("*.dad"))
        if path.name.endswith(".raw.dad") == raw
    ]
    assert paths, "no committed .dad files found — these tests would pass vacuously"
    return paths


def _declare(tmp_path, toml: str, reference="RFC9999"):
    """A sources directory declaring `toml` for the synthetic document."""
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    (sources / f"{reference}.toml").write_text(toml, encoding="utf-8")
    return sources


def pytest_addoption(parser):
    parser.addoption(
        "--update-export-pin",
        action="store_true",
        help="Rewrite tests/export.sha256 from the export before comparing.",
    )
