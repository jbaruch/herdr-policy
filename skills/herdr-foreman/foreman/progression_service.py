"""Run admitted native progression without model relays.

The schema-1 adapter advances prepared implementation/verification assignments.
It observes canonical report delivery and optional foreman assessments. It
cannot accept work, dispatch release, change a profile, waive a gate or resolve
an uncertain effect. Schema-2 tasks select WorkflowService at the CLI boundary;
their dedicated adapters own supported outcome/release transitions.

The current cursor and single pending intent live on the existing task record.
No poll writes history, copies reports or mirrors GitHub. Existing dispatch and
supervision owners retain all delivery/evidence authority.
"""

from contextlib import nullcontext, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

from . import config, load_set, members, progression_owner as authority, recovery, report_delivery, report_gates, supervision
from .assign import normalize_assignments
from .errors import ForemanError, UsageError
from .state import save_state, state_lock


CONTRACT_BYTES = 32_768
CAPTURE_BYTES = 2_097_152
MAX_STEPS = 16
MAX_INPUTS = 32
MIN_INTERVAL, MAX_INTERVAL = 1, 60
ALLOWED_ROLES = frozenset({"developer", "reviewer", "tester", "consultation"})


def capture_contract(path):
    """Return one bounded contract snapshot and its exact byte receipt."""
    try:
        with Path(path).open("rb") as stream:
            body = stream.read(CONTRACT_BYTES + 1)
        if len(body) > CONTRACT_BYTES:
            raise UsageError("Keep the active progression contract within its byte budget; reference current inputs instead of copying history.", {})
        return {"path": str(path), "sha256": hashlib.sha256(body).hexdigest()}, json.loads(body)
    except (OSError, ValueError):
        raise UsageError("Restore the admitted bounded workflow JSON before starting progression.", {}) from None


def read_contract(path):
    return capture_contract(path)[1]


def validate_progress(value):
    if isinstance(value, dict) and type(value.get("schema_version")) is int and value["schema_version"] == 2:
        from .workflow_contract import validate_progress as validate_workflow
        return validate_workflow(value)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "generation", "cursor", "pending"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["generation"]) is not int or value["generation"] < 1
            or type(value["cursor"]) is not int or not 0 <= value["cursor"] <= MAX_STEPS):
        raise UsageError("Unsupported service cursor; update the owner and preserve its pending intent.", {})
    pending = value["pending"]
    if pending is not None and (not isinstance(pending, dict) or set(pending) != {"schema_version", "step", "intent"}
            or type(pending["schema_version"]) is not int or pending["schema_version"] != 1
            or not isinstance(pending["step"], str) or authority.IDENTIFIER.fullmatch(pending["step"]) is None
            or not isinstance(pending["intent"], str) or authority.IDENTIFIER.fullmatch(pending["intent"]) is None):
        raise UsageError("Restore the current service intent without clearing or replacing uncertain work.", {})


def intent_id(task, generation, step):
    digest = hashlib.sha256(json.dumps([task, generation, step], separators=(",", ":")).encode()).hexdigest()
    return "progression-" + digest


