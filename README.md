# Infinite Wisdom — EPUB/PDF → TXT Bulk Converter

Windows-only, personal-use desktop converter. Turns EPUB + PDF books into clean TXT files for your ebook reader, **with book covers and diagrams** via a sidecar format.

See [`PLAN.md`](PLAN.md) for the full plan (architecture, decisions, milestones).

## Output format (sidecar)

```
MyBook/
  content.txt     ← pure plain text (opens anywhere)
  book.json       ← title, author, cover, image positions, captions
  assets/
    cover.jpg
    img_0001.webp
```

TXT cannot hold images — `book.json` + `assets/` hold them, your reader renders them at the recorded offsets.

## Quick start (CLI — bulk-first)

```bash
pip install -r requirements.txt

# Generate sample books to try
python -m tests.make_fixtures sample_books

# Convert a whole folder (bulk, parallel, skip already-done)
python -m converter sample_books -o Converted --workers 8 --skip-existing

# Single file, fastest text-only mode
python -m converter book.epub -o Converted --text-only --preset fast

# Force re-convert everything
python -m converter sample_books -o Converted --no-skip-existing
```

Options:
- `--workers N` — parallel workers (default: CPU cores − 1, leaves 1 core free so your PC stays responsive)
- `--preset fast|balanced|best` — fast: 1200px/150dpi · balanced: 1600px/200dpi · best: 1600px/300dpi
- `--text-only` — skip all image extraction (fastest mode)
- `--layout mirror|flat|same` — mirror preserves folder structure (recommended for bulk)
- `--ocr` — scanned-page OCR (not bundled in this build; warns and skips)

## Speed design

- **ProcessPoolExecutor** — true parallelism (threads would be blocked by Python GIL)
- **PyMuPDF + lxml** fast path only — never BeautifulSoup/pdfplumber by default
- **OCR off by default** — text extraction is ms/page, OCR is sec/page
- **Streaming page-by-page** — a 5,000-page PDF never sits fully in RAM
- **GUI (M6) will throttle UI to 10/sec** — the GUI thread never parses

Targets: EPUB <1s · 500-page PDF <5s · 100 EPUBs <2min.

## Windows portable build (personal use, no signing)

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name Converter `
  --collect-all pymupdf --collect-all lxml `
  -p . converter/__main__.py
# Output: dist\Converter\Converter.exe — copy the folder anywhere, double-click to run.
# One-folder (not one-file) = instant startup, no unpack lag.
```

## Project layout

```
converter/
  cli.py        — CLI twin (same engine as GUI)
  bulk.py       — recursive scan, ProcessPool, skip-existing, mirror/flat
  engine.py     — single-file dispatch, atomic writes, book.json
  epub.py       — zip→OPF→spine→XHTML→txt, cover chain, figure extraction
  pdf.py        — PyMuPDF page-by-page, header/footer removal, figure clip-render
  images.py     — dedupe, downscale, WebP normalize, title-card cover
  normalize.py  — NFKC, ligatures, dehyphenation, blank-line collapse
tests/
  make_fixtures.py — synthetic EPUB/PDF generator
  test_normalize.py / test_convert.py / test_bulk.py
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Status

- ✅ M0 CLI: EPUB spine→text + PDF text→text, normalization, golden-style tests
- ✅ M2 Bulk engine: ProcessPool, folder scan, skip-existing, pause/resume-ready, speed stats
- ✅ M3 Sidecar: `book.json` frozen, EPUB cover chain + inline images, SVG→PNG, dedupe, captions
- ✅ M5 PDF: cover = page-1 render, figure extraction via clip-render
- ⏳ M6 GUI: PySide6 bulk queue (next)
- ⏳ M-OCR: Tesseract plugin (optional, off by default)

## Known limitations (v1)

- Scanned PDFs without a text layer are skipped with a warning (OCR plugin later)
- Fixed-layout / comic EPUBs: detected, text conversion not meaningful
- PDF reading order: single/two-column heuristic (XY-cut lite); complex magazine layouts may need manual column hint (future)
- DRM/encrypted files: clear error, no crash
