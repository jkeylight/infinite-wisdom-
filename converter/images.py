"""Image handling: dedupe, downscale, format normalize, title-card cover.

Fast path: Pillow (C). Skip decorative/tiny images early.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Decorative filename hints (EPUB ornaments)
_DECORATIVE_HINTS = ("spacer", "bullet", "ornament", "separator", "line", "pixel", "blank")
MIN_IMAGE_SIDE = 64
MIN_COVER_SIDE = 200


def is_decorative_name(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in _DECORATIVE_HINTS)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pil_open(data: bytes) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception:
        return None


def _bake_orientation(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation if present."""
    try:
        exif = img.getexif()
        if exif:
            orientation = exif.get(274)  # 0x0112
            if orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)
    except Exception:
        pass
    return img


def normalize_and_save(
    data: bytes,
    assets_dir: Path,
    *,
    asset_id: str,
    max_side: int = 1600,
    force_ext: str | None = None,
    min_side: int = MIN_IMAGE_SIDE,
) -> dict | None:
    """Normalize image bytes and save to assets_dir. Returns asset dict or None if skipped.

    Returns dict with file, width, height, format. Caller adds id/caption/alt.
    """
    img = _pil_open(data)
    if img is None:
        return None
    img = _bake_orientation(img)
    w, h = img.size
    if w < min_side or h < min_side:
        return None

    # Downscale
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        w, h = img.size

    # Choose format: keep transparency as PNG, else WebP if available else JPEG
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if force_ext:
        ext = force_ext.lstrip(".").lower()
    elif has_alpha:
        ext = "png"
    else:
        try:
            Image.new("RGB", (1, 1)).save(io.BytesIO(), format="WEBP")
            ext = "webp"
        except Exception:
            ext = "jpg"

    if ext in ("jpg", "jpeg", "webp"):
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
    elif ext == "png" and img.mode not in ("RGBA", "RGB", "L"):
        img = img.convert("RGBA")

    assets_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_id}.{ext}"
    out_path = assets_dir / filename
    try:
        if ext == "webp":
            img.save(out_path, format="WEBP", quality=80, method=4)
        elif ext in ("jpg", "jpeg"):
            img.save(out_path, format="JPEG", quality=88, optimize=True)
        else:
            img.save(out_path, format="PNG", optimize=True)
    except Exception:
        return None

    return {"file": f"assets/{filename}", "width": w, "height": h, "format": ext}


def save_cover_image(
    data: bytes,
    assets_dir: Path,
    *,
    max_side: int = 1200,
) -> dict | None:
    """Save cover, validating min size. Returns asset dict or None."""
    img = _pil_open(data)
    if img is None:
        return None
    img = _bake_orientation(img)
    w, h = img.size
    if w < MIN_COVER_SIDE or h < MIN_COVER_SIDE:
        return None
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        w, h = img.size
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        try:
            bg.paste(img, mask=img.split()[-1])
        except Exception:
            bg.paste(img)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    assets_dir.mkdir(parents=True, exist_ok=True)
    out_path = assets_dir / "cover.jpg"
    try:
        img.save(out_path, format="JPEG", quality=90, optimize=True)
    except Exception:
        return None
    return {"file": "assets/cover.jpg", "width": w, "height": h, "format": "jpg"}


def generate_title_card(
    assets_dir: Path,
    title: str,
    author: str = "",
) -> dict:
    """Generate a placeholder cover (title card) with Pillow. Always succeeds."""
    W, H = 800, 1200
    # Warm ink + gold palette (matches reader theme)
    img = Image.new("RGB", (W, H), (18, 17, 23))
    draw = ImageDraw.Draw(img)
    gold = (201, 168, 106)
    # Border
    draw.rectangle([24, 24, W - 24, H - 24], outline=gold, width=3)
    # Try a decent font, fall back to default
    def font(size: int):
        for p in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "C:/Windows/Fonts/Georgia.ttf",
            "C:/Windows/Fonts/times.ttf",
        ):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    title = (title or "Untitled").strip() or "Untitled"
    # Wrap title
    tf = font(52)
    words = title.split()
    lines, cur = [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if draw.textlength(trial, font=tf) < W - 160:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    y = H // 2 - (len(lines) * 62) // 2 - 40
    for ln in lines[:6]:
        tw = draw.textlength(ln, font=tf)
        draw.text(((W - tw) / 2, y), ln, fill=(245, 240, 230), font=tf)
        y += 62
    if author:
        af = font(30)
        tw = draw.textlength(author, font=af)
        draw.text(((W - tw) / 2, y + 20), author, fill=gold, font=af)
    # Infinity mark
    inf = font(72)
    mark = "∞"
    tw = draw.textlength(mark, font=inf)
    draw.text(((W - tw) / 2, 90), mark, fill=gold, font=inf)

    assets_dir.mkdir(parents=True, exist_ok=True)
    out_path = assets_dir / "cover.jpg"
    img.save(out_path, format="JPEG", quality=90, optimize=True)
    return {"file": "assets/cover.jpg", "width": W, "height": H, "format": "jpg"}
