#!/usr/bin/env python3
"""Exercise CI reuse at the GitHub/artifact/runtime trust boundary."""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("ci_runtime_gate", ROOT / "scripts/ci-runtime-gate.py")
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
HEAD, MERGE, CHECKOUT, TREE = (character * 40 for character in "abcd")


class FixtureAPI:
    def __init__(self):
        self.current = {"tree": TREE, "runner": {"ImageVersion": "20261019.1"},
                        "tools": {"python3": {"version": "3.14.0", "sha256": "tool"}},
                        "environment": {"LANG": "C.UTF-8"}, "baseline_sha256": "policy"}
        self.run = {"id": 17, "run_attempt": 2, "event": "pull_request", "status": "completed",
                    "conclusion": "success", "head_sha": HEAD, "repository": {"id": 99},
                    "head_repository": {"id": 99}, "workflow_id": 13, "path": GATE.WORKFLOW}
        self.pull = {"number": 79, "merged_at": "2026-10-25T00:00:00Z", "merge_commit_sha": MERGE,
                     "base": {"ref": "main", "repo": {"id": 99}},
                     "head": {"sha": HEAD, "repo": {"id": 99, "full_name": "owner/repo"}}}
        self.record = {"schema_version": 1, "fingerprint": copy.deepcopy(self.current),
                       "provenance": {"repository": "owner/repo", "repository_id": 99,
                           "workflow_path": GATE.WORKFLOW, "event": "pull_request", "pull_request": 79,
                           "run_id": 17, "run_attempt": 2, "head_sha": HEAD, "checkout_commit": CHECKOUT},
                       "result": {"suites": 3, "passed": 3, "failed": 0}, "runtime_seconds": 716.0}
        self.artifact = {"id": 23, "name": "runtime-evidence-17-2", "expired": False,
                         "workflow_run": {"id": 17, "repository_id": 99,
                                          "head_repository_id": 99, "head_sha": HEAD}}
        self.metadata = {
            "commits/{}/pulls?per_page=100".format(MERGE): [self.pull],
            "actions/workflows/tests.yml": {"id": 13, "path": GATE.WORKFLOW, "state": "active"},
            "actions/workflows/13/runs?head_sha={}&event=pull_request&per_page=100".format(HEAD):
                {"total_count": 1, "workflow_runs": [self.run]},
            "actions/runs/17/artifacts?per_page=100": {"total_count": 1, "artifacts": [self.artifact]},
            "git/commits/" + HEAD: {"sha": HEAD, "tree": {"sha": TREE}},
            "git/commits/" + CHECKOUT: {"sha": CHECKOUT, "tree": {"sha": TREE}, "parents": [{"sha": HEAD}]},
            "actions/runs/17": self.run}
        self.repack()

    def repack(self, entries=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, body in (entries or [("runtime-evidence.json", json.dumps(self.record))]):
                archive.writestr(name, body)
        self.body = stream.getvalue()
        self.artifact.update(digest="sha256:" + hashlib.sha256(self.body).hexdigest(), size_in_bytes=len(self.body))

    def get(self, route):
        return copy.deepcopy(self.metadata[route])

    def read(self, route, limit):
        assert route == "actions/artifacts/23/zip"
        assert limit == GATE.MAX_ARCHIVE
        return self.body


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.api = FixtureAPI()
        self.environment = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_REPOSITORY_ID": "99",
                            "GITHUB_SHA": MERGE}

    def verify(self, current=None):
        return GATE.reusable(self.api, current or self.api.current, {"commit": MERGE}, self.environment)

    def test_identical_tree_different_merge_commit_reuses_successful_attempt(self):
        self.assertEqual(self.verify(), {"run_id": 17, "run_attempt": 2, "artifact_id": 23,
                                         "runtime_seconds": 716.0})

    def test_each_fingerprint_binding_must_match(self):
        for key in ("tree", "runner", "tools", "environment", "baseline_sha256"):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.api.current)
                changed[key] = "changed"
                with self.assertRaises(GATE.Unavailable):
                    self.verify(changed)

    def test_source_tests_workflows_and_dependencies_all_change_the_git_tree(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            (root / "initial").write_text("baseline")
            git("add", ".")
            git("commit", "-qm", "fixture")
            with patch.object(GATE, "ROOT", root):
                prior = GATE.tree_identity(env)["tree"]
                for filename in ("skills/runtime.py", "tests/test_runtime.py", ".github/workflows/tests.yml", "requirements.txt"):
                    with self.subTest(filename=filename):
                        target = root / filename
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text("changed\n")
                        with self.assertRaises(GATE.Unavailable):
                            GATE.tree_identity(env)
                        git("add", ".")
                        git("commit", "-qm", "fixture change")
                        current = copy.deepcopy(self.api.current)
                        current["tree"] = GATE.tree_identity(env)["tree"]
                        self.assertNotEqual(prior, current["tree"])
                        with self.assertRaises(GATE.Unavailable):
                            self.verify(current)
                        prior = current["tree"]

    def test_missing_failed_ambiguous_or_incomplete_runs_refuse_reuse(self):
        route = "actions/workflows/13/runs?head_sha={}&event=pull_request&per_page=100".format(HEAD)
        for state in ({"total_count": 0, "workflow_runs": []},
                      {"total_count": 2, "workflow_runs": [self.api.run, self.api.run]},
                      {"total_count": 2, "workflow_runs": [self.api.run]},
                      {"total_count": 1, "workflow_runs": [{**self.api.run, "conclusion": "failure"}]}):
            with self.subTest(state=state):
                self.api.metadata[route] = state
                with self.assertRaises(GATE.Unavailable):
                    self.verify()

    def test_every_run_and_provenance_binding_is_required(self):
        for key, value in {"status": "in_progress", "event": "workflow_dispatch", "head_sha": "e" * 40,
                           "repository": {"id": 100}, "head_repository": {"id": 100},
                           "workflow_id": 14, "path": "other.yml", "run_attempt": 3}.items():
            with self.subTest(key=key):
                self.api = FixtureAPI()
                self.api.run[key] = value
                with self.assertRaises(GATE.Unavailable):
                    self.verify()
        for key, value in {"repository": "fork/repo", "repository_id": 100, "workflow_path": "other.yml",
                           "event": "push", "pull_request": 80, "run_id": 18, "run_attempt": 1,
                           "head_sha": "e" * 40}.items():
            with self.subTest(provenance=key):
                self.api = FixtureAPI()
                self.api.record["provenance"][key] = value
                self.api.repack()
                with self.assertRaises(GATE.Unavailable):
                    self.verify()

    def test_fork_and_changed_pr_head_refuse_reuse(self):
        self.api.pull["head"]["repo"]["id"] = 100
        with self.assertRaises(GATE.Unavailable):
            self.verify()
        self.api = FixtureAPI()
        self.api.pull["head"]["sha"] = "e" * 40
        with self.assertRaises(KeyError):
            self.verify()

    def test_artifact_expiry_size_digest_attempt_and_owner_are_required(self):
        for key, value in {"expired": True, "size_in_bytes": GATE.MAX_ARCHIVE + 1,
                           "digest": "sha256:bad", "name": "runtime-evidence-17-1"}.items():
            with self.subTest(key=key):
                self.api = FixtureAPI()
                self.api.artifact[key] = value
                with self.assertRaises(GATE.Unavailable):
                    self.verify()
        for key, value in {"id": 18, "repository_id": 100, "head_repository_id": 100, "head_sha": "e" * 40}.items():
            with self.subTest(binding=key):
                self.api = FixtureAPI()
                self.api.artifact["workflow_run"][key] = value
                with self.assertRaises(GATE.Unavailable):
                    self.verify()

    def test_missing_ambiguous_and_truncated_artifacts_refuse_reuse(self):
        for state in ({"total_count": 0, "artifacts": []},
                      {"total_count": 2, "artifacts": [self.api.artifact, self.api.artifact]},
                      {"total_count": 2, "artifacts": [self.api.artifact]}):
            with self.subTest(state=state):
                self.api.metadata["actions/runs/17/artifacts?per_page=100"] = state
                with self.assertRaises(GATE.Unavailable):
                    self.verify()

    def test_archive_is_data_only_and_bounded(self):
        for entries in ([('../runtime-evidence.json', '{}')],
                        [('runtime-evidence.json', '{}'), ('other', 'extra')],
                        [('runtime-evidence.json', 'x' * (GATE.MAX_RECORD + 1))],
                        [('runtime-evidence.json', 'not json')]):
            with self.subTest(entries=[name for name, _ in entries]):
                self.api.repack(entries)
                with self.assertRaises(GATE.Unavailable):
                    self.verify()
        self.api.body = b"corrupt archive"
        self.api.artifact["digest"] = "sha256:" + hashlib.sha256(self.api.body).hexdigest()
        with self.assertRaises(GATE.Unavailable):
            self.verify()

    def test_tested_commit_must_have_identical_tree_and_pr_parent(self):
        for change in ({"tree": {"sha": "e" * 40}}, {"parents": [{"sha": "e" * 40}]}):
            self.api = FixtureAPI()
            self.api.metadata["git/commits/" + CHECKOUT].update(change)
            with self.assertRaises(GATE.Unavailable):
                self.verify()
        self.api = FixtureAPI()
        self.api.metadata['git/commits/' + HEAD]['tree']['sha'] = 'e' * 40
        with self.assertRaises(GATE.Unavailable):
            self.verify()

    def test_failed_incomplete_and_unknown_schema_records_refuse_reuse(self):
        for change in ({"result": {"suites": 3, "passed": 2, "failed": 1}},
                       {"result": {"suites": 0, "passed": 0, "failed": 0}}, {"schema_version": 2}):
            self.api = FixtureAPI()
            self.api.record.update(change)
            self.api.repack()
            with self.assertRaises(GATE.Unavailable):
                self.verify()

    def test_rerun_started_during_lookup_refuses_reuse(self):
        self.api.metadata["actions/runs/17"] = {**self.api.run, "run_attempt": 3, "status": "in_progress"}
        with self.assertRaises(GATE.Unavailable):
            self.verify()

    def test_baseline_digest_binds_all_files_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / 'rule.md').write_text('original')
            original = GATE.directory_digest(root)
            (root / 'rule.md').write_text('changed')
            self.assertNotEqual(original, GATE.directory_digest(root))
            (root / 'alias').symlink_to(root / 'rule.md')
            with self.assertRaises(GATE.Unavailable):
                GATE.directory_digest(root)

    def test_runtime_environment_has_no_tokens_roles_or_ambient_overrides(self):
        with tempfile.TemporaryDirectory() as scratch:
            env = GATE.runtime_environment({'RUNNER_TEMP': scratch, 'PATH': '/usr/bin',
                'HERDR_CODING_POLICY_ROOT': '/baseline', 'GH_TOKEN': 'fixture-secret',
                'TESSL_TOKEN': 'fixture-secret', 'HERDR_ENV': '1', 'PYTHONPATH': '/untrusted',
                'BASH_ENV': '/untrusted', 'GIT_CONFIG_GLOBAL': '/untrusted'})
            self.assertEqual(env['LANG'], 'C.UTF-8')
            self.assertEqual(env['TZ'], 'UTC')
            self.assertEqual(env['HOME'], scratch + '/herdr-runtime-home')
            self.assertTrue(set(env).isdisjoint({'GH_TOKEN', 'TESSL_TOKEN', 'HERDR_ENV', 'PYTHONPATH', 'BASH_ENV'}))

    def test_archive_redirect_strips_authorization(self):
        request = GATE.urllib.request.Request('https://api.github.com/archive', headers={'Authorization': 'Bearer fixture'})
        redirected = GATE.SafeRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://storage.example/artifact')
        self.assertIsNotNone(redirected)
        self.assertNotIn('Authorization', dict(redirected.header_items()))
        with self.assertRaises(GATE.Unavailable):
            GATE.SafeRedirect().redirect_request(request, None, 302, 'Found', {}, 'http://storage.example/artifact')

    def test_unavailable_proof_runs_full_suites_and_keeps_failures_fatal(self):
        for status in (0, 1):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as scratch:
                env = {**self.environment, 'RUNNER_TEMP': scratch, 'PATH': os.environ['PATH'],
                       'HERDR_CODING_POLICY_ROOT': '/baseline', 'HERDR_REUSE_RUNTIME': '1',
                       'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main', 'GH_TOKEN': 'fixture-secret'}
                evidence = Path(scratch) / 'runtime-evidence.json'
                execution = subprocess.CompletedProcess([], status, stdout='{"suites":3,"passed":3,"failed":0}')
                output = io.StringIO()
                with patch.dict(os.environ, env, clear=True), patch.object(GATE, 'fingerprint', return_value=self.api.current), \
                     patch.object(GATE, 'tree_identity', return_value={'commit': MERGE, 'tree': TREE}), \
                     patch.object(GATE, 'reusable', side_effect=GATE.Unavailable('artifact unavailable')), \
                     patch.object(GATE.subprocess, 'run', return_value=execution) as run, \
                     contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(GATE.main(['--evidence', str(evidence)]), status)
                self.assertEqual(run.call_count, 1)
                self.assertNotIn('GH_TOKEN', run.call_args.kwargs['env'])
                self.assertFalse(json.loads(output.getvalue())['reused'])
                self.assertFalse(evidence.exists())

    def test_verified_proof_avoids_only_the_runtime_child(self):
        with tempfile.TemporaryDirectory() as scratch:
            env = {**self.environment, 'RUNNER_TEMP': scratch, 'PATH': os.environ['PATH'],
                   'HERDR_CODING_POLICY_ROOT': '/baseline', 'HERDR_REUSE_RUNTIME': '1',
                   'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main'}
            with patch.dict(os.environ, env, clear=True), patch.object(GATE, 'fingerprint', return_value=self.api.current), \
                 patch.object(GATE, 'tree_identity', return_value={'commit': MERGE, 'tree': TREE}), \
                 patch.object(GATE, 'reusable', return_value={'run_id': 17}), \
                 patch.object(GATE.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(GATE.main(['--evidence', scratch + '/runtime-evidence.json']), 0)
            run.assert_not_called()
            self.assertTrue(json.loads(output.getvalue())['reused'])

    def test_pr_producer_writes_only_after_complete_unchanged_runtime_success(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as scratch:
                event = Path(scratch) / 'event.json'
                event.write_text(json.dumps({'number': 79, 'repository': {'id': 99, 'full_name': 'owner/repo'},
                                             'pull_request': self.api.pull}))
                env = {**self.environment, 'GITHUB_SHA': CHECKOUT, 'RUNNER_TEMP': scratch,
                       'PATH': os.environ['PATH'], 'HERDR_CODING_POLICY_ROOT': '/baseline',
                       'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_EVENT_PATH': str(event),
                       'GITHUB_WORKFLOW_REF': 'owner/repo/' + GATE.WORKFLOW + '@refs/pull/79/merge',
                       'GITHUB_RUN_ID': '17', 'GITHUB_RUN_ATTEMPT': '2', 'GITHUB_OUTPUT': scratch + '/output'}
                evidence = Path(scratch) / 'artifact/runtime-evidence.json'
                later = {**self.api.current, 'tree': 'e' * 40} if changed else self.api.current
                execution = subprocess.CompletedProcess([], 0, stdout='{"suites":3,"passed":3,"failed":0}')
                with patch.dict(os.environ, env, clear=True), \
                     patch.object(GATE, 'fingerprint', side_effect=[self.api.current, later]), \
                     patch.object(GATE, 'tree_identity', return_value={'commit': CHECKOUT, 'tree': TREE}), \
                     patch.object(GATE.subprocess, 'run', return_value=execution), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(GATE.main(['--evidence', str(evidence)]), 0)
                self.assertEqual(evidence.exists(), not changed)
                self.assertEqual(Path(env['GITHUB_OUTPUT']).read_text(), 'evidence_written={}\n'.format(str(not changed).lower()))
                if not changed:
                    record = json.loads(evidence.read_text())
                    self.assertGreaterEqual(record.pop('runtime_seconds'), 0)
                    expected = {key: value for key, value in self.api.record.items() if key != 'runtime_seconds'}
                    self.assertEqual(record, expected)


if __name__ == '__main__':
    unittest.main()
