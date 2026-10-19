"""Exercise the background chain through real CLI owners and fixture transport."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from tests import test_cli as fixtures
from tests.fakes import ScriptedReads, agent_json
from foreman import cli, progression_owner as owner, progression_service as service, recovery, supervision
from foreman.errors import UsageError
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

    def test_crash_after_applied_dispatch_replays_owner_receipt_without_resending(self):
        def crash(*args, **kwargs):
            self.assertEqual(self.invoke(*args, **kwargs), 0, self.last_error)
            raise RuntimeError("fixture crash after real owner commit")
        with self.session() as capability:
            with self.assertRaisesRegex(RuntimeError, "fixture crash"):
                self.runner(capability, crash).tick()
        self.assertIsNotNone(self.state()["recovery"]["tasks"]["one"]["progression"]["pending"])
        writes = list(self.fx.runner.writes())
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
        with self.session() as capability, patch("foreman.cli.config_owner.parse_config", side_effect=replace_after_capture):
            result = self.runner(capability).tick()
        self.assertEqual(result["data"]["status"], "advanced", self.last_error)
        self.assertEqual(self.state()["assignments"][0]["agent"], "grok")

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
