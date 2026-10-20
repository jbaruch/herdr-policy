"""Installed collection preserves evidence, unknowns, privacy and bounded output."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_owner_baseline import producer
from test_owner_baseline_export import END, IDENTITY, START, inputs


class MeasurementCaptureTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner, self.supervision, self.output = (self.root / name for name in
                                                   ("owner.json", "supervision.json", "report.json"))
        self.codex = self.root / "native"
        self.environment = patch.dict(os.environ, {"CODEX_HOME": str(self.codex)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.native = self.codex / "sessions/2026/10/10" / ("rollout-fixture-" + IDENTITY["value"] + ".jsonl")
        self.native.parent.mkdir(parents=True)
        final = "Private transcript material.\n\nREPORT: /private/worker-report.md"
        rows = [{"type": "session_meta", "payload": {"id": IDENTITY["value"]}},
                {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "fixture-turn"},
                 "timestamp": "2026-10-10T00:02:00Z"},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer",
                 "content": [{"type": "output_text", "text": final}]}},
                {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "fixture-turn",
                 "last_agent_message": final}, "timestamp": "2026-10-10T00:07:00Z"}]
        self.native.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        self.source_owner, self.source_supervision = inputs()
        self.source_supervision["state_path"] = str(self.owner)
        self.ledger = self.root / "assessment.md"
        header = ("---\nschema_version: 1\ntask: private-task\nbase_revision: " + "a" * 40
                  + "\ndispatch_state: " + str(self.owner) + "\n---\n\n# Task Ledger\n\n")
        event = {"schema_version": 1, "id": "assessment-1", "at": "2026-10-10T00:12:00Z", "subject": "assignment",
                 "dispatch_id": "private-dispatch", "worker": "private-worker", "role": "reviewer",
                 "report": "/private/worker-report.md", "observed": "report delivered", "decision": "accepted",
                 "head_revision": "a" * 40, "evidence": "/private/worker-report.md", "assessment": "read in full"}
        self.ledger.write_text(header + "## assessment-1\n\n"
                               + "".join("- {}: {}\n".format(key, value) for key, value in event.items()) + "\n")
        body = self.ledger.read_bytes()
        self.source_supervision["members"][0]["resolution"]["evidence"] = [
            {"schema_version": 1, "path": str(self.ledger), "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}]
        self.save_inputs()

    def save_inputs(self):
        self.owner.write_text(json.dumps(self.source_owner))
        self.supervision.write_text(json.dumps(self.source_supervision))

    def arguments(self, *extra):
        return ["--owner", str(self.owner), "--supervision", str(self.supervision),
                "--start", START.isoformat(), "--end", END.isoformat(), *map(str, extra)]

    def collect(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = producer.main(self.arguments(*extra))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_verified_native_assessment_and_resolution_have_paired_latencies_without_source_changes(self):
        before = {path: path.read_bytes() for path in (self.owner, self.supervision, self.native, self.ledger)}
        status, stdout, stderr = self.collect()
        self.assertEqual((status, stderr), (0, ""))
        result = json.loads(stdout)
        self.assertEqual((result["schema_version"], result["kind"]), (1, "coordination_capture_summary"))
        self.assertIs(result["authorizes_progression"], False)
        summary = result["summary"]
        self.assertEqual(summary["coverage"]["native_match"], {"matched": 1})
        for stage, seconds in (("native_work", 300), ("completion_to_assessment", 300), ("completion_to_resolution", 780)):
            self.assertEqual(summary["latency_seconds"][stage], {"n": 1, "median": seconds, "p90": seconds, "excluded": {}})
        self.assertEqual(summary["outcomes"], {stage: {"evidenced": 0, "unmeasured": 1}
                                              for stage in ("integration", "deployment", "acceptance")})
        self.assertEqual(summary["effort"]["foreman"]["output_bytes"]["unknown"], 1)
        self.assertEqual(result["exclusions"], {})
        for private in ("private-task", "private-dispatch", "Private transcript", str(self.ledger), "private instruction"):
            self.assertNotIn(private, stdout)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse(self.output.exists())

    def test_private_report_contains_replayable_sanitized_snapshot_and_bound_provenance(self):
        status, stdout, stderr = self.collect("--output", self.output)
        self.assertEqual((status, stderr), (0, ""))
        receipt, body = json.loads(stdout), self.output.read_bytes()
        report = json.loads(body)
        self.assertEqual((receipt["kind"], report["kind"]), ("coordination_capture_receipt", "coordination_capture_report"))
        self.assertEqual(receipt["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(receipt["bytes"], len(body))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual(report["summary"], producer.calculator.summarize(report["snapshot"]))
        self.assertEqual(report["snapshot_sha256"], hashlib.sha256(producer.calculator.encoded(report["snapshot"])).hexdigest())
        proof = report["provenance"]
        self.assertEqual(proof["schema_version"], 3)
        self.assertEqual(proof["owner_sha256"], hashlib.sha256(self.owner.read_bytes()).hexdigest())
        self.assertEqual(proof["supervision_sha256"], hashlib.sha256(self.supervision.read_bytes()).hexdigest())
        assert producer.__file__ is not None
        self.assertEqual(proof["exporter_sha256"], hashlib.sha256(Path(producer.__file__).read_bytes()).hexdigest())
        self.assertEqual(set(proof["evidence_sha256"]), {hashlib.sha256(path.read_bytes()).hexdigest()
                                                       for path in (self.native, self.ledger)})
        for private in ("Private transcript", "private-task", str(self.ledger), "private instruction"):
            self.assertNotIn(private, body.decode())
        before = self.output.stat().st_mtime_ns
        self.assertEqual(self.collect("--output", self.output), (status, stdout, stderr))
        self.assertEqual(self.output.stat().st_mtime_ns, before)
        self.source_supervision["holds"] = []
        self.save_inputs()
        refused, printed, diagnostic = self.collect("--output", self.output)
        self.assertEqual((refused, printed), (2, ""))
        self.assertIn("private report destination", diagnostic)
        self.assertEqual(self.output.read_bytes(), body)

    def test_bad_owner_inputs_refuse_without_echoing_private_contents_or_writing_report(self):
        for body in (b'{"schema_version":"private-auth-value"}', b'[{"private-auth-value"',
                     b'[' * 2000 + b'0' + b']' * 2000, b' ' * (producer.MAX_OWNER_BYTES + 1)):
            with self.subTest(bytes=len(body)):
                self.owner.write_bytes(body)
                status, printed, diagnostic = self.collect("--output", self.output)
                self.assertEqual((status, printed), (2, ""))
                self.assertIn("preserve source evidence", diagnostic)
                self.assertNotIn("private-auth-value", diagnostic)
                self.assertNotIn("Traceback", diagnostic)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.owner.read_bytes(), body)

    def test_fifo_and_symlink_inputs_refuse_without_opening_their_targets(self):
        original = self.owner.read_bytes()
        self.owner.unlink()
        os.mkfifo(self.owner)
        self.assertEqual(self.collect()[:2], (2, ""))
        self.owner.unlink()
        self.owner.symlink_to(self.supervision)
        supervision = self.supervision.read_bytes()
        self.assertEqual(self.collect()[:2], (2, ""))
        self.assertEqual(self.supervision.read_bytes(), supervision)
        self.owner.unlink()
        self.owner.write_bytes(original)

    def test_native_budget_or_unbound_final_remains_unknown_with_named_exclusions(self):
        for case in ("budget", "unbound"):
            with self.subTest(case=case):
                if case == "unbound":
                    self.native.write_text(self.native.read_text().replace("/private/worker-report.md", "/another/report.md"))
                with patch.object(producer, "MAX_NATIVE_BYTES", 1 if case == "budget" else 67_108_864):
                    status, stdout, stderr = self.collect()
                self.assertEqual((status, stderr), (0, ""))
                result = json.loads(stdout)
                self.assertEqual(result["summary"]["coverage"]["native_match"], {"unknown": 1})
                reason = "native_source_exceeds_budget" if case == "budget" else "native_final_not_bound_to_report"
                self.assertEqual(result["exclusions"], {reason: 1})
                self.assertEqual(result["summary"]["latency_seconds"]["native_work"]["n"], 0)

    def test_ledger_prefix_and_total_read_budgets_leave_assessment_unmeasured(self):
        for limit, value in (("MAX_LEDGER_BYTES", 1), ("MAX_EVIDENCE_BYTES", len(self.native.read_bytes()))):
            with self.subTest(limit=limit), patch.object(producer, limit, value):
                status, stdout, stderr = self.collect()
            self.assertEqual((status, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["summary"]["coverage"]["native_match"], {"matched": 1})
            self.assertEqual(result["exclusions"], {"ledger_receipt_exceeds_budget": 1})
            self.assertEqual(result["summary"]["waiting"]["assessment"]["excluded"], {"unmeasured_endpoint": 1})

    def test_rejected_native_read_consumes_allowance_before_subsequent_attempts(self):
        original = self.native.read_bytes()
        with patch.object(producer, "MAX_NATIVE_BYTES", len(original)), \
                patch.object(producer, "MAX_EVIDENCE_BYTES", 2 * len(original)):
            reader = producer.EvidenceReader(ROOT)
            self.native.write_bytes(original + b" ")
            self.assertEqual(reader.native(IDENTITY, "/private/worker-report.md", START, END), {})
            self.native.write_bytes(original)
            self.assertIn("native_completed_at", reader.native(IDENTITY, "/private/worker-report.md", START, END))
            self.assertEqual(reader.native(IDENTITY, "/private/worker-report.md", START, END), {})
            self.assertEqual(reader.exclusions, {"native_source_exceeds_budget": 2})

    def test_large_summary_uses_one_private_report_without_dropping_held_cohort(self):
        self.source_supervision["holds"] *= 1000
        self.save_inputs()
        status, stdout, stderr = self.collect()
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("--output", stderr)
        status, stdout, stderr = self.collect("--output", self.output)
        self.assertEqual((status, stderr), (0, ""))
        self.assertLessEqual(len(stdout.encode()), producer.calculator.OUTPUT_BYTES)
        report = json.loads(self.output.read_bytes())
        self.assertEqual(len(report["summary"]["holds"]), 1000)
        self.assertEqual(len(report["snapshot"]["tasks"][0]["holds"]), 1000)

    def test_output_preserves_repository_files_and_foreign_symlink_targets(self):
        for output in (ROOT / "measurement-capture-report.json", self.output):
            with self.subTest(output=output.name):
                if output == self.output:
                    self.output.symlink_to(self.owner)
                before = self.owner.read_bytes()
                status, stdout, stderr = self.collect("--output", output)
                self.assertEqual((status, stdout), (2, ""))
                self.assertIn("preserve source evidence", stderr)
                self.assertEqual(self.owner.read_bytes(), before)
                if output != self.output:
                    self.assertFalse(output.exists())

    def test_renamed_installed_skill_collects_without_development_files_or_bytecode_writes(self):
        skill = self.root / "consumer/.agents/skills/acr__jbaruch__herdr-policy__herdr-foreman"
        shutil.copytree(ROOT / "skills/herdr-foreman/foreman", skill / "foreman",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        shutil.copyfile(ROOT / "skills/herdr-foreman/measurements.py", skill / "measurements.py")
        before = {p.relative_to(skill): p.read_bytes() for p in skill.rglob("*") if p.is_file()}
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT", "CODEX_HOME"}}
        result = subprocess.run([sys.executable, str(skill / "measurements.py"), "collect", *self.arguments()],
                                env=environment, cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summary"]["coverage"]["native_match"], {"matched": 1})
        self.assertEqual({p.relative_to(skill): p.read_bytes() for p in skill.rglob("*") if p.is_file()}, before)


if __name__ == "__main__":
    unittest.main()
