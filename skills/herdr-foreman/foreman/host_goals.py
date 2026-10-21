"""Reset-owned transfer of a Codex host goal, with no invented goal status.

The native input hook authenticates the incoming owner before this handshake.
Retire the old scheduler before activating the new one: a failure can leave
zero executors, never two admitted executors. Persist intent before each RPC;
reconciliation reads both goals rather than repeating uncertain mutations.

Codex cannot import historical usage into another thread. The reset receipt
carries cumulative usage, and the successor receives only the remaining
budget. Chained resets carry that receipt forward for the same goal generation.
Native Claude/Grok have no Codex goal scheduler; their continuation creates no
host goal and makes no claim about an external host's scheduler.
"""

import copy
import os
import time

from .codex_goals import AppServer, control_socket, unavailable, valid_goal

QUIESCE_BUDGET_SEC = 30
QUIESCE_POLL_SEC = 0.2
PHASES = {"prepared", "quiescing", "retiring", "retired", "restoring", "restored", "verified"}
FIELDS = {"schema_version", "runtime", "socket", "source_thread", "source_goal", "target_thread",
          "target_created_at", "phase", "carried_tokens", "carried_seconds", "retiring_turn", "resume_status"}


def valid(value):
    if value is None:
        return True  # Legacy rows have no proof; a Codex input must refuse them.
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        return False
    if value.get("runtime") in ("claude", "grok"):
        return set(value) == {"schema_version", "runtime", "phase"} and value["phase"] == "not_applicable"
    return (set(value) == FIELDS and value.get("runtime") == "codex"
            and isinstance(value["socket"], str) and os.path.isabs(value["socket"])
            and isinstance(value["source_thread"], str) and bool(value["source_thread"])
            and (value["source_goal"] is None or valid_goal(value["source_goal"], value["source_thread"]))
            and (value["target_thread"] is None or isinstance(value["target_thread"], str) and bool(value["target_thread"]))
            and (value["target_created_at"] is None or type(value["target_created_at"]) is int and value["target_created_at"] >= 0)
            and (value["retiring_turn"] is None or isinstance(value["retiring_turn"], str) and bool(value["retiring_turn"]))
            and (value["resume_status"] is None if value["source_goal"] is None
                 else isinstance(value["resume_status"], str) and value["resume_status"] in
                 {"active", "paused", "blocked", "usageLimited", "budgetLimited"})
            and isinstance(value["phase"], str) and value["phase"] in PHASES
            and all(type(value[key]) is int and value[key] >= 0 for key in ("carried_tokens", "carried_seconds")))


def same_goal(left, right):
    if left is None or right is None:
        return left is None and right is None
    return all(left[key] == right[key] for key in ("threadId", "objective", "createdAt", "status", "tokenBudget"))


def prepare(runtime, session, previous=(), *, connect=None, discover=None):
    """Read-only preflight. Unavailable Codex goal control refuses before clearing."""
    if runtime in ("claude", "grok"):
        return {"schema_version": 1, "runtime": runtime, "phase": "not_applicable"}
    if runtime != "codex" or session["kind"] != "id":
        raise unavailable("unsupported_goal_runtime")
    path = (discover or control_socket)()
    with (connect or AppServer)(path) as host:
        goal = host.goal(session["value"])
    if goal is not None and goal["status"] == "complete":
        raise unavailable("completed_goal_requires_new_authority")
    carried_tokens = carried_seconds = 0
    for receipt in reversed(list(previous)):
        if (valid(receipt) and receipt is not None and receipt["runtime"] == "codex"
                and receipt["phase"] == "verified" and receipt["target_thread"] == session["value"]
                and goal is not None and receipt["source_goal"] is not None
                and receipt["target_created_at"] == goal["createdAt"]
                and receipt["source_goal"]["objective"] == goal["objective"]):
            carried_tokens, carried_seconds = receipt["carried_tokens"], receipt["carried_seconds"]
            break
    return {"schema_version": 1, "runtime": runtime, "socket": path, "source_thread": session["value"],
            "source_goal": copy.deepcopy(goal), "target_thread": None, "target_created_at": None, "phase": "prepared",
            "retiring_turn": None, "resume_status": goal["status"] if goal else None,
            "carried_tokens": carried_tokens + (goal["tokensUsed"] if goal else 0),
            "carried_seconds": carried_seconds + (goal["timeUsedSeconds"] if goal else 0)}


def refresh(receipt, host, *, interrupted=False):
    """Keep final outgoing usage; a changed goal, lifecycle or budget is new authority."""
    current = host.goal(receipt["source_thread"])
    before = receipt["source_goal"]
    observed = current
    if interrupted and current is not None and before is not None and current["status"] == "paused":
        # A real turn/interrupt can pause the host goal. Restore the original
        # lifecycle on the successor, never manufacture a pause to retire it.
        observed = {**current, "status": before["status"]}
    if not same_goal(observed, before):
        raise unavailable("source_goal_changed")
    if current is not None and before is not None:
        for stored, native in (("carried_tokens", "tokensUsed"), ("carried_seconds", "timeUsedSeconds")):
            if current[native] < before[native]:
                raise unavailable("source_usage_changed")
            receipt[stored] += current[native] - before[native]
        receipt["source_goal"] = copy.deepcopy(current)


def remaining(receipt):
    goal = receipt["source_goal"]
    return None if goal is None or goal["tokenBudget"] is None else max(0, goal["tokenBudget"] - goal["tokensUsed"])


