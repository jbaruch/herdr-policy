"""ACR public-owner identity contracts; no registry/native sessions in fixtures."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import hashlib
import json
import subprocess
import tempfile
import unittest

from foreman import native_policy
from foreman.errors import StateError


class NativePolicyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name).resolve()
        self.skill = self.project / ".codex/skills" / native_policy.SKILL
        self.skill.mkdir(parents=True)
        (self.project / ".agents").mkdir()
        self.lock = self.project / ".agents/registry.lock"
        self.lock.write_text("Private lock bytes fixture; parsed by the fake public owner.\n")
        self.targets = []
        for relative in ("SKILL.md", "foreman/remote_owner.py", "foreman/cli.py",
                         "foreman/progression_service.py", "references/team-operation.md"):
            path = self.skill / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Private native ownership fixture: " + relative + "\n")
            self.targets.append({"path": str(path.relative_to(self.project)), "entries": [
                {"source": native_policy.SOURCE, "adapter": "codex", "artifactKind": "file"}]})
        policy = self.project / "AGENTS.md"
        policy.write_text("Private rendered policy fixture.\n")
        self.targets.append({"path": "AGENTS.md", "entries": [
            {"source": native_policy.SOURCE, "adapter": "codex", "artifactKind": "managed-block"}]})
        for target in self.targets:
            target["outputHash"] = "sha256:" + hashlib.sha256((self.project / target["path"]).read_bytes()).hexdigest()
        self.listing = {"dependencies": [{"declaration": {"source": native_policy.SOURCE}, "locked": {
            "source": native_policy.SOURCE, "packageVersion": "0.4.0", "contentHash": "sha256:" + "a" * 64,
            "commit": "b" * 40}}]}
        self.checked = {"agents": ["codex"], "plan": {"operations": None, "ledgerChanged": False,
            "ledger": {"schemaVersion": 1, "targets": self.targets}}}
        self.calls = []
        native_policy._checked.clear()
        self.addCleanup(native_policy._checked.clear)

    def run_cli(self, argv, **options):
        self.calls.append((argv, options))
        result = self.listing if argv[1] == "list" else self.checked
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "command": argv[1], "result": result}), "")

    def identity(self):
        return native_policy.loaded_policy(self.skill, run=self.run_cli)

    def test_checked_bytes_stay_required_while_metadata_is_cached(self):
        original = self.identity()
        self.assertEqual(original[0], "0.4.0")
        self.assertEqual(self.identity(), original)
        self.assertEqual(len(self.calls), 2)
        (self.skill / "foreman/remote_owner.py").write_text("Private changed policy fixture.\n")
        with self.assertRaises(StateError):
            self.identity()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([call[0][1] for call in self.calls], ["list", "check"])

    def test_changed_bytes_after_public_check_are_not_admitted(self):
        def racing(argv, **options):
            result = self.run_cli(argv, **options)
            if argv[1] == "check":
                (self.skill / "foreman/remote_owner.py").write_text("Private concurrent target edit.\n")
            return result
        with self.assertRaises(StateError):
            native_policy.loaded_policy(self.skill, run=racing)

    def test_missing_invalid_and_mismatched_checked_hashes_are_refused(self):
        original = self.targets[0]["outputHash"]
        for value in (None, "sha256:unknown", "sha256:" + "0" * 64):
            native_policy._checked.clear()
            self.targets[0]["outputHash"] = value
            with self.subTest(value=value), self.assertRaises(StateError):
                self.identity()
        self.targets[0]["outputHash"] = original
        del self.targets[0]["outputHash"]
        with self.assertRaises(StateError):
            self.identity()

    def test_schema_two_can_coexist_with_coordinator_targets(self):
        original = self.identity()
        native_policy._checked.clear()
        self.checked["plan"]["ledger"]["schemaVersion"] = 2
        self.targets.append({"owner": "coordinator", "path": ".agents/skills/shared-fixture/SKILL.md", "entries": [
            {"source": native_policy.SOURCE, "adapter": "codex"}]})
        self.assertEqual(self.identity(), original)
        with self.assertRaises(StateError):
            native_policy.loaded_policy(self.project / ".agents/skills" / native_policy.SKILL, run=self.run_cli)

    def test_changed_lock_queries_current_public_owner_again(self):
        self.identity()
        self.lock.write_text("Private next lock generation.\n")
        self.listing["dependencies"][0]["locked"]["packageVersion"] = "0.4.1"
        self.assertEqual(self.identity()[0], "0.4.1")
        self.assertEqual(len(self.calls), 4)

    def test_missing_ambiguous_or_unknown_locked_identity_is_not_guessed(self):
        original = deepcopy(self.listing)
        for rows in ([], [original["dependencies"][0], original["dependencies"][0]]):
            self.listing["dependencies"] = rows
            with self.subTest(rows=rows), self.assertRaises(StateError):
                self.identity()
        self.listing = original
        del self.listing["dependencies"][0]["locked"]["commit"]
        with self.assertRaises(StateError):
            self.identity()

    def test_unrealized_or_unowned_runtime_is_refused_without_writes(self):
        before = self.lock.read_bytes()
        self.checked["plan"]["operations"] = [{"private_fixture": "unrealized"}]
        with self.assertRaises(StateError):
            self.identity()
        self.checked["plan"]["operations"] = None
        self.checked["plan"]["ledger"]["targets"] = self.targets[1:]
        with self.assertRaises(StateError):
            self.identity()
        self.assertEqual(self.lock.read_bytes(), before)

    def test_links_traversal_and_extra_unowned_runtime_are_preserved_and_refused(self):
        external = self.project / "outside"
        external.write_text("Preserve private external fixture.\n")
        required = self.skill / "SKILL.md"
        original = required.read_bytes()
        required.unlink()
        required.symlink_to(external)
        with self.assertRaises(StateError):
            self.identity()
        self.assertEqual(external.read_text(), "Preserve private external fixture.\n")
        required.unlink()
        required.write_bytes(original)
        unknown = self.skill / "unknown.py"
        unknown.write_text("Preserve private unknown fixture.\n")
        with self.assertRaises(StateError):
            self.identity()
        unknown.unlink()
        native_policy._checked.clear()
        self.checked["plan"]["ledger"]["targets"].append({"path": "../outside", "entries": [
            {"source": native_policy.SOURCE, "adapter": "codex"}]})
        with self.assertRaises(StateError):
            self.identity()

    def test_public_owner_failures_and_lock_changes_during_read_stay_unknown(self):
        def unavailable(*_args, **_options):
            raise OSError("Private CLI outage fixture.")
        with self.assertRaises(StateError):
            native_policy.loaded_policy(self.skill, run=unavailable)
        def racing(argv, **options):
            result = self.run_cli(argv, **options)
            if argv[1] == "check":
                self.lock.write_text("Private concurrent realization fixture.\n")
            return result
        with self.assertRaises(StateError):
            native_policy.loaded_policy(self.skill, run=racing)


if __name__ == "__main__":
    unittest.main()
