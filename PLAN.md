# EPUB + PDF → TXT Converter — Robust Desktop App
## Plan Mode Only — No Code Yet

**Goal:** Build a robust desktop converter that turns EPUB and PDF books into clean TXT files for your ebook reader, **including book cover extraction and images/diagrams handling** — even though TXT itself cannot store images.

**Repo:** `infinite-wisdom-` (connected, currently empty — this plan is the first commit)

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

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Best EPUB/PDF parsing ecosystem, easy multiprocessing |
| GUI | **PySide6 (Qt)** | Mature, cross-platform, drag-drop, progress UI |
| EPUB parsing | `zipfile` + `lxml` directly | `ebooklib` is thinly maintained — use it as wrapper, bypass when it fails |
| PDF parsing | **PyMuPDF (`fitz`)** primary, `pdfplumber` fallback, `pypdf` for probing | Fast, gives text + bounding boxes + font info |
| OCR (optional) | `pytesseract` + bundled Tesseract | For scanned PDFs |
| Packaging | PyInstaller (one-folder) | Bundle Tesseract + 2-3 languages only (size control) |
| Worker model | One child process per file | A bad file never kills the GUI |

**Rejected:** Electron (weak PDF text extraction), Tauri/Rust (rebuild all parsing logic), .NET (weaker OCR/layout tooling).

---

## 4. Converter Architecture

```
┌──────────────── GUI (PySide6) ────────────────┐
│ Drop zone · file queue · options · progress   │
└──────────────┬────────────────────────────────┘
               │ job specs
       ┌───────▼────────┐
       │  Job Manager   │ queue, cancel, retry, isolation
       └───────┬────────┘
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

**Key principle:** GUI never touches parsing code directly. Each conversion runs in an isolated child process with timeout (e.g. 5 min/file) and memory ceiling. This single decision buys most of your robustness.

---

## 5. EPUB Pipeline

1. **Validate container:** Open as zip, find `META-INF/container.xml`, resolve OPF path. Fallback: scan for `*.opf` if container is malformed.
2. **Parse OPF:** Read `<manifest>` + `<spine>` → **spine order is reading order** (not file order — this is where naive converters fail).
3. **Encryption check:** `META-INF/encryption.xml` → if DRM/obfuscated, report clearly, don't produce garbage.
4. **Per spine item (XHTML):**
   - Parse with `lxml` in recover mode (tolerate broken markup)
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
3. **Extraction (PyMuPDF):** Get blocks with bounding boxes + font info
4. **Reading order:** Sort top-to-bottom, left-to-right. For multi-column: cluster by x-ranges, read column-by-column (XY-cut / histogram of block x-centers)
5. **Header/footer removal:** Lines repeated at same y-position across ≥N pages (page numbers, running heads) → drop. This alone massively improves quality.
6. **OCR path (optional toggle):** Rasterize at 300 DPI → Tesseract (`--psm` tuned per layout). Cache by page hash.
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

## 10. GUI Design

- **Main window:** Drop zone, file list (name, type, size, status, message), Add Files/Folder, Remove, Convert, Cancel
- **Options (per-job defaults + per-file override):** output folder, chapter separators, OCR on/off + language, encoding, line endings, metadata header, keep footnotes/TOC, page markers
- **Progress:** Per-file bar + overall, ETA, live log pane
- **Preview:** Side-by-side "first 2 KB of source vs output" before committing a large batch
- **Presets:** "Clean novel", "Academic paper", "Scanned book (OCR)"
- **Errors:** Non-modal report, "open log", "retry with fallback"
- **CLI twin:** Same engine — `converter-cli in/ out/ --ocr --preset clean-novel` (essential for testing + power users)

---

## 11. Robustness Checklist

- [ ] Process isolation + per-file timeout + memory cap
- [ ] Atomic writes (temp file → rename); never leave half-written `.txt`
- [ ] Disk-space + permission checks before batch
- [ ] Unicode decode fallback chain; log chosen encoding
- [ ] Handle: zero-byte files, wrong extensions, zip bombs (size limits), 10k-page PDFs (stream page-by-page, don't hold all text in RAM)
- [ ] Encrypted/DRM → clear message, no crash
- [ ] Cancel mid-batch leaves completed files valid
- [ ] Crash reporting (local log file), no telemetry by default
- [ ] One bad page/file never aborts the document — collect errors per page, continue

---

## 12. Testing Strategy

- **Corpus (~50 fixtures):** clean EPUB2/EPUB3, fixed-layout EPUB, broken OPF, DRM sample, single-column PDF, two-column paper, scanned book, RTL, CJK, math-heavy, malformed PDF, 0-byte file
- **Golden-file tests:** expected `.txt` + `book.json` per fixture, diffed in CI
- **Fuzz:** random truncation/corruption → assert "no crash, error reported"
- **Property tests:** output always valid UTF-8; line endings respected; no control chars; every marker in TXT has a matching asset in JSON
- **Manual QA matrix:** Windows 10/11, macOS (arm64 + x86), Ubuntu

---

## 13. Milestones

| Milestone | Deliverable | Est. |
|---|---|---|
| **M0** | CLI only: EPUB spine→text + single-column PDF→text, normalization, golden tests on 10 fixtures | 3–4 days |
| **M1** | Multi-column PDF, header/footer removal, dehyphenation, per-page error collection | 1 wk |
| **M2** | OCR path, encryption handling, process isolation, timeouts | 1 wk |
| **M3** | `book.json` schema frozen; EPUB cover chain + inline images (extract, SVG rasterize, dedupe, markers, captions) | 1 wk |
| **M4** | Reader: inline image widgets, lazy load, tap-to-zoom, missing-asset fallback, cover thumbnails | 1 wk |
| **M5** | PDF figure extraction via clip-render; caption heuristic; PDF cover = page-1 render | 1 wk |
| **M6** | PySide6 GUI: queue, options, progress, preview, cancel, presets | 1–2 wk |
| **M7** | Packaging, signing, installers, docs, full corpus CI | 3–4 days |
| **M8** | Polish: storage budget/downscaling, CLI parity, crash logs, performance tuning | ongoing |

---

## 14. Main Risks & Mitigations

| Risk | Mitigation |
|---|---|
| PDF reading order is biggest quality risk | Start with XY-cut; add "preview & manual column hint" escape hatch |
| OCR adds ~100 MB (Tesseract) | Optional build variant `--with-ocr` |
| `ebooklib` thinly maintained | Wrap it; keep direct zip+OPF fallback |
| Scope creep toward layout fidelity | Freeze v1 on plain-text fidelity only |
| SVG with external refs (fonts/images) | Rasterize with refs inlined, else placeholder |
| Fixed-layout / comic EPUBs | Detect + warn "text conversion not meaningful" — out of scope v1 |
| CMYK / 16-bit images break readers | Convert to sRGB 8-bit on import |

---

## 15. Open Decisions (Need Your Call Before Building)

1. **Single-file vs sidecar?** Plan recommends sidecar (`content.txt` + `book.json` + `assets/`). Confirm?
2. **OCR in v1 or later?** Adds size/complexity. Plan puts it in M2.
3. **Target OS first?** Windows / macOS / Linux — affects packaging/signing order.
4. **Reader stack?** Is your reader Python/Qt, Electron, Flutter, native? Affects how `book.json` offsets/markers are consumed.
5. **Cover for TXT imports:** Auto-generate title card, or manual upload only?

---

*Plan mode only — no implementation code yet. Next step on your go-ahead: scaffold M0 CLI + fixture corpus.*
