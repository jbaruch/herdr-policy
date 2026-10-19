"""Finish-first admission over existing owners; no capacity ledger or dispatcher.

Limits are an explicit, captured config-schema-9 choice. Reserved and uncertain
work consumes a task slot. Capacity only delays new tasks: existing work must
remain able to verify, correct, release and reconcile under its original gates.
"""

import json
import re
from typing import Any

from .chronology import timestamp
from .errors import ConfigError, UsageError


LIMIT_FIELDS = frozenset({"in_flight", "integration"})
POLICY_FIELDS = frozenset({"schema_version", "global", "repositories", "exceptions", "rationale"})
INTEGRATION_ROLES = frozenset({"reviewer", "tester", "release", "judge"})
INTEGRATION_PHASES = frozenset({"verify", "release", "merge", "publish", "cleanup"})
MAX_REFERENCES = 3
REFERENCE_BYTES = 1024
MAX_THRESHOLD = (1 << 63) - 1


def _text(value, label, limit):
    if (not isinstance(value, str) or not value.strip() or len(value.encode()) > limit
            or any(ord(char) < 32 for char in value)):
        raise ConfigError("Record bounded single-line {} for the selected capacity policy.".format(label), {})


def _limits(value):
    if (not isinstance(value, dict) or set(value) != LIMIT_FIELDS
            or any(type(number) is not int or not 1 <= number <= MAX_THRESHOLD for number in value.values())):
        raise ConfigError("Declare positive signed-64-bit in_flight and integration thresholds; new starts wait when either count reaches its threshold.", {})


def parse_policy(payload) -> dict[str, Any] | None:
    """Validate an opted-in policy; omission preserves the existing config contract."""
    if not isinstance(payload, dict):
        raise ConfigError("Restore the operator-owned JSON config before selecting capacity limits.", {})
    if "backpressure" not in payload:
        return None
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 9:
        raise ConfigError("Opt in to config schema_version 9 before declaring backpressure; older readers must refuse this configuration.", {})
    value = payload["backpressure"]
    if (not isinstance(value, dict) or set(value) != POLICY_FIELDS
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1):
        raise ConfigError("Restore the complete backpressure schema 1: global, repositories, exceptions and rationale.", {})
    _limits(value["global"])
    _text(value["rationale"], "limit-calibration rationale", 512)
    repositories = value["repositories"]
    if not isinstance(repositories, dict) or len(repositories) > 50:
        raise ConfigError("Declare at most 50 explicit owner/repository capacity overrides.", {})
    normalized = {}
    for name, limits in repositories.items():
        if (not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) is None
                or name.lower() in normalized):
            raise ConfigError("Name each owner/repository capacity family once, independent of letter case.", {})
        _limits(limits)
        normalized[name.lower()] = dict(limits)
    exceptions = value["exceptions"]
    if not isinstance(exceptions, list) or len(exceptions) > 16:
        raise ConfigError("Declare at most 16 task-specific capacity exceptions with an expiry and reason.", {})
    seen = set()
    for row in exceptions:
        if not isinstance(row, dict) or set(row) != {"task", "until", "reason"}:
            raise ConfigError("A capacity exception names its task, until checkpoint and reason.", {})
        _text(row["task"], "exception task", 1024)
        _text(row["reason"], "exception reason", 512)
        _text(row["until"], "exception expiry", 128)
        try:
            timestamp(row["until"], "Capacity exception expiry")
        except UsageError:
            raise ConfigError("Give each capacity exception a timezone-aware ISO-8601 until checkpoint.", {}) from None
        if row["task"] in seen:
            raise ConfigError("Keep one explicit capacity exception per task.", {})
        seen.add(row["task"])
    return {**value, "global": dict(value["global"]), "repositories": normalized,
            "exceptions": [dict(row) for row in exceptions]}


