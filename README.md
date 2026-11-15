# Infinite Wisdom — EPUB/PDF → TXT Bulk Converter

Windows-only, personal-use desktop converter. Turns EPUB + PDF books into clean TXT files for your ebook reader, **with book covers and diagrams** via a sidecar format.

See [`PLAN.md`](PLAN.md) for the full plan (architecture, decisions, milestones).

![GUI](docs/gui.png)

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

`content.txt` starts with the book name so it is identifiable in Notepad / when copied alone:
```
Test Wisdom Book
by Test Author

---

Chapter One
...
```
Disable with CLI `--no-header` (GUI: header is always on in v1.0.1).

## Quick start

```bash
pip install -r requirements.txt

# Generate sample books to try
python -m tests.make_fixtures sample_books
```

**GUI (recommended for bulk):**
```bash
python -m converter.gui
```
Drop files/folders, pick output + preset, hit Start. Pause/Resume/Cancel, workers slider, double-click a row to preview output.

**CLI (same engine, bulk-first):**
```bash
# Convert a whole folder (bulk, parallel, skip already-done)
python -m converter sample_books -o Converted --workers 8 --skip-existing

# Single file, fastest text-only mode
python -m converter book.epub -o Converted --text-only --preset fast

# Force re-convert everything
python -m converter sample_books -o Converted --no-skip-existing
```

CLI options:
- `--workers N` — parallel workers (default: CPU cores − 1, leaves 1 core free so your PC stays responsive)
- `--preset fast|balanced|best` — fast: 1200px/150dpi · balanced: 1600px/200dpi · best: 1600px/300dpi
- `--text-only` — skip all image extraction (fastest mode)
- `--layout mirror|flat|same` — mirror preserves folder structure (recommended for bulk)
- `--ocr` — **out of scope for v1** (kept as a flag for compatibility; scanned pages are skipped with a warning)

## Speed design

- **ProcessPoolExecutor** — true parallelism (threads would be blocked by Python GIL)
- **PyMuPDF + lxml** fast path only — never BeautifulSoup/pdfplumber by default
- **No OCR (by decision)** — text extraction is ms/page, OCR is sec/page + ~100 MB. Scanned PDFs are skipped with a clear warning instead of slowing bulk.
- **Streaming page-by-page** — a 5,000-page PDF never sits fully in RAM
- **GUI never parses** — all work in `BulkController` thread + workers; log/stats throttled via QTimer (200ms/500ms); queue table is virtualized (`QTableView` renders visible rows only, 1,000 rows scroll smoothly)
- **Pause** stops submitting new files; in-flight files finish cleanly. Cancel leaves completed files valid.

Targets: EPUB <1s · 500-page PDF <5s · 100 EPUBs <2min · 20 books in 1.0s wall (4 workers, tested).

## Windows portable build (personal use, no signing)

**Easiest:** double-click **`build.bat`** on Windows (Python 3.11+ required). It installs deps + PyInstaller, then builds both:

```
dist\Converter\Converter.exe          ← GUI, double-click to run (one-folder, instant startup)
dist\converter-cli\converter-cli.exe ← CLI twin
```

Copy the `dist\Converter` folder anywhere — it is portable. Settings persist to `config.json` next to the exe (output folder, layout, preset, workers, text-only, skip-existing). No registry, no signing, no installer.

Manual equivalent:
```powershell
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --windowed --name Converter --collect-all pymupdf --collect-all lxml --collect-all PySide6 --version-file version_info.txt -p . run_gui.py
pyinstaller --noconfirm --console --name converter-cli --collect-all pymupdf --collect-all lxml -p . run_cli.py
```
> Entry points are `run_gui.py` / `run_cli.py` (not `converter/gui.py`) — PyInstaller freezes them as top-level scripts, so relative imports inside the `converter` package work correctly. Verified: built binaries smoke-tested (CLI converts, GUI opens).

## Project layout

```
converter/
  gui.py        — PySide6 MainWindow: drop zone, virtualized queue, controls, preview
  gui_bulk.py   — BulkController: incremental ProcessPool, pause/resume/cancel, Qt signals
  cli.py        — CLI twin (same engine as GUI)
  bulk.py       — recursive scan, ProcessPool, skip-existing, mirror/flat, collision-safe
  engine.py     — single-file dispatch, atomic writes, book.json
  epub.py       — zip→OPF→spine→XHTML→txt, cover chain, figure extraction
  pdf.py        — PyMuPDF page-by-page, header/footer removal, figure clip-render
  images.py     — dedupe, downscale, WebP normalize, title-card cover
  normalize.py  — NFKC, ligatures, dehyphenation, blank-line collapse
  config.py     — config.json persistence (portable, next to exe)
run_gui.py / run_cli.py — PyInstaller entry points
build.bat / build.sh / version_info.txt — Windows portable build
tests/
  make_fixtures.py — synthetic EPUB/PDF generator
  test_normalize.py / test_convert.py / test_bulk.py / test_gui.py / test_config.py
docs/
  gui.png       — GUI screenshot
```

## Tests

```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v   # offscreen needed only on headless Linux; Windows needs no env var
```

21 tests: normalize, EPUB/PDF conversion (+ header, marker offsets), bulk + skip-existing, GUI model + controller (convert, pause/resume/cancel), config persistence.

## Status

- ✅ M0 CLI: EPUB spine→text + PDF text→text, normalization, golden-style tests
- ✅ M2 Bulk engine: ProcessPool, folder scan, skip-existing, speed stats
- ✅ M3 Sidecar: `book.json` frozen, EPUB cover chain + inline images, SVG→PNG, dedupe, captions
- ✅ M5 PDF: cover = page-1 render, figure extraction via clip-render
- ✅ M6 GUI: PySide6 bulk queue — drop folders, workers slider, Start/Pause/Resume/Cancel, Retry Failed, preview, throttled log/stats
- ✅ M7 Windows packaging: `build.bat` one-folder portable (GUI + CLI), `version_info.txt` exe metadata, `config.json` persistence, built binaries smoke-tested
- ❌ OCR: **out of scope by decision** (user call) — scanned PDFs skipped with warning; keeps bulk fast + build light

## Known limitations (v1)

- Scanned PDFs without a text layer are skipped with a warning (OCR out of scope — see above)
- Fixed-layout / comic EPUBs: detected, text conversion not meaningful
- PDF reading order: single/two-column heuristic (XY-cut lite); complex magazine layouts may need manual column hint (future)
- DRM/encrypted files: clear error, no crash