def prepare_contract(value, task):
    from .cli import build_parser
    if (not isinstance(value, dict) or set(value) != {"schema_version", "task", "steps"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["task"] != task
            or not isinstance(value["steps"], list) or not 0 < len(value["steps"]) <= MAX_STEPS):
        raise UsageError("Supply a bounded schema-1 dispatch chain for the admitted task.", {})
    result, seen = [], set()
    for row in value["steps"]:
        if (not isinstance(row, dict) or set(row) != {"schema_version", "id", "argv", "after", "gate", "inputs"}
                or type(row["schema_version"]) is not int or row["schema_version"] != 1
                or not isinstance(row["id"], str) or authority.IDENTIFIER.fullmatch(row["id"]) is None or row["id"] in seen
                or not isinstance(row["argv"], list) or not 1 <= len(row["argv"]) <= 96
                or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in row["argv"])
                or row["argv"][0] != "apply" or any(arg.split("=", 1)[0] in {"--state", "--herdr-bin", "--dispatch-id", "--dry-run"} for arg in row["argv"])
                or not isinstance(row["after"], list) or any(not isinstance(key, str) or key not in seen for key in row["after"])
                or len(row["after"]) != len(set(row["after"])) or row["gate"] not in ("delivered", "assessed")
                or not isinstance(row["inputs"], list) or not 0 < len(row["inputs"]) <= MAX_INPUTS):
            raise UsageError("Restore unique prepared apply steps, earlier dependencies, explicit gates and input receipts; this adapter cannot execute arbitrary commands.", {})
        for captured in row["inputs"]:
            recovery.validate_receipt(captured)
        try:
            with redirect_stderr(io.StringIO()):
                args = build_parser().parse_args(row["argv"])
        except SystemExit:
            raise UsageError("Correct the prepared apply arguments in the admitted contract before service work.", {}) from None
        if args.task != task or not getattr(args, "config", None):
            raise UsageError("Each prepared apply must name its admitted task and explicit config input.", {})
        by_path = {item["path"]: item for item in row["inputs"]}
        if len(by_path) != len(row["inputs"]):
            raise UsageError("List each frozen dispatch input once in the admitted contract.", {})
        required = {args.config, args.assignments, args.common}
        for pair in args.briefs:
            if "=" not in pair:
                raise UsageError("Use role=absolute-path brief arguments in the prepared contract.", {})
            required.add(pair.split("=", 1)[1])
        if args.work:
            required.add(args.work)
        if not required.issubset(by_path):
            raise UsageError("Capture every config, plan, common, role brief and correction-work input before admitting progression.", {})
        captured_inputs = _verify_inputs(row)
        try:
            plan = json.loads(captured_inputs[str(Path(args.assignments).resolve())])
            config.parse_config(json.loads(captured_inputs[str(Path(args.config).resolve())]), source=args.config)
        except (OSError, ValueError):
            raise UsageError("Restore valid captured assignment-plan and config JSON before progression.", {}) from None
        roles = set(normalize_assignments(plan))
        if not roles or not roles.issubset(ALLOWED_ROLES):
            raise UsageError("This progression adapter supports implementation and independent verification only; release and specialist/profile transitions need their verified adapters.", {})
        seen.add(row["id"])
        result.append({**row, "roles": roles})
    return result


def _verify_inputs(step):
    result, total = {}, 0
    for captured in step["inputs"]:
        try:
            with Path(captured["path"]).open("rb") as stream:
                body = stream.read(CAPTURE_BYTES - total + 1)
            total += len(body)
            if total > CAPTURE_BYTES:
                raise UsageError("Keep the active dispatch inputs within the service byte budget; do not attach local history.", {})
            if not body.decode("utf-8").strip():
                raise UsageError("Restore nonempty captured dispatch inputs before service work.", {})
        except (OSError, UnicodeError):
            raise UsageError("Restore readable UTF-8 captured dispatch inputs before service work.", {}) from None
        if hashlib.sha256(body).hexdigest() != captured["sha256"]:
            raise UsageError("A prepared dispatch input changed after admission; stop and obtain an explicit new handoff.", {})
        result[str(Path(captured["path"]).resolve())] = body
    return result


