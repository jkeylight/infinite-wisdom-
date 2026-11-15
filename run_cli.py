"""PyInstaller entry point for the CLI build.

Dev usage: python -m converter  OR  python run_cli.py

freeze_support() is required for frozen multiprocessing on Windows
(see run_gui.py for details).
"""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from converter.cli import main
    sys.exit(main())
