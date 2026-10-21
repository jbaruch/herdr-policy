"""Continuous cheap collection and bounded wake precheck, not policy verdicts.

Timing/size constants are the single source of scheduling and retention behavior.
Candidates ask the observer a question; only the agent decides whether to alert.
Hourly bins contain numeric facts, model/effort totals and source byte locators.
"""

import math
import json
from pathlib import Path
import time

from . import native, sources
from foreman import observer_role
from foreman.errors import ForemanError


POLL_SECONDS = 60
ANALYSIS_SECONDS = 4 * 3600
WEEK_SECONDS = 7 * 86400
STALL_SECONDS = 10 * 60
MIN_WAKE_SECONDS = 15 * 60
DISCOVERY_RETRY_SECONDS = 5 * 60
MAX_VIEW_ROWS = 32
MAX_JOB_BYTES = 48 * 1024
MAX_PROFILES_PER_BIN = 16
STALE_PENDING_SECONDS = 30 * 60
SEND_STATES = frozenset({"new", "sending", "sent", "unknown"})


def add(target, values):
    for key, value in values.items():
        target[key] = target.get(key, 0) + value


def bin_update(store, row, at, metrics, profile=None, locator=None):
    hour = math.floor(at / 3600) * 3600
    key = native.fingerprint([row["key"], hour, row.get("role"), row.get("task")])
    value = store.get("bins", key, {"at": hour, **row, "metrics": {}, "profiles": {}, "locators": []})
    add(value["metrics"], metrics)
    if profile is not None:
        label = native.fingerprint(profile)
        if label not in value["profiles"] and len(value["profiles"]) >= MAX_PROFILES_PER_BIN:
            profile = {"model": None, "effort": None}
            label = "unattributed"
            add(value["metrics"], {"profile_omissions": 1})
        entry = value["profiles"].setdefault(label, {**profile, "metrics": {}})
        add(entry["metrics"], metrics)
    if locator:
        if value["locators"] and value["locators"][-1]["path"] == locator["path"]:
            value["locators"][-1]["end"] = locator["end"]
        elif len(value["locators"]) < 4:
            value["locators"].append(locator)
    store.put("bins", key, value, hour)


def group_rows(rows, field):
    result = {}
    for row in rows:
        key = row.get(field) or "unknown"
        entry = result.setdefault(key, {field: key, "metrics": {}})
        add(entry["metrics"], row["metrics"])
    return sorted(result.values(), key=lambda row: sum(row["metrics"].values()), reverse=True)


