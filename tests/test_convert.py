import json
from pathlib import Path

from converter.engine import ConvertOptions, convert_file
from tests.make_fixtures import make_epub, make_pdf


def test_epub_conversion(tmp_path: Path):
    src = tmp_path / "book.epub"
    make_epub(src)
    out = tmp_path / "out" / "book"
    result = convert_file(src, out, ConvertOptions())
    assert result.status == "ok", result.error
    txt = (out / "content.txt").read_text(encoding="utf-8")
    # Book name must be at the top of the TXT
    assert txt.startswith("Test Wisdom Book\nby Test Author\n\n---\n\n")
    assert "Chapter One" in txt
    assert "unexamined life" in txt
    assert "file your thoughts" in txt  # ligature expanded
    assert "example" in txt  # dehyphenated (exam- + ple across <br/> may vary, check loosely)
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    assert book["title"] == "Test Wisdom Book"
    assert book["cover"] == "assets/cover.jpg"
    assert (out / "assets" / "cover.jpg").exists()
    # Figure image extracted
    assert len(book["assets"]) >= 1
    assert any(a["id"].startswith("img_") for a in book["assets"])
    assert "[[img:" in txt


def test_pdf_conversion(tmp_path: Path):
    src = tmp_path / "book.pdf"
    make_pdf(src)
    out = tmp_path / "out" / "book"
    result = convert_file(src, out, ConvertOptions())
    assert result.status == "ok", result.error
    txt = (out / "content.txt").read_text(encoding="utf-8")
    assert txt.startswith("Test Wisdom PDF\nby Test Author\n\n---\n\n")
    assert "Wisdom begins in wonder" in txt
    assert "knowing you know nothing" in txt
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    assert book["title"] == "Test Wisdom PDF"
    assert (out / "assets" / "cover.jpg").exists()


def test_text_only_skips_images(tmp_path: Path):
    src = tmp_path / "book.epub"
    make_epub(src)
    out = tmp_path / "out" / "book"
    result = convert_file(src, out, ConvertOptions(text_only=True))
    assert result.status == "ok", result.error
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    assert book["assets"] == []
    assert "[[img:" not in (out / "content.txt").read_text(encoding="utf-8")


def test_no_header_option(tmp_path: Path):
    src = tmp_path / "book.epub"
    make_epub(src)
    out = tmp_path / "out" / "book"
    result = convert_file(src, out, ConvertOptions(include_header=False))
    assert result.status == "ok", result.error
    txt = (out / "content.txt").read_text(encoding="utf-8")
    assert not txt.startswith("Test Wisdom Book")
    assert "Chapter One" in txt


def test_marker_offset_accounts_for_header(tmp_path: Path):
    src = tmp_path / "book.epub"
    make_epub(src)
    out = tmp_path / "out" / "book"
    convert_file(src, out, ConvertOptions())
    txt = (out / "content.txt").read_text(encoding="utf-8")
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    assert book["markers"], "expected at least one image marker"
    for m in book["markers"]:
        # Offset must point at/near the [[img:...]] marker in the final TXT
        snippet = txt[m["offset"]:m["offset"] + 20]
        assert "[[img:" in snippet or txt[m["offset"] - 5:m["offset"] + 20].find("[[img:") >= 0, snippet


def test_unsupported_type(tmp_path: Path):
    src = tmp_path / "book.docx"
    src.write_text("hi")
    result = convert_file(src, tmp_path / "out", ConvertOptions())
    assert result.status == "failed"
    assert "Unsupported" in result.error
