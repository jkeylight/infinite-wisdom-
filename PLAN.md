# EPUB + PDF → TXT Converter — Robust Desktop App
## Plan Mode Only — No Code Yet

**Goal:** Build a robust **Windows-only, personal-use** desktop converter that turns EPUB and PDF books into clean TXT files for your ebook reader, **including book cover extraction and images/diagrams handling** — even though TXT itself cannot store images.

**Top 2 requirements (locked):**
1. **Bulk file converter** — drop a whole folder, convert hundreds of books unattended
2. **High-speed conversion, no lag** — GUI never freezes, maximum throughput on your PC

**Repo:** `infinite-wisdom-` (connected)

---

## 1. The Core Problem & Key Decision

TXT is plain text. It **cannot** contain:
- Book cover images
- Diagrams, figures, charts
- Inline photos

If you try to force images into TXT, you break TXT. Your reader needs a different model.

### Recommended Model: TXT + JSON Sidecar + Assets Folder

```
MyBook/
  content.txt          ← pure, readable plain text (exportable anywhere)
  book.json            ← metadata, cover path, image positions, captions
  assets/
    cover.jpg
    img_0001.png
    img_0002.webp
```

**Why this wins:**
- `content.txt` stays 100% valid plain text — opens in Notepad, easy to share
- `book.json` holds ALL structure your reader needs (cover, images, offsets)
- `assets/` holds the actual image files
- Your reader is the only consumer of the structure, so you get full fidelity without inventing a new container format

**Alternative (only if you must stay single-file):** TXT with inline markers like `[[img:img_0001]]`. Simpler parser, but your TXT is no longer pure text. Not recommended as primary — use markers only as a *decorative* fallback (see §8).

---

## 2. On-Disk Format Spec (Freeze This First)

### `book.json` — minimal schema
```json
{
  "title": "Example Book",
  "author": "Author Name",
  "language": "en",
  "source_file": "original.epub",
  "source_type": "epub",
  "cover": "assets/cover.jpg",
  "assets": [
    {
      "id": "img_0001",
      "file": "assets/img_0001.png",
      "caption": "Figure 1.2 — Water cycle",
      "alt": "Diagram of the water cycle",
      "width": 800,
      "height": 600
    }
  ],
  "markers": [
    { "type": "image", "id": "img_0001", "offset": 4523, "page": 12 }
  ]
}
```
- `offset` = character offset in `content.txt` where the image should render inline while scrolling
- Reader inserts an image widget at that offset
- If asset file is missing → reader shows `[Image unavailable: caption]` box, never crashes

### Image normalization rules (on import)
- Max 1600px longest edge (downscale larger)
- Convert to WebP q=80 unless already JPEG/PNG < 500KB
- Strip EXIF, but bake EXIF orientation into pixels first (fixes sideways photos)
- Convert CMYK JPEG / 16-bit PNG → sRGB 8-bit
- Deduplicate by content hash (EPUBs repeat ornament images per chapter)
- Skip decorative images: < 64px either side, or filename contains `spacer/bullet/line/ornament`, or identical image repeated 20+ times

---

## 3. Tech Stack — Windows Only, Personal Use

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Best EPUB/PDF parsing ecosystem, easy multiprocessing |
| GUI | **PySide6 (Qt)** | Mature, drag-drop, progress UI. Windows-only build — no cross-platform QA needed |
| EPUB parsing | `zipfile` + `lxml` directly | `ebooklib` is thinly maintained — use it as wrapper, bypass when it fails. **lxml is C-fast; never use BeautifulSoup (10-50× slower)** |
| PDF parsing | **PyMuPDF (`fitz`)** primary, `pdfplumber` fallback only on failure | PyMuPDF is the fastest Python PDF lib (C core). pdfplumber is slow — fallback only, never default |
| OCR (optional) | `pytesseract` + bundled Tesseract | For scanned PDFs. **OFF by default** — OCR is 20-100× slower than text extraction |
| Packaging | **PyInstaller one-folder** (NOT one-file) | One-file unpacks on every launch = slow startup + AV false positives. One-folder = instant launch, portable, just copy the folder |
| Worker model | **ProcessPoolExecutor, N workers = CPU cores** | True parallelism (Python GIL blocks threads). GUI process never does parsing |
| Signing / installer | **None needed** | Personal use: no code signing, no notarization, no auto-update, no installer. Just a portable folder + `.exe` |