def evidence(store, now, *, hours=168, agent=None):
    start = math.floor((now - hours * 3600) / 3600) * 3600
    rows = [row for row in store.rows("bins", start) if agent is None or row.get("name") == agent]
    totals, profiles = {}, {}
    for row in rows:
        add(totals, row["metrics"])
        for profile in row["profiles"].values():
            key = native.fingerprint([row["provider"], profile["model"], profile["effort"], row.get("task"), row.get("role")])
            entry = profiles.setdefault(key, {"provider": row["provider"], "task": row.get("task"),
                                              "role": row.get("role"), **profile, "metrics": {}})
            add(entry["metrics"], profile["metrics"])
    current = store.get("meta", "current", {})
    quota_omitted = current.get("quota_omitted", 0)
    current = {**current, "agents": [r for r in current.get("agents", []) if agent is None or r["name"] == agent]}
    if agent is not None:
        # Shared topology/quota cannot be attributed to one named agent. Keep
        # only that agent's current identity and explicitly omit fleet context.
        current = {**{key: current[key] for key in ("at", "healthy") if key in current},
                   "agents": current["agents"],
                   "unverified_agents": [r for r in current.get("unverified_agents", []) if r.get("name") == agent]}
        quota_omitted = 0
    per_hour = {}
    for row in rows:
        add(per_hour.setdefault(str(row["at"]), {}), row["metrics"])
    all_profiles = sorted(profiles.values(), key=lambda p: p["metrics"].get("tool_calls", 0)
                          + p["metrics"].get("output_tokens", 0), reverse=True)
    agents = group_rows(rows, "name")
    locators = [{"name": r["name"], "task": r.get("task"), **locator}
                for r in rows for locator in r["locators"]]
    source_rows = store.rows("sources", start)
    if agent is not None:
        sessions = {r["session_key"] for r in rows + current["agents"] if r.get("session_key")}
        source_rows = [r for r in source_rows if r["key"] in sessions and r.get("kind") != "quota"]
    coverage = [{"key": r["key"], "provider": r["provider"], "gaps": r.get("gap_history", []),
                 "backlog_bytes": r.get("backlog_bytes")} for r in source_rows if r.get("kind") != "quota"]
    quota_history = [{"profile": r["profile"], "provider": r["provider"], "window_group": r.get("window_group"),
                     "observations": r["history"][-8:], "earlier_observations_omitted": max(0, len(r["history"]) - 8)}
                    for r in source_rows if r.get("kind") == "quota"]
    comparisons, comparison_omitted = {}, {}
    for label, lower, upper in (("recent_day", now - 86400, now), ("previous_day", now - 2 * 86400, now - 86400),
                                ("recent_week", now - WEEK_SECONDS, now), ("previous_week", now - 2 * WEEK_SECONDS, now - WEEK_SECONDS)):
        if lower < start:
            comparison_omitted[label] = "outside_requested_window"
            continue
        summary = {}
        for row in rows:
            if lower <= row["at"] < upper:
                add(summary, row["metrics"])
        comparisons[label] = summary
    hours_view = dict(list(sorted(per_hour.items(), key=lambda entry: float(entry[0])))[-24:])
    result = {"schema_version": 1, "as_of": now, "bucket_start": start, "bucket_seconds": 3600,
            "scope": {"kind": "fleet"} if agent is None else {"kind": "agent", "name": agent,
                      "matched": bool(rows or current["agents"] or current["unverified_agents"])},
            "total_metrics": totals, "by_role": group_rows(rows, "role"),
            "retention": store.get("meta", "retention", {}) if agent is None else {}, "earliest_retained_bucket": min((r["at"] for r in rows), default=None),
            "by_provider": group_rows(rows, "provider"), "by_hour": hours_view, "comparisons": comparisons,
            "comparison_omitted": comparison_omitted,
            "by_agent": agents[:MAX_VIEW_ROWS], "profiles": all_profiles[:MAX_VIEW_ROWS],
            "source_locators": locators[-MAX_VIEW_ROWS:], "current": current,
            "log_coverage": coverage[-MAX_VIEW_ROWS:], "quota_history": quota_history[:MAX_VIEW_ROWS],
            "omitted": {"agents": max(0, len(agents) - MAX_VIEW_ROWS),
                        "profiles": max(0, len(profiles) - MAX_VIEW_ROWS),
                        "locators": max(0, len(locators) - MAX_VIEW_ROWS),
                        "log_coverage": max(0, len(coverage) - MAX_VIEW_ROWS),
                        "quota_history": max(0, len(quota_history) - MAX_VIEW_ROWS), "quota": quota_omitted,
                        "shared_fleet_context": agent is not None},
            "interpretation": ["sampled idle is not proof of eligible work or waste",
                               "recorded task closures are not deployment or user value",
                               "tokens are native counters where covered; output bytes and calls are proxies",
                               "quota measurements retain their source timestamps; missing usage is unknown",
                               "hour buckets overlap partial requested boundary hours",
                               "observer overhead appears when the selected scope includes that role"]}
    return result


def stale_pending(pending, now):
    if not pending.get("id"):
        return False
    if not isinstance(pending.get("send_status"), str) or pending["send_status"] not in SEND_STATES:
        raise ValueError("restore the original pending observer send receipt before recovery")
    if "recovery" in pending and not isinstance(pending["recovery"], dict):
        raise ValueError("restore the original pending observer recovery receipt")
    at = pending.get("last_wake_at", pending.get("created_at"))
    if not isinstance(at, (float, int)) or isinstance(at, bool) or not 0 <= at <= 10**12:
        raise ValueError("restore the pending observer notification timestamp")
    return now - at >= STALE_PENDING_SECONDS


