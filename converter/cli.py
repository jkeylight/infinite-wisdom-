"""CLI twin: same engine as GUI. Bulk-first.

Examples:
  python -m converter C:\\Books\\ -o C:\\Converted\\ --workers 8 --skip-existing
  python -m converter book.epub -o Converted --text-only
  python -m converter a.pdf b.epub -o out --preset fast
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .bulk import run_bulk, summarize


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="converter-cli",
        description="EPUB/PDF -> TXT bulk converter (sidecar: content.txt + book.json + assets/)",
    )
    p.add_argument("inputs", nargs="+", help="Files and/or folders (.epub/.pdf). Folders are scanned recursively.")
    p.add_argument("-o", "--output", default="Converted", help="Output root folder (default: Converted)")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                   help="Parallel workers (default: CPU cores - 1). Use 1 for single-file debug.")
    p.add_argument("--preset", choices=["fast", "balanced", "best"], default="balanced",
                   help="Fast: 1200px/150dpi. Balanced: 1600px/200dpi. Best: 1600px/300dpi.")
    p.add_argument("--text-only", action="store_true", help="Fastest mode: skip all image extraction.")
    p.add_argument("--ocr", action="store_true",
                   help="Out of scope for v1 (kept for compatibility; scanned pages are skipped with a warning).")
    p.add_argument("--skip-existing", action="store_true", default=True,
                   help="Skip files already converted and newer than source (default: on).")
    p.add_argument("--no-skip-existing", dest="skip_existing", action="store_false",
                   help="Force re-convert everything.")
    p.add_argument("--layout", choices=["mirror", "flat", "same"], default="mirror",
                   help="mirror: preserve folder structure. flat: all in output root. same: next to source.")
    p.add_argument("-v", "--verbose", action="store_true", help="Show per-file details.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    start = time.perf_counter()

    def progress(done, total, result):
        if args.verbose:
            if result.status == "ok":
                print(f"[{done}/{total}] OK  {Path(result.source).name} "
                      f"({result.duration_sec:.2f}s, {result.images} images) -> {result.output_dir}")
            elif result.status == "skipped":
                print(f"[{done}/{total}] SKIP {Path(result.source).name} (already converted)")
            else:
                print(f"[{done}/{total}] FAIL {Path(result.source).name}: {result.error}")
        else:
            # Compact progress: one line per file, throttled by print itself
            icon = {"ok": "✓", "skipped": "↷", "failed": "✗"}.get(result.status, "?")
            print(f"[{done}/{total}] {icon} {Path(result.source).name}")

    results = run_bulk(
        args.inputs,
        Path(args.output),
        workers=args.workers,
        preset=args.preset,
        text_only=args.text_only,
        ocr=args.ocr,
        skip_existing=args.skip_existing,
        layout=args.layout,
        progress_cb=progress,
    )

    print()
    print(summarize(results))
    print(f"Wall time: {time.perf_counter() - start:.1f}s | Workers: {args.workers} | Preset: {args.preset}")
    failed = [r for r in results if r.status == "failed"]
    if failed:
        print("\nFailed files:")
        for r in failed:
            print(f"  - {r.source}: {r.error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
