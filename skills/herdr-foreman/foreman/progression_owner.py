"""Task-scoped service admission and fencing in the existing state owner.

Only a verified bound foreman admits or returns a task. An admission delegates
one task and one immutable contract to a process holding its kernel lease.
The capability stays in process memory; CLI input cannot supply one. It does
not waive dispatch, evidence, supervision, review or release checks.

The recovery owner stores one current grant on a version-2 task record, never
a second task database or a local grant history. Every replacement increments
the generation. Lease death alone cannot return a task or classify a send.
"""

from copy import deepcopy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re

from . import recovery, supervision
from .errors import StateError, UsageError
from .process_lease import process_lease
from .remote_owner import loaded_policy
from .state import STATE_SCHEMA_VERSION, load_state_checked, save_state, state_lock


GRANT_VERSION = 1
GRANT_BYTES = 4_096
TASK_BYTES = 512
GRANT_FIELDS = frozenset({"schema_version", "generation", "mode", "service_id", "lease_path",
                          "contract", "policy", "binding", "authorization", "at"})
IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")
TASK_MUTATIONS = frozenset({
    "apply", "start-judge", "relaunch-worker", "task", "close-task", "checkpoint",
    "authorize-corrections", "authorize-approach", "recover-context", "recover-role-clear", "record-report",
    "record-refusal", "authorize-refused-dispatch", "diagnose", "reconcile", "recover-no-work",
    "reconcile-bootstrap", "record-release-clear", "import-correction", "record-historical-review",
    "recover-report", "assess-specialist", "close-member", "supervision-ack", "supervision-resolve",
    "foreman-reset", "foreman-reset-deliver", "foreman-reset-reconcile", "start-foreman",
})
SERVICE_COMMANDS = frozenset({"apply"})
JUDGMENT_COMMANDS = frozenset({"record-report", "close-member", "supervision-ack", "supervision-resolve",
                              "assess-specialist", "record-refusal", "checkpoint", "diagnose", "authorize-corrections",
                              "authorize-approach", "reconcile", "recover-no-work", "reconcile-bootstrap",
                              "record-release-clear", "import-correction", "record-historical-review", "recover-report",
                              "recover-role-clear", "recover-context", "authorize-refused-dispatch"})


def validate_grant(grant):
    if (not isinstance(grant, dict) or set(grant) != GRANT_FIELDS
            or type(grant["schema_version"]) is not int or grant["schema_version"] != GRANT_VERSION
            or type(grant["generation"]) is not int or grant["generation"] < 1
            or grant["mode"] not in ("legacy", "service")):
        raise UsageError("Unsupported task authority grant; update its owner and preserve unresolved work.", {})
    if len(json.dumps(grant).encode("utf-8")) > GRANT_BYTES:
        raise UsageError("Keep the current authority grant bounded; cite a concise authorization and current contract instead of copying history.", {})
    supervision.timestamp(grant["at"])
    recovery.authorization(grant["authorization"])
    fields = ("service_id", "lease_path", "contract", "policy", "binding")
    if grant["mode"] == "legacy":
        if any(grant[name] is not None for name in fields):
            raise UsageError("A returned task must clear service capabilities while retaining its generation.", {})
        return
    if (not isinstance(grant["service_id"], str) or IDENTIFIER.fullmatch(grant["service_id"]) is None
            or not isinstance(grant["lease_path"], str) or not Path(grant["lease_path"]).is_absolute()):
        raise UsageError("Restore the admitted service identity and absolute lease path through the task owner.", {})
    recovery.validate_receipt(grant["contract"])
    policy, binding = grant["policy"], grant["binding"]
    if (not isinstance(policy, dict) or set(policy) != {"version", "digest"}
            or not isinstance(policy["version"], str) or re.fullmatch(r"\d+\.\d+\.\d+", policy["version"]) is None
            or not isinstance(policy["digest"], str) or re.fullmatch(r"[a-f0-9]{64}", policy["digest"]) is None
            or not isinstance(binding, dict) or set(binding) != {"generation", "digest"}
            or type(binding["generation"]) is not int or binding["generation"] < 1
            or not isinstance(binding["digest"], str) or re.fullmatch(r"[a-f0-9]{64}", binding["digest"]) is None):
        raise UsageError("Restore the admitted policy and supervision binding before service work.", {})