**Personal-use simplifications (big win):**
- No Apple Developer account, no Microsoft signing cert, no store submission
- No auto-update system — you rebuild when you want
- Config stored locally (`config.json` next to exe), no telemetry, no accounts
- Can use absolute Windows paths, registry-free portable design
- Windows Defender SmartScreen warning is acceptable for personal use (or sign later if you share it)

**Rejected:** Electron (weak PDF text extraction, heavy), Tauri/Rust (rebuild all parsing logic), .NET (weaker OCR/layout tooling).

---

## 4. Converter Architecture — Built for Bulk + No Lag

```
┌──────────────── GUI (PySide6) ────────────────┐
│ Drop zone · bulk queue · options · progress   │
│  ↑ UI updates throttled to 10/sec — never lag │
└──────────────┬────────────────────────────────┘
               │ job specs (queue, not direct calls)
       ┌───────▼────────┐
       │  Job Manager   │ queue, pause/resume, cancel,
       │                │ skip-converted, retry, ETA
       └───────┬────────┘
               │ ProcessPoolExecutor (workers = CPU cores)
               │ one file per worker process (timeout + memory cap)
  ┌────────────▼─────────────┐   ┌──────────────────────────┐
  │  EPUB pipeline           │   │  PDF pipeline            │
  │  zip→OPF→spine→XHTML→txt │   │  probe→extract→OCR?→txt  │
  └────────────┬─────────────┘   └────────────┬─────────────┘
               └──────────────┬───────────────┘
                    ┌─────────▼──────────┐
                    │ Text Normalizer    │ shared post-processing
                    └─────────┬──────────┘
                    ┌─────────▼──────────┐
                    │ Writer (atomic)    │ temp file → rename
                    └────────────────────┘
```

**Key principles for no lag:**
1. **GUI never touches parsing code.** All conversion in child processes. GUI thread only draws.
2. **UI updates throttled:** progress/log refresh max 10×/sec, batched. Never update UI per-page/per-line.
3. **One bad file never blocks the queue** — it fails alone, next file starts immediately.
4. **Streaming, not loading:** PDFs processed page-by-page, EPUB spine item-by-item. Never hold a whole 10k-page book in RAM.

---

## 4A. Bulk Converter Design (Requirement #1)

### Input handling
- **Drag-drop files AND folders** onto the window. Folders scanned recursively (`*.epub`, `*.pdf`).
- **Add Files / Add Folder** buttons. Dedupe by absolute path + file hash (same file added twice = once).
- **Output layout options:**
  - Mirror source folder structure (recommended for bulk: `Books/Author/Book/` → `Converted/Author/Book/`)
  - Flat output folder (all books in one place)
  - Same folder as source (next to original)
- **Skip already converted:** If `content.txt` exists and is newer than source, skip (with "Force re-convert" override). Essential for re-running a 500-book folder.

### Queue controls
- **Start / Pause / Resume / Cancel All / Remove selected / Clear finished**
- **Per-file actions:** retry, open output folder, remove from queue
- **Parallel workers slider:** 1 → CPU cores (default: cores-1, leave 1 core for Windows + GUI so PC stays responsive)
- **Priority:** failed files can be retried without re-queueing everything

### Bulk reporting
- Live counters: `142 / 500 done · 3 failed · 12 skipped · ETA 04:32`
- Speed stats: files/min, pages/sec, MB/sec — so you can see it's fast
- Final summary report: converted / failed (with reason) / skipped, exportable as `.log` / `.csv`
- Failed files listed with one-click "Retry failed only"

### CLI twin (for bulk scripting)
Same engine, headless:
```
converter-cli  C:\Books\  C:\Converted\  --workers 8 --skip-existing --preset clean-novel
```
Useful for scheduled bulk runs or PowerShell automation. GUI and CLI share 100% of conversion code.

---

## 4B. High-Speed / No-Lag Design (Requirement #2)

### Where speed comes from (in order of impact)
1. **True parallelism:** `ProcessPoolExecutor` with N = CPU cores. 8-core PC ≈ 6-8× single-file speed on bulk. Threads would be blocked by Python GIL — **never use threads for parsing.**
2. **Fastest libraries only:**
   - PDF: PyMuPDF (`fitz`) — C core, ~10× faster than pdfplumber/pypdf for text extraction
   - EPUB: `lxml` (C) — never BeautifulSoup (pure Python, slow)
   - Images: Pillow (C), WebP encode only when needed
