"""Role context follows actual owner/launch checks without writing authority."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from dataclasses import replace
from functools import partial
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_progression_owner as fixture
from tests import test_command_context as remote_fixture
from foreman import cli, config, role_context, session_start_hook, supervision, tiers
from foreman.command_context import HerdrCommandContext
from foreman.errors import HerdrError, StateError, UsageError
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
        pause = self.owner.root / "worker-pause.md"
        pause.write_text("Private fixture hold covering the active worker.")
        supervision.hold(self.owner.path, {"id": "worker-pause", "kind": "waiting_for_user",
            "resume_condition": "Private explicit resume", "evidence": [str(pause)],
            "dispositions": [{"member": "private-worker", "outcome": "Private fixture held",
                              "evidence": [str(pause)]}]}, fixture.AT)
        before = self.files()
        with patch.dict(os.environ, {"HERDR_PANE_ID": "worker-pane"}):
            held = role_context.select(self.skill, client=native, state_path=self.owner.path,
                payload={**self.payload, "session_id": "worker-session"}, binding_root=self.bindings)
        self.assertEqual((held["role"], held["verified"], held["reason"]), ("recovery", True, "operator_hold"))
        self.assertNotIn("Herdr Worker Context", held["context"])
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

    def test_live_transcript_binding_wins_over_an_also_supplied_opaque_id(self):
        for agent in ("claude", "codex", "grok"):
            with self.subTest(agent=agent):
                transcript = str(self.owner.root / (agent + "-native.jsonl"))
                self.owner.native.update(source="herdr:" + agent, agent=agent, kind="path", value=transcript)
                who = supervision.identity(transcript, str(Path.cwd()), "fixture-only", kind="path", pane_id="fixture-pane")
                supervision.bind(self.owner.path, who, fixture.AT, root=self.bindings)
                before = self.files()
                result = self.select(payload={**self.payload, "transcript_path": transcript})
                self.assertEqual((result["role"], result["verified"]), ("foreman", True))
                result = self.select(payload={**self.payload, "transcript_path": transcript + ".foreign"})
                self.assertEqual((result["role"], result["context"]), ("unverified", ""))
                self.assertEqual(self.files(), before)
                with patch.object(self.owner.client, "pane_get", side_effect=HerdrError("Private outage", {})):
                    result = self.select(payload={**self.payload, "session_id": "unknown-id", "transcript_path": transcript})
                self.assertEqual((result["role"], result["verified"]), ("recovery", False))
                self.assertEqual(result["state_path"], str(self.owner.path))
                self.assertEqual(self.files(), before)

    def test_invalid_native_transcript_proof_never_selects_foreman_context(self):
        for value in (None, "", 12, "relative-transcript.jsonl"):
            with self.subTest(value=value), patch.dict(self.owner.native, {"kind": "path", "value": value}):
                before = self.files()
                result = self.select()
                self.assertNotEqual(result["role"], "foreman")
                self.assertNotIn("Herdr Foreman Operating Context", result["context"])
                self.assertEqual(self.files(), before)

    def test_worker_hook_finds_selected_store_and_current_refined_enrollment(self):
        worker = {"source": "herdr:codex", "agent": "codex", "kind": "id", "value": "refined-worker", "pane_id": "worker-pane"}
        supervision.enroll(self.owner.path, {"id": "refined", "agent": "private-worker", "task": "one",
            "report": str(self.owner.root / "refined-report.md"), "pane_id": None, "native_session": None}, fixture.AT)
        supervision.refine(self.owner.path, "refined", "worker-pane", worker, fixture.AT)
        client = SimpleNamespace(context=HerdrCommandContext("fixture-herdr"),
            pane_get=lambda pane: {"pane_id": pane, "agent_session": worker})
        environment = {"HERDR_ENV": "fixture-only", "HERDR_PANE_ID": "worker-pane",
                       "FOREMAN_CONTEXT_STATE": str(self.owner.path)}
        reader = partial(role_context.select, client=client, binding_root=self.bindings)
        before = self.files()
        result = session_start_hook.collect(self.skill, environment,
            {**self.payload, "session_id": "refined-worker"}, context_reader=reader)
        assert result is not None
        self.assertIn("Herdr Worker Context", result["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("Herdr Foreman Operating Context", result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.files(), before)
        worker["pane_id"] = "foreign-pane"
        self.assertIsNone(session_start_hook.collect(self.skill, environment,
            {**self.payload, "session_id": "refined-worker"}, context_reader=reader))
        self.assertEqual(self.files(), before)

    def test_routing_hint_cannot_redirect_a_bound_foreman_or_create_a_store(self):
        foreign = self.owner.root / "foreign-owner.json"
        environment = {**os.environ, "FOREMAN_CONTEXT_STATE": str(foreign)}
        before = self.files()
        result = role_context.select(self.skill, client=self.owner.client, environment=environment,
            payload=self.payload, binding_root=self.bindings)
        self.assertEqual((result["role"], result["reason"]), ("recovery", "owner_state_mismatch"))
        self.assertEqual(self.files(), before)
        self.assertFalse(foreign.exists())

    def test_startup_locators_are_explicit_paths_without_ambient_environment(self):
        configuration = self.owner.root / "selected-config.json"
        with patch.dict(os.environ, {"PRIVATE_FIXTURE_VALUE": "not forwarded"}):
            result = role_context.startup_environment(self.owner.path, configuration)
        self.assertEqual(result, ("FOREMAN_CONTEXT_STATE=" + str(self.owner.path),
                                  "FOREMAN_CONTEXT_CONFIG=" + str(configuration)))
        self.assertFalse(configuration.exists())
        with self.assertRaises(UsageError):
            role_context.selected_paths({"FOREMAN_CONTEXT_STATE": "relative-owner.json"})

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
            out, err = io.StringIO(), io.StringIO()
            code = cli.main(["role-context"], client=remote.client, stdout=out, stderr=err)
            self.assertEqual((code, err.getvalue()), (0, ""))
            self.assertEqual(json.loads(out.getvalue())["state_path"], str(remote.owner.state_path))
            wrong_out, wrong_err = io.StringIO(), io.StringIO()
            code = cli.main(["role-context", "--state", str(remote.root / "foreign-state.json")],
                            client=remote.client, stdout=wrong_out, stderr=wrong_err)
            self.assertNotEqual(code, 0)
            self.assertIn("remote_owner_state_path_changed", wrong_err.getvalue())
            self.assertEqual(wrong_out.getvalue(), "")
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
        environment = {**os.environ, "FOREMAN_CONTEXT_STATE": str(path), "FOREMAN_CONTEXT_CONFIG": str(configuration)}
        context = session_start_hook.collect(self.skill, environment,
            {**self.payload, "session_id": "initial-session"},
            context_reader=partial(role_context.select, client=client, binding_root=self.bindings))
        assert context is not None
        self.assertIn("Herdr Foreman Operating Context", context["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.files(), before)
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
