"""EPUB pipeline: zip -> container.xml -> OPF -> spine -> XHTML -> txt + assets.

Fast path: lxml (C). Never BeautifulSoup.
"""
from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from lxml import etree, html as lhtml

from .images import (
    generate_title_card,
    is_decorative_name,
    normalize_and_save,
    save_cover_image,
    sha256_bytes,
)
from .normalize import clean_block, normalize_document

NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}

SKIP_TAGS = {"script", "style", "nav", "head", "title", "meta", "link"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "blockquote", "pre", "figcaption"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def _find_opf_path(zf: zipfile.ZipFile) -> str:
    # container.xml
    try:
        data = zf.read("META-INF/container.xml")
        root = ET.fromstring(data)
        for el in root.iter():
            if _local(el.tag) == "rootfile":
                full = el.get("full-path")
                if full and full in zf.namelist():
                    return full
    except Exception:
        pass
    # Fallback: any .opf
    for name in zf.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise ValueError("EPUB: no OPF found (container.xml missing and no .opf)")


def _parse_opf(zf: zipfile.ZipFile, opf_path: str) -> dict:
    data = zf.read(opf_path)
    root = ET.fromstring(data)
    base_dir = posixpath.dirname(opf_path)

    def text_of(path: str) -> str:
        el = root.find(path, NS)
        return (el.text or "").strip() if el is not None and el.text else ""

    title = text_of(".//dc:title") or "Untitled"
    author = text_of(".//dc:creator")
    language = text_of(".//dc:language") or "en"

    manifest: dict[str, dict] = {}
    for item in root.iter():
        if _local(item.tag) == "item":
            iid = item.get("id")
            href = item.get("href", "")
            if iid and href:
                manifest[iid] = {
                    "href": posixpath.normpath(posixpath.join(base_dir, href)) if base_dir else href,
                    "media_type": item.get("media-type", ""),
                    "properties": item.get("properties", ""),
                }

    spine: list[str] = []
    for itemref in root.iter():
        if _local(itemref.tag) == "itemref":
            idref = itemref.get("idref")
            if idref and idref in manifest:
                spine.append(manifest[idref]["href"])

    # EPUB2 cover meta: <meta name="cover" content="id"/>
    cover_id = None
    for el in root.iter():
        if _local(el.tag) == "meta" and (el.get("name") == "cover"):
            cover_id = el.get("content")

    return {
        "title": title, "author": author, "language": language,
        "manifest": manifest, "spine": spine, "cover_id": cover_id,
        "base_dir": base_dir,
    }


def _resolve_href(base_file: str, src: str) -> str:
    src = src.split("#")[0].split("?")[0]
    if src.startswith("/"):
        return src.lstrip("/")
    base_dir = posixpath.dirname(base_file)
    return posixpath.normpath(posixpath.join(base_dir, src)) if base_dir else posixpath.normpath(src)


def _extract_cover(zf: zipfile.ZipFile, opf: dict, assets_dir: Path) -> dict | None:
    manifest = opf["manifest"]
    candidates: list[str] = []

    # 1. EPUB3 cover-image property
    for info in manifest.values():
        if "cover-image" in info.get("properties", ""):
            candidates.append(info["href"])
    # 2. EPUB2 meta cover id
    if opf.get("cover_id") and opf["cover_id"] in manifest:
        candidates.append(manifest[opf["cover_id"]]["href"])
    # 3. cover.xhtml / cover.html in spine/manifest
    for href in opf["spine"]:
        if "cover" in href.lower() and href.lower().endswith((".xhtml", ".html", ".htm")):
            candidates.append(href)
    # 4. filename contains cover + image type
    for info in manifest.values():
        if "cover" in info["href"].lower() and info["media_type"].startswith("image/"):
            candidates.append(info["href"])
    # 5. first large image in manifest (heuristic, validated later)
    for info in manifest.values():
        if info["media_type"].startswith("image/"):
            candidates.append(info["href"])

    seen = set()
    for href in candidates:
        if href in seen:
            continue
        seen.add(href)
        if href not in zf.namelist():
            continue
        # If candidate is XHTML, pull first <img> from it
        if href.lower().endswith((".xhtml", ".html", ".htm")):
            try:
                tree = lhtml.fromstring(zf.read(href))
                img_el = tree.find(".//img")
                if img_el is not None and img_el.get("src"):
                    href = _resolve_href(href, img_el.get("src"))
                    if href not in zf.namelist():
                        continue
                else:
                    continue
            except Exception:
                continue
        try:
            data = zf.read(href)
        except Exception:
            continue
        saved = save_cover_image(data, assets_dir)
        if saved:
            return saved
    return None


def _node_text(node) -> str:
    try:
        return clean_block(" ".join(node.itertext()))
    except Exception:
        return ""


def convert_epub(
    src: Path,
    out_book_dir: Path,
    *,
    text_only: bool = False,
    max_image_side: int = 1600,
    chapter_separator: str = "\n\n=== Chapter ===\n\n",
) -> dict:
    """Convert one EPUB. Returns dict with text, metadata, assets, markers, cover."""
    assets_dir = out_book_dir / "assets"
    assets: list[dict] = []
    markers: list[dict] = []
    hash_to_asset: dict[str, dict] = {}
    img_counter = [0]

    def save_image(data: bytes, src_name: str, caption: str = "", alt: str = "") -> dict | None:
        if text_only:
            return None
        if is_decorative_name(src_name):
            return None
        h = sha256_bytes(data)
        if h in hash_to_asset:
            return hash_to_asset[h]
        img_counter[0] += 1
        asset_id = f"img_{img_counter[0]:04d}"
        saved = normalize_and_save(data, assets_dir, asset_id=asset_id, max_side=max_image_side)
        if not saved:
            return None
        asset = {"id": asset_id, **saved, "caption": caption, "alt": alt}
        assets.append(asset)
        hash_to_asset[h] = asset
        return asset

    with zipfile.ZipFile(src) as zf:
        # Zip bomb guard: total uncompressed size limit (500 MB)
        total = sum(i.file_size for i in zf.infolist())
        if total > 500 * 1024 * 1024:
            raise ValueError(f"EPUB too large ({total//1024//1024} MB uncompressed) — possible zip bomb")

        # DRM check
        if "META-INF/encryption.xml" in zf.namelist():
            # Not all encryption.xml means DRM (fonts obfuscation exists) — warn in log, continue
            pass

        opf_path = _find_opf_path(zf)
        opf = _parse_opf(zf, opf_path)
        spine = opf["spine"]
        if not spine:
            # Fallback: all XHTML in manifest order
            spine = [v["href"] for v in opf["manifest"].values()
                     if v["media_type"] in ("application/xhtml+xml", "text/html")]

        cover = None
        if not text_only:
            cover = _extract_cover(zf, opf, assets_dir)
        if cover is None:
            cover = generate_title_card(assets_dir, opf["title"], opf["author"])

        blocks: list[str] = []
        # Running text length for offsets (approx char offset in final txt)
        running_len = [0]

        def emit(text: str, kind: str = "paragraph"):
            if not text:
                return
            if kind == "heading":
                blocks.append(f"\n{text}\n")
            elif kind == "bullet":
                blocks.append(f"• {text}")
            elif kind == "quote":
                blocks.append(f"  {text}")
            else:
                blocks.append(text)
            running_len[0] += len(text) + 2

        def emit_image(asset: dict, caption: str = ""):
            if asset is None:
                return
            markers.append({"type": "image", "id": asset["id"], "offset": running_len[0]})
            blocks.append(f"[[img:{asset['id']}]]")
            if caption:
                blocks.append(caption)
            running_len[0] += len(asset["id"]) + 10

        parser = lhtml.HTMLParser(recover=True, encoding="utf-8")

        for href in spine:
            if href not in zf.namelist():
                continue
            if not href.lower().endswith((".xhtml", ".html", ".htm", ".xml")):
                continue
            try:
                raw = zf.read(href)
            except Exception:
                continue
            try:
                tree = lhtml.fromstring(raw, parser=parser)
            except Exception:
                continue

            # Chapter separator between spine items (not before first)
            if blocks:
                blocks.append(chapter_separator.strip())

            # Recursive walk
            def walk(node):
                if node is None:
                    return
                # Comments / processing instructions
                if not isinstance(node.tag, str):
                    return
                tag = _local(node.tag)

                if tag in SKIP_TAGS:
                    return
                if tag == "img":
                    src_attr = node.get("src") or ""
                    if src_attr and not text_only:
                        resolved = _resolve_href(href, src_attr)
                        if resolved in zf.namelist():
                            try:
                                data = zf.read(resolved)
                                asset = save_image(
                                    data, resolved,
                                    caption=node.get("title") or "",
                                    alt=node.get("alt") or "",
                                )
                                emit_image(asset, node.get("title") or node.get("alt") or "")
                            except Exception:
                                pass
                    return
                if tag == "figure":
                    img_el = node.find(".//img")
                    cap_el = node.find(".//figcaption")
                    caption = _node_text(cap_el) if cap_el is not None else ""
                    if img_el is not None:
                        src_attr = img_el.get("src") or ""
                        if src_attr and not text_only:
                            resolved = _resolve_href(href, src_attr)
                            if resolved in zf.namelist():
                                try:
                                    data = zf.read(resolved)
                                    asset = save_image(data, resolved, caption=caption,
                                                       alt=img_el.get("alt") or "")
                                    emit_image(asset, caption)
                                    return
                                except Exception:
                                    pass
                    if caption:
                        emit(caption)
                    return
                if tag in HEADING_TAGS:
                    emit(_node_text(node), "heading")
                    return
                if tag == "p":
                    emit(_node_text(node))
                    return
                if tag == "li":
                    emit(_node_text(node), "bullet")
                    return
                if tag == "blockquote":
                    emit(_node_text(node), "quote")
                    return
                if tag == "pre":
                    try:
                        txt = "".join(node.itertext()).strip()
                        if txt:
                            blocks.append(txt)
                    except Exception:
                        pass
                    return
                if tag == "table":
                    for tr in node.iter():
                        if _local(tr.tag) == "tr":
                            cells = [_node_text(c) for c in tr.iter() if _local(c.tag) in ("td", "th")]
                            cells = [c for c in cells if c]
                            if cells:
                                blocks.append("\t".join(cells))
                    return
                if tag == "br":
                    blocks.append("")
                    return

                # Generic container: emit direct text, then recurse
                # Direct text (node.text) that isn't inside a block child
                if node.text and node.text.strip() and tag in ("div", "section", "article", "body", "span"):
                    # Only emit if no block children (avoid duplicates)
                    has_block_child = any(
                        _local(c.tag) in BLOCK_TAGS | HEADING_TAGS | {"table", "figure"}
                        for c in node.iterchildren() if isinstance(c.tag, str)
                    )
                    if not has_block_child:
                        emit(clean_block(node.text))
                for child in node.iterchildren():
                    walk(child)
                    if child.tail and child.tail.strip() and tag in ("div", "section", "article", "body"):
                        # Tail text of inline elements — emit as paragraph if substantial
                        t = clean_block(child.tail)
                        if len(t) > 2:
                            emit(t)

            walk(tree)

    raw_text = "\n\n".join(b for b in blocks if b is not None)
    text = normalize_document(raw_text)

    return {
        "text": text,
        "title": opf["title"],
        "author": opf["author"],
        "language": opf["language"],
        "cover": cover,
        "assets": assets,
        "markers": markers,
        "chapters": len(spine),
        "source_type": "epub",
    }