def current_grant(state, task):
    row = state["recovery"]["tasks"].get(task)
    return row.get("authority") if row else None


def _load(path):
    state, usable = load_state_checked(path, persist_migration=False)
    if not usable:
        raise StateError("Restore readable owner state before changing task authority; never replace it with empty state.", {})
    return state


def _binding(data):
    binding = data["binding"]
    if binding is None:
        raise UsageError("Bind and verify the current foreman before admitting background work.", {})
    return {"generation": binding["generation"], "digest": supervision.digest(binding["identity"])}


def verify_foreman(state_path, client):
    """Read the actual native caller or the existing verified remote owner."""
    data = supervision.load(state_path)
    if getattr(getattr(client, "context", None), "mode", None) == "attested-remote":
        client.remote_preflight(state_path)
        expected = supervision.remote_identity(client.context.attestation, client._remote_authority.plugin_root,
                                               owner_store_path=client._remote_authority.path)
    else:
        environment, pane_id = os.environ.get("HERDR_ENV"), os.environ.get("HERDR_PANE_ID")
        if not environment or not pane_id:
            raise UsageError("Run authority handoff from the verified bound Herdr foreman; standalone mode grants no service authority.", {})
        pane = client.pane_get(pane_id)
        native = pane.get("agent_session")
        if (pane.get("pane_id") != pane_id or not isinstance(native, dict)
                or native.get("kind") not in ("id", "path") or native.get("agent") not in ("claude", "codex", "grok")
                or native.get("source") != "herdr:" + native["agent"]):
            raise UsageError("Restore the foreman's current native identity before a task authority handoff.", {})
        expected = supervision.identity(native["value"], str(Path.cwd()), environment,
                                        kind=native["kind"], pane_id=pane_id)
    if data["binding"] is None or data["binding"]["identity"] != expected:
        raise UsageError("The caller differs from the bound foreman; reconcile ownership without replacing its records.", {})
    return data


def _settled(state, supervised, task):
    pending = [row["id"] for row in state["recovery"]["dispatches"]
               if row["task"] == task and row["status"] in recovery.PENDING_STATUSES]
    active = [row["id"] for row in supervised["members"] if row["active"] and row["assignment"]["task"] == task]
    if pending or active:
        raise UsageError("Reconcile this task's pending sends and active enrollments through their existing owners before handoff; lease exit proves no delivery outcome.",
                         {"task": task, "pending_dispatch_count": len(pending), "active_enrollment_count": len(active)})


def _unresumed_hold(supervised):
    return any(row["resumed_at"] is None for row in supervised["holds"])


