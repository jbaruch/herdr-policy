"""Full task delivery with actual temporary Git worktrees and fake remote APIs.

No GitHub publication, live native team, operator checkout or pilot is used.
Release helpers' documented subprocess contracts are fixtures; the controller,
native owner/lifecycle, evidence owners and local cleanup Git commands execute.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import importlib.util
import json
import os
import stat
import subprocess
import unittest
from unittest.mock import patch

from tests import test_workflow_service as fixture
from foreman import recovery, supervision, workflow_contract, workflow_recovery, workflow_release, workflow_review
from foreman import workflow_artifacts, workflow_rename
from foreman import progression_owner as authority
from foreman.errors import StateError
from foreman.state import load_state_checked, save_state, state_lock


class WorkflowReleaseTest(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowServiceTest()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.path, self.root = self.case.path, self.case.root
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(self.remote)],
                       check=True, capture_output=True)
        self.redirect = "url.{}.insteadOf=https://github.com/fixture/repository.git".format(self.remote)
        self.git(self.case.repository, "push", "origin", "main")
        self.calls = []
        self.fail_helper = None
        self.invalid_package = False
        self.failed_run = False
        self.moderation_version = None
        self.report_version = None
        self.report_tag = None
        self.tag_commit = None
        self.annotated_tag = False
        self.bundle = self.root / "release-skill-fixture"
        self.bundle.mkdir()
        for name in ("check-closing-issues.py", "resolve-publish-run.sh", "confirm-tessl-landed.sh",
                     "verify-moderation-cleared.sh", "verify-github-release.sh"):
            (self.bundle / name).write_text("Private ABI fixture; never executed.\n")
        self.adapter = workflow_release.WorkflowReleaseAdapter(run=self.run_tool)
        patcher = patch.object(self.adapter, "_bundle", return_value=self.bundle)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pr = None
        self.before_cleanup = None
        self.landed = "0.4.0"
        self.review_transform = None

    def git(self, root, *arguments):
        return subprocess.run(["git", "-c", self.redirect, "-C", str(root), *arguments],
                              check=True, capture_output=True, text=True).stdout

    def run_tool(self, argv, **options):
        self.calls.append(list(argv))
        if argv[0] == "git":
            actual = ["git", "-c", self.redirect, *argv[1:]] if set(argv) & {"fetch", "push", "ls-remote"} else argv
            return subprocess.run(actual, **options)
        if argv[:2] == ["gh", "api"]:
            if "/git/" in argv[2]:
                assert self.pr is not None
                target = self.tag_commit or self.pr["merge_commit_sha"]
                annotated = self.annotated_tag and "/git/ref/" in argv[2]
                payload = {"object": {"type": "tag" if annotated else "commit",
                                      "sha": "e" * 40 if annotated else target}}
            else:
                payload = self.pr
        elif argv[:3] == ["gh", "run", "watch"]:
            if self.failed_run and "--exit-status" in argv:
                return subprocess.CompletedProcess(argv, 1, None, "Private failed publisher fixture.")
            payload = None
        elif argv[:2] == ["acr", "validate"]:
            payload = {"ok": True, "result": None if self.invalid_package else {"valid": True, "version": "0.4.0"}}
        else:
            helper = Path(argv[1]).name
            if self.fail_helper == helper:
                return subprocess.CompletedProcess(argv, 2, "", "Private indeterminate tool fixture.")
            payload = {
                "check-closing-issues.py": {"verdict": "ok", "closing": [], "partial_references": [], "no_issue": True},
                "resolve-publish-run.sh": {"database_id": 42},
                "confirm-tessl-landed.sh": self.landed,
                "verify-moderation-cleared.sh": {"ok": True, "version": self.moderation_version or self.landed},
                "verify-github-release.sh": {"ok": True, "tag": "v0.4.0", "assets": 3}}[helper]
        stdout = None if options.get("stdout") == subprocess.DEVNULL else (
            payload + "\n" if isinstance(payload, str) else json.dumps(payload) + "\n")
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    def deliver(self, job):
        if job["role"] != "release":
            return self.case.deliver(job)
        # Emulate the authorized native release responsibility's completed
        # effect, independently checked by the controller after report delivery.
        claim = self.case.deliver(job)
        head = self.case.git("rev-parse", "HEAD").strip()
        review_path = Path(claim["review_evidence"]["path"])
        snapshot = json.loads(review_path.read_text())
        if self.review_transform is not None:
            snapshot = self.review_transform(snapshot)
            review_path.write_text(json.dumps(snapshot))
        self.git(self.case.worktree, "push", "origin", "feature/task")
        self.git(self.case.repository, "merge", "--no-ff", "feature/task", "-m", "Private fixture merge")
        merge = self.git(self.case.repository, "rev-parse", "HEAD").strip()
        self.git(self.case.repository, "push", "origin", "main")
        self.git(self.case.repository, "reset", "--hard", self.case.base)
        self.git(self.case.repository, "update-ref", "-d", "refs/remotes/origin/main")
        self.pr = {"merged": True, "merge_commit_sha": merge, "merged_at": "2026-10-19T00:10:00+00:00",
            "head": {"sha": head, "ref": "feature/task", "repo": {"full_name": "fixture/repository"}},
            "base": {"ref": "main", "repo": {"full_name": "fixture/repository"}}}
        channels = self.case.document["publication"]
        published = channels["tessl"] is not None or channels["acr"]
        claim.update(outcome="delivered", review_snapshot=workflow_review.identity(snapshot)["sha256"],
            review_evidence=recovery.receipt(str(review_path))[0], publication={"schema_version": 1,
                "baseline": "0.3.1" if channels["tessl"] else None,
                "baseline_at": self.case.now() if channels["tessl"] else None,
                "publisher_run": 42 if published else None, "tag": self.report_tag or ("v0.4.0" if channels["acr"] else None),
                "tessl_version": (self.report_version or self.landed) if channels["tessl"] else None})
        Path(job["report"]).write_text("WORKFLOW: " + json.dumps(claim) + "\n")
        return claim

    def runner(self, capability):
        runner = self.case.runner(capability)
        runner.release = self.adapter
        return runner

    def test_real_git_teardown_and_actual_task_closure_follow_verified_native_release(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete", delivery=self.deliver)
            assert self.pr is not None
            progress = self.case.progress()
            self.assertTrue(progress["delivery"]["accepted"])
            self.assertEqual(progress["delivery"]["merge_commit"], self.pr["merge_commit_sha"])
            self.assertFalse(self.case.worktree.exists())
            self.assertEqual(self.git(self.case.repository, "branch", "--show-current").strip(), "main")
            self.assertEqual(self.git(self.case.repository, "rev-parse", "HEAD").strip(), self.pr["merge_commit_sha"])
            refs = self.git(self.case.repository, "ls-remote", "--heads", "origin")
            self.assertNotIn("feature/task", refs)
            self.assertEqual(len([row for row in self.case.owner.state()["recovery"]["events"] if row["kind"] == "task_closed"]), 1)
            self.assertIsNone(progress["pending"])
            self.assertEqual(supervision.pending(supervision.load(self.path)), [])
            self.assertFalse(Path(self.case.document["artifact_directory"]).exists())

    def at_artifact_cleanup(self, runner):
        self.case.advance(runner, lambda: self.case.progress()["phase"] == "cleanup"
            and self.case.progress()["delivery"]["cleanup_step"] == 5
            and self.case.progress()["pending"] is None, delivery=self.deliver)
        return Path(self.case.document["artifact_directory"])

    def test_foreign_file_preserves_the_complete_task_directory(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            (root / "operator-notes.md").write_text("Owned by the operator.\n")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertFalse(self.case.progress()["phase"] == "complete")

    def test_admission_preserves_the_exclusive_retirement_namespace(self):
        reserved = self.root / (".herdr-retire-" + "a" * 32)
        self.case.document["artifact_directory"] = str(reserved)
        events = list(self.case.native.events)
        with self.assertRaisesRegex(fixture.UsageError, "retirement namespace"):
            self.case.admit()
        self.assertFalse(reserved.exists())
        self.assertEqual(self.case.native.events, events)

    def test_long_retirement_manifest_stays_out_of_current_context(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            state = self.case.owner.state()
            progress = state["recovery"]["tasks"]["one"]["progression"]
            lifecycle = progress["delivery"]["artifacts"]
            lifecycle["phase"] = "retiring"
            lifecycle["stage"] = {"schema_version": 1, "device": 1, "inode": 2}
            while len(lifecycle["remaining"]) < 256:
                count = len(lifecycle["remaining"])
                lifecycle["remaining"].append({"schema_version": 1, "name": "retained-{}-{}".format(count, "x" * 90),
                    "sha256": "a" * 64, "device": 1, "inode": count + 3})
            hidden = lifecycle["remaining"][-1]["name"]
            save_state(self.path, state)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception")
            self.assertEqual(result["data"]["delivery"]["artifacts"]["remaining_count"], 256)
            rendered = (json.dumps(result, indent=2) + "\n").encode()
            self.assertLessEqual(len(rendered), 16384)
            self.assertNotIn(hidden.encode(), rendered)
            self.assertEqual(len(self.case.progress()["delivery"]["artifacts"]["remaining"]), 256)
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_changed_closed_report_preserves_all_artifacts(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            report = next(root.glob("report-*.md"))
            report.write_bytes(report.read_bytes() + b"Changed after native closure.\n")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_changed_release_review_snapshot_preserves_all_artifacts(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            snapshot = next(root.glob("reviews-*.json"))
            snapshot.write_bytes(b'{"foreign": "Changed after release."}\n')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_missing_closed_release_report_preserves_review_snapshot(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            next(root.glob("report-*-release.md")).unlink()
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_an_unresolved_enrollment_protects_its_directory_without_a_report_file(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            supervision.enroll(self.path, {"id": "foreign", "agent": "elsewhere", "task": "two",
                "report": str(root / "foreign-report.md"), "pane_id": None, "native_session": None}, self.case.now())
            before = set(root.iterdir())
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(set(root.iterdir()), before)

    def test_linked_artifact_preserves_the_foreign_target_and_directory(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            report = next(root.glob("report-*.md"))
            other = self.root / "retained-report.md"
            os.link(report, other)
            before = set(root.iterdir())
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(set(root.iterdir()), before)
            self.assertEqual(other.read_bytes(), report.read_bytes())

    def test_a_file_changed_after_intent_preparation_is_not_removed(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            self.assertEqual(runner.tick()["data"]["status"], "prepared")
            intent = self.case.progress()["pending"]
            delivery = next(Path(row["path"]) for row in intent["inputs"] if Path(row["path"]).name.startswith("delivery-"))
            delivery.write_bytes(delivery.read_bytes() + b" \n")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertEqual(self.case.progress()["pending"]["id"], intent["id"])
            self.assertFalse(self.case.progress()["pending"]["effects_started"])

    def test_a_special_file_cannot_trap_cleanup_in_a_blocking_read(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            report = next(root.glob("report-*.md"))
            report.unlink()
            os.mkfifo(report)
            before = set(root.iterdir())
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(set(root.iterdir()), before)
            self.assertTrue(stat.S_ISFIFO(report.lstat().st_mode))

    def test_a_hold_after_artifact_preparation_preserves_every_file(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            state = self.case.owner.state()
            task = state["recovery"]["tasks"]["one"]
            supervision.hold(self.path, {"id": "artifact-hold", "kind": "waiting_for_user",
                "resume_condition": "Explicit fixture operator resumes", "evidence": [str(self.case.common)],
                "dispositions": []}, self.case.now())
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with state_lock(self.path), self.assertRaisesRegex(fixture.UsageError, "operator hold"):
                self.adapter.resume_cleanup(runner, state, task, task["progression"])
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertFalse(self.case.progress()["pending"]["effects_started"])

    def test_a_report_gate_after_artifact_preparation_preserves_every_file(self):
        from tests import test_report_gates as gate_fixture
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            state = self.case.owner.state()
            task = state["recovery"]["tasks"]["one"]
            report = next(row["assignment"]["report"] for row in supervision.load(self.path)["members"]
                          if row["assignment"]["agent"].startswith("reviewer-"))
            fixture.report_gates.record(self.path, {"schema_version": 2, "agent": "default", "labels": [
                gate_fixture.label(Path(report), gate_fixture.HIGH)], "unannotated": []}, self.case.now())
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with state_lock(self.path), self.assertRaisesRegex(fixture.UsageError, "open block gate"):
                self.adapter.resume_cleanup(runner, state, task, task["progression"])
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertFalse(self.case.progress()["pending"]["effects_started"])

    def test_owner_proved_unsent_recovery_retires_its_unused_brief(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            self.runner(capability).tick()
        state = self.case.owner.state()
        original = self.case.progress()["pending"]
        unused = Path(original["job"]["brief"])
        proof = self.root / "native-no-send-proof.json"
        proof.write_text('{"fixture": "The original startup never existed and no prompt was sent."}\n')
        recovery.reconcile(state["recovery"], state["assignments"], {"dispatch": original["job"]["id"],
            "outcome": "not_sent", "reason": "Private native no-send evidence", "authorization": fixture.owner_fixture.AUTH,
            "evidence": str(proof)}, self.case.now(), None, missing_bootstrap=True)
        save_state(self.path, state)
        with state_lock(self.path):
            authority.reconcile_intent(self.path, {"task": "one", "expected_generation": 1,
                "intent": original["id"], "authorization": fixture.owner_fixture.AUTH}, self.case.now(), self.case.owner.client)
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete", delivery=self.deliver)
            self.assertFalse(unused.exists())
            self.assertFalse(Path(self.case.document["artifact_directory"]).exists())
            self.assertEqual(next(row for row in self.case.owner.state()["recovery"]["dispatches"]
                                  if row["id"] == original["job"]["id"])["status"], "not_sent")

    def test_partial_file_cleanup_resumes_the_same_intent_after_interruption(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            intent_id = self.case.progress()["pending"]["id"]
            assignments = len(self.case.owner.state()["assignments"])
            original = os.unlink
            removed = []
            def interrupted(name, **options):
                if removed:
                    raise SystemExit("Isolated crash after one unlink.")
                original(name, **options)
                removed.append(name)
            with patch.object(workflow_artifacts.os, "unlink", side_effect=interrupted):
                with self.assertRaises(SystemExit):
                    runner.tick()
            pending = self.case.progress()["pending"]
            self.assertEqual(pending["id"], intent_id)
            self.assertTrue(pending["effects_started"])
            self.assertEqual(len(removed), 1)
            restarted = self.runner(capability)
            self.case.advance(restarted, lambda: self.case.progress()["phase"] == "complete")
            self.assertFalse(root.exists())
            self.assertEqual(len(self.case.owner.state()["assignments"]), assignments)
            self.assertEqual(len([row for row in self.case.owner.state()["recovery"]["events"]
                                  if row["kind"] == "task_closed"]), 1)

    def crash_after_quarantine_creation(self, runner):
        original = os.mkdir
        quarantine = Path(self.case.progress()["delivery"]["artifacts"]["quarantine"])
        def interrupted(path, *args, **options):
            original(path, *args, **options)
            if Path(path) == quarantine:
                raise SystemExit("Isolated crash before allocation checkpoint.")
        with patch.object(workflow_artifacts.os, "mkdir", side_effect=interrupted):
            with self.assertRaises(SystemExit):
                runner.tick()
        self.assertIsNone(self.case.progress()["delivery"]["artifacts"]["stage"])
        self.assertTrue(self.case.progress()["pending"]["effects_started"])
        return quarantine

    def test_quarantine_allocation_crash_resumes_the_original_intent(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            intent_id = self.case.progress()["pending"]["id"]
            assignments = len(self.case.owner.state()["assignments"])
            quarantine = self.crash_after_quarantine_creation(runner)
            self.assertEqual(self.case.progress()["pending"]["id"], intent_id)
            restarted = self.runner(capability)
            self.case.advance(restarted, lambda: self.case.progress()["phase"] == "complete")
            self.assertFalse(root.exists())
            self.assertFalse(quarantine.exists())
            self.assertEqual(len(self.case.owner.state()["assignments"]), assignments)

    def test_unrecorded_quarantine_with_foreign_contents_is_preserved(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            quarantine = self.crash_after_quarantine_creation(runner)
            foreign = quarantine / "operator-notes.md"
            foreign.write_bytes(b"Preserve this owner.\n")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(self.runner(capability).tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertEqual(foreign.read_bytes(), b"Preserve this owner.\n")
            self.assertIsNone(self.case.progress()["delivery"]["artifacts"]["stage"])

    def test_shared_unrecorded_quarantine_is_preserved(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            quarantine = self.crash_after_quarantine_creation(runner)
            quarantine.chmod(0o750)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(self.runner(capability).tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertEqual(stat.S_IMODE(quarantine.stat().st_mode), 0o750)

    def test_directory_replacement_during_cleanup_preserves_both_owners(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            runner.tick()
            moved = root.with_name("retained-task-artifacts")
            original = workflow_rename.exclusive
            replaced = []
            def replace_before_move(source, target, *args, **options):
                if source == root and options.get("dst_dir_fd") is not None and not replaced:
                    replaced.append(True)
                    root.rename(moved)
                    root.mkdir(mode=0o700)
                    (root / "operator-notes.md").write_text("A different owner.\n")
                return original(source, target, *args, **options)
            with patch.object(workflow_rename, "exclusive", side_effect=replace_before_move):
                self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in moved.iterdir()}, before)
            quarantine = Path(self.case.progress()["delivery"]["artifacts"]["quarantine"])
            self.assertEqual((quarantine / "task/operator-notes.md").read_text(), "A different owner.\n")

    def test_file_swap_before_quarantine_preserves_the_moved_foreign_inode(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            target = Path(self.case.progress()["pending"]["inputs"][0]["path"]).name
            expected = (root / target).read_bytes()
            original = workflow_rename.exclusive
            replaced = []
            foreign = b"Unrelated bytes arriving after preflight.\n"
            def swap_before_move(source, destination, *args, **options):
                if source == target and options.get("src_dir_fd") is not None and not replaced:
                    replaced.append(True)
                    descriptor = options["src_dir_fd"]
                    os.rename(source, "retained-original.md", src_dir_fd=descriptor, dst_dir_fd=descriptor)
                    file = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=descriptor)
                    with os.fdopen(file, "wb") as stream:
                        stream.write(foreign)
                return original(source, destination, *args, **options)
            with patch.object(workflow_rename, "exclusive", side_effect=swap_before_move):
                self.assertEqual(runner.tick()["data"]["status"], "exception")
            quarantine = Path(self.case.progress()["delivery"]["artifacts"]["quarantine"])
            self.assertEqual((quarantine / "task/retained-original.md").read_bytes(), expected)
            self.assertIn(foreign, [p.read_bytes() for p in quarantine.iterdir() if p.is_file()])

    def test_concurrent_task_destination_preserves_source_and_foreign_directory(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            runner.tick()
            quarantine = Path(self.case.progress()["delivery"]["artifacts"]["quarantine"])
            original = workflow_rename.exclusive
            foreign_inode = []
            def collide(source, target, **options):
                if source == root:
                    (quarantine / "task").mkdir(mode=0o700)
                    foreign_inode.append((quarantine / "task").stat().st_ino)
                return original(source, target, **options)
            with patch.object(workflow_rename, "exclusive", side_effect=collide):
                self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertEqual([(quarantine / "task").stat().st_ino], foreign_inode)

    def test_concurrent_file_destination_preserves_both_files(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            target = Path(self.case.progress()["pending"]["inputs"][0]["path"]).name
            expected = (root / target).read_bytes()
            original = workflow_rename.exclusive
            foreign = b"A different owner's destination.\n"
            destination = []
            def collide(source, slot, **options):
                if source == target and options.get("src_dir_fd") is not None:
                    descriptor = os.open(slot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                                         dir_fd=options["dst_dir_fd"])
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(foreign)
                    destination.append(slot)
                return original(source, slot, **options)
            with patch.object(workflow_rename, "exclusive", side_effect=collide):
                self.assertEqual(runner.tick()["data"]["status"], "exception")
            quarantine = Path(self.case.progress()["delivery"]["artifacts"]["quarantine"])
            self.assertEqual((quarantine / "task" / target).read_bytes(), expected)
            self.assertEqual((quarantine / destination[0]).read_bytes(), foreign)

    def test_concurrent_final_destination_preserves_both_empty_directories(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.at_artifact_cleanup(runner)
            self.case.advance(runner, lambda: self.case.progress()["delivery"]["artifacts"]["phase"] == "retiring"
                and not self.case.progress()["delivery"]["artifacts"]["remaining"]
                and self.case.progress()["pending"] is None)
            quarantine = Path(self.case.progress()["delivery"]["artifacts"]["quarantine"])
            final = Path(str(quarantine) + ".retired")
            runner.tick()
            original = workflow_rename.exclusive
            foreign_inode = []
            def collide(source, destination, **options):
                if source == quarantine:
                    final.mkdir(mode=0o700)
                    foreign_inode.append(final.stat().st_ino)
                return original(source, destination, **options)
            with patch.object(workflow_rename, "exclusive", side_effect=collide):
                self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertTrue(quarantine.is_dir())
            self.assertEqual([final.stat().st_ino], foreign_inode)
            self.assertEqual(list(final.iterdir()), [])

    def test_a_new_owner_at_the_original_path_survives_retirement(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            runner.tick()
            runner.tick()
            root.mkdir(mode=0o700)
            notes = root / "operator-notes.md"
            notes.write_text("Another task owns this new directory.\n")
            supervision.enroll(self.path, {"id": "new-owner", "agent": "elsewhere", "task": "two",
                "report": str(root / "new-report.md"), "pane_id": None, "native_session": None}, self.case.now())
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete")
            self.assertEqual(notes.read_text(), "Another task owns this new directory.\n")
            self.assertTrue(next(row for row in supervision.load(self.path)["members"] if row["id"] == "new-owner")["active"])

    def test_primary_owner_migrates_an_active_delivery_before_resuming(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            root = self.at_artifact_cleanup(runner)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            state = self.case.owner.state()
            delivery = state["recovery"]["tasks"]["one"]["progression"]["delivery"]
            delivery.pop("artifacts")
            delivery["schema_version"] = 1
            save_state(self.path, state)
            original = self.path.read_bytes()
            with self.assertRaisesRegex(StateError, "owner migration"):
                self.case.owner.state()
            self.assertEqual(self.path.read_bytes(), original)
            with state_lock(self.path):
                migrated, usable = load_state_checked(self.path)
            self.assertTrue(usable)
            delivery = migrated["recovery"]["tasks"]["one"]["progression"]["delivery"]
            self.assertEqual(delivery["schema_version"], 2)
            self.assertEqual(delivery["artifacts"]["phase"], "pending")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete")
            self.assertFalse(root.exists())

    def test_migrated_completed_history_preserves_its_existing_directory(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete", delivery=self.deliver)
            root = Path(self.case.document["artifact_directory"])
            root.mkdir(mode=0o700)
            legacy = root / "legacy-history.md"
            legacy.write_text("Prior completed owner history.\n")
            state = self.case.owner.state()
            delivery = state["recovery"]["tasks"]["one"]["progression"]["delivery"]
            delivery.pop("artifacts")
            delivery["schema_version"] = 1
            save_state(self.path, state)
            with state_lock(self.path):
                migrated, usable = load_state_checked(self.path)
            self.assertTrue(usable)
            self.assertEqual(migrated["recovery"]["tasks"]["one"]["progression"]["delivery"]["artifacts"]["phase"], "legacy_preserved")
            self.assertEqual(self.runner(capability).tick()["data"]["status"], "complete")
            self.assertEqual(legacy.read_text(), "Prior completed owner history.\n")

    def test_published_old_reader_refuses_the_new_delivery_lifecycle(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.at_artifact_cleanup(runner)
            # Immutable 0.5.0 compatibility oracle; review with owner-schema changes.
            source = subprocess.check_output(["git", "show",
                "fb4e7c6968b0683e348ade60653df7e432efa6a2:skills/herdr-foreman/foreman/workflow_contract.py"],
                cwd=Path(__file__).resolve().parents[3])
            file = self.root / "published-workflow-contract.py"
            file.write_bytes(source)
            spec = importlib.util.spec_from_file_location("foreman._published_workflow_contract", file)
            assert spec is not None and spec.loader is not None
            old = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(old)
            with self.assertRaisesRegex(fixture.UsageError, "workflow delivery"):
                old.validate_progress(self.case.progress())

    def test_small_cleanup_batches_retain_common_bytes_until_all_briefs_are_checked(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            with patch.object(workflow_artifacts, "BATCH_FILES", 2):
                self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete", delivery=self.deliver)
            self.assertFalse(Path(self.case.document["artifact_directory"]).exists())

    def test_dual_channel_uses_same_source_run_and_confirms_both_independently(self):
        self.case.document["publication"] = {"tessl": {"workspace": "fixture", "plugin": "package"},
                                             "acr": True, "workflow": "publish.yml"}
        self.case.document["effects"].append("publish")
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete", delivery=self.deliver)
            assert self.pr is not None
            delivery = self.case.progress()["delivery"]
            self.assertTrue(delivery["tessl_confirmed"])
            self.assertTrue(delivery["acr_confirmed"])
            self.assertEqual(delivery["publisher_run"], 42)
            self.assertEqual(delivery["tag"], "v0.4.0")
            names = [Path(call[1]).name for call in self.calls if call[0] == "bash"]
            self.assertEqual(names, ["resolve-publish-run.sh", "confirm-tessl-landed.sh",
                                     "verify-moderation-cleared.sh", "verify-github-release.sh"])
            resolution = next(call for call in self.calls if len(call) > 1 and Path(call[1]).name == "resolve-publish-run.sh")
            self.assertEqual(resolution[4:], [self.pr["merge_commit_sha"], "publish.yml", "main"])

    def test_cleanup_fetches_even_when_a_stale_tracking_ref_contains_the_merge(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "cleanup", delivery=self.deliver)
            assert self.pr is not None
            merge = self.pr["merge_commit_sha"]
            remote_head = self.git(self.case.repository, "commit-tree", merge + "^{tree}", "-p", merge,
                                   "-m", "Private fixture later remote default").strip()
            self.git(self.case.repository, "push", "origin", remote_head + ":refs/heads/main")
            self.git(self.case.repository, "update-ref", "refs/remotes/origin/main", merge)
            self.assertEqual(runner.tick()["data"]["status"], "prepared")
            self.assertEqual(self.case.progress()["delivery"]["cleanup_step"], 0)
            self.assertFalse(self.case.progress()["pending"]["effects_started"])
            self.assertEqual(runner.tick()["data"]["status"], "effect_recorded")
            self.assertEqual(self.git(self.case.repository, "rev-parse", "refs/remotes/origin/main").strip(), remote_head)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete")
            self.assertEqual(self.git(self.case.repository, "rev-parse", "HEAD").strip(), remote_head)
            self.assertEqual(len([call for call in self.calls if "fetch" in call]), 1)

    def test_cleanup_preserves_clean_local_commits_ahead_of_the_fetched_default(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "cleanup"
                and self.case.progress()["delivery"]["cleanup_step"] == 1, delivery=self.deliver)
            self.git(self.case.repository, "merge", "--ff-only", "refs/remotes/origin/main")
            source = self.case.repository / "private-local.txt"
            source.write_text("Preserve this private local fixture commit.\n")
            self.git(self.case.repository, "add", "private-local.txt")
            self.git(self.case.repository, "commit", "-m", "Private fixture local contribution")
            head = self.git(self.case.repository, "rev-parse", "HEAD").strip()
            before = len(self.calls)
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.case.progress()["delivery"]["cleanup_step"], 1)
            self.assertEqual(self.git(self.case.repository, "rev-parse", "HEAD").strip(), head)
            self.assertTrue(self.case.worktree.exists())
            self.assertFalse(any("merge" in call for call in self.calls[before:]))

    def publication(self, *, acr=True):
        self.case.document["publication"] = {"tessl": {"workspace": "fixture", "plugin": "package"},
                                             "acr": acr, "workflow": "publish.yml"}
        self.case.document["effects"].append("publish")
        self.case.admit()

    def test_failed_publisher_never_confirms_a_channel(self):
        self.publication()
        self.failed_run = True
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        delivery = self.case.progress()["delivery"]
        self.assertFalse(delivery["accepted"] or delivery["tessl_confirmed"] or delivery["acr_confirmed"])
        self.assertTrue(self.case.worktree.is_dir())

    def test_release_tag_must_resolve_to_this_merge_source(self):
        self.publication()
        self.tag_commit = "f" * 40
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            self.case.advance(runner, lambda: self.case.progress()["delivery"]["tessl_confirmed"])
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertFalse(self.case.progress()["delivery"]["acr_confirmed"])
        self.assertFalse(self.case.progress()["delivery"]["accepted"])
        self.assertTrue(self.case.worktree.is_dir())

    def test_annotated_tag_is_peeled_before_confirming_its_actual_source(self):
        self.publication()
        self.annotated_tag = True
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete", delivery=self.deliver)
        self.assertTrue(self.case.progress()["delivery"]["acr_confirmed"])
        self.assertTrue(any("/git/tags/" in part for call in self.calls for part in call))

    def test_a_gate_recorded_after_release_closure_still_holds_acceptance(self):
        from tests import test_report_gates as gate_fixture
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            report = next(row["assignment"]["report"] for row in supervision.load(self.path)["members"]
                          if row["assignment"]["agent"].startswith("reviewer-"))
            fixture.report_gates.record(self.path, {"schema_version": 2, "agent": "default", "labels": [
                gate_fixture.label(Path(report), gate_fixture.HIGH)], "unannotated": []}, self.case.now())
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertFalse(self.case.progress()["delivery"]["accepted"])
        self.assertTrue(self.case.worktree.is_dir())

    def test_a_hold_after_readback_cannot_race_task_acceptance(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            state = self.case.owner.state()
            task = state["recovery"]["tasks"]["one"]
            observed = self.adapter.observe(runner, state, task, task["progression"])
            self.assertEqual(observed["state"], "published")
            supervision.hold(self.path, {"id": "acceptance-hold", "kind": "waiting_for_user",
                "resume_condition": "Explicit fixture operator resumes", "evidence": [str(self.case.common)],
                "dispositions": []}, self.case.now())
            before = self.path.read_bytes()
            with state_lock(self.path), self.assertRaisesRegex(fixture.UsageError, "operator hold"):
                self.adapter.commit(runner, state, task, task["progression"], observed)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.case.progress()["delivery"]["accepted"])

    def test_moderation_must_name_the_observed_landed_version(self):
        self.publication()
        self.moderation_version = "0.3.9"
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            self.case.advance(runner, lambda: self.case.progress()["delivery"]["tessl_version"] is not None)
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertEqual(self.case.progress()["delivery"]["tessl_version"], self.landed)
        self.assertFalse(self.case.progress()["delivery"]["tessl_confirmed"])

    def test_native_and_independent_observed_versions_must_agree(self):
        self.publication()
        self.report_version = "0.3.9"
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            runner.tick()
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertFalse(self.case.progress()["delivery"]["tessl_confirmed"])
        self.assertFalse(self.case.progress()["delivery"]["accepted"])

    def test_tessl_only_delivery_refuses_an_unselected_acr_tag(self):
        self.publication(acr=False)
        self.report_tag = "v0.4.0"
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "merge", delivery=self.deliver)
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertFalse(self.case.progress()["delivery"]["accepted"])

    def test_release_resolves_project_policy_from_the_admitted_base_checkout(self):
        self.case.admit()
        with self.case.owner.session() as capability, patch.dict(os.environ):
            os.environ.pop("HERDR_CODING_POLICY_ROOT", None)
            runner = self.runner(capability)
            bundle = workflow_release.WorkflowReleaseAdapter._bundle(self.adapter, runner)
        self.assertEqual(bundle, self.case.repository / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        self.assertFalse((self.case.worktree / ".tessl").exists())

    def test_separate_foreign_push_url_prevents_cleanup_effects(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "cleanup", delivery=self.deliver)
            self.git(self.case.repository, "config", "--add", "remote.origin.pushurl", "https://github.com/other/repository.git")
            count = len(self.calls)
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertFalse(any("push" in call or "remove" in call for call in self.calls[count:]))
        self.assertTrue(self.case.worktree.is_dir())
        self.assertEqual(self.case.progress()["delivery"]["cleanup_step"], 0)

    def test_unknown_channel_never_claims_acceptance_or_starts_teardown(self):
        self.case.document["publication"] = {"tessl": {"workspace": "fixture", "plugin": "package"},
                                             "acr": True, "workflow": "publish.yml"}
        self.case.document["effects"].append("publish")
        self.case.admit()
        self.fail_helper = "verify-github-release.sh"
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            self.case.advance(runner, lambda: self.case.progress()["delivery"]["tessl_confirmed"])
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertFalse(self.case.progress()["delivery"]["accepted"])
            self.assertTrue(self.case.progress()["delivery"]["tessl_confirmed"])
            self.assertEqual(self.case.progress()["delivery"]["publisher_run"], 42)
            self.assertTrue(self.case.worktree.is_dir())
            self.assertEqual(self.case.progress()["delivery"]["cleanup_step"], 0)
            self.assertEqual([row for row in self.case.owner.state()["recovery"]["events"] if row["kind"] == "task_closed"], [])
        self.fail_helper = None
        packet = self.case.progress()["exception"]
        with state_lock(self.path):
            workflow_recovery.resume(self.path, {"task": "one", "expected_generation": 1,
                "exception": supervision.digest(packet), "authorization": fixture.owner_fixture.AUTH},
                self.case.now(), self.case.owner.client, fixture.ROOT)
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "complete")
        self.assertEqual(len([call for call in self.calls if len(call) > 1 and Path(call[1]).name == "resolve-publish-run.sh"]), 1)
        self.assertEqual(len([call for call in self.calls if len(call) > 1 and Path(call[1]).name == "confirm-tessl-landed.sh"]), 1)

    def test_malformed_channel_evidence_stays_unaccepted_with_a_bounded_packet(self):
        self.case.document["publication"] = {"tessl": None, "acr": True, "workflow": "publish.yml"}
        self.case.document["effects"].append("publish")
        self.case.admit()
        self.invalid_package = True
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            runner.tick()  # Resolve the one actual source-bound run.
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertEqual(result["data"]["reason"], "release_evidence_unconfirmed")
        self.assertFalse(self.case.progress()["delivery"]["accepted"])
        self.assertFalse(self.case.progress()["delivery"]["acr_confirmed"])
        self.assertTrue(self.case.worktree.is_dir())

    def test_changed_remote_source_cannot_be_confirmed_by_an_old_release_report(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "merge", delivery=self.deliver)
            assert self.pr is not None
            self.pr["head"]["sha"] = "d" * 40
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertTrue(self.case.worktree.is_dir())
            self.assertFalse(self.case.progress()["delivery"]["accepted"])

    def test_merged_is_not_operator_acceptance(self):
        self.case.document["acceptance"]["kind"] = "operator"
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "publish", delivery=self.deliver)
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.case.progress()["exception"]["code"], "actual_acceptance_evidence_required")
            self.assertFalse(self.case.progress()["delivery"]["accepted"])
            self.assertTrue(self.case.worktree.is_dir())

    def cleanup_intent(self, runner, step):
        self.case.advance(runner, lambda: self.case.progress()["phase"] == "cleanup"
            and self.case.progress()["delivery"]["cleanup_step"] == step
            and self.case.progress()["pending"] is not None, delivery=self.deliver)

    def test_cleanup_intent_cannot_execute_substituted_arguments(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.cleanup_intent(runner, 2)
            with state_lock(self.path):
                state = self.case.owner.state()
                state["recovery"]["tasks"]["one"]["progression"]["pending"]["argv"] = ["git", "status"]
                save_state(self.path, state)
            calls = list(self.calls)
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.calls, calls)
            self.assertTrue(self.case.worktree.is_dir())

    def test_new_writer_work_after_preparation_is_preserved(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.cleanup_intent(runner, 2)
            self.case.source.write_text("value = 777\n")
            self.case.git("commit", "-am", "Private operator work after release")
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertTrue(self.case.worktree.is_dir())
            self.assertEqual(self.case.source.read_text(), "value = 777\n")
            self.assertFalse(self.case.progress()["pending"]["effects_started"])

    def test_changed_remote_branch_after_preparation_is_preserved(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.cleanup_intent(runner, 4)
            assert self.pr is not None
            subprocess.run(["git", "--git-dir", str(self.remote), "update-ref", "refs/heads/feature/task", self.pr["merge_commit_sha"]],
                           check=True, capture_output=True)
            before = len([call for call in self.calls if "push" in call])
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(len([call for call in self.calls if "push" in call]), before)
            self.assertIn("refs/heads/feature/task", self.git(self.case.repository, "ls-remote", "--heads", "origin"))

    def test_interrupted_cleanup_uses_actual_absent_target_readback_without_reissue(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.cleanup_intent(runner, 2)
            self.assertEqual(runner.tick()["data"]["status"], "effect_recorded")
            self.assertFalse(self.case.worktree.exists())
            removals = len([call for call in self.calls if "remove" in call])
            runner = self.runner(capability)
            self.assertEqual(runner.tick()["data"]["status"], "advanced")
            self.assertEqual(self.case.progress()["delivery"]["cleanup_step"], 3)
            self.assertEqual(len([call for call in self.calls if "remove" in call]), removals)


    def test_reduced_ready_object_cannot_authorize_release_acceptance(self):
        self.review_transform = lambda snapshot: {field: snapshot[field] for field in
            ("pr_number", "head_sha", "review_bodies", "inline_comment_bodies", "watch")}
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "merge", delivery=self.deliver)
            result = runner.tick()
            self.assertTrue(result["wake_agent"])
            self.assertEqual(self.case.progress()["phase"], "exception")
            self.assertFalse(self.case.progress()["delivery"]["accepted"])
            self.assertTrue(self.case.worktree.exists())


class ReviewIdentityTest(unittest.TestCase):
    def test_premerge_receipt_needs_complete_consistent_canonical_fields(self):
        snapshot = fixture.ready_snapshot("a" * 40)
        self.assertEqual(workflow_review.premerge_evidence(snapshot), workflow_review.identity(snapshot))
        snapshot["reviews"]["copilot"]["state"] = "CHANGES_REQUESTED"
        snapshot["review_bodies"][1]["state"] = "CHANGES_REQUESTED"
        self.assertEqual(workflow_review.premerge_evidence(snapshot), workflow_review.identity(snapshot))
        cases = []
        for field in ("ci", "reviews", "merge_state", "inline_comments"):
            value = deepcopy(snapshot)
            del value[field]
            cases.append(value)
        for field in ("attempts", "elapsed_seconds"):
            value = deepcopy(snapshot)
            del value["watch"][field]
            cases.append(value)
        for path, replacement in ((["ci", "status"], "pending"),
                (["reviews", "codex", "state"], "CHANGES_REQUESTED"),
                (["reviews", "codex", "state"], []),
                (["reviews", "codex", "commit_id"], "b" * 40),
                (["reviews", "codex", "stale"], True),
                (["reviews", "copilot", "requested"], True),
                (["merge_state", "mergeable"], "CONFLICTING"),
                (["watch", "attempts"], 0), (["watch", "elapsed_seconds"], True)):
            value = deepcopy(snapshot)
            target = value
            for field in path[:-1]:
                target = target[field]
            target[path[-1]] = replacement
            cases.append(value)
        for field in ("review_bodies", "inline_comment_bodies"):
            value = deepcopy(snapshot)
            del value[field][0]["html_url"]
            cases.append(value)
        for number, value in enumerate(cases):
            with self.subTest(case=number), self.assertRaises(fixture.UsageError):
                workflow_review.premerge_evidence(value)

    def test_all_authors_and_inlines_bind_reading_but_watcher_timing_does_not(self):
        snapshot = {"pr_number": 1, "head_sha": "a" * 40, "review_bodies": [
            {"id": 1, "body": "Policy body", "author": "policy", "state": "APPROVED"},
            {"id": 2, "body": "Commented review with no inlines", "author": "other", "state": "COMMENTED"}],
            "inline_comment_bodies": [{"id": 3, "body": "Advisory", "author": "copilot"}],
            "watch": {"result": "ready", "attempts": 1}}
        expected = workflow_review.identity(snapshot)
        snapshot["watch"]["attempts"] = 100
        snapshot["review_bodies"].reverse()
        self.assertEqual(workflow_review.identity(snapshot), expected)
        for field in ("review_bodies", "inline_comment_bodies"):
            changed = deepcopy(snapshot)
            changed[field][0]["body"] += " edited"
            self.assertNotEqual(workflow_review.identity(changed)["sha256"], expected["sha256"])
        for field in ("review_bodies", "inline_comment_bodies"):
            changed = deepcopy(snapshot)
            changed[field][0]["author"] = "another-reviewer"
            self.assertNotEqual(workflow_review.identity(changed)["sha256"], expected["sha256"])
        changed = deepcopy(snapshot)
        changed["review_bodies"][0]["state"] = "DISMISSED"
        self.assertNotEqual(workflow_review.identity(changed)["sha256"], expected["sha256"])


if __name__ == "__main__":
    unittest.main()
