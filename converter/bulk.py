"""Bulk engine: recursive scan, ProcessPool, skip-existing, mirror/flat layout.

Top-level worker function is picklable for multiprocessing.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .engine import ConvertOptions, ConvertResult, convert_file

SUPPORTED = {".epub", ".pdf"}


def scan_inputs(inputs: list[str | Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED:
                    key = str(f.resolve())
                    if key not in seen:
                        seen.add(key)
                        found.append(f)
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED:
                key = str(p.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(p)
        else:
            # Non-existent path — include so caller reports it as failed
            found.append(p)
    return found


def output_dir_for(src: Path, output_root: Path, layout: str, input_roots: list[Path] | None = None,
                   stem: str | None = None) -> Path:
    """Compute per-book output dir.

    layout:
      mirror — preserve relative path from the input root that contains src
      flat   — all books directly under output_root/<stem>/
      same   — next to source file: <src_dir>/<stem>/
    stem: override for collision disambiguation (e.g. "sample-epub").
    """
    name = stem or src.stem
    if layout == "same":
        return src.parent / name
    if layout == "flat":
        return output_root / name
    # mirror (default)
    if input_roots:
        for root in input_roots:
            try:
                rel = src.resolve().relative_to(root.resolve())
                return output_root / rel.parent / name
            except ValueError:
                continue
    return output_root / name


def _is_already_converted(src: Path, out_dir: Path) -> bool:
    txt = out_dir / "content.txt"
    if not txt.exists():
        return False
    try:
        return txt.stat().st_mtime >= src.stat().st_mtime
    except OSError:
        return False


def _worker(task: tuple[str, str, dict]) -> ConvertResult:
    """Picklable worker: (src, out_dir, options_dict) -> ConvertResult."""
    src_s, out_s, opts = task
    return convert_file(Path(src_s), Path(out_s), ConvertOptions(**opts))


def run_bulk(
    inputs: list[str | Path],
    output_root: Path | None,
    *,
    workers: int = 4,
    preset: str = "balanced",
    text_only: bool = False,
    ocr: bool = False,
    skip_existing: bool = True,
    layout: str = "mirror",
    include_header: bool = True,
    progress_cb=None,  # callable(done, total, result)
) -> list[ConvertResult]:
    """Run bulk conversion. Returns list of results (order not guaranteed)."""
    files = scan_inputs(inputs)
    input_roots = [Path(i) for i in inputs if Path(i).is_dir()]
    output_root = Path(output_root) if output_root else Path("Converted")

    opts = ConvertOptions(preset=preset, text_only=text_only, ocr=ocr, include_header=include_header)
    opts_dict = {"preset": opts.preset, "text_only": opts.text_only, "ocr": opts.ocr,
                 "max_image_side": opts.max_image_side, "figure_dpi": opts.figure_dpi,
                 "include_header": opts.include_header}

    tasks: list[tuple[str, str, dict]] = []
    results: list[ConvertResult] = []
    total = len(files)
    done = 0

    # Collision detection: same stem + same parent in output (e.g. sample.epub + sample.pdf)
    # -> disambiguate with -epub / -pdf suffix so bulk never overwrites.
    from collections import Counter
    _stems = Counter()
    for _f in files:
        if _f.exists():
            _d = output_dir_for(_f, output_root, layout, input_roots)
            _stems[str(_d).lower()] += 1

    for src in files:
        if not src.exists():
            r = ConvertResult(status="failed", source=str(src), error="File not found")
            results.append(r)
            done += 1
            if progress_cb:
                progress_cb(done, total, r)
            continue
        _base_dir = output_dir_for(src, output_root, layout, input_roots)
        stem = src.stem if _stems[str(_base_dir).lower()] <= 1 else f"{src.stem}-{src.suffix.lstrip('.').lower()}"
        out_dir = output_dir_for(src, output_root, layout, input_roots, stem=stem)
        if skip_existing and _is_already_converted(src, out_dir):
            r = ConvertResult(status="skipped", source=str(src), output_dir=str(out_dir),
                              title=src.stem)
            results.append(r)
            done += 1
            if progress_cb:
                progress_cb(done, total, r)
            continue
        tasks.append((str(src), str(out_dir), opts_dict))

    if not tasks:
        return results

    workers = max(1, min(workers, os.cpu_count() or 1))
    if workers == 1 or len(tasks) == 1:
        for task in tasks:
            r = _worker(task)
            results.append(r)
            done += 1
            if progress_cb:
                progress_cb(done, total, r)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_worker, t): t for t in tasks}
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                except Exception as e:
                    src_s = futures[fut][0]
                    r = ConvertResult(status="failed", source=src_s,
                                      error=f"Worker crash: {type(e).__name__}: {e}")
                results.append(r)
                done += 1
                if progress_cb:
                    progress_cb(done, total, r)
    return results


def summarize(results: list[ConvertResult]) -> str:
    ok = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    total_time = sum(r.duration_sec for r in results if r.status == "ok")
    return (f"Done: {ok} converted, {failed} failed, {skipped} skipped "
            f"(total {len(results)} files, {total_time:.1f}s of conversion time)")
