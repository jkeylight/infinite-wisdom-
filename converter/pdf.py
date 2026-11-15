"""PDF pipeline: probe -> per-page extract (PyMuPDF fast path) -> normalize.

Streaming page-by-page. OCR is out of scope for v1 (user decision) —
scanned pages are skipped with a warning.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

try:
    import pymupdf  # PyMuPDF >= 1.24 (new name)
except ImportError:  # pragma: no cover - older installs
    import fitz as pymupdf  # type: ignore

from .images import generate_title_card, normalize_and_save, sha256_bytes
from .normalize import clean_block, normalize_document

MIN_TEXT_CHARS = 20  # below this, page is considered scanned/image-only


def _detect_two_columns(blocks: list, page_width: float) -> bool:
    """Heuristic: middle vertical band (45-55%) rarely crossed by blocks."""
    if len(blocks) < 6:
        return False
    mid_lo, mid_hi = page_width * 0.45, page_width * 0.55
    crossing = 0
    for b in blocks:
        x0, _, x1 = b[0], b[1], b[2]
        if x0 < mid_lo and x1 > mid_hi:
            crossing += 1
    return crossing <= max(1, len(blocks) // 10)


def _sort_blocks(blocks: list, page_width: float) -> list:
    """Reading order: column-by-column if two-column, else top-to-bottom."""
    text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
    if _detect_two_columns(text_blocks, page_width):
        mid = page_width / 2
        left = sorted([b for b in text_blocks if (b[0] + b[2]) / 2 < mid], key=lambda b: (b[1], b[0]))
        right = sorted([b for b in text_blocks if (b[0] + b[2]) / 2 >= mid], key=lambda b: (b[1], b[0]))
        return left + right
    return sorted(text_blocks, key=lambda b: (round(b[1] / 4), b[0]))


def _collect_header_footer_candidates(doc) -> set[str]:
    """Lines repeated across many pages at top/bottom — likely running heads."""
    counter: Counter[str] = Counter()
    n = doc.page_count
    if n < 5:
        return set()
    for i in range(n):
        page = doc[i]
        blocks = page.get_text("blocks")
        if not blocks:
            continue
        ordered = _sort_blocks(blocks, page.rect.width)
        if not ordered:
            continue
        first = clean_block(ordered[0][4])
        last = clean_block(ordered[-1][4])
        if first:
            counter[first] += 1
        if last:
            counter[last] += 1
    threshold = max(3, n * 0.3)
    return {line for line, c in counter.items() if c >= threshold and len(line) < 120}


def convert_pdf(
    src: Path,
    out_book_dir: Path,
    *,
    text_only: bool = False,
    max_image_side: int = 1600,
    figure_dpi: int = 200,
    ocr: bool = False,
) -> dict:
    assets_dir = out_book_dir / "assets"
    assets: list[dict] = []
    markers: list[dict] = []
    hash_to_asset: dict[str, dict] = {}
    img_counter = [0]
    running_len = [0]
    warnings: list[str] = []

    def save_rendered_image(pix, caption: str = "") -> dict | None:
        if text_only:
            return None
        try:
            data = pix.tobytes("png")
        except Exception:
            return None
        h = sha256_bytes(data)
        if h in hash_to_asset:
            return hash_to_asset[h]
        img_counter[0] += 1
        asset_id = f"img_{img_counter[0]:04d}"
        saved = normalize_and_save(data, assets_dir, asset_id=asset_id, max_side=max_image_side)
        if not saved:
            return None
        asset = {"id": asset_id, **saved, "caption": caption, "alt": ""}
        assets.append(asset)
        hash_to_asset[h] = asset
        return asset

    doc = pymupdf.open(str(src))
    try:
        if doc.needs_pass:
            raise ValueError("PDF is encrypted (password required) — skipped")
        meta = doc.metadata or {}
        title = (meta.get("title") or src.stem or "Untitled").strip()
        author = (meta.get("author") or "").strip()
        page_count = doc.page_count

        # Cover: render page 1 (deterministic, always works)
        cover = None
        if not text_only and page_count > 0:
            try:
                pix = doc[0].get_pixmap(dpi=150)
                data = pix.tobytes("png")
                from .images import save_cover_image
                cover = save_cover_image(data, assets_dir)
            except Exception:
                cover = None
        if cover is None:
            cover = generate_title_card(assets_dir, title, author)

        hf_candidates = _collect_header_footer_candidates(doc)

        all_blocks: list[str] = []
        scanned_pages = 0

        for pno in range(page_count):
            page = doc[pno]
            page_w = page.rect.width
            page_h = page.rect.height
            page_area = page_w * page_h
            blocks = page.get_text("blocks")
            ordered = _sort_blocks(blocks, page_w) if blocks else []
            page_text_len = sum(len(b[4]) for b in ordered)

            if page_text_len < MIN_TEXT_CHARS:
                scanned_pages += 1
                warnings.append(f"Page {pno+1}: scanned image — no text layer, skipped (OCR out of scope for v1)")
                all_blocks.append(f"[Page {pno+1}: scanned image]")
                continue

            # Figure extraction via clip-render (before text, so markers land near top)
            figure_markers_here: list[str] = []
            if not text_only:
                try:
                    images = page.get_images(full=True)
                    seen_rects = []
                    for img_info in images:
                        xref = img_info[0]
                        try:
                            rects = page.get_image_rects(xref)
                        except Exception:
                            continue
                        for rect in rects:
                            area = rect.width * rect.height
                            if area < page_area * 0.05:  # tiny logo/bullet
                                continue
                            if area > page_area * 0.85:  # full-page scan background
                                continue
                            # Skip overlapping duplicates
                            if any(rect.intersects(r) for r in seen_rects):
                                continue
                            seen_rects.append(rect)
                            try:
                                pix = page.get_pixmap(dpi=figure_dpi, clip=rect)
                                asset = save_rendered_image(pix)
                                if asset:
                                    markers.append({"type": "image", "id": asset["id"],
                                                    "offset": running_len[0], "page": pno + 1})
                                    figure_markers_here.append(f"[[img:{asset['id']}]]")
                            except Exception:
                                continue
                except Exception:
                    pass

            # Text blocks -> paragraphs, dropping header/footer candidates
            page_paras: list[str] = []
            for b in ordered:
                txt = clean_block(b[4])
                if not txt:
                    continue
                if txt in hf_candidates:
                    continue
                # Drop standalone page numbers
                if txt.isdigit() and len(txt) <= 4:
                    continue
                page_paras.append(txt)

            if figure_markers_here:
                all_blocks.extend(figure_markers_here)
                running_len[0] += sum(len(m) + 2 for m in figure_markers_here)
            all_blocks.extend(page_paras)
            running_len[0] += sum(len(p) + 2 for p in page_paras)

        raw_text = "\n\n".join(all_blocks)
        text = normalize_document(raw_text)

        return {
            "text": text,
            "title": title,
            "author": author,
            "language": "en",
            "cover": cover,
            "assets": assets,
            "markers": markers,
            "chapters": page_count,
            "source_type": "pdf",
            "pages": page_count,
            "scanned_pages": scanned_pages,
            "warnings": warnings,
        }
    finally:
        doc.close()
