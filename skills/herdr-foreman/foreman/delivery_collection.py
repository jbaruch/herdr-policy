"""Bounded current native collection, independent of heavy report assessment.

Canonical --once waits and original native prompt/final proof authenticate
delivery. Collection appends only a changed observation in the existing
supervision owner. No report content, classification or acceptance is copied
into a second store. One failed item preserves the independent completions.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess

from . import context_output, members, progression_owner as authority, supervision
from . import workflow_adoption, workflow_workspace as workspace
from .errors import ForemanError, StateError


WORKERS = 4


def observe(path, state, member, client, *, check=members.check):
    assigned = supervision.expected_assignment(member)
    result = {"task": assigned["task"], "dispatch": member["id"], "status": "waiting",
              "reason": "native_completion_pending", "report": None}
    try:
        dispatch = next((row for row in state["recovery"]["dispatches"] if row["id"] == member["id"]), None)
        if dispatch is None or dispatch["status"] != "applied":
            return {**result, "status": "decision", "reason": "dispatch_provenance_unconfirmed"}
        environment = {**os.environ, "HERDR_BIN": client.context.executable,
                       "FOREMAN_HERDR_BIN": client.context.executable}
        def run(argv, **kwargs):
            return subprocess.run(argv, env=environment, timeout=90, **kwargs)
        checked, code = check(path, member["id"], run=run)
        if len(checked["wait"].encode("utf-8")) > 32768:
            raise StateError("The canonical completion check exceeded its bounded evidence packet.", {})
        waited = json.loads(checked["wait"])
        if (not isinstance(waited, dict) or type(waited.get("found")) is not bool
                or waited.get("agent") != assigned["agent"] or waited.get("report_path") != assigned["report"]):
            raise StateError("The native completion check differs from its enrolled report and worker.", {})
        if code == 1 and not waited["found"] and waited.get("reason") == "checkpoint_pending" and waited.get("stall") is None:
            return result
        if code != 0 or not waited["found"]:
            return {**result, "status": "decision", "reason": "native_delivery_exception"}
        report, source, native = workflow_adoption.source_evidence(path, state, member, dispatch, check_gates=False)
        live = client.agent_get(assigned["agent"])
        if (live.get("pane_id") != assigned["pane_id"]
                or workflow_adoption.report_delivery.native_identity(live) != native):
            return {**result, "status": "decision", "reason": "native_identity_changed"}
        return {**result, "status": "collected", "reason": "authenticated_native_delivery",
                "report": report, "native_source": source, "native_session": native,
                "size": len(workspace.capture(report["path"])[1]),
                "assignment_digest": supervision.digest(assigned)}
    except ForemanError as exc:
        return {**result, "status": "decision", "reason": exc.details.get("reason", "delivery_provenance_unconfirmed"), "error": exc.code}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {**result, "status": "decision", "reason": "native_completion_check_unavailable"}


def collect(path, client, at, *, task=None, limit=context_output.DEFAULT_LIMIT, offset=0, check=members.check):
    context_output.validate_page(limit, offset)
    supervision.timestamp(at)
    state = authority._load(path)
    data = authority.verify_foreman(path, client, native_only=True)
    candidates = sorted((member for member in data["members"] if member["active"]
                         and (task is None or member["assignment"]["task"] == task)), key=lambda row: row["id"])
    selected = candidates[offset:offset + limit]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(lambda member: observe(path, state, member, client, check=check), selected))
    # Native/file reads above never hold a task-state transaction. Commit only
    # original byte-bound observations, serially through the existing owner.
    for row in rows:
        if row["status"] != "collected":
            continue
        expected_report = row["report"]
        expected_source = row["native_source"]
        assert expected_report is not None
        try:
            if (workspace.capture(expected_report["path"])[0] != expected_report
                    or workspace.capture(expected_source["path"])[0] != expected_source):
                row.update(status="decision", reason="delivery_observation_changed")
                continue
        except ForemanError:
            row.update(status="decision", reason="delivery_provenance_unavailable")
            continue
        def commit(current):
            member = next((item for item in current["members"] if item["id"] == row["dispatch"]), None)
            if (member is None or not member["active"] or supervision.digest(supervision.expected_assignment(member)) != row["assignment_digest"]):
                row.update(status="waiting", reason="delivery_observation_superseded")
                return
            detail = {"present": True, **expected_report, "size": row["size"]}
            if member["observed"].get("report") != detail:
                supervision.append_event(current, at, member["id"], "report_observed", detail)
                member["observed"]["report"] = detail
        try:
            supervision.transaction(path, commit)
        except ForemanError as exc:
            row.update(status="waiting", reason="observation_owner_unavailable", error=exc.code)
    public = [{key: value for key, value in row.items() if key not in {"size", "assignment_digest", "native_session"}}
              for row in rows]
    def build(effective):
        page = context_output.page(candidates, offset, effective)
        page.pop("items")
        return {"observed_at": at, "items": public[:effective], "pagination": page,
                "context_complete": offset == 0 and len(candidates) <= effective,
                "counts_scope": "returned_items", "authorizes_acceptance": False,
                "authorizes_dispatch": False}
    return context_output.fit_pages(build, limit, offset)


def register_commands(sub, common):
    parser = sub.add_parser("collect-deliveries", parents=[common])
    parser.add_argument("--task")
    parser.add_argument("--limit", type=int, default=context_output.DEFAULT_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--now")
