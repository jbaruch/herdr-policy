"""Bounded current decision context, never a required historical reading list.

Schema 3 is an ephemeral view; it migrates no operational owner records.
Plan returns queue/reservation facts. Brief, gate and diagnosis name the
current round's evidence. Brief and diagnosis preserve unsuperseded blocking
review references, including imported corrections. Diagnosis includes the
latest assessment per role and latest recovery records, not all prior rounds.
Wake selects one enrollment. Missing files stay visible; unknown sends refuse.

Historical investigation is question-specific. GitHub owns durable issue,
PR and review history; this command never mirrors or downloads that history.
The files field is a retrieval menu, not a must-load floor. Explicit evidence
reads return at most READ_BYTES bytes with continuation information. Every
successful view fits OUTPUT_BYTES as printed by the owner CLI. Oversized
obligations refuse rather than disappear behind truncation. No view grants
dispatch, acceptance or release authority.
"""

import codecs
import json
import os
from pathlib import Path
import stat
import sys

from . import runnable
from .attention import GATING_KINDS
from .chronology import latest_assignment, timestamp
from .context_output import OUTPUT_BYTES
from .foreman_queue import waiting
from .errors import StateError, UsageError
from .recovery import PENDING_STATUSES, active_plans, confirmed_fix, current_approach, developer_reservations, task_statuses

LOAD_SET_SCHEMA_VERSION = 3
READ_BYTES = 4_096
DECISIONS = ("plan", "brief", "gate", "diagnose", "wake")
OPEN_ATTENTION = frozenset({"open", "deferred"})


class _Files:
    """Ordered, de-duplicated file references with the reason each is loaded."""

    def __init__(self, exists):
        self.rows, self.seen, self.exists = [], set(), exists

    def add(self, path, why):
        if isinstance(path, str) and path and path not in self.seen:
            self.seen.add(path)
            self.rows.append({"path": path, "why": why, "present": self.exists(path)})


def _applied_at(assignments, index):
    return timestamp(assignments[index].get("at"), "Assignment {} chronology".format(index))


def _task_dispatches(store, assignments, task, since=None):
    """Applied dispatches of `task`, oldest first, optionally from `since` on."""
    rows = []
    for row in store["dispatches"]:
        index = row.get("assignment_index")
        if (row.get("task") != task or row.get("status") != "applied" or not isinstance(index, int)
                or not 0 <= index < len(assignments)):
            continue
        at = _applied_at(assignments, index)
        if since is None or at >= since:
            rows.append((at, row))
    rows.sort(key=lambda pair: (pair[0], pair[1].get("id", "")))
    return [row for _at, row in rows]


def _core(state, attention_entries, task):
    store = state["recovery"]
    record = store["tasks"].get(task)
    progress = record.get("progression") if isinstance(record, dict) else None
    delivery = progress.get("delivery") if isinstance(progress, dict) else None
    if (isinstance(record, dict) and isinstance(progress, dict)
            and isinstance(delivery, dict) and delivery.get("schema_version") == 2):
        from .workflow_artifacts import view
        record = {**record, "progression": {**progress, "delivery": {
            **delivery, "artifacts": view(delivery["artifacts"])}}}
    return {"task": record,
            "status": task_statuses(store, state["assignments"]).get(task),
            "attention": [entry for entry in attention_entries.values()
                          if (entry.get("task") == task or entry.get("task") is None and entry.get("kind") in GATING_KINDS)
                          and entry["status"] in OPEN_ATTENTION],
            "unknown_dispatches": [{key: row.get(key) for key in ("id", "role", "status")}
                                   for row in store["dispatches"]
                                   if row.get("task") == task and row.get("status") in PENDING_STATUSES]}


def _round_start(assignments, task):
    latest = latest_assignment(assignments, task=task, role="developer", status="applied")
    return None if latest is None else _applied_at(assignments, latest[0])


def _review_receipts(store, task):
    """Current receipts; explicitly superseded receipts are historical only."""
    return [row["report"] for row in store["dispatches"]
            if row.get("task") == task and isinstance(row.get("report"), dict)]


def _bounded(result):
    if len((json.dumps(result, indent=2) + "\n").encode("utf-8")) > OUTPUT_BYTES:
        raise UsageError(
            "Current decision context exceeds its output budget. Keep the task held; resolve or narrow owner obligations through a targeted query instead of dumping history.",
            {"reason": "context_budget_exceeded", "budget_bytes": OUTPUT_BYTES, "context_complete": False})
    return result


