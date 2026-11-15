"""PyInstaller entry point for the CLI build.

Dev usage: python -m converter  OR  python run_cli.py
"""
import sys

from converter.cli import main

if __name__ == "__main__":
    sys.exit(main())