def work_sets(state, supervised):
    """Count distinct unfinished task identities, including unsent reservations."""
    from .recovery import task_closure
    from .state import UNCOUNTED_STATUSES

    store = state["recovery"]
    active = {row["assignment"]["task"] for row in supervised["members"] if row["active"]}
    started, integration, unsettled = set(active), set(), set()
    for row in state["assignments"]:
        if not row.get("task"):
            continue
        if row["status"] not in UNCOUNTED_STATUSES:
            started.add(row["task"])
            if row["role"] in INTEGRATION_ROLES or (row.get("fix_round") or 0) > 0:
                integration.add(row["task"])
    for row in store["dispatches"]:
        if row["status"] != "not_sent":
            started.add(row["task"])
            if row["status"] != "applied":
                unsettled.add(row["task"])
            if row["role"] in INTEGRATION_ROLES or (row.get("fix_round") or 0) > 0:
                integration.add(row["task"])
    recorded = {row["id"] for row in store["dispatches"]}
    for task, row in store["tasks"].items():
        progress = row.get("progression", {})
        if progress.get("schema_version") != 2:
            continue
        unknown_jobs = any(identifier not in recorded for identifier in progress["jobs"].values())
        pending_job = (progress["pending"] or {}).get("job")
        unknown_pending = pending_job is not None and pending_job["id"] not in recorded
        if unknown_jobs or unknown_pending or progress["phase"] in INTEGRATION_PHASES or progress["round"] > 0:
            started.add(task)
        if progress["phase"] in INTEGRATION_PHASES or progress["round"] > 0:
            integration.add(task)
    unfinished = active | unsettled
    for task in started - unfinished:
        try:
            closed = task_closure(store, state["assignments"], task)
        except UsageError:
            # Ambiguous closure cannot free a slot or stop unrelated work
            # when the explicitly selected capacity still has headroom.
            closed = None
        if closed is None:
            unfinished.add(task)
    return unfinished, integration & unfinished


def evaluate(state, supervised, task, repository, policy, at, *, family):
    """A capacity decision, never task/effect authority; caller holds the owner lock."""
    now = timestamp(at, "Capacity checkpoint")
    started, integration = work_sets(state, supervised)
    counts: dict[str, Any] = {"global": {"in_flight": len(started), "integration": len(integration)},
              "repository": None, "unverified_repositories": None}
    selected = policy["repositories"].get(repository.lower())
    result: dict[str, Any] = {"schema_version": 1, "allowed": True, "reason": "capacity_available", "conditions": [],
              "counts": counts, "limits": {"global": dict(policy["global"]),
                                            "repository": dict(selected) if selected is not None else None},
              "blocking_tasks": {"total": 0, "items": [], "omitted": 0},
              "exception": None, "authorizes_progression": False}
    if task in started:
        result["reason"] = "drain_existing_task"
        return result
    reasons, blocking = [], set()
    for key, reason in (("in_flight", "global_in_flight_limit"), ("integration", "global_integration_limit")):
        if counts["global"][key] >= policy["global"][key]:
            reasons.append(reason)
            blocking.update(started if key == "in_flight" else integration)
    if selected is not None:
        families = {name: family(name) for name in started}
        unknown = {name for name, value in families.items() if value is None}
        matching = {name for name, value in families.items() if value is not None and value.lower() == repository.lower()}
        counts["repository"] = {"in_flight": len(matching), "integration": len(matching & integration)}
        counts["unverified_repositories"] = len(unknown)
        result["limits"]["repository"] = dict(selected)
        if unknown:
            reasons.append("repository_scope_unverified")
            blocking.update(unknown)
        for key, reason in (("in_flight", "repository_in_flight_limit"), ("integration", "repository_integration_limit")):
            if counts["repository"][key] >= selected[key]:
                reasons.append(reason)
                blocking.update(matching if key == "in_flight" else matching & integration)
    result["conditions"] = reasons
    if reasons:
        result.update(allowed=False, reason=reasons[0])
        exception = next((row for row in policy["exceptions"] if row["task"] == task), None)
        if exception is not None:
            active = now < timestamp(exception["until"], "Capacity exception expiry")
            result["exception"] = {**{key: exception[key] for key in ("until", "reason")}, "active": active}
            if active:
                result.update(allowed=True, reason="explicit_capacity_exception")
    references = [name for name in sorted(blocking)
                  if len(json.dumps(name).encode()) <= REFERENCE_BYTES][:MAX_REFERENCES]
    result["blocking_tasks"] = {"total": len(blocking), "items": references,
                                "omitted": len(blocking) - len(references)}
    return result