def handoff(state_path, data, at, client, plugin_root, *, returning=False):
    """Called under the canonical state lock; never bind, resume or start a worker."""
    from .progression_service import capture_contract
    fields = {"task", "expected_generation", "authorization"} | (set() if returning else {"service_id", "lease_path", "contract"})
    if not isinstance(data, dict) or set(data) != fields:
        raise UsageError("Supply the complete task authority handoff record and explicit authorization.", {})
    recovery.text(data["task"], "task")
    if len(data["task"].encode("utf-8")) > TASK_BYTES:
        raise UsageError("Use the existing concise task identity; put narrative scope in its GitHub issue.", {})
    recovery.authorization(data["authorization"])
    supervision.timestamp(at)
    state = _load(state_path)
    row = recovery.task_record(state["recovery"], data["task"])
    if not returning and recovery.task_closure(state["recovery"], state["assignments"], data["task"]) is not None:
        raise UsageError("This task is closed; register the newly authorized scope under its own task identity before admission.", {})
    old = current_grant(state, data["task"])
    generation = old["generation"] if old else 0
    if type(data["expected_generation"]) is not int or data["expected_generation"] != generation:
        raise UsageError("Read current task authority and retry the same handoff with its actual generation.", {})
    if (returning and (old is None or old["mode"] != "service")
            or not returning and old is not None and old["mode"] == "service"):
        raise UsageError("This task already belongs to the selected authority; use its existing owner instead of creating another dispatcher.", {})
    supervised = verify_foreman(state_path, client)
    _settled(state, supervised, data["task"])
    if row.get("progression", {}).get("pending") is not None:
        raise UsageError("Reconcile the service's pending transition before returning or replacing its authority; process exit proves no effect outcome.", {})
    if not returning and _unresumed_hold(supervised):
        raise UsageError("Existing operator holds prevent service admission; preserve their explicit resume conditions.", {})
    grant = {"schema_version": GRANT_VERSION, "generation": generation + 1,
             "mode": "legacy" if returning else "service", "service_id": None, "lease_path": None,
             "contract": None, "policy": None, "binding": None,
             "authorization": deepcopy(data["authorization"]), "at": at}
    if not returning:
        version, digest = loaded_policy(plugin_root)
        captured, _document = capture_contract(data["contract"])
        grant.update(service_id=data["service_id"], lease_path=data["lease_path"], contract=captured,
                     policy={"version": version, "digest": digest}, binding=_binding(supervised))
    validate_grant(grant)
    if returning:
        assert old is not None
        lease_path = old["lease_path"]
    else:
        lease_path = grant["lease_path"]
    if Path(lease_path).resolve() in {Path(state_path).resolve(), Path(str(state_path) + ".lock").resolve(),
                                    supervision.store_path(state_path).resolve()}:
        raise UsageError("Use a dedicated progression lease, distinct from owner records and transaction locks.", {})
    # A live holder prevents both replacement and return. Acquire and release
    # only after all refusal checks; no stale heartbeat or PID guess reclaims it.
    def commit(current):
        # Admission and supervision quiescence share the existing sidecar lock.
        # Legacy observation/assessment owners retain their independent lock;
        # no new index or parallel authority store is needed.
        if _binding(current) != _binding(supervised):
            raise UsageError("The bound foreman changed during handoff; verify its current owner before retrying.", {})
        _settled(state, current, data["task"])
        if not returning and _unresumed_hold(current):
            raise UsageError("An operator hold arrived during admission; preserve its resume conditions.", {})
        with process_lease(lease_path):
            row.update(schema_version=2, authority=grant)
            row.pop("progression", None)
            save_state(state_path, state)
        return {"task": data["task"], "authority": deepcopy(grant), "authorizes_dispatch": False}
    return supervision.transaction(state_path, commit)