3. **OCR OFF by default:** Text extraction = milliseconds/page. OCR = seconds/page. Only OCR pages that are actually image-only, and only when user enables it.
4. **Streaming + low memory:** Page-by-page PDF, spine-item-by-spine-item EPUB. A 5,000-page PDF never sits fully in RAM. Prevents swapping/lag.
5. **Avoid waste:**
   - Skip decorative/tiny images early (cheap check before expensive render)
   - Dedupe images by hash before writing
   - Downscale images once, not repeatedly
   - Hash source file once for cover cache — don't re-render covers on re-run
6. **Fast startup:** PyInstaller **one-folder** (not one-file). One-file unpacks ~50-100 MB on every launch = visible lag. One-folder launches instantly.
7. **GUI stays responsive:**
   - All work in workers; GUI thread only draws
   - Throttle UI refresh to 10/sec; batch log lines
   - Virtualized file list (only render visible rows) — 1,000 files in queue must not lag scrolling
   - Leave 1 CPU core free by default (workers = cores-1) so Windows + GUI never starve

### Speed targets (benchmark these in tests)
| File type | Target (typical PC) |
|---|---|
| EPUB, 500 KB, 300 pages | < 1 sec |
| PDF, 500 pages, text layer | < 5 sec |
| PDF, 500 pages + figures | < 15 sec |
| Bulk: 100 EPUBs | < 2 min |
| Bulk: 100 PDFs (500 pp each) | < 10 min |
| Scanned PDF + OCR, 100 pages | < 2 min (OCR is inherently slow — this is expected) |

### Speed settings (user-facing)
- **Workers:** slider 1–cores (default cores-1)
- **Preset: Fast / Balanced / Best quality**
  - Fast: no OCR, skip figure rendering, max image 1200px, no dedupe hash (or fast hash)
  - Balanced (default): figures on, 1600px, dedupe on
  - Best: OCR fallback on, 200-300 DPI figure render, full normalization
- **"Convert text only" toggle:** skips all image extraction — fastest possible mode for novels

### What NOT to do (lag traps)
- ❌ BeautifulSoup for EPUB parsing
- ❌ pdfplumber as default PDF extractor
- ❌ Threads for parsing (GIL)
- ❌ Loading whole PDF/EPUB into memory
- ❌ Updating progress bar per page (throttle it)
- ❌ PyInstaller one-file builds
- ❌ OCR on every page "just in case"

---

## 5. EPUB Pipeline

1. **Validate container:** Open as zip, find `META-INF/container.xml`, resolve OPF path. Fallback: scan for `*.opf` if container is malformed.
2. **Parse OPF:** Read `<manifest>` + `<spine>` → **spine order is reading order** (not file order — this is where naive converters fail).
3. **Encryption check:** `META-INF/encryption.xml` → if DRM/obfuscated, report clearly, don't produce garbage.
4. **Per spine item (XHTML):**
   - Parse with `lxml` in recover mode (tolerate broken markup) — **fast path, no BeautifulSoup**
   - Walk DOM in document order:
     - `h1-h6` → heading (blank line before/after)
     - `p, div` → paragraph break
     - `li` → bullet/numbered line
     - `blockquote` → indented/prefixed
     - `br` → newline; `pre/code` → preserve whitespace
     - `table` → flatten rows as tab/pipe-separated lines
     - `img` → emit asset + marker (see §7)
     - `ruby` → keep base text, drop/parenthesize annotation (configurable)
   - Skip `<script>`, `<style>`, `<nav>` (keep TOC optionally)
5. **Chapter boundaries:** Configurable separator (`\n\n=== Chapter N ===\n\n` or form feed)
6. **Metadata header (optional):** title, author, language, publisher, source filename
7. **Encoding:** Declared encoding → fallback UTF-8 → cp1252 → latin-1, then normalize

---

## 6. PDF Pipeline (The Hard Half)

### Stages
1. **Probe:** page count, encryption (`needs_pass` → ask user or skip), metadata, text-layer presence
2. **Per-page classification:**
   - Text page (enough characters) → extract
   - Image-only page (near-zero text) → mark for OCR
   - Mixed → extract text + OCR image region if enabled