def signal_pending(store, client, now):
    """One generic attention notice per stale job, journaled before notification."""
    if not store.get("meta", "config", {}).get("enabled"):
        return
    pending = store.get("meta", "pending", {})
    if not stale_pending(pending, now) or "attention" in pending:
        return
    with store.transaction():
        current = store.get("meta", "pending", {})
        if current.get("id") != pending["id"] or "attention" in current:
            return
        current["attention"] = {"at": now, "status": "sending"}
        store.put("meta", "pending", current)
    status = "sent"
    try:
        client.notify(attention=True)
    except ValueError:
        status = "unknown"
    with store.transaction():
        current = store.get("meta", "pending", {})
        if current.get("id") == pending["id"]:
            current["attention"]["status"] = status
            store.put("meta", "pending", current)


def anomaly(current):
    return native.fingerprint({"coordinators": sorted(r["key"] for r in current.get("agents", []) if r["role"] == "foreman"),
                               "idle": sorted(r["key"] for r in current.get("agents", []) if r["role"] not in ("foreman", "observer") and r["status"] == "idle"),
                               "duplicates": current.get("duplicates", [])})


def tick(store, client, now=None, user_home=None):
    fixed_clock = now is not None
    now = time.time() if now is None else now
    user_home = Path.home() if user_home is None else Path(user_home)
    config = store.get("meta", "config")
    binding = store.get("meta", "binding")
    if not config or not config["enabled"] or not binding:
        return {"wake_agent": False, "data": {"reason": "observer_disabled"}}
    previous = store.get("meta", "current", {})
    try:
        snapshot = client.snapshot()
    except ValueError:
        store.put("meta", "current", {"at": now, "healthy": False, "agents": [],
                                       "coverage": ["herdr_snapshot_unavailable"], "stall_since": None})
        return {"wake_agent": False, "data": {"reason": "herdr_snapshot_unavailable"}}
    roster = snapshot["agents"]
    if not fixed_clock:
        now = time.time()
    paths, gaps = sources.owner_paths(Path(config["owner_root"]), config["states"])
    roles, quota, closures, contexts, owner_gaps = sources.owners(paths, roster)
    gaps.extend(owner_gaps)
    if not contexts:
        gaps.append("no_current_factory_owner; roles_backlog_and_outcomes_unknown")
    for observation in quota:
        key = "quota:" + native.fingerprint([observation["owner"], observation["profile"]])
        saved = store.get("sources", key, {"key": key, "kind": "quota", "history": [],
                                          "profile": observation["profile"], "provider": observation["provider"],
                                          "window_group": observation["window_group"]})
        if not saved["history"] or saved["history"][-1] != observation:
            saved["history"].append(observation)
            saved["history"] = saved["history"][-64:]
        store.put("sources", key, saved, now)
    physical = {}
    for row in roster:
        who = native.identity(row)
        if who is not None:
            physical.setdefault(native.session_key(who), []).append(row)
    duplicates = [{"session": key, "panes": [row["pane_id"] for row in rows]}
                  for key, rows in physical.items() if len(rows) > 1]
    live = [rows[0] for rows in physical.values() if len(rows) == 1]
    if duplicates:
        gaps.append("duplicate_native_sessions_excluded")
    if len(live) > sources.MAX_AGENTS:
        gaps.append("live_roster_truncated")
    # Rotate the bounded log budget so a noisy coordinator cannot starve worker logs.
    live.sort(key=lambda row: row["pane_id"])
    rotation = int(previous.get("rotation", 0)) % max(1, len(live))
    live = (live[rotation:] + live[:rotation])[:sources.MAX_AGENTS]
    delta = now - previous.get("at", now)
    if not previous.get("healthy") or not 0 < delta <= 2 * POLL_SECONDS:
        if previous:
            gaps.append("sample_gap_not_extrapolated")
        delta = 0
    old_agents = {row["key"]: row for row in previous.get("agents", [])}
    sampled, budget = [], sources.LOG_BUDGET
    for raw in live:
        who = native.identity(raw)
        if who is None:
            continue
        key = native.fingerprint(who)
        session = native.session_key(who)
        role = roles.get(key, {"role": "unassigned", "task": None})
        if native.matches(binding, raw) and key not in roles:
            role = {"role": "observer", "task": None}
        status = raw.get("agent_status", "unknown")
        if status == "done":
            status = "idle"
        if status not in ("idle", "working", "blocked"):
            status = "unknown"
        row = {"key": key, "session_key": session, "name": raw.get("name") or raw["pane_id"], "pane_id": raw["pane_id"],
               "provider": who["agent"], "role": role["role"], "task": role["task"], "status": status,
               "assigned_at": role.get("assigned_at")}
        prior = old_agents.get(key)
        if delta and prior:
            # Attribute an interval to its start state, not a newly observed state.
            bin_update(store, prior, previous["at"], {prior["status"] + "_seconds": delta,
                                                    "sample_seconds": delta})
        cursor = store.get("sources", session)
        new_cursor = cursor is None
        cursor = cursor if cursor is not None else {"provider": who["agent"], "key": session}
        since = max(config["started_at"], store.get("meta", "retention", {}).get("telemetry_floor", 0)) if new_cursor else config["started_at"]
        path = Path(cursor["path"]) if cursor.get("path") else None
        if path is None and now >= cursor.get("retry_at", 0):
            try:
                path = sources.locate(who, user_home)
            except OSError:
                path = None
            cursor["retry_at"] = now + DISCOVERY_RETRY_SECONDS
        log_gaps = []
        if path is None:
            log_gaps = ["native_log_unsupported" if who["agent"] not in sources.SUPPORTED_LOGS else "native_log_not_found"]
        elif budget <= 0:
            log_gaps = ["native_log_deferred_by_cycle_budget"]
        else:
            cursor["path"] = str(path)
            try:
                batches, log_gaps, consumed = sources.read_log(path, cursor, now=now if fixed_clock else None, since=since,
                                                             budget=min(budget, sources.LOG_CHUNK))
                budget -= consumed
                for batch in batches:
                    # Session/task changes while a log backlog exists cannot be assigned retrospectively.
                    unknown_task = (row["task"] is not None and (row["assigned_at"] is None or batch["at"] < row["assigned_at"]))
                    log_row = {**row, "task": None, "role": "unattributed"} if unknown_task else row
                    bin_update(store, log_row, batch["at"], batch["metrics"],
                               {"model": batch["model"], "effort": batch["effort"]},
                               {"path": str(path), "start": batch["start"], "end": batch["end"]})
                if cursor["backlog_bytes"]:
                    log_gaps.append("native_log_backlog")
            except (OSError, ValueError):
                log_gaps = ["native_log_unreadable"]
                cursor.pop("path", None)
        cursor["coverage"] = log_gaps
        history = [item for item in cursor.get("gap_history", []) if now - item["at"] < WEEK_SECONDS * 2]
        if log_gaps and (not history or history[-1]["gaps"] != log_gaps):
            history.append({"at": now, "gaps": log_gaps})
        cursor["gap_history"] = history[-32:]
        if log_gaps:
            bin_update(store, row, now, {"log_gap_samples": 1})
        store.put("sources", session, cursor, now)
        sampled.append({**row, "log_coverage": log_gaps, "model": cursor.get("model"), "effort": cursor.get("effort")})
    # Unique closure receipts, not idle/completion_seq, supply this throughput proxy.
    recorded = store.get("meta", "closures", {"by_owner": {}})
    previous_sequences = dict(recorded["by_owner"])
    new_closure = False
    for closure in closures:
        sequence = closure["sequence"]
        if type(sequence) is not int or sequence < 0:
            gaps.append("closure_sequence_unknown")
            continue
        at = sources.instant(closure["at"])
        if at is None or at > now:
            gaps.append("closure_timestamp_unavailable_or_ahead")
            continue
        prior_sequence = previous_sequences.get(closure["owner"], -1)
        # Refresh current owners before trimming; dict assignment alone does not
        # refresh insertion order. Missing watermarks use the eviction floor.
        floor = recorded.get("evicted_through", -1) if closure["owner"] not in previous_sequences else -1
        recorded["by_owner"][closure["owner"]] = max(recorded["by_owner"].pop(closure["owner"], -1), sequence)
        if floor >= at:
            gaps.append("closure_history_before_eviction_floor_excluded")
        if config["started_at"] <= at <= now and at > floor and sequence > prior_sequence:
            outcome = closure.get("outcome")
            outcome_metric = ({"merged": "merged_task_closures", "abandoned": "abandoned_task_closures"}.get(outcome, "closure_outcome_unknown")
                              if isinstance(outcome, str) else "closure_outcome_unknown")
            bin_update(store, {"key": "outcomes", "name": "recorded-task-closures", "provider": "owner",
                               "role": "outcome", "task": closure["task"]}, at,
                       {"recorded_task_closures": 1, outcome_metric: 1})
            new_closure = new_closure or outcome == "merged"
    if len(recorded["by_owner"]) > sources.MAX_FACTORIES:
        recorded["evicted_through"] = max(recorded.get("evicted_through", 0), now)
    recorded["by_owner"] = dict(list(recorded["by_owner"].items())[-sources.MAX_FACTORIES:])
    store.put("meta", "closures", recorded)
    coordinators = [r for r in sampled if r["role"] == "foreman"]
    workers = [r for r in sampled if r["role"] not in ("foreman", "observer")]
    active = [r for r in sampled if r["role"] != "observer" and r["status"] == "working"]
    concentrated = ((any(r["status"] == "working" for r in coordinators)
                     and not any(r["status"] == "working" for r in workers)) or len(active) == 1)
    idle = len([r for r in sampled if r["role"] != "observer" and r["status"] == "idle"])
    stranded = not active and any(context["active_assignments"] for context in contexts) and idle >= 2
    concentrated = (concentrated or stranded) and idle >= 2 and not new_closure
    stall_since = (previous.get("stall_since") or now) if concentrated and delta else (now if concentrated else None)
    current = {"at": now, "healthy": True, "agents": sampled, "quota": quota[:MAX_VIEW_ROWS],
               "reporter_present": len([r for r in roster if native.matches(binding, r)]) == 1,
               "quota_omitted": max(0, len(quota) - MAX_VIEW_ROWS), "factories": contexts,
               "duplicates": duplicates[:MAX_VIEW_ROWS], "coverage": sorted(set(gaps)), "rotation": rotation + 1,
               "unverified_agents": [{"name": r.get("name"), "provider": r.get("agent"), "status": r.get("agent_status")}
                                     for r in roster if native.identity(r) is None][:MAX_VIEW_ROWS],
               "stall_since": stall_since, "log_bytes_read": sources.LOG_BUDGET - budget}
    store.put("meta", "current", current)
    store.prune(now if fixed_clock else time.time())
    return precheck(store, current, binding, live, now if fixed_clock else time.time())


