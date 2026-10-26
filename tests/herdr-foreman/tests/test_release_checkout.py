"""Owned Git/native lifecycle fixtures; no live factory or publication effects.

The local bare remote replaces network transport only. Native launch/report
transport is the existing controlled fixture; actual Git, owner leases,
contracts, report receipts, generation fencing and release cleanliness run.
Unknown setup and private files stay in their original checkout byte-for-byte.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import io
import json
import os
import stat
import subprocess
import unittest
from unittest.mock import patch

from tests import test_workflow_service as fixture
from tests import test_workflow_adoption as adoption_fixture
from tests.test_members import ledger_text
from foreman import cli, progression_owner as authority, provision, recovery, release_checkout, supervision
from foreman.errors import ForemanError, StateError, UsageError
from foreman.state import load_state_checked, save_state, state_lock


class ReleaseCheckoutTest(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowServiceTest()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.setup_repo(self.case)

    def setup_repo(self, case):
        self.case = case
        activation = patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", True)
        activation.start()
        self.addCleanup(activation.stop)
        with state_lock(case.path):
            load_state_checked(case.path)
        self.root, self.path = self.case.root, self.case.path
        self.source, self.target = self.case.worktree, self.root / "release"
        self.env = patch.dict(os.environ, {"WORKTREE_ROOT": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.remote = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        self.case.git("push", str(self.remote), "main")
        # Keep the admitted literal GitHub origin. Only network I/O goes to
        # the fixture's real bare repository, preserving all Git ref checks.
        original = release_checkout.git
        def local_network(path, *args):
            if args == ("fetch", "--quiet", "origin"):
                return original(path, "fetch", "--quiet", str(self.remote),
                                "+refs/heads/*:refs/remotes/origin/*")
            if args[:3] == ("ls-remote", "--heads", "origin"):
                return original(path, "ls-remote", "--heads", str(self.remote), *args[3:])
            return original(path, *args)
        transport = patch.object(release_checkout, "git", side_effect=local_network)
        transport.start()
        self.addCleanup(transport.stop)
        self.case.git("fetch", str(self.remote), "+refs/heads/*:refs/remotes/origin/*")
        self.original = provision.record(self.source, "feature/task", "origin/main", self.case.base,
                                         "origin/main", self.case.base)
        self.original_bytes = provision.receipt_path(self.source).read_bytes()
        self.ledger = self.root / "TASK-LEDGER.md"

    def verified(self, *, legacy=False, complex_work=False):
        self.case.admit(complex_work=complex_work)
        with self.case.owner.session() as capability:
            runner = self.case.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "release", delivery=self.case.deliver)
        self.head = self.case.git("rev-parse", "HEAD").strip()
        self.case.git("push", str(self.remote), "feature/task")
        if legacy:
            data = {"task": "one", "expected_generation": 1, "authorization": fixture.owner_fixture.AUTH}
            with state_lock(self.path):
                authority.handoff(self.path, data, self.case.now(), self.case.owner.client, fixture.ROOT, returning=True)
            event = {"schema_version": 1, "id": "ready", "at": self.case.now(), "subject": "task",
                     "dispatch_id": "not_applicable", "worker": "not_applicable", "role": "not_applicable",
                     "report": "unknown", "observed": "Original independent current-tip verification",
                     "decision": "ready_for_release", "head_revision": self.head,
                     "evidence": "Original closed developer and independent verifier reports",
                     "assessment": "All selected independent responsibilities approved this exact pushed head"}
            self.ledger.write_text(ledger_text("one", [event], self.path, base=self.case.base))

    def local_files(self):
        values = {"AGENTS.md": b"Private runtime setup; creator is not inferred.\n",
                  ".codex/skills/.gitignore": b"private runtime cache\n",
                  "config.toml": b"private_setting = true\n", "private-notes.txt": b"Do not discard.\n"}
        for relative, body in values.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return values

    def prepare(self, *, via_cli=False):
        if via_cli:
            out, err = io.StringIO(), io.StringIO()
            arguments = ["prepare-release-checkout", "--state", str(self.path), "--task", "one",
                "--source", str(self.source), "--target", str(self.target), "--head", self.head,
                "--now", self.case.now()]
            if self.ledger.exists():
                arguments.extend(["--ledger", str(self.ledger)])
            code = cli.main(arguments, stdout=out, stderr=err, client=self.case.owner.client)
            self.assertEqual(code, 0, err.getvalue())
            return json.loads(out.getvalue())
        return release_checkout.prepare(self.path, "one", self.source, self.target, self.head,
            str(self.ledger) if self.ledger.exists() else None, self.case.now(), self.case.owner.client, fixture.ROOT)

    def leftovers(self, root):
        policy = Path(os.environ["HERDR_CODING_POLICY_ROOT"])
        result = subprocess.run(["bash", str(policy / "skills/release/check-leftovers.sh"),
            "--repo", str(root), "--release"], text=True, capture_output=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def assert_preserved(self, values):
        for relative, body in values.items():
            self.assertEqual((self.source / relative).read_bytes(), body)
        self.assertEqual(provision.receipt_path(self.source).read_bytes(), self.original_bytes)
        self.assertEqual(provision.git(self.source, "rev-parse", "HEAD"), self.head)
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "")

    def test_legacy_provision_setup_verify_release_gate_preserves_unknown_files(self):
        self.verified(legacy=True)
        values = self.local_files()
        before = self.case.owner.state()
        self.assertEqual(self.leftovers(self.source)[0], 1)
        result = self.prepare(via_cli=True)
        self.assertFalse(result["authorizes_release"])
        self.assertEqual(self.case.owner.state(), before)
        self.assert_preserved(values)
        self.assertEqual(provision.read(self.target), {**self.original, "path": str(self.target)})
        self.assertEqual(provision.git(self.target, "rev-parse", "HEAD"), self.head)
        code, gate = self.leftovers(self.target)
        self.assertEqual(code, 0, gate)
        retained = next(row for row in gate["others"] if row["path"] == str(self.source))
        self.assertEqual(retained["verdict"], "in_progress")
        with self.ledger.open("a") as stream:
            stream.write("\nRetained ledger history may append after the original ready evidence.\n")
        self.prepare()
        (self.target / "unrelated-private.txt").write_text("Unrelated work is never disposable.\n")
        self.assertEqual(self.leftovers(self.target)[0], 1)
        self.assertTrue((self.target / "unrelated-private.txt").is_file())
        with self.assertRaises(ForemanError):
            self.prepare()
        failed_remove = subprocess.run(["git", "-C", str(self.case.repository), "worktree", "remove", str(self.source)],
                                       capture_output=True, check=False)
        self.assertNotEqual(failed_remove.returncode, 0)
        self.assert_preserved(values)

    def test_native_rebind_preserves_project_only_bootstrap_and_clean_business_checkout(self):
        self.verified()
        values = self.local_files()
        project = {".tessl/RULES.md": b"Project-only Tessl policy fixture.\n",
                   "agents.yaml": b"Project-only ACR declaration fixture.\n",
                   ".codex/config.toml": b"project_only = true\n"}
        for relative, body in project.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        values.update(project)
        with self.case.owner.session() as capability:
            failure = self.case.runner(capability).tick()
        self.assertEqual(failure["data"]["exception"]["code"], "workflow_owner_refused")
        before = self.case.owner.state()
        result = self.prepare(via_cli=True)
        self.assertEqual(result["generation"], 2)
        self.assertFalse(result["exception_preserved"])
        after = self.case.owner.state()
        old, new = before["recovery"]["tasks"]["one"], after["recovery"]["tasks"]["one"]
        self.assertEqual(new["progression"]["phase"], "release")
        for key in ("jobs", "head", "round", "delivery", "publication_baseline", "blockers"):
            self.assertEqual(new["progression"][key], old["progression"][key])
        for key in ("assignments", "specialist_assessments"):
            self.assertEqual(after[key], before[key])
        for key in ("dispatches", "reports", "diagnoses", "correction_grants", "approach_grants"):
            if key in before["recovery"]:
                self.assertEqual(after["recovery"][key], before["recovery"][key])
        self.assertEqual(after["recovery"]["tasks"]["two"], before["recovery"]["tasks"]["two"])
        self.assert_preserved(values)
        self.assertEqual(self.leftovers(self.target)[0], 0)
        saved = deepcopy(after)
        self.assertEqual(self.prepare()["generation"], 2)
        self.assertEqual(self.case.owner.state(), saved)
        self.case.worktree = self.target
        self.case.document = json.loads(Path(new["authority"]["contract"]["path"]).read_text())
        locations = []
        original_start = self.case.native.workspace_create
        def setup(**options):
            root = Path(options["cwd"])
            locations.append(root)
            self.assertEqual(root, self.source)
            for relative, body in project.items():
                self.assertEqual((root / relative).read_bytes(), body)
                self.assertFalse((self.target / relative).exists())
            # Model ordinary provider setup without reclassifying or replacing
            # pre-existing user files. Its project remains the retained source.
            (root / "native-setup-created.txt").write_text("Private fixture startup.\n")
            return original_start(**options)
        with patch.object(self.case.native, "workspace_create", side_effect=setup), self.case.owner.session(generation=2) as capability:
            runner = self.case.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "merge", delivery=self.case.deliver)
        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0], self.source)
        self.assertFalse(Path(str(self.path) + ".release-runtime").exists())
        self.assertEqual(self.leftovers(self.target)[0], 0)
        self.assertEqual([row["role"] for row in self.case.owner.state()["assignments"]], ["developer", "reviewer", "release"])
        self.assert_preserved(values)

    def test_prepared_target_is_recoverable_after_git_add_before_receipts(self):
        self.verified(legacy=True)
        values = self.local_files()
        original = provision.record
        with patch.object(provision, "record", side_effect=UsageError("Fixture storage interruption; keep both checkouts.", {})):
            with self.assertRaisesRegex(UsageError, "storage interruption"):
                self.prepare()
        self.assertTrue(self.target.is_dir())
        self.assertFalse(provision.receipt_path(self.target).exists())
        with patch.object(provision, "record", side_effect=original), patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", False):
            self.prepare()
        self.assertEqual(self.leftovers(self.target)[0], 0)
        self.assert_preserved(values)

    def test_changed_remote_unverified_head_and_tracked_changes_refuse_without_detach(self):
        self.verified(legacy=True)
        self.local_files()
        original_head = self.head
        self.head = self.case.base
        with self.assertRaisesRegex(UsageError, "freshly fetched remote"):
            self.prepare()
        self.head = original_head
        self.case.source.write_text("uncommitted = True\n")
        with self.assertRaisesRegex(UsageError, "staged or unstaged"):
            self.prepare()
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")
        self.assertFalse(self.target.exists())

    def test_deleted_remote_branch_cannot_reuse_its_stale_tracking_head(self):
        self.verified(legacy=True)
        values = self.local_files()
        self.case.git("fetch", str(self.remote), "+refs/heads/*:refs/remotes/origin/*")
        self.case.git("config", "fetch.prune", "false")
        self.case.git("config", "remote.origin.prune", "false")
        self.assertEqual(self.case.git("rev-parse", "refs/remotes/origin/feature/task").strip(), self.head)
        self.case.git("push", str(self.remote), "--delete", "feature/task")
        with self.assertRaisesRegex(UsageError, "freshly fetched remote"):
            self.prepare()
        self.assertEqual(self.case.git("rev-parse", "refs/remotes/origin/feature/task").strip(), self.head)
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")
        self.assertFalse(self.target.exists())
        for relative, body in values.items():
            self.assertEqual((self.source / relative).read_bytes(), body)

    def test_existing_armed_native_rebind_replays_with_new_writes_disabled(self):
        self.verified()
        values = self.local_files()
        with patch("foreman.release_rebind.save_state", side_effect=StateError("Fixture primary write failed; preserve the intent.", {})):
            with self.assertRaisesRegex(StateError, "primary write failed"):
                self.prepare()
        self.assertEqual(self.case.owner.state()["recovery"]["tasks"]["one"]["authority"]["generation"], 1)
        with patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", False):
            self.assertEqual(self.prepare()["generation"], 2)
        self.assert_preserved(values)

    def test_fresh_native_release_keeps_existing_cwd_without_runtime_store(self):
        self.verified()
        before = self.path.read_bytes()
        with patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", False):
            self.assertEqual(release_checkout.native_cwd(self.path, "one", str(self.source)), str(self.source))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(str(self.path) + ".release-runtime").exists())

    def test_shared_metadata_modes_refuse_reads_and_republication_without_changes(self):
        self.verified(legacy=True)
        self.local_files()
        result = self.prepare()
        intent = Path(result["intent"])
        paths = (intent, release_checkout.receipt_path(self.target), Path(str(intent) + ".ready"))
        for path in paths:
            body = path.read_bytes()
            value = json.loads(body)
            for mode in (0o644, 0o666):
                with self.subTest(path=path.name, mode=oct(mode)):
                    path.chmod(mode)
                    if path != paths[-1]:
                        with self.assertRaises(ForemanError) as refused:
                            release_checkout._read(path)
                        self.assertEqual(refused.exception.details["reason"], "release_checkout_evidence_unsafe")
                    with self.assertRaises(ForemanError) as refused:
                        release_checkout._publish(path, value)
                    self.assertEqual(refused.exception.details["reason"], "release_checkout_evidence_unsafe")
                    self.assertEqual(path.read_bytes(), body)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
            path.chmod(0o600)  # Restore only this controlled fixture's metadata.

    def test_ordinary_contract_and_provision_modes_keep_compatibility(self):
        provision.receipt_path(self.source).chmod(0o644)
        self.case.common.chmod(0o644)
        for captured in self.case.document["briefs"].values():
            Path(captured["path"]).chmod(0o644)
        self.verified()
        self.local_files()
        self.prepare()
        task = self.case.owner.state()["recovery"]["tasks"]["one"]
        path = Path(task["authority"]["contract"]["path"])
        body = path.read_bytes()
        path.chmod(0o644)
        release_checkout._publish(path, json.loads(body), metadata=False)
        self.assertEqual(path.read_bytes(), body)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(provision.receipt_path(self.source).stat().st_mode), 0o644)

    def test_live_lease_and_pending_effect_preserve_source(self):
        self.verified()
        self.local_files()
        with self.case.owner.session(), self.assertRaisesRegex(ForemanError, "Another progression"):
            self.prepare()
        self.assertFalse(list((self.case.repository / ".git").glob("foreman-release-*")))
        state = self.case.owner.state()
        recovery.reserve(state["recovery"], {"id": "unknown-send", "fingerprint": "c" * 64,
            "task": "one", "role": "developer", "agent": "unknown-worker", "fix_round": None,
            "plan": None, "work": None}, self.case.now())
        save_state(self.path, state)
        with self.assertRaisesRegex(UsageError, "pending sends"):
            self.prepare()
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")
        self.assertFalse(self.target.exists())

    def test_foreign_or_existing_target_never_becomes_disposable(self):
        self.verified(legacy=True)
        self.local_files()
        self.target.mkdir()
        private = self.target / "private.txt"
        private.write_bytes(b"Keep unknown existing target.\n")
        with self.assertRaisesRegex(UsageError, "already exists"):
            self.prepare()
        self.assertEqual(private.read_bytes(), b"Keep unknown existing target.\n")
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")

    def test_wrong_native_owner_preserves_original_source(self):
        self.verified()
        self.local_files()
        self.case.owner.native["value"] = "unrelated-session"
        with self.assertRaisesRegex(UsageError, "differs"):
            self.prepare()
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")
        self.assertFalse(self.target.exists())

    def test_operator_hold_and_changed_verifier_report_are_not_checkout_waivers(self):
        self.verified()
        self.local_files()
        reviewer = self.case.progress()["jobs"]["reviewer"]
        member = next(row for row in supervision.load(self.path)["members"] if row["id"] == reviewer)
        report = Path(member["assignment"]["report"])
        with report.open("a") as stream:
            stream.write("\nUnreviewed changed evidence.\n")
        with self.assertRaisesRegex(UsageError, "byte-bound"):
            self.prepare()
        supervision.hold(self.path, {"id": "operator-hold", "kind": "waiting_for_user",
            "resume_condition": "The operator explicitly resumes this hold", "evidence": [str(self.case.common)],
            "dispositions": []}, self.case.now())
        held = supervision.store_path(self.path).read_bytes()
        with self.assertRaisesRegex(UsageError, "operator hold"):
            self.prepare()
        self.assertEqual(supervision.store_path(self.path).read_bytes(), held)
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")
        self.assertFalse(self.target.exists())

    def test_independent_admitted_writer_with_unknown_send_does_not_block_this_handoff(self):
        self.verified()
        values = self.local_files()
        other = self.root / "other-writer"
        self.case.git("worktree", "add", "-b", "feature/other", str(other), "main")
        document = deepcopy(self.case.document)
        document.update(task="two", artifact_directory=str(self.root / "other-current"))
        document["repository"].update(worktree=str(other), branch="feature/other")
        contract = self.root / "other-contract.json"
        contract.write_text(json.dumps(document))
        state = self.case.owner.state()
        state["recovery"]["tasks"]["two"]["base_revision"] = self.case.base
        save_state(self.path, state)
        data = {**self.case.owner.data, "task": "two", "service_id": "other-service",
                "contract": str(contract), "lease_path": str(self.root / "other.lease")}
        with state_lock(self.path):
            authority.handoff(self.path, data, self.case.now(), self.case.owner.client, fixture.ROOT)
        state = self.case.owner.state()
        recovery.reserve(state["recovery"], {"id": "other-unknown-send", "fingerprint": "d" * 64,
            "task": "two", "role": "developer", "agent": "other-worker", "fix_round": None,
            "plan": None, "work": None}, self.case.now())
        save_state(self.path, state)
        expected = deepcopy(state["recovery"]["tasks"]["two"])
        with authority.service_session(self.path, "two", 1, "other-service", fixture.ROOT):
            self.prepare()
        actual = self.case.owner.state()
        self.assertEqual(actual["recovery"]["tasks"]["two"], expected)
        self.assertEqual(actual["recovery"]["dispatches"][-1], state["recovery"]["dispatches"][-1])
        self.assert_preserved(values)

    def test_unattributed_pending_writer_scope_remains_explicitly_unknown(self):
        self.verified()
        self.local_files()
        state = self.case.owner.state()
        recovery.reserve(state["recovery"], {"id": "unscoped-send", "fingerprint": "e" * 64,
            "task": "two", "role": "developer", "agent": "unscoped-worker", "fix_round": None,
            "plan": None, "work": None}, self.case.now())
        save_state(self.path, state)
        with self.assertRaisesRegex(UsageError, "pending writer") as refusal:
            self.prepare()
        self.assertEqual(refusal.exception.details["reason"], "release_checkout_writer_scope_unknown")
        self.assertEqual(self.case.owner.state(), state)
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")
        self.assertFalse(self.target.exists())

    def admit_other_writer(self, *, shared):
        other = self.source if shared else self.root / "late-other-writer"
        if not shared:
            self.case.git("worktree", "add", "-b", "feature/late-other", str(other), "main")
        document = deepcopy(self.case.document)
        document.update(task="two", artifact_directory=str(self.root / "late-other-current"))
        document["repository"].update(worktree=str(other), branch="feature/task" if shared else "feature/late-other")
        contract = self.root / "late-other-contract.json"
        contract.write_text(json.dumps(document))
        state = self.case.owner.state()
        state["recovery"]["tasks"]["two"]["base_revision"] = self.case.base
        save_state(self.path, state)
        data = {**self.case.owner.data, "task": "two", "service_id": "late-other-service",
                "contract": str(contract), "lease_path": str(self.root / "late-other.lease")}
        with state_lock(self.path):
            authority.handoff(self.path, data, self.case.now(), self.case.owner.client, fixture.ROOT)

    def late_writer(self, *, shared):
        self.admit_other_writer(shared=shared)
        self.verified()
        values = self.local_files()
        original = release_checkout.git
        injected = []
        def git(root, *arguments):
            if Path(root) == self.target and arguments == ("fetch", "--quiet", "origin") and not injected:
                with state_lock(self.path):
                    state = self.case.owner.state()
                    recovery.reserve(state["recovery"], {"id": "late-other-send", "fingerprint": "9" * 64,
                        "task": "two", "role": "developer", "agent": "late-other-worker", "fix_round": None,
                        "plan": None, "work": None}, self.case.now())
                    save_state(self.path, state)
                    injected.append(deepcopy(state["recovery"]["dispatches"][-1]))
            return original(root, *arguments)
        with patch.object(release_checkout, "git", side_effect=git):
            if shared:
                with self.assertRaisesRegex(UsageError, "Another task"):
                    self.prepare()
            else:
                self.prepare()
        self.assertEqual(len(injected), 1)
        actual = self.case.owner.state()
        self.assertEqual(next(row for row in actual["recovery"]["dispatches"] if row["id"] == "late-other-send"), injected[0])
        self.assertEqual(actual["recovery"]["tasks"]["one"]["authority"]["generation"], 1 if shared else 2)
        from foreman import release_flight
        self.assertEqual(release_flight.locator_path(self.path, "one").exists(), shared)
        self.assert_preserved(values)

    def test_new_pending_writer_on_same_source_refuses_fresh_commit_and_retains_flight(self):
        self.late_writer(shared=True)

    def test_new_independent_pending_writer_is_preserved_by_fresh_commit(self):
        self.late_writer(shared=False)

    def test_new_legacy_handoff_stays_staged_before_any_intent_or_git_effect(self):
        self.verified(legacy=True)
        values = self.local_files()
        with patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", False), self.assertRaisesRegex(UsageError, "staged"):
            self.prepare()
        self.assertFalse(self.target.exists())
        self.assertFalse(list((self.case.repository / ".git").glob("foreman-release-*")))
        self.assertEqual(provision.git(self.source, "branch", "--show-current"), "feature/task")
        for path, body in values.items():
            self.assertEqual((self.source / path).read_bytes(), body)

    def test_actual_git_and_native_boundaries_allow_independent_checkpoints(self):
        self.verified(legacy=True)
        values = self.local_files()
        checkpoints = []
        code = """import json, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from foreman import progression_owner, recovery, release_flight, supervision
