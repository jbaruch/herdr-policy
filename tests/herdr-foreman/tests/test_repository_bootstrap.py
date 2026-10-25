"""Empty-repository bootstrap against real local Git, without network or agents."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills/herdr-foreman/bootstrap-repository.py"
SPEC = importlib.util.spec_from_file_location("repository_bootstrap", SCRIPT)
assert SPEC and SPEC.loader
BOOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOT)


class RepositoryBootstrapTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="herdr-bootstrap-test-")
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                            "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "Fixture",
                            "GIT_CONFIG_KEY_1": "user.email", "GIT_CONFIG_VALUE_1": "fixture@example.invalid",
                            "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z"}
        self.remote, self.shared = self.root / "remote.git", self.root / "shared"
        self.call("git", "init", "--bare", "--quiet", "--initial-branch", "main", str(self.remote))
        self.call("git", "clone", "--quiet", str(self.remote), str(self.shared))
        (self.shared / "operator-file.txt").write_text("preserve local work\n")

    def call(self, *arguments):
        return subprocess.run(arguments, capture_output=True, text=True, check=True, env=self.environment).stdout.strip()

    def git_run(self, argv, **options):
        return subprocess.run(argv, **{**options, "env": self.environment})

    def initialize(self, **options):
        return BOOT.bootstrap(self.shared, "main", initialize=True, run=options.get("run", self.git_run))

    def writer(self, message="Concurrent initializer"):
        path = self.root / "racer"
        self.call("git", "clone", "--quiet", str(self.remote), str(path))
        (path / "README.md").write_text("Existing implementation must survive.\n")
        self.call("git", "-C", str(path), "add", "README.md")
        self.call("git", "-C", str(path), "commit", "--quiet", "-m", message)
        self.call("git", "-C", str(path), "push", "--quiet", "origin", "HEAD:refs/heads/main")
        return self.call("git", "-C", str(path), "rev-parse", "HEAD")

    def test_empty_remote_gets_a_real_empty_base_and_normal_worktree_provisioning(self):
        receipt = self.initialize()
        self.assertTrue(receipt["created"])
        self.assertFalse(receipt["authorizes_implementation"])
        revision = receipt["base_revision"]
        self.assertEqual(self.call("git", "--git-dir", str(self.remote), "rev-parse", "main"), revision)
        self.assertEqual(self.call("git", "--git-dir", str(self.remote), "ls-tree", "-r", "--name-only", revision), "")
        self.assertEqual((self.shared / "operator-file.txt").read_text(), "preserve local work\n")
        worktrees = self.root / "worktrees"
        worktree = worktrees / "new-plugin"
        result = subprocess.run(["bash", str(ROOT / "skills/herdr-foreman/provision-worktree.sh"), str(self.shared),
                                 "feat/new-plugin", str(worktree)], env={**self.environment, "WORKTREE_ROOT": str(worktrees)},
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_revision"], revision)
        self.assertEqual(self.call("git", "-C", str(worktree), "rev-parse", "HEAD"), revision)
        self.assertEqual((self.shared / "operator-file.txt").read_text(), "preserve local work\n")

    def test_default_inspection_never_initializes_empty_origin(self):
        with self.assertRaisesRegex(BOOT.BootstrapError, "--initialize-empty"):
            BOOT.bootstrap(self.shared, "main", run=self.git_run)
        self.assertEqual(self.call("git", "-C", str(self.shared), "ls-remote", "--refs", "origin"), "")

    def test_existing_history_is_used_without_rewriting_it(self):
        revision = self.writer()
        result = self.initialize()
        self.assertFalse(result["created"])
        self.assertEqual(result["base_revision"], revision)
        self.assertIn("README.md", self.call("git", "--git-dir", str(self.remote), "ls-tree", "-r", "--name-only", "main"))

    def test_concurrent_initializer_wins_without_a_force_push(self):
        race = []
        def run(argv, **options):
            self.assertNotIn("--force", argv)
            if "push" in argv and not race:
                race.append(self.writer())
            return self.git_run(argv, **options)
        result = self.initialize(run=run)
        self.assertFalse(result["created"])
        self.assertEqual(result["base_revision"], race[0])
        self.assertEqual(self.call("git", "--git-dir", str(self.remote), "rev-parse", "main"), race[0])

    def test_lost_push_response_is_resolved_by_actual_remote_readback(self):
        def run(argv, **options):
            result = self.git_run(argv, **options)
            return SimpleNamespace(returncode=1, stdout="", stderr="withheld") if "push" in argv else result
        result = self.initialize(run=run)
        self.assertTrue(result["created"])
        self.assertEqual(self.call("git", "--git-dir", str(self.remote), "rev-parse", "main"), result["base_revision"])

    def test_unreadable_remote_never_becomes_empty_and_conflicting_push_target_is_refused(self):
        self.call("git", "-C", str(self.shared), "remote", "set-url", "origin", str(self.root / "missing.git"))
        with self.assertRaisesRegex(BOOT.BootstrapError, "Git operation failed"):
            self.initialize()
        self.call("git", "-C", str(self.shared), "remote", "set-url", "origin", str(self.remote))
        self.call("git", "-C", str(self.shared), "remote", "set-url", "--push", "origin", str(self.root / "other.git"))
        with self.assertRaisesRegex(BOOT.BootstrapError, "matching origin"):
            self.initialize()


if __name__ == "__main__":
    unittest.main()
