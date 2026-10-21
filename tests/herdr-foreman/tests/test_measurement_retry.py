"""Public retries keep successful account-window readings without new probes."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3] / "skills/herdr-foreman"
sys.path.insert(0, str(ROOT))

import io
import json
import tempfile
import unittest
from unittest.mock import patch

from foreman import cli
from foreman.herdr import HerdrClient
from foreman.state import SNAPSHOT_SCHEMA_VERSION

AT = "2026-10-21T01:00:00+00:00"
RETRY = "2026-10-21T01:02:00+00:00"


class MeasurementRetryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "config.json"
        self.config.write_bytes((ROOT / "config.example.json").read_bytes())
        self.state = self.root / "state.json"
        self.client = HerdrClient(binary="herdr-fixture")
        self.probes = []
        self.failures = set()
        self.skipped = set()

    def measured(self, client, agents, at, **options):
        self.probes.append([agent.name for agent in agents])
        records = {}
        for agent in agents:
            record = {"kind": agent.kind, "state": "idle", "windows": [], "credits": None,
                      "plan": None, "headroom_pct": 66, "window_group": agent.window_group,
                      "skipped": agent.name in self.skipped, "tier_billing": {}}
            if agent.name in self.failures:
                record.update(headroom_pct=None, error={"code": "herdr_error", "message": "fixture startup failed", "details": {}})
            records[agent.name] = record
        return {"schema_version": SNAPSHOT_SCHEMA_VERSION, "measured_at": at, "agents": records,
                "measurement_context_sha256": None, "reused_agents": [],
                "failed_agents": sorted(set(records) & self.failures)}

    def invoke(self, *options, at=AT):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("foreman.cli.lifecycle.measure_worker_kinds", side_effect=self.measured):
            code = cli.main(["--config", str(self.config), "--state", str(self.state),
                             "measure", "--now", at, *options], stdout=stdout, stderr=stderr, client=self.client)
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else {}, stderr.getvalue()

    def test_targeted_success_then_retry_measures_only_missing_profiles(self):
        self.assertEqual(self.invoke("--agent", "codex")[0], 0)
        code, result, error = self.invoke("--retry-failed", at=RETRY)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(self.probes, [["codex"], ["claude", "grok"]])
        self.assertEqual(sorted(result["agents"]), ["claude", "codex", "grok"])
        self.assertEqual(result["reused_agents"], ["codex"])
        self.assertEqual(result["measured_at"], AT)
        self.assertEqual(self.invoke("--retry-failed", at=RETRY)[0], 0)
        self.assertEqual(len(self.probes), 2)

    def test_failures_are_retried_without_remeasuring_a_successful_provider(self):
        self.failures = {"claude", "grok"}
        self.assertEqual(self.invoke()[0], 1)
        self.failures.clear()
        code, result, _ = self.invoke("--retry-failed", at=RETRY)
        self.assertEqual(code, 0)
        self.assertEqual(self.probes, [["claude", "codex", "grok"], ["claude", "grok"]])
        self.assertEqual(result["failed_agents"], [])
        self.assertEqual(result["reused_agents"], ["codex"])
        self.assertEqual(result["measured_at"], AT)

    def test_repeated_failure_keeps_unknown_capacity(self):
        self.failures = {"grok"}
        self.invoke()
        code, result, _ = self.invoke("--retry-failed", at=RETRY)
        self.assertEqual(code, 1)
        self.assertEqual(self.probes[-1], ["grok"])
        self.assertIsNone(result["agents"]["grok"]["headroom_pct"])
        self.assertEqual(result["failed_agents"], ["grok"])

    def test_expired_or_future_readings_require_fresh_measurement(self):
        for at in ("2026-10-21T01:15:00+00:00", "2026-10-21T00:59:00+00:00"):
            with self.subTest(at=at):
                self.invoke()
                _, result, _ = self.invoke("--retry-failed", at=at)
                self.assertEqual(self.probes[-1], ["claude", "codex", "grok"])
                self.assertEqual(result["reused_agents"], [])
                self.assertEqual(result["measured_at"], at)

    def test_changed_account_window_or_transport_invalidates_reuse(self):
        self.invoke()
        config = json.loads(self.config.read_text())
        config["worker_kinds"][0]["window_group"] = "changed-account"
        self.config.write_text(json.dumps(config))
        _, result, _ = self.invoke("--retry-failed", at=RETRY)
        self.assertEqual(result["reused_agents"], [])
        self.assertEqual(self.probes[-1], ["claude", "codex", "grok"])
        self.client = HerdrClient(binary="different-herdr")
        _, result, _ = self.invoke("--retry-failed", at=RETRY)
        self.assertEqual(result["reused_agents"], [])

    def test_skipped_profile_is_retried(self):
        self.skipped = {"claude"}
        self.invoke()
        self.skipped.clear()
        _, result, _ = self.invoke("--retry-failed", at=RETRY)
        self.assertEqual(self.probes[-1], ["claude"])
        self.assertEqual(result["reused_agents"], ["codex", "grok"])

    def test_shared_window_members_are_remeasured_together(self):
        config = json.loads(self.config.read_text())
        for profile in config["worker_kinds"][:2]:
            profile["window_group"] = "shared-account-window"
        self.config.write_text(json.dumps(config))
        self.failures = {"claude"}
        self.invoke()
        self.failures.clear()
        self.invoke("--retry-failed", at=RETRY)
        self.assertEqual(self.probes[-1], ["claude", "codex"])

    def test_older_snapshot_without_context_proof_is_not_reused(self):
        self.invoke()
        state = json.loads(self.state.read_text())
        prior = state["snapshots"][-1]
        prior["schema_version"] = 5
        del prior["measurement_context_sha256"], prior["reused_agents"]
        self.state.write_text(json.dumps(state))
        _, result, _ = self.invoke("--retry-failed", at=RETRY)
        self.assertEqual(result["reused_agents"], [])
        self.assertEqual(self.probes[-1], ["claude", "codex", "grok"])

    def test_newer_state_refuses_before_any_probe_and_preserves_its_bytes(self):
        self.invoke()
        state = json.loads(self.state.read_text())
        state["snapshots"][-1]["schema_version"] = SNAPSHOT_SCHEMA_VERSION + 1
        original = json.dumps(state).encode()
        self.state.write_bytes(original)
        count = len(self.probes)
        self.assertEqual(self.invoke("--retry-failed", at=RETRY)[0], 1)
        self.assertEqual(len(self.probes), count)
        self.assertEqual(self.state.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
