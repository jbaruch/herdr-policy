"""Known writer contradictions are preserved and downgraded, never made proof."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import hashlib
import io
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from foreman import context_evidence as owner, recovery
from foreman.errors import StateError, UsageError
from foreman.state import add_assignment, empty_state, load_state_checked

AT = "2026-02-03T10:00:00+00:00"
AUTH = {"source": "fixture operator instruction", "quote": "Preserve and quarantine the exact contradictory context evidence."}


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "state.json"
        state = empty_state()
        recovery.register_task(state["recovery"], {"task": "fixture", "base_revision": "a" * 40,
            "scope": "Fixture source work", "allowed_paths": ["src/*"], "authorization": AUTH}, AT)
        add_assignment(state, AT, "developer", "unrelated", task="unrelated")
        add_assignment(state, AT, "developer", "worker", task="fixture")
        record = {"id": "fixture:developer", "task": "fixture", "role": "developer", "agent": "worker",
                  "fix_round": None, "fingerprint": "a" * 64, "plan": "fixture-plan", "work": None,
                  "worker_kind": "claude"}
        recovery.reserve(state["recovery"], record, AT)
        result = {"status": "applied", "task": "fixture", "role": "developer", "agent": "worker",
                  "fix_round": None, "worker_kind": "claude", "assignment_scoped": True,
                  "cleared": True, "clear_reason": "hand", "context_session": None}
        recovery.finish_dispatch(state["recovery"], record["id"], result, 1, AT)
        state["assignments"][1].update(cleared=True, clear_reason="hand")
        self.state = state
        self.original = (json.dumps(state, indent=2) + "\n").encode()
        self.path.write_bytes(self.original)
        self.data = {"schema_version": 1, "id": "fixture-repair", "assignment_index": 1,
                     "assignment_sha256": owner.digest(state["assignments"][1]),
                     "dispatch": record["id"], "authorization": AUTH}
        verifier = patch.object(owner.progression_owner, "verify_foreman", return_value={})
        self.verify = verifier.start()
        self.addCleanup(verifier.stop)
        self.client = SimpleNamespace()

    def run_repair(self, **kwargs):
        return owner.quarantine(self.path, self.data, AT, self.client, **kwargs)

    def test_preserves_original_bytes_history_and_dispatch_without_inventing_clear(self):
        result = self.run_repair()
        self.verify.assert_called_once_with(self.path, self.client, native_only=True)
        actual, usable = load_state_checked(self.path)
        self.assertTrue(usable)
        expected = deepcopy(self.state)
        expected["assignments"][1].update(cleared=None, clear_reason="unknown")
        self.assertEqual(actual, expected)
        self.assertEqual(Path(result["backup"]).read_bytes(), self.original)
        journal = json.loads(Path(result["journal"]).read_text())
        self.assertEqual(journal["original_assignment"], self.state["assignments"][1])
        self.assertEqual(journal["original_state_sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertFalse(result["authorizes_dispatch"])
        self.assertEqual(Path(result["backup"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(result["journal"]).parent.stat().st_mode & 0o777, 0o700)

    def test_dry_run_does_not_write_owner_or_evidence(self):
        result = self.run_repair(dry_run=True)
        self.assertTrue(result["would_quarantine"])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(Path(str(self.path) + ".context-evidence").exists())

    def test_cli_recovers_unreadable_owner_without_empty_state_fallback(self):
        from foreman.cli import main
        record = self.path.with_name("request.json")
        record.write_text(json.dumps(self.data))
        output, errors = io.StringIO(), io.StringIO()
        result = main(["quarantine-context-evidence", "--state", str(self.path),
                       "--record", str(record), "--now", AT], stdout=output, stderr=errors, client=self.client)
        self.assertEqual(result, 0, errors.getvalue())
        self.assertTrue(json.loads(output.getvalue())["quarantined"])
        self.assertTrue(load_state_checked(self.path)[1])

    def test_exact_retry_after_owner_write_is_idempotent(self):
        first = self.run_repair()
        before = self.path.read_bytes()
        result = self.run_repair()
        self.assertTrue(result["replayed"])
        self.assertEqual(set(result), set(first))
        self.assertEqual(result["backup"], first["backup"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(Path(first["backup"]).read_bytes(), self.original)

    def test_interruption_after_journal_before_owner_write_retries_without_resend(self):
        with patch.object(owner, "save_state", side_effect=OSError("fixture crash")):
            with self.assertRaises(OSError):
                self.run_repair()
        self.assertEqual(self.path.read_bytes(), self.original)
        result = self.run_repair()
        self.assertTrue(result["quarantined"])
        self.assertEqual(Path(result["backup"]).read_bytes(), self.original)

    def test_unverified_caller_is_refused_before_evidence_or_owner_writes(self):
        self.verify.side_effect = UsageError("unverified fixture caller", {})
        with self.assertRaisesRegex(UsageError, "unverified"):
            self.run_repair()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(Path(str(self.path) + ".context-evidence").exists())

    def test_wrong_row_or_dispatch_and_changed_history_are_not_quarantined(self):
        for key, value in (("assignment_sha256", "b" * 64), ("dispatch", "different"),
                           ("assignment_index", True), ("id", "../outside")):
            with self.subTest(key=key):
                with self.assertRaises((StateError, UsageError)):
                    owner.quarantine(self.path, {**self.data, key: value}, AT, self.client)
                self.assertEqual(self.path.read_bytes(), self.original)
        other = deepcopy(self.state)
        other["assignments"][0]["clear_reason"] = "unsupported"
        self.path.write_text(json.dumps(other))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(StateError, "Other owner evidence"):
            self.run_repair()
        self.assertEqual(self.path.read_bytes(), before)

    def test_symlink_owner_and_evidence_directory_are_preserved(self):
        real = self.path.with_name("real.json")
        self.path.rename(real)
        self.path.symlink_to(real)
        with self.assertRaisesRegex(StateError, "owned regular"):
            self.run_repair()
        self.assertEqual(real.read_bytes(), self.original)
        self.path.unlink()
        self.path.write_bytes(self.original)
        outside = self.path.with_name("outside")
        outside.mkdir()
        Path(str(self.path) + ".context-evidence").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(StateError, "private"):
            self.run_repair()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_corrupt_backup_prevents_a_successful_replay(self):
        result = self.run_repair()
        Path(result["backup"]).write_text("changed")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(StateError, "original ledger backup"):
            self.run_repair()
        self.assertEqual(self.path.read_bytes(), before)

    def test_changed_input_cannot_reuse_a_prepared_journal(self):
        with patch.object(owner, "save_state", side_effect=OSError("fixture crash")):
            with self.assertRaises(OSError):
                self.run_repair()
        altered = {**self.data, "authorization": {"source": "different", "quote": "Different request"}}
        with self.assertRaisesRegex(StateError, "different evidence"):
            owner.quarantine(self.path, altered, AT, self.client)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_changed_owner_after_preparation_is_preserved(self):
        with patch.object(owner, "save_state", side_effect=OSError("fixture crash")):
            with self.assertRaises(OSError):
                self.run_repair()
        changed = deepcopy(self.state)
        changed["assignments"][0]["agent"] = "different-history"
        self.path.write_text(json.dumps(changed))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(StateError, "Owner changed"):
            self.run_repair()
        self.assertEqual(self.path.read_bytes(), before)

    def test_preservation_failure_never_changes_the_owner(self):
        with patch.object(owner, "_immutable", side_effect=StateError("fixture preservation failure", {})):
            with self.assertRaisesRegex(StateError, "preservation failure"):
                self.run_repair()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_temporary_creation_failure_is_actionable_and_preserves_owner(self):
        with patch.object(owner.tempfile, "mkstemp", side_effect=OSError("fixture disk full")):
            with self.assertRaisesRegex(StateError, "Cannot preserve context evidence"):
                self.run_repair()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(Path(str(self.path) + ".context-evidence").iterdir()), [])

    def test_cleanup_failure_does_not_mask_preservation_failure(self):
        with patch.object(owner.os, "link", side_effect=OSError("fixture storage failure")), \
                patch.object(Path, "unlink", side_effect=PermissionError("fixture cleanup failure")), \
                patch.object(owner, "stderr_warn") as warning:
            with self.assertRaisesRegex(StateError, "Cannot preserve context evidence"):
                self.run_repair()
            warning.assert_called_once()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_action_router_exposes_the_guarded_unreadable_owner_recovery(self):
        skill = Path(__file__).resolve().parents[3] / "skills/herdr-foreman"
        router = (skill / "SKILL.md").read_text()
        self.assertIn("quarantine contradictory context evidence", router)
        self.assertIn("owner_state_unreadable", router)
        self.assertIn("## Step 10 — Quarantine Context Evidence", router)
        reference = (skill / "references/context-quarantine.md").read_text()
        self.assertIn("bound native foreman", reference)
        self.assertIn("existing explicit operator authorization", reference)
        self.assertIn("quarantine-context-evidence --state", reference)
        self.assertIn("--dry-run", reference)


if __name__ == "__main__":
    unittest.main()
