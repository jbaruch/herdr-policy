#!/usr/bin/env python3
"""Compatibility entrypoint for the packaged coordination measurement owner."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/herdr-foreman"))

from foreman.coordination_metrics import main, summarize

__all__ = ["main", "summarize"]


if __name__ == "__main__":
    raise SystemExit(main())
