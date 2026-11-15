"""PyInstaller entry point for the GUI build.

Run as script (not -m) so relative imports inside the converter package work
when frozen. Dev usage: python -m converter.gui  OR  python run_gui.py
"""
import sys

from converter.gui import main

if __name__ == "__main__":
    sys.exit(main())