class ProgressionService:
    """One task's portable loop; injected clocks/probes are fixture seams only."""

    def __init__(self, capability, client, *, check=None, invoke=None):
        from .cli import main
        if not isinstance(capability, authority.ServiceCapability):
            raise UsageError("Start progression through the owner's admitted service session.", {})
        self.capability, self.client = capability, client
        self.check = check if check is not None else self._check_native
        self.invoke = invoke if invoke is not None else main
        state = authority._load(capability.state_path)
        capability.require_current(capability.state_path, state, capability.task)
        grant = authority.current_grant(state, capability.task)
        assert grant is not None
        captured, document = capture_contract(grant["contract"]["path"])
        if captured != grant["contract"]:
            raise UsageError("Restore the admitted contract before preparing its dispatch chain.", {})
        self.steps = prepare_contract(document, capability.task)

    def _check_native(self, enrollment):
        binary = self.client.context.executable
        environment = {**os.environ, "FOREMAN_HERDR_BIN": binary, "HERDR_BIN": binary}
        def run(argv, **kwargs):
            return subprocess.run(argv, env=environment, **kwargs)
        return members.check(self.capability.state_path, enrollment, run=run)

    def _transport(self):
        if getattr(getattr(self.client, "context", None), "mode", None) != "native":
            raise UsageError("The initial progression adapter needs the existing native connection; remote service delivery verification is not enabled.", {})
        binding = supervision.load(self.capability.state_path)["binding"]
        if binding is None or binding["schema_version"] != 1:
            raise UsageError("Use the verified native owner for this progression adapter.", {})
        who = binding["identity"]
        if not os.environ.get("HERDR_ENV") or os.environ.get("HERDR_ENV") != who.get("herdr_env"):
            raise UsageError("Launch from the actual connected native owner environment; never manufacture HERDR_ENV from a saved grant.", {})

    def _view(self, state, *, status, wake=False, reason=None, refusal=None):
        progress = state["recovery"]["tasks"][self.capability.task].get("progression", {"cursor": 0, "pending": None})
        return load_set._bounded({"schema_version": 1, "wake_agent": wake, "data": {
            "task": self.capability.task, "generation": self.capability.generation,
            "status": status, "cursor": progress["cursor"], "steps": len(self.steps),
            "pending_intent": progress["pending"]["intent"] if progress["pending"] else None,
            "reason": reason, "refusal": refusal, "authorizes_acceptance": False, "authorizes_release": False}})

    @staticmethod
    def _refusal(text):
        try:
            value = json.loads(text)
        except ValueError:
            value = {}
        message = value.get("message") if isinstance(value, dict) else None
        code = value.get("error") if isinstance(value, dict) else None
        message = message if isinstance(message, str) else "Inspect the recorded dispatch and current inputs before attempting this intent again."
        raw = message.encode("utf-8")
        return {"schema_version": 1, "code": code[:64] if isinstance(code, str) else "owner_refusal",
                "message": raw[:2048].decode("utf-8", errors="ignore"), "truncated": len(raw) > 2048}

    @staticmethod
    def _member_stamp(member):
        return supervision.digest({"assignment": supervision.expected_assignment(member),
                                   "active": member["active"], "resolution": member["resolution"]})

    @staticmethod
    def closed_dependency(state_path, state, member, *, native_source_required=True):
        """Verify canonical accepted evidence after the scoped pane has closed."""
        def refuse(stage, message):
            return ProgressionService._refusal(json.dumps({"error": "closed_dependency_" + stage, "message": message}))
        expected = supervision.expected_assignment(member)
        resolution = member["resolution"]
        evidence = resolution["evidence"] if resolution else []
        if len(evidence) != 1:
            return refuse("ledger", "Restore this enrollment's single owner-bound assessment-ledger receipt before progression; preserve its unresolved obligation.")
        captured = evidence[0]
        dispatch = next((row for row in state["recovery"]["dispatches"] if row["id"] == member["id"]), None)
        if dispatch is None or any(dispatch[key] != expected[key] for key in ("task", "agent")):
            return refuse("owner", "Reconcile the closed enrollment with its original task dispatch owner; another worker's report supplies no authority.")
        identity = report_delivery.native_identity({"agent_session": expected["native_session"]})
        if identity is None or not Path(expected["report"]).is_file():
            return refuse("report", "Restore the original enrolled native identity and report file, or record their unavailability through the bound foreman.")
        stage = "ledger"
        try:
            with Path(captured["path"]).open("rb") as stream:
                body = stream.read(CAPTURE_BYTES + 1)
            if (len(body) > CAPTURE_BYTES or len(body) < captured["size"]
                    or hashlib.sha256(body[:captured["size"]]).hexdigest() != captured["sha256"]):
                return refuse("ledger", "Restore the original captured assessment-ledger prefix; changed or unavailable bytes require owner recovery, never acceptance.")
            with tempfile.NamedTemporaryFile(suffix=".md") as ledger:
                ledger.write(body)
                ledger.flush()
                event = members.assessed_event(ledger.name, expected, state_path)
            if (event["decision"] != "accepted" or resolution["outcome"] not in
                    {"accepted", "Task ledger event {}: accepted".format(event["id"])}):
                return refuse("assessment", "Obtain the current bound foreman's accepted assessment for this enrollment; a different resolution or later invalidation remains blocking.")
            stage = "contract"
            members._require_contract(state_path, member["id"], expected["report"])
            stage = "classifier_gate"
            report_gates.require_clear(state_path, expected["report"], True)
            if not native_source_required:
                return None
            stage = "native_source"
            path = report_delivery.source_path(identity)
            source = report_delivery.read_native_source(path) if path is not None else None
            if source is None or not report_delivery.bare_final(
                    report_delivery.source_final(source[1], identity["agent"], identity["value"], path=path), expected["report"]):
                return refuse(stage, "Restore this enrollment's exact native final-source/report proof; missing or contradictory delivery evidence keeps progression held.")
            return None
        except ForemanError as exc:
            return refuse(stage, exc.to_dict()["message"])
        except (OSError, UnicodeError, ValueError):
            return refuse(stage, "Restore readable, valid original {} evidence through its owner, then retry; preserve the closed enrollment meanwhile.".format(stage))

    def _closed_dependency(self, state, member):
        return self.closed_dependency(self.capability.state_path, state, member)

    def _dependencies(self, state, step):
        """Probe without holding the global task-state transaction lock."""
        cap = self.capability
        supervised = supervision.load(cap.state_path)
        stamps = {}
        for dependency in step["after"]:
            prior = next(item for item in self.steps if item["id"] == dependency)
            prefix = intent_id(cap.task, cap.generation, dependency)
            for role in sorted(prior["roles"]):
                identifier = prefix + ":" + role
                member = next((item for item in supervised["members"] if item["id"] == identifier), None)
                if member is None or member["assignment"]["task"] != cap.task:
                    return self._view(state, status="exception", wake=True, reason="dependency_enrollment_unproved"), stamps
                if step["gate"] == "assessed":
                    resolution = member["resolution"]
                    if member["active"] or resolution is None:
                        return self._view(state, status="waiting", reason="assessment_required"), stamps
                if not member["active"]:
                    refusal = self._closed_dependency(state, member)
                    if refusal is not None:
                        return self._view(state, status="exception", wake=True, reason="closed_dependency_evidence_unproved", refusal=refusal), stamps
                    stamps[identifier] = self._member_stamp(member)
                    continue
                expected = supervision.expected_assignment(member)
                info = self.client.agent_get(expected["agent"])
                native = report_delivery.native_identity(info)
                enrolled = expected["native_session"]
                if isinstance(enrolled, dict):
                    enrolled = {key: value for key, value in enrolled.items() if key != "pane_id"}
                if native is None or native != enrolled or info.get("pane_id") != expected["pane_id"]:
                    return self._view(state, status="exception", wake=True, reason="dependency_native_identity_changed"), stamps
                checked, code = self.check(identifier)
                if code == 1:
                    return self._view(state, status="waiting", reason="report_not_delivered"), stamps
                if code != 0:
                    return self._view(state, status="exception", wake=True, reason="delivery_check_refused"), stamps
                try:
                    wait = json.loads(checked["wait"])
                except (KeyError, TypeError, ValueError):
                    return self._view(state, status="exception", wake=True, reason="delivery_check_invalid"), stamps
                after = self.client.agent_get(expected["agent"])
                if (not isinstance(wait, dict) or wait.get("found") is not True or wait.get("report_path") != expected["report"]
                        or report_delivery.native_identity(after) != native or after.get("pane_id") != expected["pane_id"]):
                    return self._view(state, status="exception", wake=True, reason="delivery_check_invalid"), stamps
                stamps[identifier] = self._member_stamp(member)
        return None, stamps

    def tick(self):
        cap, path = self.capability, self.capability.state_path
        self._transport()
        with state_lock(path):
            state = authority._load(path)
            cap.require_current(path, state, cap.task)
            row = state["recovery"]["tasks"][cap.task]
            progress = row.get("progression", {"schema_version": 1, "generation": cap.generation, "cursor": 0, "pending": None})
            validate_progress(progress)
            if progress["generation"] != cap.generation or progress["cursor"] > len(self.steps):
                raise UsageError("Reconcile the service cursor with its admitted generation and dispatch chain.", {})
            if progress["cursor"] == len(self.steps):
                if progress["pending"] is not None:
                    raise UsageError("A complete dispatch cursor cannot erase a pending effect; reconcile that intent through its owner.", {})
                return self._view(state, status="dispatch_chain_complete")
            step = self.steps[progress["cursor"]]
            expected_cursor = progress["cursor"]
        waiting, stamps = self._dependencies(state, step)
        if waiting is not None:
            return waiting
        with state_lock(path):
            state = authority._load(path)
            cap.require_current(path, state, cap.task)
            row = state["recovery"]["tasks"][cap.task]
            progress = row.get("progression", {"schema_version": 1, "generation": cap.generation, "cursor": 0, "pending": None})
            if progress["cursor"] != expected_cursor or progress["generation"] != cap.generation:
                raise UsageError("The pending service decision changed during observation; recover its original cursor.", {})
            _verify_inputs(step)
            supervised = supervision.load(path)
            current_members = {item["id"]: item for item in supervised["members"]}
            if any(key not in current_members or self._member_stamp(current_members[key]) != stamp for key, stamp in stamps.items()):
                return self._view(state, status="waiting", reason="dependency_changed_during_observation")
            gate_reports = [supervision.expected_assignment(current_members[key])["report"]
                            for key in stamps if not current_members[key]["active"]]
            identifier = intent_id(cap.task, cap.generation, step["id"])
            expected = {identifier + ":" + role for role in step["roles"]}
            if progress["pending"] is not None:
                if progress["pending"] != {"schema_version": 1, "step": step["id"], "intent": identifier}:
                    raise UsageError("Restore the original pending step identity; never retarget a service intent.", {})
                applied = {item["id"] for item in state["recovery"]["dispatches"]
                           if item["id"] in expected and item["task"] == cap.task and item["status"] == "applied"}
                if applied != expected:
                    return self._view(state, status="exception", wake=True, reason="pending_effect_requires_reconciliation")
            else:
                progress = {**progress, "pending": {"schema_version": 1, "step": step["id"], "intent": identifier}}
                row["progression"] = progress
                save_state(path, state)
        # The CLI reacquires the same owner lock and fences this capability
        # inside its mutation transaction. Do not hold an outer lock or bypass
        # the owner with direct transport calls.
        out, err = io.StringIO(), io.StringIO()
        with cap.prepared_step(step["id"], gate_reports=gate_reports):
            code = self.invoke([*step["argv"], "--state", str(path), "--dispatch-id", identifier],
                               stdout=out, stderr=err, client=self.client, service_capability=cap)
        with state_lock(path):
            state = authority._load(path)
            progress = state["recovery"]["tasks"][cap.task]["progression"]
            if code != 0:
                return self._view(state, status="exception", wake=True, reason="dispatch_owner_refused", refusal=self._refusal(err.getvalue()))
            cap.require_current(path, state, cap.task)
            # Even an exit-zero adapter must prove the exact expected owner
            # dispatches. No output string or process exit grants progression.
            applied = {item["id"] for item in state["recovery"]["dispatches"]
                       if item["id"] in expected and item["task"] == cap.task and item["status"] == "applied"}
            if applied != expected:
                return self._view(state, status="exception", wake=True, reason="dispatch_readback_unproved")
            progress.update(cursor=progress["cursor"] + 1, pending=None)
            save_state(path, state)
            return self._view(state, status="advanced")


