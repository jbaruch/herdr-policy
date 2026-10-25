#!/usr/bin/env python3
"""Print one bounded private owner projection; no runtime effects or migration.

argv: --state PATH, --section binding|current|closures, --offset N, --limit N.
stdout: observer_projection JSON page; stderr: actionable error. Exit 0 success,
2 unusable evidence or usage. State and supervision schemas remain owner-owned.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foreman.context_output import validate_page
from foreman.errors import ForemanError, StateError, UsageError
from foreman.observer_projection import SECTIONS, view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--section", choices=SECTIONS, default="current")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    try:
        validate_page(args.limit, args.offset)
    except UsageError as exc:
        print(json.dumps({"error": "owner_projection_invalid_page", "recovery": exc.message}), file=sys.stderr)
        return 2
    try:
        result = view(args.state, args.section, offset=args.offset, limit=args.limit)
    except (ForemanError, OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        reason = ("owner_schema_unsupported" if isinstance(exc, StateError) else
                  "owner_projection_row_exceeds_budget" if isinstance(exc, ForemanError) else
                  "owner_projection_source_unreadable" if isinstance(exc, OSError) else "owner_projection_source_invalid")
        print(json.dumps({"error": reason, "recovery": "Preserve the original owner. Inspect this selected observer-view section and restore its supported readable metadata; no migration or runtime action was attempted."}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
