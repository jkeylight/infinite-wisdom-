"""PyInstaller entry point for the GUI build.

Run as script (not -m) so relative imports inside the converter package work
when frozen. Dev usage: python -m converter.gui  OR  python run_gui.py

IMPORTANT (Windows frozen multiprocessing):
multiprocessing.freeze_support() MUST be called before anything else.
Without it, each ProcessPool worker re-executes this script as a new
process and opens another GUI window (3 workers = 3 windows), then crashes.
"""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from converter.gui import main
    sys.exit(main())