def read_evidence(packet, path, question, offset=0):
    """Read one listed current reference without treating an excerpt as approval."""
    if (not isinstance(question, str) or not question.strip() or len(question.encode("utf-8")) > 512
            or type(offset) is not int or not 0 <= offset <= sys.maxsize):
        raise UsageError("Supply a specific evidence question of at most 512 bytes and a nonnegative byte offset.", {})
    if not any(row["path"] == path for row in packet["files"]):
        raise UsageError("Select one current evidence reference from this task's decision context; investigate GitHub history separately by question.", {})
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise StateError("The selected evidence is not a regular file. Preserve the reference and restore its owner-written regular bytes before deciding.", {})
            stream.seek(offset)
            raw = stream.read(READ_BYTES + 1)
    except OSError:
        raise StateError("Cannot read the selected evidence. Restore access or record its unavailability before deciding.", {}) from None
    try:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        text = decoder.decode(raw[:READ_BYTES], final=len(raw) <= READ_BYTES)
    except UnicodeError:
        raise UsageError("Evidence is not valid UTF-8 at this offset. Use the returned next_offset at a character boundary, or restore the original valid UTF-8 report before deciding.", {}) from None
    # A chunk is evidence, never a second copy of the entire decision packet.
    # Keep its current task binding and make the omitted decision context explicit.
    result = {key: packet[key] for key in ("schema_version", "decision", "task", "enrollment", "round_start", "budget")}
    result.update(kind="evidence_chunk", decision_context_included=False, authorizes_progression=False)
    content = text.encode("utf-8")
    more = len(raw) > len(content)
    result["evidence"] = {"path": path, "question": question, "offset": offset, "bytes": len(content), "content": text,
                          "next_offset": offset + len(content) if more else None, "excerpt": offset != 0 or more}
    return fit_evidence(result)


