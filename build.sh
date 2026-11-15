#!/usr/bin/env bash
# Dev/test build (Linux/macOS). For Windows use build.bat.
set -euo pipefail
cd "$(dirname "$0")"

python3 --version
python3 -m pip install -r requirements.txt pyinstaller

echo "Building GUI (one-folder)..."
python3 -m PyInstaller --noconfirm --windowed --name Converter \
  --collect-all pymupdf --collect-all lxml --collect-all PySide6 \
  -p . run_gui.py

echo "Building CLI (one-folder)..."
python3 -m PyInstaller --noconfirm --console --name converter-cli \
  --collect-all pymupdf --collect-all lxml \
  -p . run_cli.py

echo "Build complete: dist/Converter/ dist/converter-cli/"
