#!/usr/bin/env python3
"""Summarize sanitized coordination records without reading live team state.

argv: one JSON snapshot path; schema in references/coordination-metrics.md.
stdout: one bounded JSON summary or private-report receipt. stderr: actionable
diagnostics. Exit 0 success, 2 unusable input/output. No native owner mutations.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import statistics
import sys

from .context_output import OUTPUT_BYTES


OLDEST_PENDING_LIMIT = 10
MAX_SNAPSHOT_BYTES = 2_097_152
QUEUE_STATES = frozenset({"completed", "pending", "unmeasured"})
QUEUE_FIELDS = {"assessed_at": "assessment_state", "resolved_at": "resolution_state"}


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


def paired(assignments, first, second, observed_end):
    values = []
    excluded = Counter()
    for item in assignments:
        if item["native_match"] != "matched":
            excluded["unknown_native"] += 1
        elif not item.get(first) or not item.get(second):
            excluded["missing_endpoint"] += 1
        else:
            opened, closed = instant(item[first]), instant(item[second])
            duration = (closed - opened).total_seconds()
            if opened > observed_end or closed > observed_end:
                excluded["future_endpoint"] += 1
            elif duration < 0:
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


def queue_state(item, endpoint, closed, end, version):
    """Positive timestamps or an explicit boundary state establish queue status."""
    observed = "unmeasured" if closed is None else "pending" if closed > end else "completed"
    stated = item.get(QUEUE_FIELDS[endpoint]) if version == 2 else None
    if stated is not None and closed is not None and stated != observed:
        raise ValueError("queue state contradicts its timestamp at the observation boundary")
    return stated or observed


def waiting(assignments, start, end, endpoint, version):
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
        status = queue_state(item, endpoint, closed, end, version)
        if status == "unmeasured" or status == "completed" and closed is None:
            excluded["unmeasured_endpoint"] += 1
            continue
        if closed is not None and closed < start:
            excluded["outside_window"] += 1
            continue
        if status == "pending":
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
    if type(snapshot["schema"]) is not int or snapshot["schema"] not in (1, 2):
        raise ValueError("unsupported snapshot schema; export schema 1 or 2")
    start, end = (instant(snapshot["window"][key]) for key in ("start", "end"))
    if start >= end:
        raise ValueError("the observation window must have positive duration")
    tasks = identified(snapshot["tasks"])
    assignments = list(identified(snapshot["assignments"]).values())
    for item in assignments:
        if item["task_id"] not in tasks or item["native_match"] not in ("matched", "unknown"):
            raise ValueError("each assignment must name a listed task and matched/unknown native identity")
        if snapshot["schema"] == 2 and any(field in item and (not isinstance(item[field], str)
                                          or item[field] not in QUEUE_STATES)
                                          for field in QUEUE_FIELDS.values()):
            raise ValueError("queue states must be completed, pending or unmeasured")
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
        "schema": 2, "authorizes_progression": False,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "coverage": {"tasks": len(tasks), "assignments": len(assignments),
                     "native_match": dict(Counter(item["native_match"] for item in assignments)),
                     "task_states": dict(Counter(task["state"] for task in tasks.values())),
                     "class_risk_mix": dict(Counter(task["class"] + "/" + task["risk"] for task in tasks.values()))},
        "outcomes": outcomes,
        "latency_seconds": {"native_work": paired(assignments, "native_started_at", "native_completed_at", end),
                            "completion_to_assessment": paired(assignments, "native_completed_at", "assessed_at", end),
                            "completion_to_resolution": paired(assignments, "native_completed_at", "resolved_at", end)},
        "waiting": {"assessment": waiting(assignments, start, end, "assessed_at", snapshot["schema"]),
                    "resolution": waiting(assignments, start, end, "resolved_at", snapshot["schema"])},
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


def encoded(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def read_snapshot(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("select a frozen regular JSON snapshot file")
        body = stream.read(MAX_SNAPSHOT_BYTES + 1)
    if len(body) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds its input budget; export compact measurements for the full preregistered cohort")
    return body


def report_path(value):
    raw = value.expanduser()
    path = raw.parent.resolve() / raw.name
    skill = Path(__file__).resolve().parents[1]
    installation = skill.parent.parent if skill.parent.name == "skills" else skill
    forbidden = {installation}
    for start in (skill, Path.cwd(), path.parent):
        for root in (start, *start.parents):
            if (root / ".git").exists():
                forbidden.add(root)
                break
    if any(path.is_relative_to(root) for root in forbidden):
        raise ValueError("choose a private report path outside repositories and this installed package")
    return path


def write_private_report(path, body):
    """Create one explicit report; identical repeats never rewrite its bytes."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                    or stream.read(len(body) + 1) != body):
                raise ValueError("preserve the existing report; select a fresh private output path for changed evidence")
        return
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, help="create a private comparison report and print its bounded receipt")
    args = parser.parse_args()
    try:
        source = read_snapshot(args.snapshot)
        snapshot = json.loads(source.decode("utf-8"))
        result = summarize(snapshot)
        output_file = None
        if args.output is not None:
            path = report_path(args.output)
            digest = hashlib.sha256(source).hexdigest()
            body = encoded({"schema_version": 1, "kind": "coordination_measurement_report",
                            "snapshot_sha256": digest, "input_schema": snapshot["schema"],
                            "producer": {"schema_version": 1, "python": sys.version.split()[0],
                                         "calculator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                            "summary": result})
            output_file = path, body
            rendered = encoded({"schema_version": 1, "kind": "measurement_report_receipt",
                                "authorizes_progression": False, "path": str(path),
                                "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                                "snapshot_sha256": digest, "summary_schema": result["schema"],
                                "tasks": result["coverage"]["tasks"], "assignments": result["coverage"]["assignments"]})
        else:
            rendered = encoded(result)
        if len(rendered) > OUTPUT_BYTES:
            raise ValueError("summary exceeds its printed context budget; retain the full cohort and use --output with a private report path")
        if output_file is not None:
            write_private_report(*output_file)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print("coordination-baseline: {} — repair the snapshot or output path using references/coordination-metrics.md and rerun".format(exc), file=sys.stderr)
        return 2
    sys.stdout.write(rendered.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