def fit_evidence(packet):
    """Fit the final envelope, including any receipt, with UTF-8-safe progress."""
    result = {**packet, "evidence": dict(packet["evidence"])}
    evidence = result["evidence"]
    while len((json.dumps(result, indent=2) + "\n").encode("utf-8")) > OUTPUT_BYTES:
        text = evidence["content"]
        if len(text) <= 1:
            raise UsageError("Evidence metadata cannot fit the response budget. Narrow the question or ask its owner for bounded evidence; keep unread bytes and gates unresolved.",
                             {"reason": "context_budget_exceeded", "context_complete": False})
        text = text[:len(text) // 2]
        size = len(text.encode("utf-8"))
        evidence.update(content=text, bytes=size, next_offset=evidence["offset"] + size, excerpt=True)
    return result


def _historical(store, assignments, task, since=None):
    """Imported corrections of `task`, from `since` on: they have no dispatch."""
    rows = []
    for row in store["historical_attempts"]:
        index = row.get("assignment_index")
        if row.get("task") == task and isinstance(index, int) and 0 <= index < len(assignments) and (
                since is None or _applied_at(assignments, index) >= since):
            rows.append(row)
    return rows


def _add_historical_files(files, row, *, verdicts=None):
    reviews = [review.get("input", {}) for review in row.get("reviews", [])]
    if verdicts is not None:
        reviews = [review for review in reviews if review.get("verdict") in verdicts]
        if not reviews:
            return
    files.add(((row.get("receipts") or {}).get("report") or {}).get("path"), "report for imported correction " + row["id"])
    for body in reviews:
        files.add(body.get("report"), "{} review of imported correction {} at {}".format(
            body.get("verdict"), row["id"], body.get("head_revision")))


def _add_dispatch_files(files, row, reports, *, briefs=True):
    label = "{} {}".format(row.get("role"), row.get("id"))
    if briefs:
        files.add(row.get("brief"), "brief for " + label)
        files.add(row.get("common"), "common brief for " + label)
    files.add(reports.get(row.get("id")), "report for " + label)


def build(state, reports, attention_entries, busy_tasks, decision, *, task=None, enrollment=None, exists, supervision_view=None):
    """Return the load set for one decision.

    `reports` maps an enrollment (dispatch) id to its report path, from the
    supervision owner. `busy_tasks` feeds the queue entry. `exists` is the
    file probe, injected so the join stays testable.
    """
    store, assignments = state["recovery"], state["assignments"]
    files, records = _Files(exists), {}
    if decision == "wake":
        row = next((item for item in store["dispatches"] if item.get("id") == enrollment), None)
        task = row.get("task") if row else None
        records["dispatch"] = row
        if row is not None:
            _add_dispatch_files(files, row, reports)
    if decision in ("brief", "gate", "diagnose"):
        pending = sorted(row["id"] for row in store["dispatches"]
                         if row.get("task") == task and row.get("status") in PENDING_STATUSES)
        if pending:
            # An unknown send outcome is reconciled before anything reads the
            # round as complete (Dispatch Safety).
            examples = [identifier for identifier in pending if len(identifier.encode("utf-8")) <= 256][:8]
            raise UsageError("Task has dispatches with an unknown send outcome: {}. Reconcile through `{}` before this decision.".format(
                ", ".join(examples), runnable.command("reconcile")), {"pending": examples, "pending_count": len(pending)})
    start = _round_start(assignments, task) if task is not None else None
    if decision in ("brief", "gate", "diagnose"):
        selected = _task_dispatches(store, assignments, task, since=start)
        unenrolled = sorted(row["id"] for row in selected if not reports.get(row.get("id")))
        if unenrolled:
            # Every dispatch is enrolled before its brief is sent (Fleet
            # Supervision); a missing enrollment is lost evidence, not "no report".
            raise UsageError("Dispatches have no supervision enrollment with a report path. Restore supervision or reconcile before this decision.",
                             {"unenrolled": [identifier for identifier in unenrolled if len(identifier.encode("utf-8")) <= 256][:8],
                              "unenrolled_count": len(unenrolled)})
    if decision == "plan":
        records["queue"] = next((entry for entry in waiting(store, assignments, busy_tasks)["queue"]
                                 if entry["task"] == task), None)
        records["reserved_developer"] = sorted(agent for agent, held in developer_reservations(store, assignments).items()
                                               if held == task)
    elif decision in ("brief", "gate"):
        for row in _task_dispatches(store, assignments, task, since=start):
            _add_dispatch_files(files, row, reports)
        records["historical_attempts"] = _historical(store, assignments, task, since=start)
        for row in records["historical_attempts"]:
            _add_historical_files(files, row)
        if decision == "brief":
            receipts = [receipt for receipt in _review_receipts(store, task) if receipt.get("verdict") == "blocking"]
            for receipt in receipts:
                files.add(receipt.get("report"), "blocking review receipt at {}".format(receipt.get("head_revision")))
            for row in _historical(store, assignments, task):
                _add_historical_files(files, row, verdicts={"blocking"})
            # A plan whose last fix is already spent authorizes nothing more;
            # the task re-enters diagnosis instead (Fix Loops).
            spent = confirmed_fix(assignments, task)
            records["correction_plan"] = next((plan for plan in reversed(active_plans(store))
                                               if plan["task"] == task and plan["last_fix"] > spent), None)
            records["approach"] = current_approach(store, task)
    elif decision == "diagnose":
        for row in _task_dispatches(store, assignments, task, since=start):
            _add_dispatch_files(files, row, reports, briefs=False)
        records["historical_attempts"] = _historical(store, assignments, task, since=start)
        for row in records["historical_attempts"]:
            _add_historical_files(files, row)
        for receipt in _review_receipts(store, task):
            if receipt.get("verdict") == "blocking":
                files.add(receipt.get("report"), "blocking review receipt at {}".format(receipt.get("head_revision")))
        for row in _historical(store, assignments, task):
            _add_historical_files(files, row, verdicts={"blocking"})
        latest_assessments = {row.get("role"): row for row in state["specialist_assessments"] if row.get("task") == task}
        records["assessments"] = list(latest_assessments.values())
        for assessment in records["assessments"]:
            files.add(assessment.get("report"), "assessed {} report".format(assessment.get("role", "specialist")))
        for name in ("checkpoints", "diagnoses", "approaches"):
            records[name] = [row for row in store[name] if row.get("task") == task][-1:]
        records["plans"] = [plan for plan in active_plans(store) if plan["task"] == task]
    return _bounded({"schema_version": LOAD_SET_SCHEMA_VERSION, "decision": decision, "task": task,
            "enrollment": enrollment, "round_start": start.isoformat() if start else None,
            "core": _core(state, attention_entries, task) if task is not None else None,
            "records": records, "files": files.rows, "supervision": supervision_view,
            "history_included": False, "authorizes_progression": False,
            "budget": {"output_bytes": OUTPUT_BYTES, "evidence_read_bytes": READ_BYTES}})