class ServiceCapability:
    """Mint only while holding the admitted kernel lease; never serialize."""

    def __init__(self, *, state_path, task, generation, service_id, lease, plugin_root):
        if type(generation) is not int or generation < 1:
            raise UsageError("Supply the actual positive owner generation before claiming progression.", {})
        self.state_path = Path(state_path).resolve()
        self.task, self.generation, self.service_id = task, generation, service_id
        self.lease, self.plugin_root = lease, Path(plugin_root).resolve()
        self._prepared = None
        self.gate_reports = ()

    def require_current(self, state_path, state, task):
        from .progression_service import capture_contract
        self.lease.require_current()
        if Path(state_path).resolve() != self.state_path or task != self.task:
            raise UsageError("The progression capability covers only its admitted state and task.", {})
        grant = current_grant(state, task)
        if (grant is None or grant["mode"] != "service" or grant["generation"] != self.generation
                or grant["service_id"] != self.service_id or Path(grant["lease_path"]).resolve() != self.lease._path.resolve()):
            raise UsageError("The task authority generation changed; stop effects and reconcile through its current owner.", {})
        supervised = supervision.load(state_path)
        if _binding(supervised) != grant["binding"] or _unresumed_hold(supervised):
            raise UsageError("The supervision binding or operator hold prevents service effects; preserve pending deliveries and resume conditions.", {})
        known = {item["id"] for item in state["recovery"]["dispatches"]
                 if item["task"] == task and item["status"] != "not_sent"}
        if any(item["active"] and item["assignment"]["task"] == task and item["id"] not in known
               for item in supervised["members"]):
            raise UsageError("This task has an enrollment without a confirmed dispatch owner; reconcile it before service effects.", {})
        version, digest = loaded_policy(self.plugin_root)
        if grant["policy"] != {"version": version, "digest": digest}:
            raise UsageError("Loaded service policy changed; stop effects and obtain an explicit new authority handoff.", {})
        captured, _document = capture_contract(grant["contract"]["path"])
        if captured != grant["contract"]:
            raise UsageError("The admitted workflow contract changed; preserve the current task and hand it off explicitly.", {})

    @contextmanager
    def prepared_step(self, step_id, *, gate_reports=()):
        from .progression_service import capture_contract
        state = _load(self.state_path)
        self.require_current(self.state_path, state, self.task)
        grant = current_grant(state, self.task)
        assert grant is not None
        captured, contract = capture_contract(grant["contract"]["path"])
        if captured != grant["contract"]:
            raise UsageError("Restore the admitted contract before selecting its prepared step.", {})
        step = next((row for row in contract["steps"] if row["id"] == step_id), None)
        if step is None or self._prepared is not None:
            raise UsageError("Select one admitted dispatch step at a time; do not substitute another operation.", {})
        self._prepared = step
        self.gate_reports = tuple(gate_reports)
        try:
            yield
        finally:
            self._prepared = None
            self.gate_reports = ()

    def capture_inputs(self, args):
        from .cli import build_parser
        from .progression_service import _verify_inputs
        if self._prepared is None:
            raise UsageError("A service apply must execute one immutable admitted step.", {})
        expected = {key: value for key, value in vars(build_parser().parse_args(self._prepared["argv"])).items()
                    if key not in {"state", "dispatch_id"}}
        actual = {key: value for key, value in vars(args).items() if key not in {"state", "dispatch_id"}}
        if actual != expected:
            raise UsageError("Service arguments differ from the admitted step; preserve its original intent.", {})
        return _verify_inputs(self._prepared)

    def authorized_client(self, client):
        """Called inside the CLI's primary transaction; clone only its transport."""
        from .herdr import HerdrClient
        if self._prepared is None or not isinstance(client, HerdrClient) or client.context.mode != "native":
            raise UsageError("Use the admitted prepared step and native Herdr client for service effects.", {})
        state = _load(self.state_path)
        self.require_current(self.state_path, state, self.task)
        grant = current_grant(state, self.task)
        assert grant is not None
        expected = deepcopy(grant["binding"])
        original = client._runner
        def guarded(argv):
            self.lease.require_current()
            with supervision.effect_boundary(self.state_path) as current:
                if _binding(current) != expected or _unresumed_hold(current):
                    raise UsageError("A current operator hold or changed foreman binding prevents worker transport. Preserve the pending intent and use the current owner to resume or reconcile it.", {})
                who = current["binding"]["identity"]
                if not os.environ.get("HERDR_ENV") or os.environ.get("HERDR_ENV") != who.get("herdr_env"):
                    raise UsageError("Restore the actual connected native foreman environment before worker transport; saved records cannot supply it.", {})
                return original(argv)
        return HerdrClient(context=client.context, runner=guarded, trace=client._trace)


def command_tasks(args, state_path, state):
    """Resolve task scope from current owner identities, including event batches."""
    tasks = set()
    task = getattr(args, "task", None)
    if task:
        tasks.add(task)
    record = {}
    path = getattr(args, "record", None)
    if path:
        try:
            record = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise UsageError("Restore the readable command record before checking task authority.", {}) from None
        if not isinstance(record, dict):
            raise UsageError("Supply an object command record before checking task authority.", {})
        if isinstance(record.get("task"), str):
            tasks.add(record["task"])
    identifier = getattr(args, "enrollment", None) or getattr(args, "dispatch", None) or record.get("dispatch")
    if args.command == "supervision-resolve":
        identifier = record.get("id")
    if identifier is not None and not isinstance(identifier, str):
        raise UsageError("Use the recorded enrollment or dispatch identity before checking task authority.", {})
    if identifier or args.command == "supervision-ack":
        supervised = supervision.load(state_path)
        members = {row["id"]: row["assignment"]["task"] for row in supervised["members"]}
        if identifier in members:
            tasks.add(members[identifier])
        dispatch = next((row for row in state["recovery"]["dispatches"] if row["id"] == identifier), None)
        if dispatch:
            tasks.add(dispatch["task"])
        if args.command == "supervision-ack":
            events = {row["id"]: row["member"] for row in supervised["events"]}
            outcomes = record.get("outcomes", [])
            if not isinstance(outcomes, list):
                raise UsageError("Supply the recorded supervision event outcomes before checking task authority.", {})
            for outcome in outcomes:
                if isinstance(outcome, dict) and isinstance(outcome.get("event"), str) and events.get(outcome["event"]) in members:
                    tasks.add(members[events[outcome["event"]]])
    return tasks


