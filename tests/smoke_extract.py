"""What `seanchai[extract]` adds: the extractor imports, and the validators open
real files. Run with `-I` by the CI step installing the wheel with the extra.
"""

import tempfile
from pathlib import Path

import docx
import pypdf

from seanchai.downloader import core
from seanchai.extractor import tgpp_docx

assert callable(tgpp_docx.extract_with_comments)

with tempfile.TemporaryDirectory() as scratch:
    document = Path(scratch) / "file.docx"
    docx.Document().save(str(document))
    core.validate_docx(document)

    pdf = Path(scratch) / "file.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf)
    core.validate_pdf(pdf)

print("seanchai[extract]: the extractor and the validators read their formats")
