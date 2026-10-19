"""Paired delays, unknowns and evidenced outcomes survive baseline aggregation."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/herdr-foreman"))
from scripts.coordination_baseline import summarize
from foreman.coordination_metrics import MAX_SNAPSHOT_BYTES
from foreman.context_output import OUTPUT_BYTES


def fixture():
    return {"schema": 1, "window": {"start": "2026-10-10T00:00:00Z", "end": "2026-10-10T01:00:00Z"},
            "tasks": [{"id": "one", "state": "integrated", "class": "bounded", "risk": "low",
                       "integration": {"at": "2026-10-10T00:20:00Z", "evidence": ["fixture:commit"]},
                       "foreman": {"output_bytes": 600}, "rework_rounds": 1, "escaped_defects": 0},
                      {"id": "two", "state": "blocked", "class": "complex", "risk": "high",
                       "acceptance": {"at": "2026-10-10T00:30:00Z", "evidence": []},
                       "foreman": {"output_bytes": 400},
                       "holds": [{"start": "2026-10-10T00:10:00Z", "end": None, "reason": "operator"}]}],
            "assignments": [{"id": "a", "task_id": "one", "native_match": "matched",
                             "dispatched_at": "2026-10-10T00:00:00Z", "native_started_at": "2026-10-10T00:00:00Z",
                             "native_completed_at": "2026-10-10T00:05:00Z", "assessed_at": "2026-10-10T00:15:00Z",
                             "resolved_at": "2026-10-10T00:25:00Z", "report_bytes": 100},
                            {"id": "b", "task_id": "two", "native_match": "unknown",
                             "dispatched_at": "2026-10-10T00:02:00Z", "report_bytes": None}],
            "activity_minutes": ["2026-10-10T00:03:00Z", "2026-10-10T00:06:00Z"]}


class BaselineTest(unittest.TestCase):
    def command(self, snapshot, *arguments, cwd=None):
        return subprocess.run([sys.executable, str(ROOT / "skills/herdr-foreman/measurements.py"),
                               str(snapshot), *(str(value) for value in arguments)],
                              capture_output=True, text=True, cwd=cwd, timeout=20)

    def test_summary_versions_its_new_shape_and_accepts_the_original_input(self):
        data = fixture()
        result = summarize(data)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(result["schema"], 2)
        self.assertEqual(set(result["waiting"]), {"assessment", "resolution"})

    def test_paired_delays_keep_denominators_and_overlapping_waits_separate(self):
        result = summarize(fixture())
        latency = result["latency_seconds"]
        self.assertEqual(latency["native_work"]["median"], 300)
        self.assertEqual(latency["completion_to_assessment"]["median"], 600)
        self.assertEqual(latency["completion_to_resolution"]["median"], 1200)
        self.assertEqual(latency["completion_to_resolution"]["n"], 1)
        self.assertEqual(latency["completion_to_resolution"]["excluded"], {"unknown_native": 1})

    def test_unknown_native_remains_possibly_busy_and_missing_effort_is_not_zero(self):
        result = summarize(fixture())
        self.assertEqual(result["activity"]["mean_possibly_busy_envelopes"], 1.5)
        self.assertEqual(result["activity"]["zero_possibly_busy_minutes"], 0)
        self.assertEqual(result["effort"]["report_bytes"], {"known": 1, "unknown": 1, "total": 100})
        self.assertEqual(result["coverage"]["task_states"], {"integrated": 1, "blocked": 1})
        self.assertEqual(result["holds"][0]["reason"], "operator")

    def test_overlapping_waits_are_counted_once_per_task_in_each_queue(self):
        data = fixture()
        data["assignments"].append({"id": "c", "task_id": "one", "native_match": "matched",
            "dispatched_at": "2026-10-10T00:00:00Z", "native_completed_at": "2026-10-10T00:10:00Z",
            "assessed_at": "2026-10-10T00:20:00Z", "resolved_at": "2026-10-10T00:35:00Z"})
        queues = summarize(data)["waiting"]
        self.assertEqual(queues["assessment"]["wait_task_seconds"], 900)
        self.assertEqual(queues["resolution"]["wait_task_seconds"], 1800)
        self.assertEqual(queues["resolution"]["covered_tasks"], 1)
        self.assertEqual(queues["resolution"]["pending_age_seconds"]["n"], 0)
        self.assertEqual(queues["resolution"]["excluded"], {"unknown_native": 1})

    def test_pending_ages_use_the_observation_boundary_and_retain_blocked_work(self):
        data = fixture()
        data["schema"] = 2
        data["assignments"][0].update(assessed_at="2026-10-10T01:01:00Z", resolved_at="2026-10-10T01:05:00Z")
        data["assignments"].append({"id": "c", "task_id": "two", "native_match": "matched",
            "assessment_state": "pending", "resolution_state": "pending",
            "dispatched_at": "2026-10-10T00:40:00Z", "native_completed_at": "2026-10-10T00:50:00Z"})
        result = summarize(data)
        for queue in result["waiting"].values():
            self.assertEqual(queue["pending_age_seconds"], {"n": 2, "median": 1950, "p90": 3300})
            self.assertEqual([row["assignment_id"] for row in queue["oldest"]], ["a", "c"])
            self.assertEqual(queue["wait_task_seconds"], 3900)
            self.assertEqual(queue["covered_tasks"], 2)
        for name in ("completion_to_assessment", "completion_to_resolution"):
            self.assertEqual(result["latency_seconds"][name]["n"], 0)
            self.assertEqual(result["latency_seconds"][name]["excluded"],
                {"future_endpoint": 1, "unknown_native": 1, "missing_endpoint": 1})
        self.assertEqual(result["coverage"]["task_states"]["blocked"], 1)

    def test_unmeasured_and_inconsistent_waits_are_named_and_excluded(self):
        data = fixture()
        data["assignments"][0]["resolved_at"] = "2026-10-10T00:04:00Z"
        data["assignments"].extend([
            {"id": "c", "task_id": "one", "native_match": "matched", "dispatched_at": "2026-10-10T00:10:00Z",
             "native_started_at": "2026-10-10T00:10:00Z",
             "native_completed_at": "2026-10-10T01:10:00Z"},
            {"id": "d", "task_id": "two", "native_match": "matched", "dispatched_at": "2026-10-10T00:20:00Z"}])
        result = summarize(data)
        queue = result["waiting"]["resolution"]
        self.assertEqual(queue["excluded"], {"reversed_clock": 1, "unknown_native": 1,
            "future_completion": 1, "missing_completion": 1})
        self.assertEqual(queue["pending_age_seconds"]["n"], 0)
        self.assertEqual(queue["wait_task_seconds"], 0)
        self.assertEqual(result["latency_seconds"]["native_work"]["excluded"],
            {"unknown_native": 1, "future_endpoint": 1, "missing_endpoint": 1})

    def test_oldest_pending_rows_are_bounded_without_dropping_the_count(self):
        data = fixture()
        data["schema"] = 2
        data["assignments"].extend({"id": "c{:02d}".format(i), "task_id": "one", "native_match": "matched",
            "assessment_state": "pending", "resolution_state": "pending",
            "dispatched_at": "2026-10-10T00:00:00Z", "native_completed_at": "2026-10-10T00:01:00Z"}
            for i in range(25))
        queue = summarize(data)["waiting"]["resolution"]
        self.assertEqual(queue["pending_age_seconds"]["n"], 25)
        self.assertEqual(len(queue["oldest"]), 10)
        self.assertEqual(queue["omitted_pending"], 15)
        self.assertEqual(queue["wait_task_seconds"], 3540)
        self.assertEqual(queue["oldest"][0]["assignment_id"], "c00")

    def test_wait_exposure_is_clipped_but_pending_age_keeps_its_original_start(self):
        data = fixture()
        data["schema"] = 2
        data["assignments"][0].update(dispatched_at="2026-10-09T23:40:00Z",
            native_started_at="2026-10-09T23:45:00Z", native_completed_at="2026-10-09T23:50:00Z")
        data["assignments"][0].pop("resolved_at")
        data["assignments"][0]["resolution_state"] = "pending"
        queue = summarize(data)["waiting"]["resolution"]
        self.assertEqual(queue["pending_age_seconds"]["median"], 4200)
        self.assertEqual(queue["wait_task_seconds"], 3600)

    def test_missing_legacy_endpoints_remain_unmeasured_even_after_resolution(self):
        data = fixture()
        data["assignments"][0].pop("assessed_at")
        queue = summarize(data)["waiting"]["assessment"]
        self.assertEqual(queue["pending_age_seconds"]["n"], 0)
        self.assertEqual(queue["covered_tasks"], 0)
        self.assertEqual(queue["excluded"], {"unmeasured_endpoint": 1, "unknown_native": 1})
        data["assignments"][0].pop("resolved_at")
        self.assertEqual(summarize(data)["waiting"]["resolution"]["pending_age_seconds"]["n"], 0)

    def test_completed_without_a_measured_time_is_not_a_pending_queue(self):
        data = fixture()
        data["schema"] = 2
        data["assignments"][0].pop("assessed_at")
        data["assignments"][0]["assessment_state"] = "completed"
        queue = summarize(data)["waiting"]["assessment"]
        self.assertEqual(queue["pending_age_seconds"]["n"], 0)
        self.assertEqual(queue["excluded"]["unmeasured_endpoint"], 1)

    def test_invalid_or_contradictory_queue_states_are_rejected(self):
        for state in ("pending", "unmeasured", "unsupported", 1):
            data = fixture()
            data["schema"] = 2
            data["assignments"][0]["assessment_state"] = state
            with self.subTest(state=state), self.assertRaises(ValueError):
                summarize(data)

    def test_assessment_subset_has_its_own_denominator_and_tail(self):
        data = fixture()
        data["assignments"].append({"id": "c", "task_id": "one", "native_match": "matched",
                                    "dispatched_at": "2026-10-10T00:06:00Z",
                                    "native_started_at": "2026-10-10T00:06:00Z",
                                    "native_completed_at": "2026-10-10T00:11:00Z",
                                    "resolved_at": "2026-10-10T00:41:00Z"})
        latency = summarize(data)["latency_seconds"]
        self.assertEqual(latency["completion_to_assessment"]["n"], 1)
        self.assertEqual(latency["completion_to_resolution"]["n"], 2)
        self.assertEqual(latency["completion_to_resolution"]["median"], 1500)
        self.assertEqual(latency["completion_to_resolution"]["p90"], 1800)
        self.assertEqual(latency["completion_to_assessment"]["excluded"], {"unknown_native": 1, "missing_endpoint": 1})

    def test_integration_is_not_deployment_or_acceptance(self):
        data = fixture()
        result = summarize(data)
        self.assertEqual(result["outcomes"]["integration"]["evidenced"], 1)
        self.assertEqual(result["outcomes"]["acceptance"]["evidenced"], 0)
        self.assertIsNone(result["effort"]["foreman_output_bytes_per_accepted"])
        data["tasks"][0]["acceptance"] = {"at": "2026-10-10T00:40:00Z", "evidence": ["fixture:readback"]}
        self.assertEqual(summarize(data)["effort"]["foreman_output_bytes_per_accepted"], 1000)
        data["tasks"][1]["foreman"].pop("output_bytes")
        self.assertIsNone(summarize(data)["effort"]["foreman_output_bytes_per_accepted"])

    def test_missing_and_reversed_clock_pairs_remain_visible(self):
        data = fixture()
        data["assignments"][0]["assessed_at"] = "2026-10-10T00:04:00Z"
        data["assignments"][0].pop("resolved_at")
        result = summarize(data)["latency_seconds"]
        self.assertEqual(result["completion_to_assessment"]["excluded"], {"reversed_clock": 1, "unknown_native": 1})
        self.assertEqual(result["completion_to_resolution"]["excluded"], {"missing_endpoint": 1, "unknown_native": 1})

    def test_invalid_or_duplicate_records_are_rejected(self):
        for mutation in (lambda d: d["tasks"].append(copy.deepcopy(d["tasks"][0])),
                         lambda d: d["activity_minutes"].append(d["activity_minutes"][0]),
                         lambda d: d["tasks"][0]["foreman"].update(output_bytes=-1),
                         lambda d: d["window"].update(start="2026-10-10T00:00:00")):
            data = fixture()
            mutation(data)
            with self.assertRaises(ValueError):
                summarize(data)

    def test_cli_failure_emits_diagnostic_without_a_measurement(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "snapshot.json"
            path.write_text(json.dumps({"schema": 999}))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/coordination_baseline.py"), str(path)], capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertIn("repair the snapshot", result.stderr)

    def test_native_entrypoint_matches_the_repository_wrapper_outside_the_checkout(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "snapshot.json"
            path.write_text(json.dumps(fixture()))
            native = self.command(path, cwd=scratch)
            legacy = subprocess.run([sys.executable, str(ROOT / "scripts/coordination_baseline.py"), str(path)],
                                    capture_output=True, text=True, cwd=scratch)
            self.assertEqual((native.returncode, legacy.returncode), (0, 0))
            self.assertEqual(native.stdout, legacy.stdout)
            result = json.loads(native.stdout)
            self.assertEqual(result["schema"], 2)
            self.assertIs(result["authorizes_progression"], False)
            self.assertEqual(result["coverage"]["tasks"], 2)

    def test_summary_entrypoints_leave_fresh_payloads_unchanged_without_bytecode_environment_flags(self):
        for command in ("native", "compatibility"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                clone = root / "source"
                skill = clone / "skills/herdr-foreman"
                shutil.copytree(ROOT / "skills/herdr-foreman/foreman", skill / "foreman",
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
                shutil.copyfile(ROOT / "skills/herdr-foreman/measurements.py", skill / "measurements.py")
                (clone / "scripts").mkdir()
                shutil.copyfile(ROOT / "scripts/coordination_baseline.py", clone / "scripts/coordination_baseline.py")
                path = root / "snapshot.json"
                path.write_text(json.dumps(fixture()))
                before = {p.relative_to(clone) for p in clone.rglob("*")}
                environment = dict(os.environ)
                environment.pop("PYTHONDONTWRITEBYTECODE", None)
                entrypoint = skill / "measurements.py" if command == "native" else clone / "scripts/coordination_baseline.py"
                result = subprocess.run([sys.executable, str(entrypoint), str(path)], capture_output=True,
                                        text=True, cwd=root, env=environment, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["schema"], 2)
                self.assertEqual({p.relative_to(clone) for p in clone.rglob("*")}, before)

    def test_reports_preserve_foreign_tessl_native_and_manifest_owned_packages(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            path = root / "snapshot.json"
            path.write_text(json.dumps(fixture()))
            relative = ["global/.tessl/plugins/other/package", "global/.codex/skills/acr__other__package__skill",
                        "global/.claude/plugins/cache/other/package", "global/.cursor/skills/other",
                        "global/.agents/skills/other", "other-manifest-package", "other-skill"]
            for selected in relative:
                with self.subTest(package=selected):
                    package = root / selected
                    package.mkdir(parents=True)
                    if selected == "other-manifest-package":
                        (package / "agent-plugin.yaml").write_text("schemaVersion: 1\n")
                    if selected == "other-skill":
                        (package / "SKILL.md").write_text("# Another installed skill\n")
                    sentinel = package / "original.txt"
                    sentinel.write_bytes(b"Other owner bytes.\n")
                    output = package / "measurement-report.json"
                    result = self.command(path, "--output", output, cwd=root)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))
                    self.assertIn("outside repositories and installed code", result.stderr)
                    self.assertFalse(output.exists())
                    self.assertEqual(sentinel.read_bytes(), b"Other owner bytes.\n")

    def test_large_reports_keep_the_full_cohort_and_return_only_a_private_receipt(self):
        with tempfile.TemporaryDirectory() as scratch:
            path, output = Path(scratch) / "snapshot.json", Path(scratch) / "report.json"
            data = fixture()
            data["tasks"][1]["holds"] *= 1000
            path.write_text(json.dumps(data))
            refused = self.command(path)
            self.assertEqual((refused.returncode, refused.stdout), (2, ""))
            self.assertIn("--output", refused.stderr)
            saved = self.command(path, "--output", output)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertLessEqual(len(saved.stdout.encode()), OUTPUT_BYTES)
            receipt = json.loads(saved.stdout)
            report_bytes = output.read_bytes()
            report = json.loads(report_bytes)
            self.assertEqual((receipt["schema_version"], report["schema_version"]), (1, 1))
            self.assertEqual(receipt["sha256"], hashlib.sha256(report_bytes).hexdigest())
            self.assertEqual(receipt["bytes"], len(report_bytes))
            self.assertEqual(report["snapshot_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(report["producer"]["schema_version"], 1)
            self.assertEqual(report["producer"]["python"], sys.version.split()[0])
            self.assertEqual(report["producer"]["calculator_sha256"], hashlib.sha256(
                (ROOT / "skills/herdr-foreman/foreman/coordination_metrics.py").read_bytes()).hexdigest())
            self.assertEqual(report["summary"]["coverage"]["tasks"], 2)
            self.assertEqual(len(report["summary"]["holds"]), 1000)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            before = output.stat().st_mtime_ns
            repeated = self.command(path, "--output", output)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(repeated.stdout, saved.stdout)
            self.assertEqual(output.stat().st_mtime_ns, before)
            output.write_bytes(report_bytes + b"Changed after measurement.\n")
            changed = output.read_bytes()
            preserved = self.command(path, "--output", output)
            self.assertEqual((preserved.returncode, preserved.stdout), (2, ""))
            self.assertEqual(output.read_bytes(), changed)

    def test_oversized_input_refuses_before_creating_an_output(self):
        with tempfile.TemporaryDirectory() as scratch:
            path, output = Path(scratch) / "snapshot.json", Path(scratch) / "report.json"
            path.write_bytes(b" " * (MAX_SNAPSHOT_BYTES + 1))
            result = self.command(path, "--output", output)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertIn("input budget", result.stderr)
            self.assertFalse(output.exists())

    def test_nonregular_input_refuses_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "snapshot.pipe"
            os.mkfifo(path)
            result = self.command(path)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertIn("regular JSON snapshot", result.stderr)

    def test_deeply_nested_input_emits_an_actionable_diagnostic_without_a_report(self):
        with tempfile.TemporaryDirectory() as scratch:
            path, output = Path(scratch) / "snapshot.json", Path(scratch) / "report.json"
            path.write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
            result = self.command(path, "--output", output)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertIn("repair the snapshot", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_report_outputs_refuse_repository_paths(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "snapshot.json"
            path.write_text(json.dumps(fixture()))
            result = self.command(path, "--output", ROOT)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertIn("outside repositories", result.stderr)

    def test_report_outputs_preserve_symlink_targets(self):
        with tempfile.TemporaryDirectory() as scratch:
            path, output = Path(scratch) / "snapshot.json", Path(scratch) / "report.json"
            target = Path(scratch) / "foreign.json"
            path.write_text(json.dumps(fixture()))
            target.write_bytes(b"Private foreign bytes.\n")
            output.symlink_to(target)
            result = self.command(path, "--output", output)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertEqual(target.read_bytes(), b"Private foreign bytes.\n")
            self.assertTrue(output.is_symlink())

    def test_report_outputs_refuse_another_repository_from_a_private_working_directory(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            path, repo = root / "snapshot.json", root / "other-repository"
            path.write_text(json.dumps(fixture()))
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            output = repo / "report.json"
            result = self.command(path, "--output", output, cwd=root)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertIn("outside repositories", result.stderr)
            self.assertFalse(output.exists())

    def test_nonfinite_aggregate_refuses_without_a_partial_report(self):
        for value in (1e308, 10 ** 1000):
            with self.subTest(value_type=type(value).__name__), tempfile.TemporaryDirectory() as scratch:
                path, output = Path(scratch) / "snapshot.json", Path(scratch) / "report.json"
                data = fixture()
                data["tasks"][0]["acceptance"] = {"at": "2026-10-10T00:40:00Z", "evidence": ["fixture:readback"]}
                for task in data["tasks"]:
                    task["foreman"]["output_bytes"] = value
                path.write_text(json.dumps(data))
                result = self.command(path, "--output", output)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertIn("repair the snapshot", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(output.exists())

    def test_summary_does_not_forward_unexpected_source_metadata(self):
        data = fixture()
        data["window"]["private_source_path"] = "private-window-metadata"
        data["tasks"][1]["holds"][0]["raw_transcript"] = "private-hold-metadata"
        result = json.dumps(summarize(data))
        self.assertNotIn("private-window-metadata", result)
        self.assertNotIn("private-hold-metadata", result)


if __name__ == "__main__":
    unittest.main()