from foreman.errors import UsageError
from foreman.state import load_state_checked, save_state, state_lock
path, identifier, at = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
with state_lock(path):
    state, usable = load_state_checked(path, persist_migration=False)
    assert usable
    locator = release_flight.locator_path(path, 'one')
    if locator.exists():
        try:
            progression_owner.require_command(path, SimpleNamespace(command='apply', task='one'))
        except UsageError as exc:
            assert exc.details['reason'] == 'release_checkout_pending'
        else:
            raise AssertionError('A same-task effect crossed the armed handoff')
    recovery.register_task(state['recovery'], {'task': identifier, 'base_revision': 'a' * 40,
        'scope': 'Independent fixture native checkpoint', 'allowed_paths': ['src/*'],
        'authorization': {'source': 'private fixture', 'quote': 'This fixture checkpoint only'}}, at)
    recovery.reserve(state['recovery'], {'id': identifier, 'fingerprint': 'd' * 64,
        'task': identifier, 'role': 'reviewer', 'agent': identifier, 'fix_round': None,
        'plan': None, 'work': None}, at)
    recovery.observe_reserved(state['recovery'], identifier, {'fixture_checkpoint': identifier})
    save_state(path, state)
    supervision.transaction(path, lambda current: supervision.append_event(current, at, None,
        'checkpoint', {'fixture_checkpoint': identifier, 'observation_only': True}))