def precheck(store, current, binding, live, now):
    schedule = store.get("meta", "schedule", {})
    config = store.get("meta", "config")
    last_analysis = schedule.get("last_analysis", config["started_at"])
    last_weekly = schedule.get("last_weekly", config["started_at"])
    reasons = []
    if now - last_weekly >= WEEK_SECONDS:
        reasons.append("weekly_report_due")
    if now - last_analysis >= ANALYSIS_SECONDS and any(r["status"] == "working" for r in current["agents"] if r["role"] != "observer"):
        reasons.append("periodic_open_ended_analysis")
    fresh_anomaly = anomaly(current) != schedule.get("last_anomaly") or now - last_analysis >= ANALYSIS_SECONDS
    if (current["stall_since"] is not None and now - current["stall_since"] >= STALL_SECONDS
            and now - last_analysis >= MIN_WAKE_SECONDS and fresh_anomaly):
        if not any(r["status"] == "working" for r in current["agents"] if r["role"] != "observer"):
            reasons.append("idle_factory_with_open_work_check")
        else:
            reasons.append("coordinator_only_activity_check" if any(r["role"] == "foreman" and r["status"] == "working" for r in current["agents"]) else "single_active_agent_check")
    if current["duplicates"] and now - last_analysis >= MIN_WAKE_SECONDS and fresh_anomaly:
        reasons.append("duplicate_session_binding_check")
    pending = store.get("meta", "pending", {})
    if not pending.get("id") and reasons:
        data = evidence(store, now, hours=336)
        # Keep the scheduled context bounded; filtered evidence remains queryable.
        if len(json.dumps(data).encode()) > MAX_JOB_BYTES:
            data["omitted"]["locators"] += len(data["source_locators"])
            data["source_locators"] = []
            data["omitted"]["current_agents"] = max(0, len(data["current"]["agents"]) - MAX_VIEW_ROWS)
            data["current"]["agents"] = data["current"]["agents"][:MAX_VIEW_ROWS]
            data["context_truncated"] = True
        while len(json.dumps(data).encode()) > MAX_JOB_BYTES:
            lists = [(data, "profiles"), (data, "by_agent"), (data, "log_coverage"), (data, "quota_history"),
                     (data["current"], "quota"), (data["current"], "agents")]
            parent, field = max(lists, key=lambda item: len(json.dumps(item[0][item[1]])))
            if not parent[field]:
                # Keep essential state and make any larger evidence an explicit query.
                data = {"schema_version": 1, "as_of": now, "context_truncated": True,
                        "current": {k: current[k] for k in ("at", "healthy", "coverage", "stall_since")},
                        "total_metrics": data["total_metrics"], "comparisons": data["comparisons"],
                        "comparison_omitted": data["comparison_omitted"]}
                break
            removed = len(parent[field]) - len(parent[field]) // 2
            category = {"by_agent": "agents", "agents": "current_agents"}.get(field, field)
            data["omitted"][category] = data["omitted"].get(category, 0) + removed
            parent[field] = parent[field][:len(parent[field]) // 2]
            data["context_truncated"] = True
        pending = {"id": native.fingerprint([now, binding["identity"]]), "created_at": now,
                   "reasons": reasons, "data": data, "send_status": "new", "anomaly": anomaly(current)}
        store.put("meta", "pending", pending)
    observer = [row for row in live if native.matches(binding, row)]
    ready = len(observer) == 1 and observer[0].get("agent_status") in ("idle", "done")
    recover = bool(pending.get("id") and pending["send_status"] != "new"
                   and "recovery" not in pending and stale_pending(pending, now))
    return {"wake_agent": bool(pending.get("id") and (pending["send_status"] == "new" or recover) and ready),
            "recovery": recover,
            "data": {"job": pending} if pending.get("id") else {"reason": "no_analysis_due"}}


def dispatch(store, client, checked, now=None):
    """Journal the initial wake and at most one explicit reconciliation request.

Recovery preserves the original send receipt and job; it never repeats factory
work. Private report/ack operations remain idempotent on that original job ID.
"""
    if not checked["wake_agent"]:
        return checked
    pending = store.get("meta", "pending")
    binding = store.get("meta", "binding")
    recovery = checked.get("recovery", False)
    now = time.time() if now is None else now
    if not store.get("meta", "config", {}).get("enabled"):
        return {"wake_agent": False, "data": {"reason": "observer_disabled"}}
    try:
        owner = observer_role.delivery_owner(binding["identity"]["pane_id"], store.get("meta", "config").get("states", []))
    except (ForemanError, OSError, ValueError):
        return {"wake_agent": False, "data": {"reason": "observer_ownership_unavailable"}}
    if owner is not None:
        return {"wake_agent": False, "data": {"reason": "observer_has_delivery_ownership"}}
    if (not pending or pending["id"] != checked["data"]["job"]["id"]
            or not recovery and pending["send_status"] != "new"
            or recovery and ("recovery" in pending or not stale_pending(pending, now))):
        return {"wake_agent": False, "data": {"reason": "job_changed"}}
    # Revalidate this exact reporter just before sending; no worker can be targeted.
    rows = client.snapshot()["agents"]
    ready = [row for row in rows if native.matches(binding, row) and row.get("agent_status") in ("idle", "done")]
    if len(ready) != 1:
        return {"wake_agent": False, "data": {"reason": "observer_not_ready"}}
    with store.transaction():
        saved = store.get("meta", "pending", {})
        if (saved.get("id") != pending["id"] or not recovery and saved.get("send_status") != "new"
                or recovery and "recovery" in saved):
            return {"wake_agent": False, "data": {"reason": "job_changed"}}
        pending = saved
        if recovery:
            pending["recovery"] = {"at": now, "status": "sending"}
        else:
            pending["send_status"] = "sending"
        pending["last_wake_at"] = now
        store.put("meta", "pending", pending)
    status = "sent"
    try:
        client.prompt(binding["name"], recovery=recovery)
    except ValueError:
        status = "unknown"
    with store.transaction():
        current = store.get("meta", "pending", {})
        if current.get("id") == pending["id"]:
            if recovery:
                current["recovery"]["status"] = status
            else:
                current["send_status"] = status
            store.put("meta", "pending", current)
    return {"wake_agent": True, "data": {"job_id": pending["id"], "send_status": status, "recovery": recovery}}