3. **Extraction (PyMuPDF):** Get blocks with bounding boxes + font info — **fast path**
4. **Reading order:** Sort top-to-bottom, left-to-right. For multi-column: cluster by x-ranges, read column-by-column (XY-cut / histogram of block x-centers)
5. **Header/footer removal:** Lines repeated at same y-position across ≥N pages (page numbers, running heads) → drop. This alone massively improves quality.
6. **OCR path (optional toggle, OFF by default):** Rasterize at 300 DPI → Tesseract (`--psm` tuned per layout). Cache by page hash.
7. **Line assembly:** Join wrapped lines into paragraphs (new paragraph on blank gap, indent, or terminal punctuation). Remove soft hyphens: `exam-\nple` → `example`
8. **Page boundaries:** Configurable — continuous flow (default), form feed, or `--- page N ---`
9. **Fallbacks:** PyMuPDF garbage (CID fonts/mojibake) → retry with `pdfplumber` → if both fail, log page, OCR if enabled. **One bad page never aborts the document.**

### Shared Text Normalization (both pipelines)
1. Unicode NFKC, strip control chars except `\n`/`\t`
2. Ligature expansion (`ﬁ`→`fi`), smart quotes → ASCII (configurable)
3. Dehyphenation + line reflow
4. Collapse >2 blank lines, trim trailing spaces
5. Strip running headers/footers (PDF) and TOC/nav leftovers (EPUB)
6. Optional: dedupe repeated paragraphs (common in bad OCR)
7. Final encoding + line ending (`\n` vs `\r\n`)

---

## 7. Cover Extraction — Priority Chain (First Hit Wins)

### EPUB
1. **EPUB3:** manifest item with `properties="cover-image"`
2. **EPUB2:** `<meta name="cover" content="id">` in OPF metadata → resolve in manifest
3. **`cover.xhtml` / `cover.html`** in spine → first `<img>` / `<svg><image>`
4. **Heuristic:** first spine image that is page-sized (aspect ~0.6–0.75, large dimensions)
5. **Fallback:** first manifest image with "cover" in filename
6. **Last resort:** generated placeholder title card (title + author on colored background) — shelf UI never breaks

**Validation before accepting:** reject < 200px either axis, reject 1×1 tracking pixels, rasterize SVG to PNG at 800px wide.

### PDF
No "cover" concept exists. **Render page 1 at 150–200 DPI → `cover.jpg`.** Deterministic, always works. Don't over-engineer with title-page heuristics in v1.

### Plain TXT sources (imported)
No embedded image. Options: user assigns manually in reader, or generate title card. Add "Edit cover" action in library UI.

### Cache key
Hash source file (SHA-256 of first+last MB + size) so covers survive re-imports and don't regenerate every launch.

---

## 8. Images & Diagrams Extraction

### EPUB
- Walk DOM in spine order; on `<img>`, `<svg><image>`, `<figure>`:
  - Resolve `src` against XHTML base path inside zip
  - Extract binary; **SVG → PNG** (rasterize at 2× CSS size or 1024px, whichever larger)
  - Normalize formats: keep PNG/JPEG/WebP, GIF→WebP (first frame), BMP/TIFF→PNG
  - Read `<figcaption>` / `alt` / `title` → caption/alt in JSON
  - Deduplicate by content hash
  - Emit marker at exact text position
- Skip decorative images (see §2 rules)

### PDF — Three Forms, Three Handlings
| Form | Detection | Strategy |
|---|---|---|
| Embedded raster images | `page.get_images(full=True)` | Extract via `doc.extract_image(xref)`, skip < 100×100 (logos/bullets) |
| Vector diagrams (charts, line art) | `page.get_drawings()` many primitives | Cluster bounding boxes → rasterize cluster to PNG |
| Scanned page images | One large image ≈ full page, little text | Already OCR source — save as asset only if "keep figures" enabled |

**Practical PDF algorithm per page:**
1. Get image xrefs + on-page rects
2. Get drawing clusters (bounding boxes of ≥N primitives)
3. Merge overlapping rects
4. Filter by area (drop < 5% of page) and aspect (drop full-page background scans unless flagged)
5. **Render each kept rect at 200–300 DPI via `page.get_pixmap(clip=rect, dpi=…)`** — this one method handles rasters, vectors, and mixed figures uniformly. Render the region, don't reconstruct from parts.
6. Caption detection: text blocks directly below rect within N points → caption
7. Emit marker at block's reading-order position