def require_command(state_path, args, capability=None, client=None, client_factory=None):
    """Fence primary transactions and independently locked supervision judgments."""
    if capability is None and getattr(args, "dry_run", False):
        return
    if capability is None and args.command not in TASK_MUTATIONS:
        return
    if not Path(state_path).exists():
        if capability is not None:
            raise UsageError("Restore the admitted state before service work.", {})
        return
    if capability is None:
        # Legacy stores cannot own grants. Leave their migration to the
        # selected existing owner; a read-only fence must not demand a second
        # migration command or rewrite history before that owner runs.
        try:
            raw = json.loads(Path(state_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise StateError("Restore readable owner state before continuing; writing an empty ledger would destroy its contents.", {}) from None
        if isinstance(raw, dict):
            root_version = raw.get("schema_version", 0)
            store = raw.get("recovery", {})
            if isinstance(store, dict):
                version = store.get("schema_version", 0)
                if (type(root_version) is int and 0 <= root_version <= STATE_SCHEMA_VERSION
                        and type(version) is int and 0 <= version < 19):
                    tasks = store.get("tasks", {})
                    if isinstance(tasks, dict) and any(isinstance(row, dict) and "authority" in row for row in tasks.values()):
                        raise UsageError("Older recovery contains unowned task authority; preserve it for its current owner.", {})
                    return
    state = _load(state_path)
    active = {task for task, row in state["recovery"]["tasks"].items()
              if row.get("authority", {}).get("mode") == "service"}
    if not active and capability is None:
        return
    tasks = command_tasks(args, state_path, state)
    if capability is not None:
        if not isinstance(capability, ServiceCapability):
            raise UsageError("Use an owner-minted in-process service capability; command input cannot grant authority.", {})
        if args.command not in SERVICE_COMMANDS or tasks != {capability.task}:
            raise UsageError("The progression capability does not authorize this command or task set.", {})
        capability.require_current(state_path, state, capability.task)
    elif tasks.intersection(active) and args.command in JUDGMENT_COMMANDS:
        # Judgment remains with the real foreman. This does not transfer the
        # dispatch lease; the service observes the recorded assessment next tick.
        if client is None and client_factory is not None:
            client = client_factory()
        if client is None:
            raise UsageError("Use the verified bound foreman to assess an exception on a service-owned task.", {})
        verify_foreman(state_path, client)
    elif tasks.intersection(active) or not tasks and active:
        raise UsageError("This task belongs to a progression service. Use its current authority or explicitly return a settled task; legacy dispatch cannot run alongside it.",
                         {"tasks": sorted(tasks), "service_owned_count": len(active)})


@contextmanager
def service_session(state_path, task, generation, service_id, plugin_root):
    """Claim an existing grant, with no new admission and no native impersonation."""
    state = _load(state_path)
    grant = current_grant(state, task)
    if grant is None or grant["mode"] != "service":
        raise UsageError("Have the verified bound foreman explicitly admit this task before starting its progression service.", {})
    with process_lease(grant["lease_path"]) as lease:
        capability = ServiceCapability(state_path=state_path, task=task, generation=generation,
                                       service_id=service_id, lease=lease, plugin_root=plugin_root)
        with state_lock(state_path):
            capability.require_current(state_path, _load(state_path), task)
        yield capability


def reconcile_intent(state_path, data, at, client):
    """Clear only a complete owner-proved no-send set, never infer an effect."""
    from .progression_service import capture_contract, intent_id, prepare_contract
    if not isinstance(data, dict) or set(data) != {"task", "expected_generation", "intent", "authorization"}:
        raise UsageError("Supply task, current generation, pending intent and explicit reconciliation authorization.", {})
    recovery.text(data["task"], "task")
    recovery.text(data["intent"], "pending intent")
    if len(json.dumps(data).encode("utf-8")) > GRANT_BYTES:
        raise UsageError("Keep intent reconciliation within the owner record budget; reference the task's GitHub issue for narrative.", {})
    recovery.authorization(data["authorization"])
    supervision.timestamp(at)
    state = _load(state_path)
    row = recovery.task_record(state["recovery"], data["task"])
    grant = current_grant(state, data["task"])
    if (grant is None or grant["mode"] != "service" or type(data["expected_generation"]) is not int
            or data["expected_generation"] != grant["generation"]):
        raise UsageError("Read the current service grant and reconcile its actual generation; do not replace task authority.", {})
    supervised = verify_foreman(state_path, client)
    progress = row.get("progression")
    if not progress or progress["pending"] is None:
        replay = any(event["kind"] == "progression_intent_reconciled" and event["task"] == data["task"]
                     and event["details"] == data for event in state["recovery"]["events"])
        if replay:
            return {"task": data["task"], "intent": data["intent"], "outcome": "not_sent", "replayed": True,
                    "authorizes_dispatch": False}
        raise UsageError("No matching pending intent exists; preserve the current cursor and inspect the current authority record.", {})
    captured, document = capture_contract(grant["contract"]["path"])
    if captured != grant["contract"]:
        raise UsageError("Restore the admitted contract before reconciling its expected dispatch set.", {})
    steps = prepare_contract(document, data["task"])
    if progress["cursor"] >= len(steps):
        raise UsageError("Restore the pending cursor's admitted step before intent reconciliation.", {})
    step = steps[progress["cursor"]]
    identifier = intent_id(data["task"], grant["generation"], step["id"])
    if (progress["pending"] != {"schema_version": 1, "step": step["id"], "intent": identifier}
            or data["intent"] != identifier):
        raise UsageError("Reconcile only the current pending intent; a different step supplies no no-send proof.", {})
    expected = {identifier + ":" + role for role in step["roles"]}
    if any(any(item["id"].startswith(base + ":transport-retry-") for base in expected)
           for item in state["recovery"]["dispatches"]):
        raise UsageError("This intent has associated transport retries. Preserve their actual owner identities and reconcile their effects; the original no-send rows cannot clear a later attempt.", {})
    dispatches = {item["id"]: item for item in state["recovery"]["dispatches"] if item["id"] in expected}
    if (set(dispatches) != expected or any(item["task"] != data["task"] or item["status"] != "not_sent"
                                          for item in dispatches.values())):
        raise UsageError("Every expected dispatch must be owner-proved not_sent; preserve missing, uncertain or partially applied effects for native reconciliation.", {})
    _settled(state, supervised, data["task"])
    def commit(current):
        if _binding(current) != _binding(supervised):
            raise UsageError("Verify the current bound foreman before reconciling this intent.", {})
        _settled(state, current, data["task"])
        with process_lease(grant["lease_path"]):
            progress["pending"] = None
            recovery._event(state["recovery"], at, "progression_intent_reconciled", data["task"], deepcopy(data))
            save_state(state_path, state)
        return {"task": data["task"], "intent": identifier, "outcome": "not_sent", "replayed": False,
                "authorizes_dispatch": False}
    return supervision.transaction(state_path, commit)


def register_commands(sub, common):
    for name in ("progression-admit", "progression-return", "progression-reconcile"):
        parser = sub.add_parser(name, parents=[common], help="Explicit task authority handoff through the verified bound foreman.")
        parser.add_argument("--record", required=True, metavar="FILE")
        parser.add_argument("--now", metavar="ISO")


def run_command(args, state_path, at, client):
    try:
        data = json.loads(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UsageError("Restore the complete authority handoff JSON record before retrying.", {}) from None
    if args.command == "progression-reconcile":
        return reconcile_intent(state_path, data, at, client), None
    return handoff(state_path, data, at, client, Path(__file__).resolve().parents[3],
                   returning=args.command == "progression-return"), None
