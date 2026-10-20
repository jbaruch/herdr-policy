#!/usr/bin/env python3
"""Summarize a snapshot, or collect selected frozen evidence through its owner."""

import sys

sys.dont_write_bytecode = True

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foreman import coordination_metrics, measurement_capture


def main():
    if sys.argv[1:2] == ["collect"]:
        return measurement_capture.main(sys.argv[2:])
    return coordination_metrics.main()


if __name__ == "__main__":
    raise SystemExit(main())
