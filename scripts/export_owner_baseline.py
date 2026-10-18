#!/usr/bin/env python3
"""Export sanitized measurements from frozen owner/supervision evidence.

argv: owner and supervision JSON, explicit window, trusted Herdr source checkout,
and a private provenance-output path. stdout: schema-1 baseline snapshot only.
stderr: actionable setup failures; exit 0 success, 2 unusable input or output.
Reads native sources and saved ledgers; never calls workers or mutates owners.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]


def instant(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, timezone.utc)
    if not isinstance(value, str):
        raise ValueError("timestamps must be offset-aware ISO strings or native Unix seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamps must use valid offset-aware ISO strings; restore the source clock evidence") from None
    if parsed.tzinfo is None:
        raise ValueError("measurement timestamps require UTC offsets")
    return parsed.astimezone(timezone.utc)


def opaque(value, prefix):
    if not isinstance(value, str) or not value:
        raise ValueError("source identities must be nonempty strings")
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:20]


def indexed(rows):
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("source collection contains duplicate identities")
    return result


def candidate_identity(dispatch, member, end):
    candidates = [dispatch.get("result", {}).get("context_session"),
                  member["assignment"].get("native_session")]
    candidates.extend(row.get("native_session") for row in member.get("refinements", [])
                      if instant(row["at"]) <= end)
    observed = member.get("observed", {})
    resolution = member.get("resolution")
    expected_pane = member["assignment"].get("pane_id")
    for refinement in member.get("refinements", []):
        if instant(refinement["at"]) <= end:
            expected_pane = refinement.get("pane_id", expected_pane)
    observation = observed.get("identity", {})
    # A resolved enrollment freezes its last observation before the recorded
    # resolution. This is only a source candidate; native report proof follows.
    if (member.get("active") is False and resolution and instant(resolution["at"]) <= end
            and observation.get("pane_id") and (expected_pane is None or observation["pane_id"] == expected_pane)
            and not any(key in observed for key in ("identity_changed", "identity_unverified", "unavailable", "observation_error"))):
        candidates.append(observation.get("native_session"))
    identities = set()
    for row in candidates:
        if row is None:
            continue
        kind = row.get("agent")
        if (kind not in ("codex", "claude", "grok") or row.get("source") != "herdr:" + kind
                or row.get("kind") != "id" or not isinstance(row.get("value"), str)
                or re.fullmatch(r"[A-Za-z0-9_-]+", row["value"]) is None):
            return None
        identities.add((row["source"], kind, row["kind"], row["value"]))
    if len(identities) != 1:
        return None
    return dict(zip(("source", "agent", "kind", "value"), identities.pop()))


def native_times(rows, kind, session, claude):
    """Read turn timestamps after the canonical reader verifies its final message."""
    if kind == "codex":
        starts = [row for row in rows if row.get("type") == "event_msg"
                  and row.get("payload", {}).get("type") == "task_started"]
        finishes = [row for row in rows if row.get("type") == "event_msg"
                    and row.get("payload", {}).get("type") == "task_complete"]
    elif kind == "claude":
        chain = claude.main_chain(rows, session)
        if chain is None:
            raise ValueError("native main chain is unusable")
        starts = [row for row in chain if row["type"] == "user" and not claude.tool_output(row["message"])]
        finishes = [row for row in chain if row["type"] == "assistant"]
    elif kind == "grok":
        starts = [row for row in rows if row.get("params", {}).get("update", {}).get("event_name") == "user_prompt_submit"]
        finishes = [row for row in rows if row.get("params", {}).get("update", {}).get("sessionUpdate") == "turn_completed"]
    else:
        raise ValueError("unsupported native timestamp source")
    return (instant(starts[-1]["timestamp"]) if starts else None,
            instant(finishes[-1]["timestamp"]) if finishes else None)


class EvidenceReader:
    """Reuse the extracted owners' source/ledger parsers without state loading."""

    def __init__(self, source):
        skill = source.resolve() / "skills/herdr-foreman"
        if not (skill / "foreman/report_delivery.py").is_file():
            raise ValueError("select a trusted extracted Herdr source checkout with --herdr-source")
        sys.path.insert(0, str(skill))
        from foreman import claude_native, members, report_delivery
        from foreman.errors import UsageError
        if not Path(report_delivery.__file__).resolve().is_relative_to(skill):
            raise ValueError("restart in a fresh process; another Herdr reader is already imported")
        self.native_reader, self.claude_reader, self.ledger_reader = report_delivery, claude_native, members
        self.source_error = UsageError
        self.exclusions = Counter()
        self.source_digests = set()
        self.paths = {}

    def native(self, identity, report, dispatched, end):
        key = tuple(identity[name] for name in ("source", "agent", "kind", "value"))
        try:
            if key not in self.paths:
                self.paths[key] = self.native_reader.source_path(identity)
            path = self.paths[key]
            if path is None:
                self.exclusions["native_source_missing_or_ambiguous"] += 1
                return {}
            body = path.read_bytes()
            self.source_digests.add(hashlib.sha256(body).hexdigest())
            text = body.decode("utf-8")
            kind, session = identity["agent"], identity["value"]
            final = self.native_reader.source_final(text, kind, session)
            if not final or not self.native_reader.bare_final(final, report):
                self.exclusions["native_final_not_bound_to_report"] += 1
                return {}
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            started, completed = native_times(rows, kind, session, self.claude_reader)
            if completed is None:
                self.exclusions["native_completion_timestamp_missing"] += 1
                return {}
            if not dispatched <= completed <= end:
                self.exclusions["native_completion_outside_assignment_window"] += 1
                return {}
            result = {"native_completed_at": completed.isoformat()}
            if started is not None and dispatched <= started <= completed:
                result["native_started_at"] = started.isoformat()
            return result
        except (OSError, OverflowError, UnicodeError, ValueError, KeyError, TypeError, self.source_error):
            self.exclusions["native_source_unusable"] += 1
            return {}

    def assessment(self, member, state_identity, end):
        assignment = member["assignment"]
        candidates = (member.get("resolution") or {}).get("evidence", [])
        times = set()
        for evidence in candidates:
            try:
                path = Path(evidence["path"])
                if path.suffix != ".md":
                    continue
                header, events = self.ledger_reader.ledger_events(path)
                if (header["task"] != assignment["task"]
                        or Path(header["dispatch_state"]).expanduser().resolve() != Path(state_identity).resolve()):
                    continue
                self.source_digests.add(hashlib.sha256(path.read_bytes()).hexdigest())
                times.update(instant(row["at"]) for row in events
                             if row["subject"] == "assignment" and row["dispatch_id"] == assignment["id"]
                             and row["worker"] == assignment["agent"] and row["report"] == assignment["report"]
                             and row["decision"] in self.ledger_reader.ASSESSED and instant(row["at"]) <= end)
            except (OSError, ValueError, KeyError, TypeError, self.source_error):
                self.exclusions["ledger_reference_not_usable"] += 1
        return min(times).isoformat() if times else None