"""
        def checkpoint(boundary):
            identifier = "independent-checkpoint-{}".format(len(checkpoints))
            result = subprocess.run([sys.executable, "-B", "-c", code,
                str(fixture.ROOT / "skills/herdr-foreman"), str(self.path), identifier, self.case.now()],
                capture_output=True, text=True, timeout=3, check=False)
            self.assertEqual(result.returncode, 0, boundary + ": " + result.stderr)
            checkpoints.append(identifier)
        original_git = release_checkout.git
        def git(root, *arguments):
            if arguments[:1] in (("fetch",), ("worktree",), ("switch",)):
                checkpoint("Git " + arguments[0])
            return original_git(root, *arguments)
        original_pane = self.case.owner.client.pane_get
        def pane_get(pane):
            checkpoint("native identity")
            return original_pane(pane)
        with patch.object(release_checkout, "git", side_effect=git), patch.object(self.case.owner.client, "pane_get", side_effect=pane_get):
            self.prepare(via_cli=True)
        actual = self.case.owner.state()
        self.assertGreaterEqual(len(checkpoints), 5)
        for identifier in checkpoints:
            self.assertIn(identifier, actual["recovery"]["tasks"])
            row = next(row for row in actual["recovery"]["dispatches"] if row["id"] == identifier)
            self.assertEqual(row["observed_before"], {"fixture_checkpoint": identifier})
        events = supervision.load(self.path)["events"]
        self.assertEqual({row["data"].get("fixture_checkpoint") for row in events if row["kind"] == "checkpoint"}, set(checkpoints))
        self.assert_preserved(values)
        self.assertEqual(self.leftovers(self.target)[0], 0)


class AdoptedReleaseCheckoutTest(unittest.TestCase):
    def setUp(self):
        self.adoption = adoption_fixture.WorkflowAdoptionTest()
        self.adoption.setUp()
        self.addCleanup(self.adoption.doCleanups)
        self.helper = ReleaseCheckoutTest()
        self.helper.setup_repo(self.adoption.fx)
        self.addCleanup(self.helper.doCleanups)
        self.case = self.adoption.fx
        self.adoption.prepare()
        self.adoption.admit()
        with self.case.owner.session() as capability:
            runner = self.case.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "release", delivery=self.case.deliver)
        self.helper.head = self.case.git("rev-parse", "HEAD").strip()
        self.case.git("push", str(self.helper.remote), "feature/task")
        self.values = self.helper.local_files()

    def test_adopted_handoff_retains_original_transfer_and_launches_native_release(self):
        with self.case.owner.session() as capability:
            failure = self.case.runner(capability).tick()
        self.assertEqual(failure["data"]["exception"]["code"], "workflow_owner_refused")
        before = self.case.owner.state()
        original = deepcopy(self.case.document["adoption"])
        with patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", False), self.assertRaisesRegex(UsageError, "staged"):
            self.helper.prepare()
        self.assertFalse(self.helper.target.exists())
        with patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", True):
            result = self.helper.prepare()
        self.assertEqual(result["generation"], 2)
        new = self.case.owner.state()["recovery"]["tasks"]["one"]
        self.case.document = json.loads(Path(new["authority"]["contract"]["path"]).read_text())
        self.assertEqual(self.case.document["adoption"], original)
        self.assertEqual(new["authority"]["schema_version"], 3)
        self.assertEqual(new["progression"]["jobs"], before["recovery"]["tasks"]["one"]["progression"]["jobs"])
        self.assertEqual(new["progression"]["round"], before["recovery"]["tasks"]["one"]["progression"]["round"])
        self.helper.assert_preserved(self.values)
        self.case.worktree = self.helper.target
        # Reader mode can execute/replay already owned handoffs. It cannot
        # create a fresh adopted interpretation before shared activation.
        with patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", False), self.case.owner.session(generation=2) as capability:
            runner = self.case.runner(capability)
            self.case.advance(runner, lambda: self.case.progress()["phase"] == "merge", delivery=self.case.deliver)
        after = self.case.owner.state()
        self.assertEqual(after["assignments"][:2], before["assignments"])
        self.assertEqual([row["role"] for row in after["assignments"]], ["developer", "reviewer", "release"])
        self.assertNotIn("WORKFLOW:", self.adoption.report.read_text())
        self.assertEqual(self.helper.leftovers(self.helper.target)[0], 0)
        self.helper.assert_preserved(self.values)

    def test_unrelated_receipt_stale_generation_and_unknown_version_never_bridge_source_scope(self):
        from foreman import workflow_adoption
        with patch("foreman.release_activation.NEW_OWNER_WRITES_ENABLED", True):
            self.helper.prepare()
        state = self.case.owner.state()
        task = state["recovery"]["tasks"]["one"]
        document = json.loads(Path(task["authority"]["contract"]["path"]).read_text())
        source = next(row for row in state["recovery"]["dispatches"] if row["id"] == document["adoption"]["dispatch"])
        # The old strict source-scope call has no bridge and fails closed.
        with self.assertRaisesRegex(UsageError, "original source brief"):
            workflow_adoption.source_scope(document, source)
        stale = deepcopy(state)
        stale["recovery"]["tasks"]["one"]["authority"]["generation"] += 1
        stale["recovery"]["tasks"]["one"]["progression"]["generation"] += 1
        with self.assertRaisesRegex(UsageError, "current grant generation"):
            release_checkout.original_scope(document, self.case.path, stale)
        other = self.case.root / "equivalent-branch"
        self.case.git("worktree", "add", "-b", "feature/equivalent", str(other), self.helper.head)
        location = release_checkout.receipt_path(self.helper.target)
        original = location.read_bytes()
        other_receipt = release_checkout.receipt_path(other)
        other_receipt.write_bytes(original)
        other_receipt.chmod(0o600)
        unrelated = deepcopy(document)
        unrelated["repository"].update(worktree=str(other), branch="feature/equivalent")
        with self.assertRaisesRegex(UsageError, "exact task and owner"):
            release_checkout.original_scope(unrelated, self.case.path, state)
        unknown = json.loads(original)
        unknown["schema_version"] = 2
        preserved = json.dumps(unknown).encode()
        location.write_bytes(preserved)
        with self.assertRaisesRegex(UsageError, "supported complete"):
            release_checkout.original_scope(document, self.case.path, state)
        self.assertEqual(location.read_bytes(), preserved)
        self.assertEqual(self.case.owner.state(), state)
        self.helper.assert_preserved(self.values)


if __name__ == "__main__":
    unittest.main()
