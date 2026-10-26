"""Run bounded independent task cycles without a foreman model relay.

The current task grants select existing executors. Each task retains its own
kernel lease, durable pending intent and native send owner. Preparation runs
concurrently; primary transactions remain canonical. There is no saved batch
board or replacement assignment history.
"""

from concurrent.futures import ThreadPoolExecutor
import time
from typing import Callable

from . import context_output, progression_owner as authority, supervision
from .errors import ForemanError, UsageError
from .native_policy import executing_policy_root
from .workflow_service import WorkflowService
from .state import TransactionBusy


WORKERS = 4
TICKS_PER_CYCLE = 16
INTERVAL_SECONDS = 5


def _drive(path, client, grant, task, root, *, session=authority.service_session, factory: Callable[..., WorkflowService] = WorkflowService):
    try:
        with session(path, task, grant["generation"], grant["service_id"], root) as capability:
            service = factory(capability, client)
            result = None
            for _ in range(TICKS_PER_CYCLE):
                result = service.tick()
                if result["data"]["status"] in {"waiting", "exception", "complete"}:
                    break
            assert result is not None
            return result["data"]
    except TransactionBusy:
        return {"task": task, "generation": grant["generation"], "status": "waiting",
                "reason": "owner_transaction_busy", "authorizes_acceptance": False, "authorizes_release": False}
    except ForemanError as exc:
        return {"task": task, "generation": grant["generation"], "status": "decision",
                "reason": exc.details.get("reason", "task_executor_unavailable"), "error": exc.code,
                "diagnostic": exc.message[:1024],
                "authorizes_acceptance": False, "authorizes_release": False}


def cycle(path, client, at, *, task=None, limit=context_output.DEFAULT_LIMIT, offset=0,
          root=None, session=authority.service_session, factory: Callable[..., WorkflowService] = WorkflowService):
    context_output.validate_page(limit, offset)
    supervision.timestamp(at)
    state = authority._load(path)
    authority.verify_foreman(path, client, native_only=True)
    candidates = sorted(name for name, row in state["recovery"]["tasks"].items()
                        if row.get("authority", {}).get("mode") == "service"
                        and row["authority"].get("contract_schema") in (2, 3)
                        and (task is None or name == task))
    selected = candidates[offset:offset + limit]
    if task is not None and task not in candidates:
        raise UsageError("Admit this existing task through its actual owner before running its executor; an unsupported manual boundary is not an empty completed batch.",
                         {"reason": "task_not_admitted"})
    policy_root = executing_policy_root() if root is None else root
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(lambda name: _drive(path, client,
            state["recovery"]["tasks"][name]["authority"], name, policy_root, session=session, factory=factory), selected))
    # A concurrent short owner transaction is an observation, never a task
    # decision. Retry each contended item after the preparation wave drains.
    for index, row in enumerate(rows):
        if row.get("reason") == "owner_transaction_busy":
            name = selected[index]
            rows[index] = _drive(path, client, state["recovery"]["tasks"][name]["authority"],
                name, policy_root, session=session, factory=factory)
    initial = {row["id"] for row in state["recovery"]["dispatches"] if row["status"] == "applied"}
    current = authority._load(path)
    for row in rows:
        row["started_dispatches"] = [item["id"] for item in current["recovery"]["dispatches"]
            if item["task"] == row["task"] and item["status"] == "applied" and item["id"] not in initial]
    def build(effective):
        items = rows[:effective]
        page = context_output.page(candidates, offset, effective)
        page.pop("items")
        return {"observed_at": at, "items": items, "pagination": page,
                "context_complete": offset == 0 and len(candidates) <= effective,
                "counts_scope": "returned_items", "counts": {
                    "started": sum(len(row["started_dispatches"]) for row in items),
                    "waiting": sum(row["status"] == "waiting" for row in items),
                    "decisions": sum(row["status"] in {"exception", "decision"} for row in items)},
                "wake_agent": any(row["status"] in {"exception", "decision"} for row in items),
                "authorizes_acceptance": False, "authorizes_release": False}
    return context_output.fit_pages(build, limit, offset)


def run_command(args, path, client, *, clock, sleeper=time.sleep):
    while True:
        result = cycle(path, client, clock(), task=args.task, limit=args.limit, offset=args.offset)
        if args.once or not result["items"] or all(row["status"] in {"complete", "exception", "decision"} for row in result["items"]):
            return result, None
        sleeper(INTERVAL_SECONDS)


def register_commands(sub, common):
    parser = sub.add_parser("progression-batch", parents=[common])
    parser.add_argument("--task")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=context_output.DEFAULT_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