def matches_target(receipt, goal, target):
    source = receipt["source_goal"]
    return (goal is not None and source is not None and goal["threadId"] == target
            and goal["objective"] == source["objective"] and goal["status"] == receipt["resume_status"]
            and goal["tokenBudget"] == remaining(receipt)
            and (receipt["target_created_at"] is None or receipt["target_created_at"] == goal["createdAt"]))


def quiescent(host, thread_id, sleep, clock):
    deadline = clock() + QUIESCE_BUDGET_SEC
    while True:
        thread = host.call("thread/read", {"threadId": thread_id}).get("thread")
        if not isinstance(thread, dict) or thread.get("id") != thread_id:
            raise unavailable("invalid_source_thread")
        status = thread.get("status")
        if isinstance(status, dict) and status.get("type") in ("idle", "notLoaded"):
            return
        if not isinstance(status, dict) or status.get("type") != "active" or clock() >= deadline:
            raise unavailable("source_executor_not_quiescent")
        sleep(QUIESCE_POLL_SEC)


def retire_turn(receipt, host, persist, sleep, clock):
    """Interrupt only the exact obsolete host turn, retaining final usage."""
    refresh(receipt, host, interrupted=receipt["retiring_turn"] is not None)
    thread = host.call("thread/read", {"threadId": receipt["source_thread"]}).get("thread")
    if not isinstance(thread, dict) or thread.get("id") != receipt["source_thread"]:
        raise unavailable("invalid_source_thread")
    status = thread.get("status")
    if isinstance(status, dict) and status.get("type") == "active":
        if receipt["resume_status"] != "active":
            # No automatic executor is being retired. A manual turn around an
            # absent/inactive goal must finish without synthetic cancellation.
            quiescent(host, receipt["source_thread"], sleep, clock)
            refresh(receipt, host)
            return
        turns = host.call("thread/turns/list", {"threadId": receipt["source_thread"], "limit": 1,
                                               "sortDirection": "desc", "itemsView": "notLoaded"}).get("data")
        turn = turns[0] if isinstance(turns, list) and len(turns) == 1 else None
        if (not isinstance(turn, dict) or turn.get("status") != "inProgress"
                or not isinstance(turn.get("id"), str) or not turn["id"]
                or receipt["retiring_turn"] not in (None, turn["id"])):
            raise unavailable("source_turn_changed")
        receipt["retiring_turn"] = turn["id"]
        persist()
        host.call("turn/interrupt", {"threadId": receipt["source_thread"], "turnId": turn["id"]})
    quiescent(host, receipt["source_thread"], sleep, clock)
    refresh(receipt, host, interrupted=receipt["retiring_turn"] is not None)


def transfer(receipt, target, persist, *, connect=None, sleep=time.sleep, clock=time.monotonic):
    """Complete/recover only this authenticated reset's journaled host handoff."""
    if not valid(receipt) or receipt is None:
        raise unavailable("missing_goal_preflight")
    if receipt["runtime"] != "codex":
        return
    if target == receipt["source_thread"] or receipt["target_thread"] not in (None, target):
        raise unavailable("target_thread_changed")
    with (connect or AppServer)(receipt["socket"]) as host:
        if receipt["phase"] == "prepared":
            refresh(receipt, host)
            if host.goal(target) is not None:
                raise unavailable("target_goal_already_exists")
            receipt.update(target_thread=target, phase="quiescing")
            persist()
        if receipt["phase"] == "quiescing":
            retire_turn(receipt, host, persist, sleep, clock)
            receipt["phase"] = "retiring"
            persist()
        if receipt["phase"] == "retiring":
            current = host.goal(receipt["source_thread"])
            if current is not None:
                quiescent(host, receipt["source_thread"], sleep, clock)
                refresh(receipt, host)
                persist()
                # --explicit-reset records the operator's requested handoff.
                # Clearing an obsolete executor is not completion or a pause.
                result = host.call("thread/goal/clear", {"threadId": receipt["source_thread"], "origin": "user"})
                if result.get("cleared") is not True:
                    raise unavailable("source_retirement_unverified")
            if host.goal(receipt["source_thread"]) is not None:
                raise unavailable("source_retirement_unverified")
            receipt["phase"] = "retired"
            persist()
        # A cleared goal stops future continuation, not a turn already in flight.
        # Do not admit the incoming turn until that executor has actually ended.
        quiescent(host, receipt["source_thread"], sleep, clock)
        if host.goal(receipt["source_thread"]) is not None:
            raise unavailable("source_goal_reactivated")
        if receipt["phase"] == "retired":
            if host.goal(target) is not None:
                raise unavailable("target_goal_already_exists")
            receipt["phase"] = "restoring"
            persist()
        if receipt["phase"] == "restoring":
            goal = host.goal(target)
            if receipt["source_goal"] is not None:
                if goal is None:
                    source = receipt["source_goal"]
                    host.call("thread/goal/set", {"threadId": target, "objective": source["objective"],
                                                 "status": receipt["resume_status"], "tokenBudget": remaining(receipt), "origin": "user"})
                    goal = host.goal(target)
                if goal is None or not matches_target(receipt, goal, target):
                    raise unavailable("target_goal_changed")
                receipt["target_created_at"] = goal["createdAt"]
            elif goal is not None:
                raise unavailable("unexpected_target_goal")
            receipt["phase"] = "restored"
            persist()
        goal = host.goal(target)
        if ((receipt["source_goal"] is None and goal is not None)
                or receipt["source_goal"] is not None and not matches_target(receipt, goal, target)
                or host.goal(receipt["source_thread"]) is not None):
            raise unavailable("goal_transfer_unverified")
        receipt["phase"] = "verified"
        persist()
