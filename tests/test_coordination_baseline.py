"""Paired delays, unknowns and evidenced outcomes survive baseline aggregation."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.coordination_baseline import summarize


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
        data["assignments"][0].update(assessed_at="2026-10-10T01:01:00Z", resolved_at="2026-10-10T01:05:00Z")
        data["assignments"].append({"id": "c", "task_id": "two", "native_match": "matched",
            "dispatched_at": "2026-10-10T00:40:00Z", "native_completed_at": "2026-10-10T00:50:00Z"})
        result = summarize(data)
        for queue in result["waiting"].values():
            self.assertEqual(queue["pending_age_seconds"], {"n": 2, "median": 1950, "p90": 3300})
            self.assertEqual([row["assignment_id"] for row in queue["oldest"]], ["a", "c"])
            self.assertEqual(queue["wait_task_seconds"], 3900)
            self.assertEqual(queue["covered_tasks"], 2)
        self.assertEqual(result["coverage"]["task_states"]["blocked"], 1)

    def test_unmeasured_and_inconsistent_waits_are_named_and_excluded(self):
        data = fixture()
        data["assignments"][0]["resolved_at"] = "2026-10-10T00:04:00Z"
        data["assignments"].extend([
            {"id": "c", "task_id": "one", "native_match": "matched", "dispatched_at": "2026-10-10T00:10:00Z",
             "native_completed_at": "2026-10-10T01:10:00Z"},
            {"id": "d", "task_id": "two", "native_match": "matched", "dispatched_at": "2026-10-10T00:20:00Z"}])
        queue = summarize(data)["waiting"]["resolution"]
        self.assertEqual(queue["excluded"], {"reversed_clock": 1, "unknown_native": 1,
            "future_completion": 1, "missing_completion": 1})
        self.assertEqual(queue["pending_age_seconds"]["n"], 0)
        self.assertEqual(queue["wait_task_seconds"], 0)

    def test_oldest_pending_rows_are_bounded_without_dropping_the_count(self):
        data = fixture()
        data["assignments"].extend({"id": "c{:02d}".format(i), "task_id": "one", "native_match": "matched",
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
        data["assignments"][0].update(dispatched_at="2026-10-09T23:40:00Z",
            native_started_at="2026-10-09T23:45:00Z", native_completed_at="2026-10-09T23:50:00Z")
        data["assignments"][0].pop("resolved_at")
        queue = summarize(data)["waiting"]["resolution"]
        self.assertEqual(queue["pending_age_seconds"]["median"], 4200)
        self.assertEqual(queue["wait_task_seconds"], 3600)

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

    def test_summary_does_not_forward_unexpected_source_metadata(self):
        data = fixture()
        data["window"]["private_source_path"] = "private-window-metadata"
        data["tasks"][1]["holds"][0]["raw_transcript"] = "private-hold-metadata"
        result = json.dumps(summarize(data))
        self.assertNotIn("private-window-metadata", result)
        self.assertNotIn("private-hold-metadata", result)


if __name__ == "__main__":
    unittest.main()
