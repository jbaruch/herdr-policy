#!/usr/bin/env python3
"""Summarize a sanitized measurement snapshot through the installed owner."""

import sys

sys.dont_write_bytecode = True

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foreman.coordination_metrics import main


if __name__ == "__main__":
    raise SystemExit(main())
