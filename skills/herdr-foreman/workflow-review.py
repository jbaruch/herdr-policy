#!/usr/bin/env python3
"""Bind a saved canonical PR snapshot after reading every body in full.

Usage: python3 workflow-review.py <snapshot.json>
stdout: schema-1 identity JSON (sha256, PR, head and body counts).
stderr: actionable failures. Exit 0 identity only; 2 invalid/unreadable input.
No API, worker, checkout or owner state is read or changed. A digest grants
neither reading credit nor merge permission; see the workflow report contract.
"""

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from foreman.errors import ForemanError
from foreman.workflow_review import identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        with args.snapshot.open("rb") as stream:
            raw = stream.read(2_097_153)
        if len(raw) > 2_097_152:
            raise ValueError("snapshot exceeds 2 MiB; retain its source for a bounded reading decision")
        result = identity(json.loads(raw))
    except (OSError, ValueError, UnicodeError, ForemanError) as exc:
        print("workflow-review: {}. Restore the complete current canonical snapshot before claiming its reading.".format(exc), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
