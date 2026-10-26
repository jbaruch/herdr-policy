"""Bounded reader-only checkout fences; no Git, native or publication effects."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import hashlib
import json
import os
import subprocess
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_progression_owner as fixture
from foreman import progression_owner as authority, release_flight, workflow_contract
from foreman.errors import ForemanError, UsageError


class ReleaseFlightTest(unittest.TestCase):
    def setUp(self):
        self.owner = fixture.ProgressionOwnerTest()
        self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.path, self.root = self.owner.path, self.owner.root
        self.state = self.owner.state()

    def write(self, path, value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def seed(self, *, workflow=False):
        target = self.root / "clean-successor"
        source = self.root / "original-source"
        path = self.root / ("foreman-release-" + hashlib.sha256(str(target).encode()).hexdigest() + ".json")
        generation = 0
        evidence = {"kind": "ledger", "receipt": {"path": str(self.root / "ledger.md"), "sha256": "c" * 64, "bytes": 123}}
        if workflow:
            self.owner.admit()
            self.state = self.owner.state()
            old = self.state["recovery"]["tasks"]["one"]["authority"]
            old["contract_schema"] = 2
            generation = old["generation"]
            progress = workflow_contract.initial_progress(generation, fixture.AT)
            evidence = {"kind": "workflow", "grant": deepcopy(old), "progress": progress,
                        "reports": [{"path": str(self.root / (role + ".md")), "sha256": "d" * 64} for role in ("developer", "reviewer")],
                        "successor": {"path": str(self.root / "successor-contract.json"), "sha256": "e" * 64}}
        self.intent = {"schema_version": 1, "state_path": str(self.path), "task": "one", "source": str(source), "path": str(target),
            "branch": "feature/one", "head": "b" * 40, "base_revision": "a" * 40,
            "source_provenance": {"schema_version": 1, "path": str(source), "branch": "feature/one", "base_ref": "origin/main",
                "base_revision": "a" * 40, "fetched_default_ref": "origin/main", "fetched_default_revision": "a" * 40},
            "evidence": evidence, "binding": {"generation": 1, "digest": "f" * 64}, "at": fixture.AT, "authorizes_release": False}
        if workflow:
            self.intent["binding"] = deepcopy(evidence["grant"]["binding"])
        captured = self.write(path, self.intent)
        self.locator = {"schema_version": 1, "state_path": str(self.path), "task": "one", "intent": captured,
                        "ready": str(path) + ".ready", "generation": generation,
                        "task_sha256": release_flight.task_fingerprint(self.state["recovery"]["tasks"]["one"], self.intent["binding"])}
        self.location = release_flight.locator_path(self.path, "one")
        self.write(self.location, self.locator)
        self.ready = {key: self.locator[key] for key in ("schema_version", "state_path", "task", "intent", "generation", "task_sha256")}
        self.ready["authorizes_progression"] = False
        if workflow:
            self.ready["generation"] += 1
            successor = deepcopy(evidence["grant"])
            successor.update(generation=self.ready["generation"], contract=evidence["successor"], at=fixture.AT)
            self.state["recovery"]["tasks"]["one"].update(authority=successor,
                progression=workflow_contract.initial_progress(successor["generation"], fixture.AT))

    def test_pending_fence_stops_only_its_task_and_preserves_owner_bytes(self):
        self.seed()
        original = self.path.read_bytes()
        with patch("subprocess.run", side_effect=AssertionError("Reader invoked Git/native I/O")):
            release_flight.require_clear(self.path, self.state, {"two"})
            with self.assertRaisesRegex(UsageError, "in-flight") as held:
                release_flight.require_clear(self.path, self.state, {"one"})
        self.assertEqual(held.exception.details["task"], "one")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.location.read_text(), json.dumps(self.locator))

    def test_legacy_command_and_native_capability_obey_the_same_selected_gate(self):
        self.seed()
        with self.assertRaisesRegex(UsageError, "in-flight"):
            authority.require_command(self.path, SimpleNamespace(command="apply", task="one"))
        authority.require_command(self.path, SimpleNamespace(command="apply", task="two"))
        with self.assertRaisesRegex(UsageError, "in-flight"):
            self.owner.admit()
        original = deepcopy(self.owner.state()["recovery"]["tasks"]["one"])
        contract = self.root / "two.json"
        contract.write_text(json.dumps({"schema_version": 1, "task": "two"}))
        data = {**self.owner.data, "task": "two", "service_id": "two-service",
                "lease_path": str(self.root / "two.lease"), "contract": str(contract)}
        from foreman.state import state_lock
        with state_lock(self.path):
            authority.handoff(self.path, data, fixture.AT, self.owner.client, fixture.ROOT)
        self.assertEqual(self.owner.state()["recovery"]["tasks"]["one"], original)
        self.location.unlink()  # Controlled fixture, before native grant setup.
        self.owner.admit()
        self.write(self.location, self.locator)
        with self.assertRaisesRegex(UsageError, "in-flight"):
            with self.owner.session():
                self.fail("A native capability crossed a pending checkout transaction")

    def test_exact_ready_is_only_absence_of_fence_and_never_authority(self):
        for workflow in (False, True):
            with self.subTest(workflow=workflow):
                if self.location_exists():
                    self.location.unlink()
                self.seed(workflow=workflow)
                self.write(Path(self.locator["ready"]), self.ready)
                result = release_flight.inspect(self.path, self.state, "one")
                assert result is not None
                self.assertFalse(result["pending"])
                self.assertFalse(result["authorizes_progression"])
                release_flight.require_clear(self.path, self.state, {"one"})
                if workflow:
                    self.state["recovery"]["tasks"]["one"]["progression"].update(phase="verify", head={
                        "commit": "b" * 40, "tree": "c" * 40, "paths": ["src/example.py"]})
                    release_flight.require_clear(self.path, self.state, {"one"})

    def location_exists(self):
        return hasattr(self, "location") and self.location.exists()

    def test_copied_changed_or_wrong_generation_ready_never_clears(self):
        self.seed(workflow=True)
        for field, value in (("task", "two"), ("generation", 1), ("task_sha256", "2" * 64),
                             ("intent", {"path": self.locator["intent"]["path"], "sha256": "9" * 64}),
                             ("authorizes_progression", True)):
            with self.subTest(field=field):
                self.write(Path(self.locator["ready"]), {**self.ready, field: value})
                with self.assertRaises(ForemanError):
                    release_flight.require_clear(self.path, self.state, {"one"})
                release_flight.require_clear(self.path, self.state, {"two"})
        self.write(Path(self.locator["ready"]), self.ready)
        self.state["recovery"]["tasks"]["one"]["authority"]["generation"] += 1
        with self.assertRaisesRegex(UsageError, "different current workflow generation"):
            release_flight.require_clear(self.path, self.state, {"one"})

    def test_same_generation_changed_task_facts_or_original_binding_cannot_replay_ready(self):
        self.seed()
        self.write(Path(self.locator["ready"]), self.ready)
        for field, value in (("scope", "Changed task authorization scope"), ("allowed_paths", ["other/*"]),
                             ("authorization", {"source": "changed", "quote": "Changed authorization"}),
                             ("at", "2026-10-11T10:00:00+00:00")):
            with self.subTest(field=field):
                changed = deepcopy(self.state)
                changed["recovery"]["tasks"]["one"][field] = value
                with self.assertRaisesRegex(UsageError, "scope/authorization"):
                    release_flight.require_clear(self.path, changed, {"one"})
                release_flight.require_clear(self.path, changed, {"two"})
        self.intent["binding"]["generation"] += 1
        self.locator["intent"] = self.write(Path(self.locator["intent"]["path"]), self.intent)
        self.ready["intent"] = self.locator["intent"]
        self.write(self.location, self.locator)
        self.write(Path(self.locator["ready"]), self.ready)
        with self.assertRaisesRegex(UsageError, "original intent binding"):
            release_flight.require_clear(self.path, self.state, {"one"})

    def test_unknown_versions_changed_intent_symlinks_and_oversize_preserve_the_gate(self):
        self.seed()
        for path, changed in ((self.location, {**self.locator, "schema_version": 2}),
                              (Path(self.locator["intent"]["path"]), {**self.intent, "schema_version": 2})):
            before = path.read_bytes()
            self.write(path, changed)
            with self.assertRaises(ForemanError):
                release_flight.require_clear(self.path, self.state, {"one"})
            self.assertEqual(json.loads(path.read_text())["schema_version"], 2)
            path.write_bytes(before)
        intent = Path(self.locator["intent"]["path"])
        before = intent.read_bytes()
        intent.write_bytes(before + b"\n")
        with self.assertRaisesRegex(UsageError, "do not agree"):
            release_flight.require_clear(self.path, self.state, {"one"})
        intent.write_bytes(before)
        self.location.write_bytes(b" " * (release_flight.LOCATOR_BYTES + 1))
        with self.assertRaises(ForemanError):
            release_flight.require_clear(self.path, self.state, {"one"})
        self.write(self.location, self.locator)
        moved = self.root / "retained-locator.json"
        self.location.rename(moved)
        self.location.symlink_to(moved)
        with self.assertRaises(ForemanError):
            release_flight.require_clear(self.path, self.state, {"one"})
        self.assertTrue(self.location.is_symlink())

    def test_every_flight_gate_input_requires_private_mode_without_chmod_repair(self):
        self.seed()
        self.write(Path(self.locator["ready"]), self.ready)
        paths = (self.location, Path(self.locator["intent"]["path"]), Path(self.locator["ready"]))
        for path in paths:
            body = path.read_bytes()
            for mode in (0o644, 0o666):
                with self.subTest(path=path.name, mode=oct(mode)):
                    path.chmod(mode)
                    with self.assertRaises(ForemanError) as refused:
                        release_flight.require_clear(self.path, self.state, {"one"})
                    self.assertEqual(refused.exception.details["reason"], "release_checkout_evidence_unsafe")
                    release_flight.require_clear(self.path, self.state, {"two"})
                    self.assertEqual(path.read_bytes(), body)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
            path.chmod(0o600)

    def test_actual_fifo_refuses_without_blocking_the_owner(self):
        self.seed()
        self.location.unlink()
        os.mkfifo(self.location, 0o600)
        code = """import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from foreman import release_flight
from foreman.errors import ForemanError
path = Path(sys.argv[2])
try:
    release_flight.require_clear(path, json.loads(path.read_text()), {'one'})
except ForemanError as exc:
    assert exc.details['reason'] == 'release_checkout_evidence_unsafe'
    raise SystemExit(0)
raise AssertionError('A FIFO cleared the selected checkout fence')
"""
        result = subprocess.run([sys.executable, "-B", "-c", code,
            str(fixture.ROOT / "skills/herdr-foreman"), str(self.path)],
            capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.location.is_fifo())


if __name__ == "__main__":
    unittest.main()
