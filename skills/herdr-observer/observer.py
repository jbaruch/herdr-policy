#!/usr/bin/env python3
"""Installed entrypoint. Only the co-shipped package is added to the import path."""

from pathlib import Path
import sys


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from factory_observer.cli import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
