"""Generate synthetic EPUB + PDF fixtures for tests and manual demo.

Run: python -m tests.make_fixtures [output_dir]
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

from PIL import Image


def _png_bytes(color=(201, 168, 106), size=(400, 600)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_epub(path: Path) -> None:
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookID">urn:uuid:test-1</dc:identifier>
    <dc:title>Test Wisdom Book</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>en</dc:language>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover-img" href="cover.png" media-type="image/png" properties="cover-image"/>
    <item id="fig1" href="fig1.png" media-type="image/png"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chap1"/>
    <itemref idref="chap2"/>
  </spine>
</package>"""
    chap1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter 1</title></head>
<body><h1>Chapter One</h1><p>The unexamined life is not worth living.</p>
<p>ﬁle your thoughts carefully, exam-<br/>ple by example.</p></body></html>"""
    chap2 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter 2</title></head>
<body><h1>Chapter Two</h1><p>Knowledge speaks, wisdom listens.</p>
<figure><img src="fig1.png" alt="A diagram"/><figcaption>Figure 1 — Test diagram</figcaption></figure>
<ul><li>First point</li><li>Second point</li></ul></body></html>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/chap1.xhtml", chap1)
        zf.writestr("OEBPS/chap2.xhtml", chap2)
        zf.writestr("OEBPS/cover.png", _png_bytes((18, 17, 23), (400, 600)))
        zf.writestr("OEBPS/fig1.png", _png_bytes((201, 168, 106), (400, 300)))


def make_pdf(path: Path) -> None:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4
    page.insert_text((72, 72), "Test Wisdom PDF", fontsize=24)
    page.insert_text((72, 120), "Wisdom begins in wonder.", fontsize=14)
    page.insert_text((72, 150), "The only true wisdom is in knowing you know nothing.", fontsize=12)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 72), "Chapter Two", fontsize=20)
    page2.insert_text((72, 110), "Knowledge speaks, wisdom listens.", fontsize=12)
    # Add a simple image (figure) on page 2
    img_path = path.with_suffix(".tmp.png")
    Image.new("RGB", (300, 200), (100, 150, 200)).save(img_path)
    page2.insert_image(pymupdf.Rect(72, 150, 372, 350), filename=str(img_path))
    img_path.unlink(missing_ok=True)
    doc.set_metadata({"title": "Test Wisdom PDF", "author": "Test Author"})
    doc.save(str(path))
    doc.close()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_books")
    out.mkdir(parents=True, exist_ok=True)
    make_epub(out / "sample.epub")
    make_pdf(out / "sample.pdf")
    print(f"Fixtures written to {out}/")


if __name__ == "__main__":
    main()