def run_command(args, state_path, client, *, sleeper):
    if not MIN_INTERVAL <= args.interval <= MAX_INTERVAL:
        raise UsageError("Select a progression interval within the service's supported bounds.", {})
    from .native_policy import executing_policy_root
    plugin_root = executing_policy_root()
    with authority.service_session(state_path, args.task, args.generation, args.service_id, plugin_root) as capability:
        state = authority._load(state_path)
        grant = authority.current_grant(state, args.task)
        assert grant is not None
        _captured, document = capture_contract(grant["contract"]["path"])
        workflow = isinstance(document, dict) and type(document.get("schema_version")) is int and document["schema_version"] in (2, 3)
        if workflow:
            from . import progression_runtime
            from .cli import now_iso
            from .workflow_service import WorkflowService
            service = WorkflowService(capability, client, sleeper=sleeper)
            lifetime = progression_runtime.keep_alive(capability, now_iso)
        else:
            service = ProgressionService(capability, client)
            lifetime = nullcontext(lambda: None)
        with lifetime as require_healthy:
            while True:
                require_healthy()
                result = service.tick()
                if args.once or result["wake_agent"] or result["data"]["status"] in ("dispatch_chain_complete", "complete"):
                    return result, None
                sleeper(args.interval)


def register_commands(sub, common):
    parser = sub.add_parser("progression-run", parents=[common], help="Run an explicitly admitted native task workflow or prepared chain independently of model turns.")
    parser.add_argument("--task", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5)
