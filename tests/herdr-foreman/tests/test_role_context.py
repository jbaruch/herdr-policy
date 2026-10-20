"""Role context follows actual owner/launch checks without writing authority."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from dataclasses import replace
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_progression_owner as fixture
from tests import test_command_context as remote_fixture
from foreman import cli, config, role_context, supervision, tiers
from foreman.command_context import HerdrCommandContext
from foreman.errors import HerdrError, StateError
from foreman.state import empty_state, save_state


class RoleContextTest(unittest.TestCase):
    def setUp(self):
        self.owner = fixture.ProgressionOwnerTest()
        self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.skill = fixture.ROOT / "skills/herdr-foreman"
        self.payload = {"session_id": "fixture-session", "cwd": str(Path.cwd())}
        self.bindings = self.owner.root / "bindings"

    def files(self):
        return {str(path.relative_to(self.owner.root)): path.read_bytes()
                for path in self.owner.root.rglob("*") if path.is_file()}

    def select(self, **options):
        return role_context.select(self.skill, client=self.owner.client, state_path=self.owner.path,
            payload=options.pop("payload", self.payload), binding_root=self.bindings, **options)

    def test_standalone_reads_neither_owner_nor_controller(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(supervision, "load", side_effect=AssertionError("owner read")):
            result = role_context.select(self.skill)
        self.assertEqual((result["role"], result["context"], result["reference"]), ("standalone", "", None))
        self.assertFalse(result["verified"])

    def test_bound_foreman_gets_small_current_contract_without_owner_edits(self):
        before = self.files()
        result = self.select()
        self.assertEqual((result["role"], result["verified"], result["reason"]),
                         ("foreman", True, "bound_native_foreman"))
        self.assertIn("Herdr Foreman Operating Context", result["context"])
        self.assertNotIn("## Step 17", result["context"])
        self.assertLessEqual(len(result["context"].encode()), role_context.CONTEXT_BYTES)
        self.assertLessEqual(len((json.dumps(result, indent=2) + "\n").encode()), 16_384)
        for field in ("authorizes_dispatch", "authorizes_progression", "authorizes_release"):
            self.assertFalse(result[field])
        self.assertEqual(self.files(), before)

    def test_hook_session_must_match_the_controller_identity(self):
        result = self.select(payload={**self.payload, "session_id": "another-session"})
        self.assertEqual((result["role"], result["reason"], result["context"]),
                         ("unverified", "hook_session_mismatch", ""))

    def test_hook_cwd_cannot_misstate_the_current_native_owner(self):
        for value in ("relative/path", "/another/private/fixture", None):
            with self.subTest(cwd=value):
                result = self.select(payload={**self.payload, "cwd": value})
                self.assertEqual((result["role"], result["reason"], result["context"]),
                                 ("unverified", "hook_session_mismatch", ""))

    def test_changed_native_session_does_not_inherit_foreman_context(self):
        self.owner.native["value"] = "replacement-session"
        result = self.select(payload={**self.payload, "session_id": "replacement-session"})
        self.assertEqual(result["role"], "unverified")
        self.assertEqual(result["context"], "")

    def test_outage_retains_known_session_recovery_without_rebinding(self):
        before = self.files()
        with patch.object(self.owner.client, "pane_get", side_effect=HerdrError("Private fixture unavailable", {})):
            result = self.select()
        self.assertEqual((result["role"], result["verified"]), ("recovery", False))
        self.assertIn("unknown sends", result["context"])
        self.assertIn("operator holds", result["context"])
        self.assertEqual(result["state_path"], str(self.owner.path))
        self.assertEqual(self.files(), before)

    def test_unknown_session_outage_receives_no_foreman_contract(self):
        with patch.object(self.owner.client, "pane_get", side_effect=HerdrError("Private fixture unavailable", {})):
            result = self.select(payload={**self.payload, "session_id": "unknown"})
        self.assertEqual((result["role"], result["context"]), ("unverified", ""))

    def test_explicit_state_cannot_redirect_an_existing_binding(self):
        result = role_context.select(self.skill, client=self.owner.client,
            state_path=self.owner.root / "foreign-state.json", payload=self.payload, binding_root=self.bindings)
        self.assertEqual((result["role"], result["reason"]), ("recovery", "owner_state_mismatch"))
        self.assertFalse((self.owner.root / "foreign-state.json").exists())

    def test_worker_receives_its_protocol_without_foreman_choreography(self):
        worker = {"source": "herdr:codex", "agent": "codex", "kind": "id", "value": "worker-session"}
        supervision.enroll(self.owner.path, {"id": "private-worker", "agent": "worker", "task": "one",
            "report": str(self.owner.root / "worker-report.md"), "pane_id": "worker-pane", "native_session": worker}, fixture.AT)
        native = SimpleNamespace(context=HerdrCommandContext("fixture-herdr"),
            pane_get=lambda pane: {"pane_id": pane, "agent_session": worker})
        before = self.files()
        with patch.dict(os.environ, {"HERDR_PANE_ID": "worker-pane"}):
            result = role_context.select(self.skill, client=native, state_path=self.owner.path,
                payload={**self.payload, "session_id": "worker-session"}, binding_root=self.bindings)
        self.assertEqual((result["role"], result["verified"]), ("worker", True))
        self.assertIn("Herdr Worker Context", result["context"])
        self.assertNotIn("## Step", result["context"])
        self.assertNotIn("Herdr Foreman Operating Context", result["context"])
        self.assertEqual(self.files(), before)

    def test_operator_hold_selects_recovery_and_is_not_cleared(self):
        pause = self.owner.root / "pause.md"
        pause.write_text("Private fixture operator hold.")
        supervision.hold(self.owner.path, {"id": "pause", "kind": "waiting_for_user",
            "resume_condition": "Explicit private fixture resume", "evidence": [str(pause)],
            "dispositions": []}, fixture.AT)
        before = self.files()
        result = self.select()
        self.assertEqual((result["role"], result["reason"]), ("recovery", "operator_hold"))
        self.assertEqual(self.files(), before)

    def test_discovery_generation_must_match_the_actual_owner(self):
        identity = supervision.identity("fixture-session", str(Path.cwd()), "fixture-only", pane_id="fixture-pane")
        path = supervision.binding_path(identity, self.bindings)
        binding = json.loads(path.read_text())
        binding["generation"] += 1
        path.write_text(json.dumps(binding))
        before = self.files()
        result = self.select()
        self.assertEqual((result["role"], result["reason"]), ("recovery", "binding_generation_mismatch"))
        self.assertEqual(self.files(), before)

    def test_attested_remote_uses_its_actual_owner_without_inventing_native_context(self):
        remote = remote_fixture.RemoteOwnerFixture()
        with patch.dict(os.environ, {}, clear=True):
            remote.setUp()
            self.addCleanup(remote.doCleanups)
            before = {str(path): path.read_bytes() for path in remote.root.rglob("*") if path.is_file()}
            result = role_context.select(self.skill, client=remote.client)
            self.assertEqual((result["role"], result["verified"]), ("foreman", True))
            self.assertEqual(result["state_path"], str(remote.owner.state_path))
            self.assertNotIn("HERDR_ENV", os.environ)
            self.assertEqual(remote.effects(), [])
            self.assertEqual({str(path): path.read_bytes() for path in remote.root.rglob("*") if path.is_file()}, before)
            remote.current_receipt = replace(remote.receipt, lease_epoch=2)
            result = role_context.select(self.skill, client=remote.client)
            self.assertEqual((result["role"], result["verified"]), ("recovery", False))
            self.assertEqual(remote.effects(), [])

    def test_initial_foreman_requires_configured_seat_and_exact_process_argv(self):
        path = self.owner.root / "initial.json"
        save_state(path, empty_state())
        configuration = self.owner.root / "config.json"
        configuration.write_bytes((self.skill / "config.example.json").read_bytes())
        seat = config.load_foreman(configuration)
        assert seat is not None
        tier = tiers.select_tier(seat, "foreman")
        native = {"source": "herdr:" + seat.kind, "agent": seat.kind, "kind": "id", "value": "initial-session"}
        argv = [seat.kind, *seat.launch_args, *tiers.launch_flags(seat.kind, tier)]
        client = SimpleNamespace(context=HerdrCommandContext("fixture-herdr"),
            pane_get=lambda pane: {"pane_id": pane, "agent_session": native},
            agent_get=lambda name: {"name": name, "agent": seat.kind, "pane_id": "fixture-pane"},
            pane_process_info=lambda pane: {"foreground_processes": [{"name": seat.kind, "pid": 200, "argv": argv}]})
        options = {"client": client, "state_path": path, "config_path": configuration,
            "payload": {**self.payload, "session_id": "initial-session"}, "binding_root": self.bindings}
        before = self.files()
        result = role_context.select(self.skill, **options)
        self.assertEqual((result["role"], result["reason"]), ("foreman", "configured_native_foreman"))
        argv.append("--resume")
        result = role_context.select(self.skill, **options)
        self.assertEqual((result["role"], result["context"]), ("unverified", ""))
        self.assertEqual(self.files(), before)

    def test_oversized_contract_refuses_instead_of_truncating(self):
        private = self.owner.root / "skill"
        (private / "references").mkdir(parents=True)
        (private / "references/foreman-context.md").write_bytes(b"x" * (role_context.CONTEXT_BYTES + 1))
        with self.assertRaises(StateError):
            role_context.select(private, client=self.owner.client, state_path=self.owner.path,
                payload=self.payload, binding_root=self.bindings)

    def test_offline_cli_does_not_need_a_usable_owner(self):
        self.owner.path.write_text("Preserve unreadable private owner")
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            code = cli.main(["role-context", "--state", str(self.owner.path), "--config", str(self.owner.root / "absent")],
                            stdout=out, stderr=err)
        self.assertEqual((code, err.getvalue()), (0, ""))
        self.assertEqual(json.loads(out.getvalue())["role"], "standalone")
        self.assertEqual(self.owner.path.read_text(), "Preserve unreadable private owner")


if __name__ == "__main__":
    unittest.main()
