#!/usr/bin/env python3
"""Summarize a sanitized measurement snapshot through the installed owner."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foreman.coordination_metrics import main


if __name__ == "__main__":
    raise SystemExit(main())
