"""Printed-byte budgets for current-context views; never task authority.

Owners supply a pure page builder. Shrinking its page retains its ordering,
totals and continuation instead of truncating a record or hiding obligations.
An indivisible oversized record refuses. Persisted owner schemas are unchanged.
"""

import json

from .errors import UsageError

OUTPUT_BYTES = 16_384
VIEW_SCHEMA_VERSION = 2
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def validate_page(limit, offset):
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT or type(offset) is not int or offset < 0:
        raise UsageError("Use --limit 1–{} and a nonnegative --offset; follow next_offset for another page.".format(MAX_LIMIT), {})


def page(rows, offset, limit):
    selected = rows[offset:offset + limit]
    return {"total": len(rows), "offset": offset, "limit": limit, "returned": len(selected),
            "omitted": len(rows) - len(selected),
            "next_offset": offset + len(selected) if offset + len(selected) < len(rows) else None,
            "items": selected}


def validate_sequence(through, after):
    if type(after) is not int or not 0 <= after <= through:
        raise UsageError("Use a nonnegative --after sequence within the selected through snapshot.", {})


def sequence_page(rows, through, after, limit, key):
    """A stable event cursor even when earlier returned events are acknowledged."""
    validate_sequence(through, after)
    later = [row for row in rows if key(row) > after]
    selected = later[:limit]
    return {"through": through, "after": after, "limit": limit, "total": len(rows),
            "earlier_pending": len(rows) - len(later), "returned": len(selected),
            "omitted": len(rows) - len(selected),
            "next_after": key(selected[-1]) if len(later) > len(selected) else None,
            "items": selected}


def bounded(result):
    result["schema_version"] = VIEW_SCHEMA_VERSION
    result["authorizes_progression"] = False
    result["budget"] = {"output_bytes": OUTPUT_BYTES}
    if len((json.dumps(result, indent=2) + "\n").encode("utf-8")) > OUTPUT_BYTES:
        raise UsageError(
            "Current context exceeds its printed output budget. Keep unexamined obligations unresolved; select a narrower task or evidence question instead of dumping history.",
            {"reason": "context_budget_exceeded", "budget_bytes": OUTPUT_BYTES, "context_complete": False})
    return result


def fit_pages(builder, limit, offset):
    validate_page(limit, offset)
    for effective in range(limit, 0, -1):
        result = builder(effective)
        try:
            return bounded(result)
        except UsageError:
            if effective == 1:
                raise
    raise AssertionError("A validated page always has a positive limit.")
