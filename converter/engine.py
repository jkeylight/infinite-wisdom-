"""Single-file conversion orchestration: dispatch, atomic write, book.json."""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .epub import convert_epub
from .pdf import convert_pdf


def txt_filename_for(out_book_dir: Path) -> str:
    """TXT filename = book folder name + .txt (e.g. 'Atomic Habits.txt').

    Folder name comes from the source stem (disambiguated -epub/-pdf on
    collision), so the TXT is identifiable when copied alone — unlike the
    old generic 'content.txt'.
    """
    name = Path(out_book_dir).name or "book"
    return f"{name}.txt"


@dataclass
class ConvertOptions:
    preset: str = "balanced"  # fast | balanced | best
    text_only: bool = False
    ocr: bool = False
    max_image_side: int = 1600
    figure_dpi: int = 200
    include_header: bool = True  # prepend Title/Author header to the TXT

    def __post_init__(self):
        if self.preset == "fast":
            self.max_image_side = 1200
            self.figure_dpi = 150
        elif self.preset == "best":
            self.max_image_side = 1600
            self.figure_dpi = 300
        if self.text_only:
            # Text-only overrides image settings (fastest mode)
            pass


@dataclass
class ConvertResult:
    status: str  # ok | failed | skipped
    source: str
    output_dir: str = ""
    txt_path: str = ""
    json_path: str = ""
    title: str = ""
    images: int = 0
    pages_or_chapters: int = 0
    duration_sec: float = 0.0
    error: str = ""
    warnings: list[str] = field(default_factory=list)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def convert_file(src: Path, out_book_dir: Path, options: ConvertOptions) -> ConvertResult:
    """Convert one EPUB/PDF into out_book_dir/{<BookName>.txt, book.json, assets/}."""
    start = time.perf_counter()
    src = Path(src)
    try:
        suffix = src.suffix.lower()
        if suffix == ".epub":
            result = convert_epub(
                src, out_book_dir,
                text_only=options.text_only,
                max_image_side=options.max_image_side,
            )
        elif suffix == ".pdf":
            result = convert_pdf(
                src, out_book_dir,
                text_only=options.text_only,
                max_image_side=options.max_image_side,
                figure_dpi=options.figure_dpi,
                ocr=options.ocr,
            )
        else:
            return ConvertResult(status="failed", source=str(src),
                                 error=f"Unsupported file type: {suffix or '(no extension)'}")

        # Header: book name at the top of the TXT so it is
        # identifiable when opened in Notepad / copied alone.
        # Format:
        #   <Title>
        #   by <Author>          (only if author known)
        #
        #   ---
        #
        #   <body...>
        header = ""
        if options.include_header:
            title = (result.get("title") or src.stem or "Untitled").strip()
            author = (result.get("author") or "").strip()
            lines = [title]
            if author:
                lines.append(f"by {author}")
            lines += ["", "---", ""]
            header = "\n".join(lines) + "\n"
        full_text = header + result["text"]
        header_len = len(header)

        # Shift image markers by header length, then snap each offset to the
        # exact [[img:id]] position in the final TXT (converters track
        # approximate running lengths; this makes offsets exact for the reader).
        markers = []
        search_from = 0
        for m in result.get("markers", []):
            m2 = dict(m)
            approx = m2.get("offset", 0) + header_len
            needle = f"[[img:{m2.get('id', '')}]]"
            found = full_text.find(needle, search_from)
            if found >= 0:
                m2["offset"] = found
                search_from = found + len(needle)
            else:
                m2["offset"] = approx
            markers.append(m2)

        txt_name = txt_filename_for(out_book_dir)
        txt_path = out_book_dir / txt_name
        json_path = out_book_dir / "book.json"
        _atomic_write_text(txt_path, full_text)

        book_json = {
            "title": result["title"],
            "author": result["author"],
            "language": result.get("language", "en"),
            "source_file": src.name,
            "source_type": result["source_type"],
            "text_file": txt_name,
            "cover": result["cover"]["file"] if result.get("cover") else "",
            "assets": result["assets"],
            "markers": markers,
        }
        _atomic_write_json(json_path, book_json)

        return ConvertResult(
            status="ok",
            source=str(src),
            output_dir=str(out_book_dir),
            txt_path=str(txt_path),
            json_path=str(json_path),
            title=result["title"],
            images=len(result["assets"]),
            pages_or_chapters=result.get("chapters", 0),
            duration_sec=time.perf_counter() - start,
            warnings=result.get("warnings", []),
        )
    except Exception as e:
        return ConvertResult(
            status="failed", source=str(src),
            duration_sec=time.perf_counter() - start,
            error=f"{type(e).__name__}: {e}",
        )
