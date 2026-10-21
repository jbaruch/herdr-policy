"""Retry failed/missing measurements using only the latest existing snapshot.

No cache store or background refresh. Reused readings retain the oldest
observation time; they never acquire the retry's timestamp or effect authority.
"""

import hashlib
import json
import os
import socket
from dataclasses import asdict
from datetime import timedelta

from .chronology import timestamp
from .command_context import HerdrCommandContext
from .errors import UsageError
from .tier_routing import CAPACITY_MAX_AGE


def context_digest(agents, client):
    context = getattr(client, "context", None)
    if not isinstance(context, HerdrCommandContext):
        return None  # An unbound test/custom transport cannot prove reuse.
    facts = {"profiles": [{**agent.as_dict(), "window_group": agent.window_group} for agent in agents],
             "transport": asdict(context), "host": socket.gethostname(), "herdr_env": os.environ.get("HERDR_ENV")}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def split(agents, previous, digest, at):
    """Keep a successful shared window only when all its profiles still fit."""
    if not digest or not isinstance(previous, dict) or previous.get("measurement_context_sha256") != digest:
        return agents, {}
    try:
        age = timestamp(at, "Measurement retry") - timestamp(previous.get("measured_at"), "Previous measurement")
    except UsageError:
        return agents, {}
    if not timedelta(0) <= age < CAPACITY_MAX_AGE:
        return agents, {}
    records = previous.get("agents", {})
    if not isinstance(records, dict):
        return agents, {}
    groups = {}
    for agent in agents:
        groups.setdefault(("shared", agent.window_group) if agent.window_group else ("worker", agent.name), []).append(agent)
    attempted, reused = [], {}
    for members in groups.values():
        usable = all(isinstance(records.get(agent.name), dict)
                     and "error" not in records[agent.name] and not records[agent.name].get("skipped")
                     and isinstance(records[agent.name].get("headroom_pct"), (int, float))
                     and not isinstance(records[agent.name]["headroom_pct"], bool)
                     and 0 <= records[agent.name]["headroom_pct"] <= 100
                     and records[agent.name].get("kind") == agent.kind
                     and records[agent.name].get("window_group") == agent.window_group
                     for agent in members)
        if usable:
            reused.update({agent.name: records[agent.name] for agent in members})
        else:
            attempted.extend(members)
    return attempted, reused


def combine(snapshot, reused, previous, digest):
    snapshot["measurement_context_sha256"] = digest
    snapshot["reused_agents"] = sorted(reused)
    if reused:
        snapshot["agents"] = {**reused, **snapshot["agents"]}
        # Existing readers use the global time. Keeping the older time makes
        # every freshness check conservative without another per-profile clock.
        snapshot["measured_at"] = previous["measured_at"]
    return snapshot
