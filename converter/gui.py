"""GUI stub — M6 PySide6 bulk queue (next milestone).

The CLI engine (bulk.py + engine.py) is GUI-ready:
- run_bulk(..., progress_cb=...) already supports throttled UI callbacks
- ConvertResult carries per-file status/duration/images for the queue table
- Workers default to cores-1 so the GUI thread stays responsive

Planned GUI (M6):
  - Drop zone (files + folders), virtualized queue table (1,000 rows, no lag)
  - Workers slider, Fast/Balanced/Best presets, Text-only toggle
  - Start/Pause/Resume/Cancel, Retry-Failed-Only, live ETA + files/min
  - Preview pane (first 2 KB source vs output)
  - Windows portable build: PyInstaller one-folder, no signing (personal use)

Run the CLI today:
  python -m converter C:\\Books\\ -o C:\\Converted\\ --workers 8
"""
from __future__ import annotations


def main() -> None:
    print(__doc__)
    print("GUI is M6 — use the CLI for now:  python -m converter <folder> -o <output>")


if __name__ == "__main__":
    main()
