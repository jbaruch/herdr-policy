#!/usr/bin/env python3
"""Summarize sanitized coordination records without reading live team state.

argv: one JSON snapshot path; schema documented in docs/coordination-baseline.md.
stdout: one JSON summary. stderr: actionable input/setup diagnostics. Exit 0 on
success, 2 on invalid input. No network, worker, state or production mutations.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import statistics
import sys


OLDEST_PENDING_LIMIT = 10


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must carry a UTC offset")
    return parsed.astimezone(timezone.utc)


def nonnegative(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)) or value < 0:
        raise ValueError("effort values must be finite, nonnegative numbers or null")
    return value


def totals(values):
    known = [nonnegative(value) for value in values if value is not None]
    return {"known": len(known), "unknown": len(values) - len(known), "total": sum(known)}


def distribution(values):
    ordered = sorted(values)
    return {"n": len(ordered), "median": statistics.median(ordered) if ordered else None,
            "p90": ordered[math.ceil(0.9 * len(ordered)) - 1] if ordered else None}


def identified(records):
    result = {}
    for record in records:
        identity = record["id"]
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError("record ids must be nonempty and unique within each collection")
        result[identity] = record
    return result


def paired(assignments, first, second):
    values = []
    excluded = Counter()
    for item in assignments:
        if item["native_match"] != "matched":
            excluded["unknown_native"] += 1
        elif not item.get(first) or not item.get(second):
            excluded["missing_endpoint"] += 1
        else:
            duration = (instant(item[second]) - instant(item[first])).total_seconds()
            if duration < 0:
                excluded["reversed_clock"] += 1
            else:
                values.append(duration)
    return {**distribution(values), "excluded": dict(excluded)}


def union_seconds(intervals):
    """Count overlapping waits once within one task and one queue."""
    total, right = 0.0, None
    for opened, closed in sorted(intervals):
        left = max(opened, right) if right is not None else opened
        total += max(0.0, (closed - left).total_seconds())
        right = max(right, closed) if right is not None else closed
    return total


def waiting(assignments, start, end, endpoint):
    """Observe pending ages at the window end and union waits inside it."""
    excluded, by_task, pending = Counter(), {}, []
    for item in assignments:
        if item["native_match"] != "matched":
            excluded["unknown_native"] += 1
            continue
        if not item.get("native_completed_at"):
            excluded["missing_completion"] += 1
            continue
        opened = instant(item["native_completed_at"])
        closed = instant(item[endpoint]) if item.get(endpoint) else None
        if opened > end:
            excluded["future_completion"] += 1
            continue
        if closed is not None and closed < opened:
            excluded["reversed_clock"] += 1
            continue
        if closed is not None and closed < start:
            excluded["outside_window"] += 1
            continue
        if closed is None or closed > end:
            pending.append({"assignment_id": item["id"], "task_id": item["task_id"],
                            "age_seconds": (end - opened).total_seconds()})
        by_task.setdefault(item["task_id"], []).append((max(opened, start), min(closed or end, end)))
    pending.sort(key=lambda row: (-row["age_seconds"], row["assignment_id"]))
    return {"pending_age_seconds": distribution([row["age_seconds"] for row in pending]),
            "oldest": pending[:OLDEST_PENDING_LIMIT], "oldest_limit": OLDEST_PENDING_LIMIT,
            "omitted_pending": max(0, len(pending) - OLDEST_PENDING_LIMIT),
            "wait_task_seconds": sum(union_seconds(rows) for rows in by_task.values()),
            "covered_tasks": len(by_task), "excluded": dict(excluded)}


def summarize(snapshot):
    if type(snapshot["schema"]) is not int or snapshot["schema"] != 1:
        raise ValueError("unsupported snapshot schema; export schema 1")
    start, end = (instant(snapshot["window"][key]) for key in ("start", "end"))
    if start >= end:
        raise ValueError("the observation window must have positive duration")
    tasks = identified(snapshot["tasks"])
    assignments = list(identified(snapshot["assignments"]).values())
    for item in assignments:
        if item["task_id"] not in tasks or item["native_match"] not in ("matched", "unknown"):
            raise ValueError("each assignment must name a listed task and matched/unknown native identity")
    outcomes = {}
    for stage in ("integration", "deployment", "acceptance"):
        evidenced = 0
        for task in tasks.values():
            event = task.get(stage) or {}
            evidence = event.get("evidence") or []
            if not isinstance(evidence, list) or any(not isinstance(value, str) or not value for value in evidence):
                raise ValueError("stage evidence must be a list of nonempty references")
            if event.get("at") and evidence:
                if not start <= instant(event["at"]) <= end:
                    raise ValueError("outcome timestamps must fall within the observation window")
                evidenced += 1
        outcomes[stage] = {"evidenced": evidenced, "unmeasured": len(tasks) - evidenced}
    intervals = []
    for item in assignments:
        # Unknown envelopes remain possibly busy until their recorded resolution
        # or the observation boundary. They are never counted as proven idle.
        if item["native_match"] == "unknown":
            opened, closed = item["dispatched_at"], item.get("resolved_at")
        else:
            opened = item.get("native_started_at") or item["dispatched_at"]
            closed = item.get("native_completed_at") or item.get("resolved_at")
        left, right = instant(opened), instant(closed) if closed else end
        if right < left:
            raise ValueError("busy intervals cannot end before they start")
        intervals.append((left, right))
    samples = [instant(value) for value in snapshot.get("activity_minutes", [])]
    if len(samples) != len(set(samples)) or any(not start <= value < end or value.second or value.microsecond for value in samples):
        raise ValueError("activity minutes must be unique, minute-aligned and inside the observation window")
    busy = [sum(left < min(at + timedelta(minutes=1), end) and right > at for left, right in intervals)
            for at in samples]
    effort = {name: totals([task.get("foreman", {}).get(name) for task in tasks.values()])
              for name in ("active_seconds", "exec_calls", "output_bytes", "reconstruction_bytes")}
    accepted = outcomes["acceptance"]["evidenced"]
    holds = []
    for task in tasks.values():
        for hold in task.get("holds", []):
            left = instant(hold["start"])
            right = instant(hold["end"]) if hold.get("end") else None
            reason = hold["reason"]
            if (right and right < left) or reason not in ("operator", "policy", "dependency", "quota", "outage", "verification", "unknown"):
                raise ValueError("holds require ordered timestamps and a documented reason category")
            holds.append({"task_id": task["id"], "start": left.isoformat(),
                          "end": right.isoformat() if right else None, "reason": reason})
    return {
        "schema": 1, "window": {"start": start.isoformat(), "end": end.isoformat()},
        "coverage": {"tasks": len(tasks), "assignments": len(assignments),
                     "native_match": dict(Counter(item["native_match"] for item in assignments)),
                     "task_states": dict(Counter(task["state"] for task in tasks.values())),
                     "class_risk_mix": dict(Counter(task["class"] + "/" + task["risk"] for task in tasks.values()))},
        "outcomes": outcomes,
        "latency_seconds": {"native_work": paired(assignments, "native_started_at", "native_completed_at"),
                            "completion_to_assessment": paired(assignments, "native_completed_at", "assessed_at"),
                            "completion_to_resolution": paired(assignments, "native_completed_at", "resolved_at")},
        "waiting": {"assessment": waiting(assignments, start, end, "assessed_at"),
                    "resolution": waiting(assignments, start, end, "resolved_at")},
        "effort": {"foreman": effort, "report_bytes": totals([item.get("report_bytes") for item in assignments]),
                   "foreman_output_bytes_per_accepted": effort["output_bytes"]["total"] / accepted
                   if accepted and effort["output_bytes"]["unknown"] == 0 else None,
                   "rework_rounds": totals([task.get("rework_rounds") for task in tasks.values()]),
                   "escaped_defects": totals([task.get("escaped_defects") for task in tasks.values()])},
        "activity": {"sampled_minutes": len(busy),
                     "mean_possibly_busy_envelopes": statistics.mean(busy) if busy else None,
                     "zero_possibly_busy_minutes": busy.count(0),
                     "at_most_two_possibly_busy_minutes": sum(value <= 2 for value in busy),
                     "peak_possibly_busy_envelopes": max(busy) if busy else None},
        "holds": holds,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        result = summarize(json.loads(args.snapshot.read_text()))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print("coordination-baseline: {} — repair the snapshot using docs/coordination-baseline.md and rerun".format(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
