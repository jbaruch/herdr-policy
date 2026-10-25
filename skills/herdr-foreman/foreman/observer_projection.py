"""Read-only owner metadata pages for the private observer, never authority.

The owner may read its own complete JSON; the consumer receives only selected
current fields and explicit page coverage. Historical prompts, reports, holds'
evidence and dispatch bodies are never exported. This reader never migrates.
"""

import json
import os
from pathlib import Path
import stat

from . import context_output
from .errors import StateError


MAX_EVENTS = 10_000
SECTIONS = ("binding", "current", "closures")


def _read(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("owner evidence must be regular JSON")
        return json.load(stream)


def view(path, section="current", *, offset=0, limit=50):
    """Project supported owner schemas, with bounded printed pages."""
    context_output.validate_page(limit, offset)
    if section not in SECTIONS:
        raise ValueError("select binding, current or closures")
    supervised = _read(str(path) + ".supervision.json")
    if not isinstance(supervised, dict) or supervised.get("schema_version") != 1:
        raise StateError("Restore supported supervision owner evidence before observing this factory; no migration was attempted.", {})
    rows, gaps = [], []
    if section == "binding":
        rows = [{"kind": "binding", "value": supervised.get("binding")}]
    else:
        data = _read(Path(path))
        if (not isinstance(data, dict) or data.get("schema_version") != 11
                or data.get("recovery", {}).get("schema_version") != 19):
            raise StateError("Restore the supported state/recovery owner before observing this factory; no migration was attempted.", {})
        if section == "current":
            active = [row for row in supervised.get("members", []) if row.get("active")]
            profiles = {row.get("agent"): row for row in data.get("assignments", [])}
            rows = [{"kind": "binding", "value": supervised.get("binding")},
                    {"kind": "context", "value": {"holds": sum(row.get("resumed_at") is None for row in supervised.get("holds", [])),
                                                   "active_assignments": len(active)}}]
            for member in active:
                assignment = member.get("assignment", {})
                refinements = member.get("refinements", [])
                current = refinements[-1] if refinements else assignment
                profile = profiles.get(assignment.get("agent"), {})
                rows.append({"kind": "assignment", "value": {
                    "agent": assignment.get("agent"), "task": assignment.get("task"),
                    "role": profile.get("role", "worker"), "at": profile.get("at") or member.get("at"),
                    "pane_id": current.get("pane_id"), "native_session": current.get("native_session")}})
            snapshots = data.get("snapshots", [])
            snapshot = snapshots[-1] if snapshots else {}
            if snapshot.get("schema_version") in (5, 6):
                for name, row in snapshot.get("agents", {}).items():
                    windows = {key: {field: value.get(field) for field in ("used_pct", "remaining_pct", "resets")}
                               for key, value in row.get("windows", {}).items() if isinstance(value, dict)}
                    rows.append({"kind": "quota", "value": {"profile": name, "measured_at": snapshot.get("measured_at"),
                        "kind": row.get("kind"), "window_group": row.get("window_group"), "windows": windows,
                        "headroom_pct": row.get("headroom_pct"), "skipped": row.get("skipped")}})
            else:
                gaps.append("quota_snapshot_missing_or_unsupported")
        else:
            events = data["recovery"].get("events", [])
            if len(events) > MAX_EVENTS:
                gaps.append("closure_history_truncated")
            for event in reversed(events[-MAX_EVENTS:]):
                if event.get("kind") == "task_closed":
                    rows.append({"kind": "closure", "value": {
                        **{key: event.get(key) for key in ("task", "at", "sequence")},
                        "outcome": (event.get("details") or {}).get("outcome")}})

    def page(effective):
        selected = context_output.page(rows, offset, effective)
        return {"kind": "observer_projection", "section": section, "rows": selected.pop("items"),
                "pagination": selected, "gaps": gaps, "authorizes_dispatch": False,
                "context_complete": selected["omitted"] == 0}
    return context_output.fit_pages(page, limit, offset)
