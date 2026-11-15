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


def test_unsupported_type(tmp_path: Path):
    src = tmp_path / "book.docx"
    src.write_text("hi")
    result = convert_file(src, tmp_path / "out", ConvertOptions())
    assert result.status == "failed"
    assert "Unsupported" in result.error