### Marker Grammar (decorative fallback in TXT)
```
[[img:img_0001]]                        ← inline image reference
[[img:img_0001|caption=Figure 1.2]]     ← with caption override
[[page:42]]                             ← optional page break (PDF)
```
Rules: column 0, own line, `[[`/`]]` reserved, escape literal as `[[[`. Also append caption as plain text on next line so Notepad shows something meaningful:
```
[[img:img_0001]]
Figure 1.2 — Diagram of the water cycle
```
**JSON is authoritative; TXT markers are decorative.**

---

## 9. Reader-Side Rendering

- **Inline images in scroll:** Lazy-load from `assets/` by offset; placeholder box with fixed aspect ratio (prevents scroll jump); tap → full-screen viewer with zoom
- **Cover:** From `book.json.cover`, cached 300px thumbnail generated once in app cache (not in book folder)
- **Missing asset:** Render `[Image unavailable: caption]` box — never crash
- **Storage budget:** Typical novel < 5 MB assets; illustrated book 20–80 MB. Warn in UI if > 200 MB
- **Future:** Global content-addressed store (dedupe across books in a series)

---

## 10. GUI Design — Bulk-First, No-Lag

- **Main window:** Drop zone (files + folders), bulk file list (name, type, size, status, message, speed), Add Files/Folder, Remove, Convert, Pause, Cancel
- **Queue controls:** Start/Pause/Resume/Cancel All, Retry Failed Only, Clear Finished, workers slider (1–cores, default cores-1)
- **Options (per-job defaults):** output folder + layout (mirror/flat/same), chapter separators, OCR on/off + language, encoding, line endings, metadata header, keep footnotes/TOC, page markers, **Fast/Balanced/Best preset**, **Text-only (no images) toggle**
- **Progress:** Per-file bar + overall `142/500`, ETA, files/min + pages/sec, live log pane (throttled)
- **Preview:** Side-by-side "first 2 KB of source vs output" before committing a large batch
- **Presets:** "Fast bulk", "Clean novel", "Academic paper", "Scanned book (OCR)"
- **Errors:** Non-modal report, "open log", "retry with fallback"
- **CLI twin:** Same engine — `converter-cli C:\Books\ C:\Converted\ --workers 8 --skip-existing`
- **Performance rules:** virtualized list (1,000 rows scroll smoothly), UI refresh ≤10/sec, GUI thread never parses

---

## 11. Robustness Checklist

