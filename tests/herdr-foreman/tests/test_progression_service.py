"""Exercise the background chain through real CLI owners and fixture transport."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
from contextlib import contextmanager
import hashlib
import io
import json
import os
import threading
import unittest
from unittest.mock import patch

from tests import test_cli as fixtures, test_report_delivery as native_fixtures, test_report_gates as gate_fixtures
from tests.fakes import ScriptedReads, agent_json
from foreman import cli, progression_owner as owner, progression_service as service, recovery, report_gates, supervision
from foreman.errors import ForemanError, UsageError
from foreman.state import empty_state, load_state_checked, save_state, state_lock


AT = "2026-02-03T10:00:00+00:00"
ROOT = Path(__file__).resolve().parents[3]
AUTH = {"source": "private unit fixture", "quote": "Admit this prepared fixture task only."}
SESSION = "01234567-89ab-cdef-0123-456789abcdef"


class ProgressionServiceTest(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.ApplyCommandTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.path = self.fx.state
        self.client = self.fx._client({"grok": "idle", "claude": "idle", "codex": "idle"},
                                      sessions={name: SESSION for name in ("grok", "claude", "codex")})
        for name, pane in (("grok", "w4:p1"), ("claude", "w2:p1"), ("codex", "w3:p1")):
            self.fx.runner.responses["agent get " + name] = ScriptedReads([
                agent_json(name, "idle", pane, "previous-fixture-session"), agent_json(name, "idle", pane, SESSION)])
        self.fx.runner.set("pane get fixture-foreman", json.dumps({"result": {"pane": {
            "pane_id": "fixture-foreman", "agent_session": {"source": "herdr:codex", "agent": "codex",
            "kind": "id", "value": "fixture-foreman-session"}}}}))
        environment = patch.dict(os.environ, {"HERDR_ENV": "fixture-only", "HERDR_PANE_ID": "fixture-foreman"})
        environment.start()
        self.addCleanup(environment.stop)
        state = empty_state()
        recovery.register_task(state["recovery"], {"task": "one", "base_revision": "a" * 40,
                               "scope": "Fixture parser correction", "allowed_paths": ["src/*"], "authorization": AUTH}, AT)
        save_state(self.path, state)
        who = supervision.identity("fixture-foreman-session", str(Path.cwd()), "fixture-only", pane_id="fixture-foreman")
        supervision.bind(self.path, who, AT, root=self.fx.tmp / "bindings")
        self.contract = self.fx.tmp / "workflow.json"
        self.document = {"schema_version": 1, "task": "one", "steps": [
            self.step("implement", {"developer": "grok"}),
            self.step("verify", {"reviewer": "claude", "tester": "codex"}, after=["implement"])]}
        self.contract.write_text(json.dumps(self.document))
        with state_lock(self.path):
            owner.handoff(self.path, {"task": "one", "expected_generation": 0, "authorization": AUTH,
                          "service_id": "fixture-service", "lease_path": str(self.fx.tmp / "service.lease"),
                          "contract": str(self.contract)}, AT, self.client, ROOT)
        self.delivered = False
        self.probe_code = 0
        self.invocations = 0
        self.last_error = ""

    def step(self, identifier, assignments, after=None):
        plan = self.fx.tmp / (identifier + "-plan.json")
        plan.write_text(json.dumps(assignments))
        argv = ["apply", "--config", str(self.fx.config), "--assignments", str(plan),
                "--task", "one", "--common", str(self.fx.common),
                "--now", AT, "--composer-settle", "0"]
        paths = [self.fx.config, plan, self.fx.common]
        for role in assignments:
            report = self.fx.tmp / (identifier + "-" + role + "-report.md")
            self.fx.assign_report(self.fx.briefs[role], report)
            argv += ["--brief", role + "=" + str(self.fx.briefs[role]), "--report", role + "=" + str(report)]
            paths.append(self.fx.briefs[role])
        return {"schema_version": 1, "id": identifier, "argv": argv, "after": after or [], "gate": "delivered",
                "inputs": [recovery.receipt(str(path))[0] for path in paths]}

    def state(self):
        state, usable = load_state_checked(self.path, persist_migration=False)
        self.assertTrue(usable)
        return state

    def session(self):
        return owner.service_session(self.path, "one", 1, "fixture-service", ROOT)

    def invoke(self, *args, **kwargs):
        self.invocations += 1
        code = cli.main(*args, **kwargs)
        self.last_error = kwargs["stderr"].getvalue()
        return code

    def check(self, identifier):
        # Waiting for native completion must not monopolize other task owners.
        with state_lock(self.path):
            member = next(row for row in supervision.load(self.path)["members"] if row["id"] == identifier)
        wait = {"found": self.delivered, "report_path": member["assignment"]["report"]}
        return {"wait": json.dumps(wait)}, self.probe_code if self.delivered else 1

    def runner(self, capability, invoke=None):
        return service.ProgressionService(capability, self.client, check=self.check, invoke=invoke or self.invoke)

    def test_delivered_implementation_dispatches_verification_without_a_model_relay(self):
        with self.session() as capability:
            runner = self.runner(capability)
            first = runner.tick()
            self.assertEqual(first["data"]["status"], "advanced", self.last_error)
            self.assertEqual(len(self.state()["assignments"]), 1)
            before = self.path.read_bytes()
            for _ in range(2):
                self.assertEqual(runner.tick()["data"]["status"], "waiting")
            self.assertEqual(self.path.read_bytes(), before)
            self.delivered = True
            self.assertEqual(runner.tick()["data"]["status"], "advanced", self.last_error)
            self.assertEqual(len(self.state()["assignments"]), 3)
            final = runner.tick()
            self.assertEqual(final["data"]["status"], "dispatch_chain_complete")
            self.assertFalse(final["data"]["authorizes_acceptance"])
            self.assertFalse(final["data"]["authorizes_release"])
            self.assertEqual(self.invocations, 2)

    def change_supervision_authority(self, kind):
        if kind == "hold":
            supervision.hold(self.path, {"id": "boundary-hold", "kind": "waiting_for_user",
                "resume_condition": "Fixture operator explicitly resumes", "evidence": [str(self.fx.common)], "dispositions": []}, AT)
        else:
            who = supervision.identity("replacement-foreman-session", str(Path.cwd()), "fixture-only", pane_id="replacement-foreman")
            supervision.bind(self.path, who, AT, root=self.fx.tmp / "replacement-bindings")

    def refuse_changed_authority_at_transport(self, kind):
        original = supervision.effect_boundary
        interrupted = False
        @contextmanager
        def arriving(state_path):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                self.change_supervision_authority(kind)
            with original(state_path) as current:
                yield current
        with self.session() as capability, patch("foreman.supervision.effect_boundary", arriving):
            result = self.runner(capability).tick()
        self.assertTrue(interrupted)
        self.assertTrue(result["wake_agent"])
        self.assertEqual(result["data"]["reason"], "dispatch_owner_refused")
        self.assertIn("operator hold or changed foreman binding", result["data"]["refusal"]["message"])
        self.assertEqual(self.fx.runner.writes(), [])
        self.assertIsNotNone(self.state()["recovery"]["tasks"]["one"]["progression"]["pending"])
        if kind == "hold":
            self.assertIsNone(supervision.load(self.path)["holds"][0]["resumed_at"])
        else:
            self.assertEqual(supervision.load(self.path)["binding"]["identity"]["pane_id"], "replacement-foreman")

    def test_hold_arriving_after_initial_authorization_refuses_transport(self):
        self.refuse_changed_authority_at_transport("hold")

    def test_rebind_arriving_after_initial_authorization_refuses_transport(self):
        self.refuse_changed_authority_at_transport("bind")

    def test_transport_invocation_serializes_concurrent_hold_and_rebind(self):
        original = self.client._runner
        denied = []
        def transport(argv):
            for kind in ("hold", "bind"):
                def update(which=kind):
                    try:
                        self.change_supervision_authority(which)
                    except ForemanError:
                        denied.append(which)
                thread = threading.Thread(target=update)
                thread.start()
                thread.join(5)
                self.assertFalse(thread.is_alive(), "Supervision lock contention must refuse, not deadlock")
            return original(argv)
        self.client._runner = transport
        before = supervision.store_path(self.path).read_bytes()
        with self.session() as capability, capability.prepared_step("implement"), state_lock(self.path):
            client = capability.authorized_client(self.client)
            self.assertEqual(client.agent_get("grok")["pane_id"], "w4:p1")
        self.assertEqual(denied, ["hold", "bind"])
        self.assertEqual(supervision.store_path(self.path).read_bytes(), before)

    def test_native_checkpoint_uses_the_selected_executable_in_both_interfaces(self):
        def checkpoint(_path, _enrollment, *, run):
            child = run([sys.executable, "-c", 'import json,os; print(json.dumps([os.environ.get("HERDR_BIN"),os.environ.get("FOREMAN_HERDR_BIN")]))'],
                        capture_output=True, text=True, check=False)
            return {"wait": child.stdout}, child.returncode
        with self.session() as capability:
            runner = self.runner(capability)
            with patch("foreman.progression_service.members.check", side_effect=checkpoint), \
                    patch.dict(os.environ, {"HERDR_BIN": "wrong-binary", "FOREMAN_HERDR_BIN": "wrong-binary"}):
                result, code = runner._check_native("fixture-no-network")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(result["wait"]), [self.client.context.executable] * 2)

    def test_crash_after_applied_dispatch_replays_owner_receipt_without_resending(self):
        def crash(*args, **kwargs):
            self.assertEqual(self.invoke(*args, **kwargs), 0, self.last_error)
            raise RuntimeError("fixture crash after real owner commit")
        with self.session() as capability:
            with self.assertRaisesRegex(RuntimeError, "fixture crash"):
                self.runner(capability, crash).tick()
        self.assertIsNotNone(self.state()["recovery"]["tasks"]["one"]["progression"]["pending"])
        writes = list(self.fx.runner.writes())
        before = self.path.read_bytes()
        intent = self.state()["recovery"]["tasks"]["one"]["progression"]["pending"]["intent"]
        with state_lock(self.path), self.assertRaisesRegex(UsageError, "owner-proved not_sent"):
            owner.reconcile_intent(self.path, {"task": "one", "expected_generation": 1, "intent": intent,
                                              "authorization": AUTH}, AT, self.client)
        self.assertEqual(self.path.read_bytes(), before)
        with self.session() as capability:
            result = self.runner(capability).tick()
            self.assertEqual(result["data"]["status"], "advanced", self.last_error)
        self.assertEqual(self.fx.runner.writes(), writes)
        self.assertEqual(len(self.state()["assignments"]), 1)

    def test_uncertain_intent_survives_restart_without_another_send(self):
        def crash(*_args, **_kwargs):
            raise RuntimeError("fixture crash before owner response")
        with self.session() as capability:
            with self.assertRaises(RuntimeError):
                self.runner(capability, crash).tick()
        before = self.path.read_bytes()
        with self.session() as capability:
            result = self.runner(capability).tick()
        self.assertTrue(result["wake_agent"])
        self.assertEqual(result["data"]["reason"], "pending_effect_requires_reconciliation")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.invocations, 0)
        self.assertEqual(self.fx.runner.writes(), [])
        intent = self.state()["recovery"]["tasks"]["one"]["progression"]["pending"]["intent"]
        with state_lock(self.path), self.assertRaisesRegex(UsageError, "owner-proved not_sent"):
            owner.reconcile_intent(self.path, {"task": "one", "expected_generation": 1, "intent": intent,
                                              "authorization": AUTH}, AT, self.client)
        self.assertEqual(self.path.read_bytes(), before)

    def test_zero_exit_without_expected_owner_dispatch_does_not_advance(self):
        with self.session() as capability:
            result = self.runner(capability, lambda *_args, **_kwargs: 0).tick()
        self.assertTrue(result["wake_agent"])
        self.assertEqual(result["data"]["reason"], "dispatch_readback_unproved")
        self.assertEqual(result["data"]["cursor"], 0)
        self.assertIsNotNone(result["data"]["pending_intent"])

    def test_native_identity_change_cannot_trigger_followup(self):
        with self.session() as capability:
            runner = self.runner(capability)
            self.assertEqual(runner.tick()["data"]["status"], "advanced", self.last_error)
            self.delivered = True
            self.fx.runner.set("agent get grok", agent_json("grok", "idle", "w4:p1", "another-native-session"))
            before = self.path.read_bytes()
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertEqual(result["data"]["reason"], "dependency_native_identity_changed")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.invocations, 1)

    def test_frozen_bytes_must_match_the_admitted_brief(self):
        original = cli.freeze_paths
        def changed(paths):
            self.fx.common.write_text("Unexpected replacement before freezing.\n")
            return original(paths)
        with self.session() as capability, patch("foreman.cli.freeze_paths", side_effect=changed):
            result = self.runner(capability).tick()
        self.assertTrue(result["wake_agent"])
        self.assertIn("Frozen dispatch bytes differ", self.last_error)
        self.assertEqual(self.fx.runner.writes(), [])
        self.assertEqual(self.state()["assignments"], [])

    def test_contract_refuses_release_arbitrary_commands_and_unbounded_configuration(self):
        for argv in (["start-foreman"], ["apply", "--state", "other.json"]):
            document = copy.deepcopy(self.document)
            document["steps"][0]["argv"] = argv
            with self.assertRaises(UsageError):
                service.prepare_contract(document, "one")
        oversized = self.fx.tmp / "oversized.json"
        oversized.write_bytes(b" " * (service.CONTRACT_BYTES + 1))
        with self.assertRaisesRegex(UsageError, "byte budget"):
            service.read_contract(oversized)

    def test_input_config_is_parsed_from_verified_bytes_without_a_second_file_read(self):
        original = cli.config_owner.parse_config
        def replace_after_capture(payload, source):
            self.fx.config.write_text('{"schema_version": 1, "agents": []}')
            return original(payload, source=source)
        with self.session() as capability:
            runner = self.runner(capability)
            with patch("foreman.cli.config_owner.parse_config", side_effect=replace_after_capture):
                result = runner.tick()
        self.assertEqual(result["data"]["status"], "advanced", self.last_error)
        self.assertEqual(self.state()["assignments"][0]["agent"], "grok")

    def test_contract_input_verification_enforces_the_total_capture_budget(self):
        document = copy.deepcopy(self.document)
        body = b"x" * service.CAPTURE_BYTES
        self.fx.common.write_bytes(body)
        for step in document["steps"]:
            for captured in step["inputs"]:
                if captured["path"] == str(self.fx.common):
                    captured["sha256"] = hashlib.sha256(body).hexdigest()
        with self.assertRaisesRegex(UsageError, "byte budget"):
            service.prepare_contract(document, "one")
        self.assertEqual(self.fx.runner.writes(), [])

    def test_contract_plan_is_parsed_from_the_verified_bytes(self):
        document = copy.deepcopy(self.document)
        document["steps"] = document["steps"][:1]
        original = service._verify_inputs
        def replace_after_capture(step):
            captured = original(step)
            plan = step["argv"][step["argv"].index("--assignments") + 1]
            Path(plan).write_text('{"release": "grok"}')
            return captured
        with patch("foreman.progression_service._verify_inputs", side_effect=replace_after_capture):
            prepared = service.prepare_contract(document, "one")
        self.assertEqual(prepared[0]["roles"], {"developer"})
        self.assertEqual(self.fx.runner.writes(), [])

    def test_malformed_admitted_config_is_a_structured_refusal_before_any_intent(self):
        with state_lock(self.path):
            owner.handoff(self.path, {"task": "one", "expected_generation": 1, "authorization": AUTH},
                          AT, self.client, ROOT, returning=True)
        self.fx.config.write_text("{malformed config")
        for step in self.document["steps"]:
            for captured in step["inputs"]:
                if captured["path"] == str(self.fx.config):
                    captured["sha256"] = hashlib.sha256(self.fx.config.read_bytes()).hexdigest()
        self.contract.write_text(json.dumps(self.document))
        with state_lock(self.path):
            owner.handoff(self.path, {"task": "one", "expected_generation": 2, "authorization": AUTH,
                          "service_id": "fixture-service", "lease_path": str(self.fx.tmp / "service.lease"),
                          "contract": str(self.contract)}, AT, self.client, ROOT)
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["progression-run", "--state", str(self.path), "--task", "one", "--generation", "3",
                         "--service-id", "fixture-service", "--once"], stdout=out, stderr=err, client=self.client)
        self.assertEqual(code, 1)
        self.assertIn("config JSON", json.loads(err.getvalue())["message"])
        self.assertNotIn("progression", self.state()["recovery"]["tasks"]["one"])
        self.assertEqual(self.fx.runner.writes(), [])

    def test_all_judgment_commands_fence_service_owned_members_without_taking_the_main_lock(self):
        with self.session() as capability:
            self.assertEqual(self.runner(capability).tick()["data"]["status"], "advanced", self.last_error)
        member = supervision.load(self.path)["members"][0]
        event = supervision.transaction(self.path, lambda data: supervision.append_event(data, AT, member["id"], "fixture", {}))
        records = {"supervision-resolve": {"id": member["id"], "outcome": "accepted", "evidence": [str(self.fx.common)]},
                   "supervision-ack": {"through": event["seq"], "outcomes": [
                       {"event": event["id"], "outcome": "handled", "evidence": [str(self.fx.common)]}]}}
        self.fx.runner.set("pane get wrong-foreman", json.dumps({"result": {"pane": {
            "pane_id": "wrong-foreman", "agent_session": {"source": "herdr:codex", "agent": "codex",
            "kind": "id", "value": "unbound-fixture-session"}}}}))
        for command in ("close-member", "supervision-ack", "supervision-resolve"):
            with self.subTest(command=command):
                if command == "close-member":
                    argv = [command, "--enrollment", member["id"], "--ledger", str(self.fx.common)]
                else:
                    record = self.fx.tmp / (command + ".json")
                    record.write_text(json.dumps(records[command]))
                    argv = [command, "--record", str(record)]
                argv += ["--state", str(self.path), "--now", AT]
                before = supervision.store_path(self.path).read_bytes()
                with patch.dict(os.environ, {"HERDR_PANE_ID": "wrong-foreman"}):
                    out, err = io.StringIO(), io.StringIO()
                    code = cli.main(argv, stdout=out, stderr=err, client=self.client)
                self.assertEqual(code, 1)
                self.assertEqual(supervision.store_path(self.path).read_bytes(), before)
                self.assertIn("foreman", err.getvalue())
                # Use the real authority fence, with only the downstream owner
                # replaced: this checks permission separately from ledger rules.
                with state_lock(self.path), patch.dict(cli.COMMANDS, {command: lambda *a, **k: ({"authorized": True}, None)}):
                    out, err = io.StringIO(), io.StringIO()
                    self.assertEqual(cli.main(argv, stdout=out, stderr=err, client=self.client), 0, err.getvalue())
                self.assertTrue(json.loads(out.getvalue())["authorized"])

    def test_accepted_closed_worker_uses_bound_ledger_and_native_source_without_a_live_pane(self):
        # This adapter may consume a normal close-member result after pane teardown.
        self.document["steps"][1]["gate"] = "assessed"
        self.contract.write_text(json.dumps(self.document))
        with state_lock(self.path):
            owner.handoff(self.path, {"task": "one", "expected_generation": 1, "authorization": AUTH},
                          AT, self.client, ROOT, returning=True)
            owner.handoff(self.path, {"task": "one", "expected_generation": 2, "authorization": AUTH,
                          "service_id": "fixture-service", "lease_path": str(self.fx.tmp / "service.lease"),
                          "contract": str(self.contract)}, AT, self.client, ROOT)
        with owner.service_session(self.path, "one", 3, "fixture-service", ROOT) as capability:
            runner = self.runner(capability)
            self.assertEqual(runner.tick()["data"]["status"], "advanced", self.last_error)
            member = supervision.load(self.path)["members"][0]
            assignment = supervision.expected_assignment(member)
            report = Path(assignment["report"])
            report.write_text("Completed fixture implementation.\n")
            ledger = self.fx.tmp / "accepted-ledger.md"
            fields = {"schema_version": 1, "id": "accepted-one", "at": AT, "subject": "assignment",
                      "dispatch_id": member["id"], "worker": assignment["agent"], "role": "developer",
                      "report": str(report), "observed": "Delivered report", "decision": "accepted",
                      "head_revision": "a" * 40, "evidence": str(report), "assessment": "Read in full"}
            body = ("---\nschema_version: 1\ntask: one\nbase_revision: " + "a" * 40 + "\ndispatch_state: "
                    + str(self.path) + "\n---\n\n## accepted-one\n\n"
                    + "".join("- {}: {}\n".format(k, v) for k, v in fields.items()))
            ledger.write_text(body)
            supervision.resolve(self.path, {"id": member["id"], "outcome": "Task ledger event accepted-one: accepted",
                                           "evidence": [str(ledger)]}, AT)
            source = self.fx.tmp / "closed-native.jsonl"
            native_body = native_fixtures.encode(native_fixtures.grok_rows("REPORT: " + str(report))).replace(native_fixtures.SESSION, SESSION)
            source.write_text(native_body)
            original_get = self.client.agent_get
            def only_current_workers(name):
                if name == "grok":
                    raise AssertionError("Closed dependency must not need a live worker")
                return original_get(name)
            with patch("foreman.report_delivery.source_path", return_value=source), patch.object(self.client, "agent_get", side_effect=only_current_workers):
                for invalid in ("ledger", "native"):
                    with self.subTest(invalid=invalid):
                        ledger.write_text(body.replace("Read in full", "Changed bytes") if invalid == "ledger" else body)
                        source.write_text(native_body.replace(SESSION, "another-session") if invalid == "native" else native_body)
                        result = runner.tick()
                        self.assertEqual(result["data"]["reason"], "closed_dependency_evidence_unproved")
                        self.assertTrue(result["data"]["refusal"]["message"])
                        self.assertIn("Restore", result["data"]["refusal"]["message"])
                        self.assertEqual(self.invocations, 1)
                ledger.write_text(body)
                source.write_text(native_body)
                self.assertEqual(runner.tick()["data"]["status"], "advanced", self.last_error)
                report_gates.record(self.path, {"schema_version": 2, "agent": "default", "labels": [
                    gate_fixtures.label(report, gate_fixtures.HIGH)], "unannotated": []}, AT)
                refusal = runner._closed_dependency(self.state(), supervision.load(self.path)["members"][0])
                self.assertEqual(refusal["code"], "closed_dependency_classifier_gate")
                self.assertIn("open block gate", refusal["message"])
                writes = list(self.fx.runner.writes())
                step = self.document["steps"][1]
                with capability.prepared_step("verify", gate_reports=[str(report)]):
                    out, err = io.StringIO(), io.StringIO()
                    code = cli.main([*step["argv"], "--state", str(self.path), "--dispatch-id", service.intent_id("one", 3, "verify")],
                                    stdout=out, stderr=err, client=self.client, service_capability=capability)
                self.assertEqual(code, 1)
                self.assertIn("open block gate", err.getvalue())
                self.assertEqual(self.fx.runner.writes(), writes)

    def test_proved_no_send_intent_can_be_reconciled_and_returned_without_advancing(self):
        original, failed = cli.save_state, False
        def fail_after_reservation(path, state):
            nonlocal failed
            original(path, state)
            if not failed and any(row["status"] == "reserved" for row in state["recovery"]["dispatches"]):
                failed = True
                raise UsageError("Fixture known pre-send failure", {})
        with self.session() as capability, patch("foreman.cli.save_state", side_effect=fail_after_reservation):
            result = self.runner(capability).tick()
        self.assertTrue(result["wake_agent"])
        state = self.state()
        self.assertEqual([row["status"] for row in state["recovery"]["dispatches"]], ["not_sent"])
        proof = self.fx.tmp / "no-send-proof.json"
        proof.write_text(self.last_error)
        for member in supervision.load(self.path)["members"]:
            if member["active"]:
                supervision.resolve(self.path, {"id": member["id"], "outcome": "not_sent", "evidence": [str(proof)]}, AT)
        intent = state["recovery"]["tasks"]["one"]["progression"]["pending"]["intent"]
        record = self.fx.tmp / "reconcile-intent.json"
        data = {"task": "one", "expected_generation": 1, "intent": intent, "authorization": AUTH}
        record.write_text(json.dumps(data))
        before = self.path.read_bytes()
        associated = self.state()
        associated["recovery"]["dispatches"].append({**associated["recovery"]["dispatches"][0],
            "id": associated["recovery"]["dispatches"][0]["id"] + ":transport-retry-1", "status": "applied"})
        # The owner-reader seam represents a later validated attempt. Even
        # without examining its native evidence, the original row is no proof.
        with patch("foreman.progression_owner._load", return_value=associated), state_lock(self.path), self.assertRaisesRegex(UsageError, "associated transport retries"):
            owner.reconcile_intent(self.path, data, AT, self.client)
        self.assertEqual(self.path.read_bytes(), before)
        with self.session(), state_lock(self.path), self.assertRaisesRegex(ForemanError, "Another progression"):
            owner.reconcile_intent(self.path, data, AT, self.client)
        self.assertEqual(self.path.read_bytes(), before)
        for _ in range(2):
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(cli.main(["progression-reconcile", "--state", str(self.path), "--record", str(record), "--now", AT],
                                      stdout=out, stderr=err, client=self.client), 0, err.getvalue())
            self.assertFalse(json.loads(out.getvalue())["authorizes_dispatch"])
        progress = self.state()["recovery"]["tasks"]["one"]["progression"]
        self.assertEqual(progress["cursor"], 0)
        self.assertIsNone(progress["pending"])
        with state_lock(self.path):
            returned = owner.handoff(self.path, {"task": "one", "expected_generation": 1, "authorization": AUTH},
                                     AT, self.client, ROOT, returning=True)
        self.assertEqual(returned["authority"]["mode"], "legacy")
        self.assertEqual(self.fx.runner.writes(), [])

    def test_zero_exit_with_false_delivery_cannot_trigger_verification(self):
        with self.session() as capability:
            runner = self.runner(capability)
            self.assertEqual(runner.tick()["data"]["status"], "advanced", self.last_error)
            runner.check = lambda _identifier: ({"wait": json.dumps({"found": False})}, 0)
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertEqual(result["data"]["reason"], "delivery_check_invalid")
        self.assertEqual(self.invocations, 1)

    def test_background_child_advances_real_owner_without_parent_relays(self):
        child = os.fork()
        if child == 0:
            try:
                self.delivered = True
                with self.session() as capability:
                    runner = self.runner(capability)
                    if runner.tick()["data"]["status"] != "advanced":
                        os._exit(2)
                    if runner.tick()["data"]["status"] != "advanced":
                        os._exit(3)
                os._exit(0)
            except (AssertionError, UsageError):
                os._exit(4)
        _pid, status = os.waitpid(child, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertEqual(len(self.state()["assignments"]), 3)
        self.assertEqual(self.state()["recovery"]["tasks"]["one"]["progression"]["cursor"], 2)


if __name__ == "__main__":
    unittest.main()
