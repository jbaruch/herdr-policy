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
WARNING_BYTES = 4_096

# Foreman-facing knowledge views. Native Stop/executor owners use their own
# observation APIs; this exposure gate never changes their effect authority.
READ_COMMANDS = frozenset({
    "state", "status", "foreman-queue", "workflow-readiness", "cost-report",
    "memory-list", "memory-show", "attention-list", "attention-show", "catch-up",
    "supervision-gate", "supervision-status", "supervision-drain", "supervision-watch",
    "retro-check", "retro-list", "retro-show", "capability-check", "capability-show",
    "report-gate-status", "github-context", "foreman-reset-status",
})


def printed_json(value):
    return json.dumps(value, indent=2) + "\n"


def utf8_size(value: str, label: str):
    """Measure semantic context text without exposing malformed input bytes."""
    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        raise UsageError("Use valid UTF-8 for {} before requesting context. Preserve the original owner and unread evidence while correcting the text.".format(label),
                         {"context_complete": False}) from None


def error_text(error, diagnostics=""):
    """Retain complete JSON errors; never cut an oversized diagnostic in half."""
    result = diagnostics + printed_json(error.to_dict())
    if len(result.encode("utf-8")) <= OUTPUT_BYTES:
        return result
    return printed_json(UsageError(
        "The requested operation failed and its diagnostic exceeds the context budget. Preserve the original owner records, holds and unknown outcomes; narrow the evidence question or repair the source diagnostic before retrying. No omitted evidence is accepted.",
        {"reason": "context_diagnostic_budget_exceeded", "context_complete": False,
         "operation_failed": True}).to_dict())


def validate_page(limit, offset):
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT or type(offset) is not int or offset < 0:
        raise UsageError("Use --limit 1–{} and a nonnegative --offset; follow next_offset for another page.".format(MAX_LIMIT), {})


def page(rows, offset, limit):
    selected = rows[offset:offset + limit]
    return {"total": len(rows), "offset": offset, "limit": limit, "returned": len(selected),
            "omitted": len(rows) - len(selected),
            "next_offset": offset + len(selected) if offset + len(selected) < len(rows) else None,
            "items": selected}


def section_page(rows, offset, limit, *, selected):
    """Retain counts and a start cursor for a section outside the selected view."""
    result = page(rows, offset if selected else 0, limit if selected else 0)
    result["selected"] = selected
    return result


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
            "next_after": (key(selected[-1]) if selected else after) if len(later) > len(selected) else None,
            "items": selected}


def enforce_budget(result, recovery):
    """Check exact stdout bytes without changing an existing document schema."""
    if len((json.dumps(result, indent=2) + "\n").encode("utf-8")) > OUTPUT_BYTES:
        raise UsageError(
            recovery,
            {"reason": "context_budget_exceeded", "budget_bytes": OUTPUT_BYTES, "context_complete": False})
    return result


def bounded(result):
    result["schema_version"] = VIEW_SCHEMA_VERSION
    result["authorizes_progression"] = False
    result["budget"] = {"output_bytes": OUTPUT_BYTES}
    return enforce_budget(result,
                          "Current context exceeds its printed output budget. Keep unexamined obligations unresolved; select a narrower task, --section where available, or evidence question instead of dumping history.")


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