- [ ] Process isolation + per-file timeout + memory cap
- [ ] Atomic writes (temp file → rename); never leave half-written `.txt`
- [ ] Disk-space + permission checks before batch
- [ ] Unicode decode fallback chain; log chosen encoding
- [ ] Handle: zero-byte files, wrong extensions, zip bombs (size limits), 10k-page PDFs (stream page-by-page, don't hold all text in RAM)
- [ ] Encrypted/DRM → clear message, no crash
- [ ] Cancel/pause mid-batch leaves completed files valid; resume continues queue
- [ ] Crash reporting (local log file), no telemetry by default
- [ ] One bad page/file never aborts the document — collect errors per page, continue
- [ ] **No-lag:** GUI responsive during 500-file bulk run; workers leave 1 core free; UI throttled

---

## 12. Testing Strategy — Windows Only

- **Corpus (~50 fixtures):** clean EPUB2/EPUB3, fixed-layout EPUB, broken OPF, DRM sample, single-column PDF, two-column paper, scanned book, RTL, CJK, math-heavy, malformed PDF, 0-byte file
- **Golden-file tests:** expected `.txt` + `book.json` per fixture, diffed in CI (Windows runner)
- **Fuzz:** random truncation/corruption → assert "no crash, error reported"
- **Property tests:** output always valid UTF-8; line endings respected; no control chars; every marker in TXT has a matching asset in JSON
- **Benchmark tests:** assert speed targets in §4B on a reference PC; fail CI if regression >20%
- **Bulk stress test:** 500-file folder, assert GUI stays responsive (UI thread heartbeat < 100ms), all files processed, pause/resume works
- **Manual QA:** Windows 10 + Windows 11 only (personal use — no macOS/Linux matrix)

---

## 13. Milestones — Windows Personal Build

| Milestone | Deliverable | Est. |
|---|---|---|
| **M0** | CLI only: EPUB spine→text + single-column PDF→text, normalization, golden tests on 10 fixtures | 3–4 days |
| **M1** | Multi-column PDF, header/footer removal, dehyphenation, per-page error collection | 1 wk |
| **M2** | **Bulk engine:** ProcessPoolExecutor, folder recursive scan, skip-existing, pause/resume, speed stats, benchmark tests | 1 wk |
| **M3** | `book.json` schema frozen; EPUB cover chain + inline images (extract, SVG rasterize, dedupe, markers, captions) | 1 wk |
| **M4** | Reader: inline image widgets, lazy load, tap-to-zoom, missing-asset fallback, cover thumbnails | 1 wk |
| **M5** | PDF figure extraction via clip-render; caption heuristic; PDF cover = page-1 render | 1 wk |
| **M6** | PySide6 GUI: bulk queue, drop folders, workers slider, progress, preview, presets, virtualized list | 1–2 wk |
| **M7** | **Windows packaging:** PyInstaller one-folder portable build, `config.json`, README, full corpus + bulk stress CI | 3–4 days |
| **M8** | Polish: Fast/Balanced/Best presets, text-only mode, crash logs, speed tuning | ongoing |
| ~~M-OCR~~ | OCR path (optional plugin, OFF by default) | add when needed |

---

## 14. Main Risks & Mitigations

| Risk | Mitigation |
|---|---|
| PDF reading order is biggest quality risk | Start with XY-cut; add "preview & manual column hint" escape hatch |
| OCR adds ~100 MB + slowness | Optional plugin, OFF by default; never block bulk on OCR |
| `ebooklib` thinly maintained | Wrap it; keep direct zip+OPF fallback |
| Scope creep toward layout fidelity | Freeze v1 on plain-text fidelity only |
| SVG with external refs (fonts/images) | Rasterize with refs inlined, else placeholder |
| Fixed-layout / comic EPUBs | Detect + warn "text conversion not meaningful" — out of scope v1 |
| CMYK / 16-bit images break readers | Convert to sRGB 8-bit on import |
| **GUI lag on large bulk queues** | ProcessPool + throttled UI + virtualized list + workers=cores-1 |
| **Slow parsing libs (BeautifulSoup/pdfplumber)** | lxml + PyMuPDF only on fast path; slow libs fallback-only |

---

## 15. Decisions — Locked

### 1. Single-file vs sidecar? → **SIDECAR. Locked.**
`content.txt` + `book.json` + `assets/`. TXT stays pure/exportable; JSON is authoritative.

### 2. OCR in v1 or later? → **LATER, optional plugin. OFF by default.**
Ship v1 without OCR. Design pipeline so OCR drops in later. Build variants: light (no OCR) / full.

### 3. Target OS? → **WINDOWS ONLY, personal use. Locked.**
- No macOS/Linux builds, no code signing, no notarization, no auto-update, no installer.
- Deliverable = PyInstaller **one-folder** portable build: copy folder, double-click exe, done.
- QA only on Windows 10/11. This removes ~30% of packaging/QA work.

### 4. Reader stack? → **Converter in Python; reader format is stack-agnostic.**
Converter = Python + PySide6. `book.json` = plain JSON + offsets, consumable by any reader stack.

### 5. Cover for TXT imports? → **BOTH: auto-generate + manual override.**
Auto title card on import; "Edit cover" always available.

### 6. Bulk converter? → **BULK-FIRST. Locked.**
- Drag-drop folders, recursive scan, mirror/flat output, skip-existing, pause/resume, retry-failed-only.
- Queue must handle 500+ files without lag (virtualized list, throttled UI).
- CLI twin for scripted bulk runs.

### 7. High speed / no lag? → **SPEED IS A FEATURE. Locked.**
- ProcessPoolExecutor (workers = cores-1), PyMuPDF + lxml fast path only, OCR off by default, streaming page-by-page, one-folder build for instant startup.
- Fast/Balanced/Best presets + Text-only toggle.
- Benchmark tests in CI; speed targets in §4B.

### Summary table
| # | Decision | Call |
|---|---|---|
| 1 | Format | Sidecar (`txt + json + assets/`) |
| 2 | OCR | Optional plugin, OFF by default |
| 3 | OS | **Windows only, personal use** — portable one-folder, no signing |
| 4 | Stack | Converter: Python/PySide6. Format: stack-agnostic JSON |
| 5 | TXT covers | Auto-generate + manual override |
| 6 | Bulk | **Bulk-first:** folder drop, recursive, skip-existing, pause/resume |
| 7 | Speed | **ProcessPool + PyMuPDF/lxml, workers=cores-1, throttled UI, one-folder build** |

---

*Plan mode only — no implementation code yet. Next step on your go-ahead: scaffold M0 CLI + bulk engine (M0+M2 combined for speed-first build).*