def export(owner, supervision, start, end, native, assessment):
    versions = ((owner.get("schema_version"), 11), (owner["recovery"].get("schema_version"), 18),
                (supervision.get("schema_version"), 1))
    if any(type(value) is not int or value != expected for value, expected in versions):
        raise ValueError("unsupported owner evidence schema; preserve it and update this reader")
    if start >= end:
        raise ValueError("the observation window must have positive duration")
    store = owner["recovery"]
    dispatches = [row for row in store["dispatches"] if start <= instant(row["at"]) < end]
    selected = [row for row in dispatches if row["status"] in ("applied", "sent_but_not_started")]
    indexed(selected)
    members = indexed(supervision["members"])
    tasks = {row["task"] for row in dispatches}
    tasks.update(row["task"] for row in store["tasks"].values() if start <= instant(row["at"]) < end)
    closed = {row["task"] for row in store["events"]
              if row["kind"] == "task_closed" and instant(row["at"]) <= end}
    task_rows: list[dict[str, object]] = [
        {"id": opaque(task, "task-"), "state": "owner_closed" if task in closed else "owner_open",
         "class": "unknown", "risk": "unknown"} for task in sorted(tasks)]
    assignments = []
    for dispatch in selected:
        row = {"id": opaque(dispatch["id"], "assignment-"), "task_id": opaque(dispatch["task"], "task-"),
               "dispatched_at": instant(dispatch["at"]).isoformat(), "native_match": "unknown"}
        member = members.get(dispatch["id"])
        if member:
            assignment = member["assignment"]
            if any(assignment[name] != dispatch[name] for name in ("id", "task", "agent")):
                raise ValueError("dispatch and enrollment identities contradict; reconcile the frozen evidence")
            identity = candidate_identity(dispatch, member, end)
            if identity:
                observed = native(identity, assignment["report"], instant(dispatch["at"]), end)
                if observed.get("native_completed_at"):
                    row["native_match"] = "matched"
                    for key in ("native_started_at", "native_completed_at"):
                        if observed.get(key) is not None:
                            row[key] = instant(observed[key]).isoformat()
            resolution = member.get("resolution")
            if resolution and instant(resolution["at"]) <= end:
                row["resolved_at"] = instant(resolution["at"]).isoformat()
            assessed = assessment(member, supervision["state_path"], end)
            if assessed is not None:
                row["assessed_at"] = assessed
            reports = [event for event in supervision["events"] if event["member"] == member["id"]
                       and event["kind"] == "report_observed" and instant(event["at"]) <= end]
            if reports and reports[-1]["data"].get("present"):
                row["report_bytes"] = reports[-1]["data"].get("size")
        assignments.append(row)
    for task in task_rows:
        task["holds"] = [{"start": hold["at"],
                          "end": hold.get("resumed_at") if hold.get("resumed_at") and instant(hold["resumed_at"]) <= end else None,
                          "reason": "operator" if hold["kind"] == "waiting_for_user" else "unknown"}
                         for hold in supervision["holds"]
                         if any(item["member"] in members
                                and opaque(members[item["member"]]["assignment"]["task"], "task-") == task["id"]
                                for item in hold["dispositions"])
                         and instant(hold["at"]) < end
                         and (not hold.get("resumed_at") or instant(hold["resumed_at"]) > start)]
    return {"schema": 1, "window": {"start": start.isoformat(), "end": end.isoformat()},
            "tasks": task_rows, "assignments": assignments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--supervision", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--herdr-source", type=Path, default=ROOT)
    parser.add_argument("--provenance-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.provenance_output.resolve().is_relative_to(ROOT):
            raise ValueError("keep provenance outside the repository; select a private --provenance-output")
        owner_bytes, supervision_bytes = args.owner.read_bytes(), args.supervision.read_bytes()
        reader = EvidenceReader(args.herdr_source)
        snapshot = export(json.loads(owner_bytes), json.loads(supervision_bytes), instant(args.start), instant(args.end),
                          reader.native, reader.assessment)
        sys.path.insert(0, str(ROOT))
        from scripts.coordination_baseline import summarize
        summarize(snapshot)
        runtime = args.herdr_source / "skills/herdr-foreman/foreman"
        provenance = {"schema_version": 2, "python_version": ".".join(str(part) for part in sys.version_info[:3]),
                      "owner_sha256": hashlib.sha256(owner_bytes).hexdigest(),
                      "supervision_sha256": hashlib.sha256(supervision_bytes).hexdigest(),
                      "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "reader_source_sha256": {str(path.relative_to(runtime)): hashlib.sha256(path.read_bytes()).hexdigest()
                                               for path in sorted(runtime.rglob("*.py"))},
                      "evidence_sha256": sorted(reader.source_digests), "exclusions": dict(reader.exclusions)}
        body = json.dumps(provenance, sort_keys=True, indent=2) + "\n"
        if args.provenance_output.exists():
            if args.provenance_output.read_text() != body:
                raise ValueError("provenance output already differs; choose a fresh output path")
        else:
            with os.fdopen(os.open(args.provenance_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as target:
                target.write(body)
    except (OSError, OverflowError, UnicodeError, ValueError, KeyError, TypeError, ImportError, AttributeError) as exc:
        print("export-owner-baseline: {} — restore frozen inputs and the trusted reader, then retry".format(exc), file=sys.stderr)
        return 2
    print(json.dumps(snapshot, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
