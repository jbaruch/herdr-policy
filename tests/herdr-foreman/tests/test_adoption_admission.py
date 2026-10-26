"""Real owner locks, Git and native fixtures for a two-phase legacy admission."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import io
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from tests import test_workflow_adoption as fixture
from tests import test_report_gates as gate_fixture
from foreman import cli, progression_owner as authority, report_gates, supervision, workflow_adoption as adoption
from foreman import workflow_workspace as workspace
from foreman.errors import UsageError
from foreman.state import TransactionBusy, add_assignment, save_state, state_lock


ROOT = Path(__file__).resolve().parents[3]


class AdmissionLockTest(unittest.TestCase):
    def setUp(self):
        self.source = fixture.WorkflowAdoptionTest()
        actual_git = fixture.workflow_fixture.WorkflowServiceTest.git
        def seeded_git(case, *args):
            if args == ("commit", "-m", "Private fixture base"):
                (case.worktree / "src/untouched.py").write_text("baseline = True\n")
                actual_git(case, "add", "src/untouched.py")
            return actual_git(case, *args)
        with patch.object(fixture.workflow_fixture.WorkflowServiceTest, "git", seeded_git):
            self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.fx = self.source.fx
        self.source.prepare()

    def admit(self):
        return authority.admit(self.fx.path, self.fx.owner.data, self.fx.now(), self.fx.native, ROOT)

    def peer_checkpoint(self, label):
        with report_gates.holding(self.fx.path), state_lock(self.fx.path):
            state = self.fx.owner.state()
            add_assignment(state, self.fx.now(), "developer", "peer-" + label, task="two",
                           cleared=True, clear_reason="automatic")
            save_state(self.fx.path, state)

    def test_cli_native_and_remote_reads_allow_real_concurrent_peer_checkpoints(self):
        native, git, policy = self.fx.native.agent_get, workspace.git, authority.loaded_policy
        checked = []
        def read_native(name):
            if name == self.source.source_job["agent"]:
                pool.submit(self.peer_checkpoint, "native").result(timeout=3)
                checked.append("native")
            return native(name)
        def read_git(root, *args, **kwargs):
            if args[:1] == ("ls-remote",):
                pool.submit(self.peer_checkpoint, "remote").result(timeout=3)
                checked.append("remote")
            return git(root, *args, **kwargs)
        def read_policy(root):
            with state_lock(self.fx.path):
                pass
            return policy(root)
        record = self.fx.root / "admission.json"
        record.write_text(json.dumps(self.fx.owner.data))
        out, err = io.StringIO(), io.StringIO()
        with ThreadPoolExecutor(max_workers=1) as pool, \
                patch.object(self.fx.native, "agent_get", side_effect=read_native), \
                patch.object(authority, "loaded_policy", side_effect=read_policy), \
                patch.object(workspace, "git", side_effect=read_git):
            code = cli.main(["progression-admit", "--state", str(self.fx.path), "--record", str(record),
                             "--now", self.fx.now()], client=self.fx.native, stdout=out, stderr=err)
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(checked, ["native", "remote"])
        state = self.fx.owner.state()
        self.assertEqual([row["agent"] for row in state["assignments"][-2:]], ["peer-native", "peer-remote"])
        self.assertEqual(state["recovery"]["tasks"]["one"]["authority"]["schema_version"], 3)
        self.assertEqual(self.fx.progress()["phase"], "verify")
        self.assertEqual(self.fx.progress()["pending"]["operation"], "adopt")

    def gate_record(self):
        return report_gates.record(self.fx.path, gate_fixture.label(self.source.report, gate_fixture.HIGH), self.fx.now())

    def test_classifier_gate_writer_is_fenced_before_primary_lock_through_save(self):
        original_save = authority.save_state
        path = report_gates.storage_path(self.fx.path)
        prior = path.read_bytes() if path.exists() else None
        source = self.fx.owner.state()
        members = supervision.load(self.fx.path)["members"]
        checked = []
        def writer_is_busy(stage):
            with self.assertRaises(TransactionBusy):
                pool.submit(self.gate_record).result(timeout=3)
            self.assertEqual(path.read_bytes() if path.exists() else None, prior)
            checked.append(stage)
        @contextmanager
        def primary(path):
            writer_is_busy("before_primary")
            with state_lock(path):
                yield
        def save(path, state):
            writer_is_busy("before_save")
            return original_save(path, state)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch.object(authority, "state_lock", primary), patch.object(authority, "save_state", side_effect=save):
                self.admit()
            self.assertEqual(checked, ["before_primary", "before_save"])
            recorded = pool.submit(self.gate_record).result(timeout=3)
        self.assertEqual(len(recorded["recorded"]), 1)
        current = self.fx.owner.state()
        self.assertEqual(current["assignments"], source["assignments"])
        self.assertEqual(current["recovery"]["dispatches"], source["recovery"]["dispatches"])
        self.assertEqual(supervision.load(self.fx.path)["members"], members)
        self.assertEqual(self.fx.progress()["pending"]["operation"], "adopt")
        self.assertFalse(self.fx.progress()["pending"]["effects_started"])

    def test_classifier_gate_recorded_before_commit_refuses_without_owner_changes(self):
        self.race(self.gate_record)
        self.assertEqual(len(report_gates.open_gates(self.fx.path, str(self.source.report))), 1)

    def race(self, change):
        original = adoption.prepare_admission
        preserved = []
        def prepare(*args, **kwargs):
            proof = original(*args, **kwargs)
            change()
            preserved.append((self.fx.path.read_bytes(), supervision.store_path(self.fx.path).read_bytes()))
            return proof
        before = len([event for event in self.fx.native.events if event[0] == "prompt"])
        with patch.object(adoption, "prepare_admission", side_effect=prepare), self.assertRaises(UsageError):
            self.admit()
        self.assertEqual(len(preserved), 1, "The intended race must actually be applied")
        self.assertEqual((self.fx.path.read_bytes(), supervision.store_path(self.fx.path).read_bytes()), preserved[0])
        self.assertNotIn("authority", self.fx.owner.state()["recovery"]["tasks"]["one"])
        self.assertFalse(Path(self.fx.document["artifact_directory"]).exists())
        self.assertEqual(len([event for event in self.fx.native.events if event[0] == "prompt"]), before)

    def test_changed_task_authorization_preserves_the_new_owner_facts(self):
        def change():
            with state_lock(self.fx.path):
                state = self.fx.owner.state()
                state["recovery"]["tasks"]["one"]["authorization"]["quote"] = "Changed authorized fixture scope"
                save_state(self.fx.path, state)
        self.race(change)

    def test_new_confirmed_correction_remains_with_the_original_task(self):
        def change():
            with state_lock(self.fx.path):
                state = self.fx.owner.state()
                add_assignment(state, self.fx.now(), "developer", "new-correction", task="one", fix_round=1,
                               cleared=True, clear_reason="automatic")
                save_state(self.fx.path, state)
        self.race(change)
        self.assertEqual(self.fx.owner.state()["assignments"][-1]["fix_round"], 1)

    def test_changed_source_enrollment_resolution_retains_its_actual_outcome(self):
        self.race(lambda: supervision.resolve(self.fx.path, {"id": self.source.source_job["id"],
            "outcome": "Fixture source owner closed delivery; acceptance remains unknown",
            "evidence": [str(self.source.report)]}, self.fx.now()))

    def test_concurrent_collection_observation_survives_admission_and_transfer(self):
        original = adoption.prepare_admission
        evidence = {"present": True, **workspace.capture(self.source.report)[0],
                    "size": self.source.report.stat().st_size}
        def prepare(*args, **kwargs):
            proof = original(*args, **kwargs)
            def observe(current):
                member = next(row for row in current["members"] if row["id"] == self.source.source_job["id"])
                supervision.append_event(current, self.fx.now(), member["id"], "report_observed", evidence)
                member["observed"]["report"] = evidence
            supervision.transaction(self.fx.path, observe)
            return proof
        with patch.object(adoption, "prepare_admission", side_effect=prepare):
            self.admit()
        self.assertEqual(supervision.load(self.fx.path)["members"][0]["observed"]["report"], evidence)
        with self.fx.owner.session() as capability:
            self.assertEqual(self.fx.runner(capability).tick()["data"]["status"], "effect_recorded")
        self.assertFalse(supervision.load(self.fx.path)["members"][0]["active"])

    def test_policy_upgrade_during_native_verification_cannot_relabel_its_proof(self):
        policy = self.fx.root / "policy"
        for relative in ("rules", "skills/herdr-foreman", ".tessl-plugin"):
            shutil.copytree(ROOT / relative, policy / relative, ignore=shutil.ignore_patterns("__pycache__"))
        original = self.fx.native.agent_get
        def native(name):
            result = original(name)
            if name == self.source.source_job["agent"]:
                manifest = policy / ".tessl-plugin/plugin.json"
                value = json.loads(manifest.read_text())
                value["version"] = "99.0.0"
                manifest.write_text(json.dumps(value))
            return result
        before = self.fx.path.read_bytes()
        with patch.object(self.fx.native, "agent_get", side_effect=native), \
                self.assertRaisesRegex(UsageError, "changed during verification"):
            authority.admit(self.fx.path, self.fx.owner.data, self.fx.now(), self.fx.native, policy)
        self.assertEqual(self.fx.path.read_bytes(), before)
        self.assertNotIn("authority", self.fx.owner.state()["recovery"]["tasks"]["one"])

    def test_policy_identity_and_metadata_capture_cannot_straddle_a_replacement(self):
        policy = self.fx.root / "policy"
        for relative in ("rules", "skills/herdr-foreman", ".tessl-plugin"):
            shutil.copytree(ROOT / relative, policy / relative, ignore=shutil.ignore_patterns("__pycache__"))
        original = authority.loaded_policy
        def replace_after_read(root):
            result = original(root)
            manifest = policy / ".tessl-plugin/plugin.json"
            value = json.loads(manifest.read_text())
            value["version"] = "99.0.0"
            manifest.write_text(json.dumps(value))
            return result
        before = self.fx.path.read_bytes()
        with patch.object(authority, "loaded_policy", side_effect=replace_after_read), \
                self.assertRaisesRegex(UsageError, "Policy changed"):
            authority.admit(self.fx.path, self.fx.owner.data, self.fx.now(), self.fx.native, policy)
        self.assertEqual(self.fx.path.read_bytes(), before)

    def test_changed_binding_refuses_the_old_native_verification(self):
        def change():
            bound = supervision.load(self.fx.path)["binding"]["identity"]
            supervision.bind(self.fx.path, {**bound, "value": "00000000-0000-4000-8000-000000000099"}, self.fx.now(),
                             root=self.fx.root / "bindings")
        self.race(change)

    def test_late_operator_hold_remains_effective(self):
        self.race(lambda: supervision.hold(self.fx.path, {"id": "late-hold", "kind": "waiting_for_user",
            "resume_condition": "Existing fixture operator resumes", "evidence": [str(self.source.report)],
            "dispositions": [{"member": self.source.source_job["id"], "outcome": "Fixture operator holds the source",
                              "evidence": [str(self.source.report)]}]}, self.fx.now()))

    def test_changed_git_head_after_verification_refuses_without_reverting_source(self):
        def change():
            self.fx.source.write_text("value = 999\n")
            self.fx.git("commit", "-am", "Preserve concurrent source correction")
        self.race(change)
        self.assertEqual(self.fx.source.read_text(), "value = 999\n")

    def test_different_branch_at_the_same_commit_refuses(self):
        before = self.fx.git("rev-parse", "HEAD")
        self.race(lambda: self.fx.git("switch", "-c", "different-owner-branch"))
        self.assertEqual(self.fx.git("rev-parse", "HEAD"), before)

    def origin_include(self, *, conditional=False):
        path = self.fx.root / "origin.include"
        path.write_text('[url "https://github.com/fixture/repository.git"]\n\tinsteadOf = fixture-origin:\n')
        if not conditional:
            self.fx.git("config", "remote.origin.url", "fixture-origin:")
        key = "includeIf.onbranch:feature/task.path" if conditional else "include.path"
        self.fx.git("config", key, str(path))
        return path

    def test_included_fetch_rewrite_change_refuses_without_altering_config(self):
        path = self.origin_include()
        config = self.fx.repository / ".git/config"
        before = config.read_bytes()
        def change():
            path.write_text('[url "https://github.com/foreign/repository.git"]\n\tinsteadOf = fixture-origin:\n')
            self.assertEqual(self.fx.git("remote", "get-url", "origin").strip(), "https://github.com/foreign/repository.git")
        self.race(change)
        self.assertEqual(config.read_bytes(), before)
        self.assertIn("foreign/repository", path.read_text())

    def test_conditional_included_push_rewrite_refuses_with_unchanged_fetch(self):
        path = self.origin_include(conditional=True)
        original = path.read_text()
        def change():
            path.write_text(original + '\n[url "https://github.com/foreign/repository.git"]\n\tpushInsteadOf = https://github.com/fixture/repository.git\n')
            self.assertEqual(self.fx.git("remote", "get-url", "origin").strip(), "https://github.com/fixture/repository.git")
            self.assertEqual(self.fx.git("remote", "get-url", "--push", "--all", "origin").strip(), "https://github.com/foreign/repository.git")
        self.race(change)

    def test_worktree_push_target_change_refuses_and_preserves_worktree_config(self):
        self.fx.git("config", "extensions.worktreeConfig", "true")
        self.fx.git("config", "--worktree", "remote.origin.pushurl", "https://github.com/fixture/repository.git")
        config = self.fx.repository / ".git/config"
        before = config.read_bytes()
        self.race(lambda: self.fx.git("config", "--worktree", "remote.origin.pushurl", "https://github.com/foreign/repository.git"))
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(self.fx.git("remote", "get-url", "--push", "origin").strip(), "https://github.com/foreign/repository.git")

    def test_secondary_fetch_url_cannot_hide_behind_an_explicit_valid_push_target(self):
        path = self.origin_include()
        self.fx.git("config", "remote.origin.pushurl", "https://github.com/fixture/repository.git")
        original = path.read_text()
        def change():
            path.write_text(original + '\n[remote "origin"]\n\turl = https://github.com/foreign/repository.git\n')
            self.assertEqual(self.fx.git("remote", "get-url", "--all", "origin").splitlines(),
                ["https://github.com/fixture/repository.git", "https://github.com/foreign/repository.git"])
            self.assertEqual(self.fx.git("remote", "get-url", "--push", "--all", "origin").splitlines(),
                ["https://github.com/fixture/repository.git"])
        self.race(change)

    def test_all_push_targets_must_match_even_when_the_first_is_valid(self):
        self.fx.git("config", "extensions.worktreeConfig", "true")
        self.fx.git("config", "--worktree", "remote.origin.pushurl", "https://github.com/fixture/repository.git")
        self.race(lambda: self.fx.git("config", "--worktree", "--add", "remote.origin.pushurl", "https://github.com/foreign/repository.git"))

    def test_unchanged_include_and_worktree_origins_keep_supported_url_identity(self):
        self.origin_include()
        self.fx.git("config", "extensions.worktreeConfig", "true")
        for url in ("https://github.com/fixture/repository.git", "git@github.com:FIXTURE/REPOSITORY",
                    "ssh://git@github.com/fixture/repository.git"):
            self.fx.git("config", "--worktree", "--add", "remote.origin.pushurl", url)
        self.admit()
        self.assertEqual(self.fx.progress()["phase"], "verify")

    def test_local_head_tree_must_match_the_verified_adoption_tree(self):
        expected = {**self.fx.document["adoption"]["head"], "tree": "0" * 40}
        before = self.fx.path.read_bytes()
        with self.assertRaises(UsageError):
            adoption._require_local_head(self.fx.document, expected)
        self.assertEqual(self.fx.path.read_bytes(), before)

    def test_dirty_tracked_file_outside_the_original_diff_stays_unmodified(self):
        other = self.fx.worktree / "src/untouched.py"
        self.assertNotIn("src/untouched.py", self.fx.document["adoption"]["head"]["paths"])
        self.race(lambda: other.write_text("preserve = 'late source'\n"))
        self.assertEqual(other.read_text(), "preserve = 'late source'\n")

    def test_untracked_path_created_after_preparation_is_preserved(self):
        target = self.fx.worktree / "private-new.txt"
        self.race(lambda: target.write_text("Preserve this private input.\n"))
        self.assertEqual(target.read_text(), "Preserve this private input.\n")

    def test_new_untracked_file_in_preexisting_empty_directory_refuses(self):
        directory = self.fx.worktree / "empty"
        directory.mkdir()
        target = directory / "private-new.txt"
        self.race(lambda: target.write_text("Preserve nested private input.\n"))

    def test_ignored_cache_addition_remains_eligible(self):
        exclude = self.fx.repository / ".git/info/exclude"
        with exclude.open("a") as stream:
            stream.write("\ncache/\n")
        original = adoption.prepare_admission
        def prepare(*args, **kwargs):
            proof = original(*args, **kwargs)
            target = self.fx.worktree / "cache/private.txt"
            target.parent.mkdir()
            target.write_text("Unchanged ignored runtime cache.\n")
            return proof
        with patch.object(adoption, "prepare_admission", side_effect=prepare):
            self.admit()
        self.assertEqual(self.fx.progress()["phase"], "verify")

    def test_changed_report_after_verification_preserves_bytes_and_refuses(self):
        self.race(lambda: self.source.report.write_text("Preserve the owner's changed report.\n"))
        self.assertEqual(self.source.report.read_text(), "Preserve the owner's changed report.\n")

    def test_report_replacement_during_final_git_checks_is_not_admitted(self):
        original = adoption._require_local_head
        def read(*args, **kwargs):
            original(*args, **kwargs)
            self.source.report.write_text("Preserve this late native report.\n")
        before = self.fx.path.read_bytes()
        with patch.object(adoption, "_require_local_head", side_effect=read), self.assertRaises(UsageError):
            self.admit()
        self.assertEqual(self.fx.path.read_bytes(), before)
        self.assertFalse(Path(self.fx.document["artifact_directory"]).exists())
        self.assertEqual(self.source.report.read_text(), "Preserve this late native report.\n")

    def test_template_replacement_during_final_git_checks_is_not_admitted(self):
        original = adoption._require_local_head
        def read(*args, **kwargs):
            original(*args, **kwargs)
            self.fx.common.write_text("Preserve this changed template.\n")
        before = self.fx.path.read_bytes()
        with patch.object(adoption, "_require_local_head", side_effect=read), self.assertRaises(UsageError):
            self.admit()
        self.assertEqual(self.fx.path.read_bytes(), before)
        self.assertFalse(Path(self.fx.document["artifact_directory"]).exists())

    def test_locked_low_level_call_cannot_fall_back_to_native_source_verification(self):
        with state_lock(self.fx.path), patch.object(self.fx.native, "pane_get", side_effect=AssertionError("No native I/O under lock")), \
                patch.object(adoption, "require_current", side_effect=AssertionError("No source I/O under lock")), \
                self.assertRaisesRegex(UsageError, "owner-managed preflight"):
            authority.handoff(self.fx.path, self.fx.owner.data, self.fx.now(), self.fx.native, ROOT)

    def test_unknown_head_shape_refuses_before_git_or_native_source_reads(self):
        self.fx.document["adoption"]["head"] = None
        self.fx.owner.contract.write_text(json.dumps(self.fx.document))
        before = self.fx.path.read_bytes()
        with patch.object(workspace, "git", side_effect=AssertionError("Unknown heads must not reach Git")), \
                self.assertRaisesRegex(UsageError, "actual implementation"):
            self.admit()
        self.assertEqual(self.fx.path.read_bytes(), before)

    def test_fifo_swap_refuses_without_blocking_the_shared_owner(self):
        program = """
import os
from pathlib import Path
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'tests/herdr-foreman'))
sys.path.insert(0, str(root / 'skills/herdr-foreman'))
from tests.test_adoption_admission import AdmissionLockTest
case = AdmissionLockTest()
case.setUp()
try:
    for target in (case.source.report, case.fx.owner.contract, case.fx.common):
        original = target.read_bytes()
        def replace():
            target.unlink()
            os.mkfifo(target, 0o600)
        case.race(replace)
        target.unlink()
        target.write_bytes(original)
finally:
    case.doCleanups()
"""
        result = subprocess.run([sys.executable, "-I", "-c", program, str(ROOT)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
