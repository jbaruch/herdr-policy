"""Capacity classifications; native transaction behavior has service fixtures."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import json
import unittest

from foreman import recovery, workflow_capacity as capacity
from foreman.errors import ConfigError
from foreman.state import empty_state

AT = "2026-10-19T12:00:00Z"
LATER = "2026-10-19T12:01:00Z"


def declaration():
    return {"schema_version": 9, "backpressure": {
        "schema_version": 1, "global": {"in_flight": 2, "integration": 1},
        "repositories": {}, "exceptions": [], "rationale": "Explicit fixture limits."}}


class CapacityTest(unittest.TestCase):
    def setUp(self):
        self.state = empty_state()
        self.supervised = {"members": []}
        self.configuration = declaration()

    def reserve(self, task="old", *, identifier="d1", role="developer", status="prepared"):
        self.state["recovery"]["dispatches"].append({"id": identifier, "task": task,
            "role": role, "status": status, "fix_round": None})

    def decide(self, task="new", *, families=None):
        return capacity.evaluate(self.state, self.supervised, task, "fixture/repository",
            capacity.parse_policy(self.configuration), AT, family=lambda name: (families or {}).get(name))

    def test_existing_configuration_does_not_invent_capacity_limits(self):
        self.assertIsNone(capacity.parse_policy({"schema_version": 8}))

    def test_backpressure_cannot_be_silently_ignored_by_an_old_reader(self):
        self.configuration["schema_version"] = 8
        with self.assertRaises(ConfigError):
            capacity.parse_policy(self.configuration)

    def test_invalid_thresholds_are_not_disabled_limits(self):
        for value in (True, 0, -1, 1.5, "2", 1 << 63):
            with self.subTest(value=value):
                self.configuration["backpressure"]["global"]["in_flight"] = value
                with self.assertRaises(ConfigError):
                    capacity.parse_policy(self.configuration)

    def test_repository_aliases_cannot_define_conflicting_limits(self):
        self.configuration["backpressure"]["repositories"] = {
            "Fixture/Repository": {"in_flight": 1, "integration": 1},
            "fixture/repository": {"in_flight": 2, "integration": 2}}
        with self.assertRaises(ConfigError):
            capacity.parse_policy(self.configuration)

    def test_duplicate_and_invalid_expiry_exceptions_refuse_configuration(self):
        exception = {"task": "new", "until": LATER, "reason": "A fixture urgent task."}
        for rows in ([exception, exception], [{**exception, "until": "unknown"}]):
            self.configuration["backpressure"]["exceptions"] = rows
            with self.assertRaises(ConfigError):
                capacity.parse_policy(self.configuration)

    def test_indivisible_oversized_expiry_refuses_before_a_native_decision(self):
        self.configuration["backpressure"]["exceptions"] = [{"task": "new",
            "until": "2099-01-01T00:00:00." + "1" * 30000 + "Z", "reason": "Fixture exception."}]
        with self.assertRaises(ConfigError):
            capacity.parse_policy(self.configuration)

    def test_valid_maximum_metadata_stays_within_the_context_budget(self):
        self.configuration["backpressure"]["global"] = {"in_flight": capacity.MAX_THRESHOLD,
                                                         "integration": capacity.MAX_THRESHOLD}
        self.configuration["backpressure"]["repositories"]["fixture/repository"] = {"in_flight": 1, "integration": 1}
        self.configuration["backpressure"]["exceptions"] = [{"task": "new",
            "until": "2099-01-01T00:00:00." + "1" * 100 + "Z", "reason": "雪" * 170}]
        families = {}
        for index in range(3):
            task = str(index) + "x" * 1000
            self.reserve(task, identifier="d-{}".format(index))
            families[task] = "fixture/repository"
        result = self.decide(families=families)
        self.assertTrue(result["allowed"])
        self.assertLess(len((json.dumps(result, indent=2) + "\n").encode()), 16384)

    def test_reservations_and_unknown_delivery_each_consume_one_task_slot(self):
        self.reserve(status="prepared")
        self.reserve(identifier="d2", status="unknown")
        self.reserve("another", identifier="d3", status="unknown")
        result = self.decide()
        self.assertFalse(result["allowed"])
        self.assertEqual(result["counts"]["global"]["in_flight"], 2)
        self.assertEqual(result["reason"], "global_in_flight_limit")

    def test_proven_no_send_is_not_an_in_flight_reservation(self):
        self.reserve(status="not_sent")
        self.state["recovery"]["tasks"]["old"] = {"progression": {"schema_version": 2,
            "phase": "exception", "round": 0, "jobs": {"developer": "d1"}, "pending": None}}
        self.assertEqual(self.decide()["counts"]["global"]["in_flight"], 0)

    def test_closure_releases_capacity_but_an_active_enrollment_remains_uncertain_work(self):
        self.reserve(status="applied")
        recovery._event(self.state["recovery"], LATER, "task_closed", "old", {"outcome": "merged"})
        self.assertEqual(self.decide()["counts"]["global"]["in_flight"], 0)
        self.supervised["members"].append({"active": True, "assignment": {"task": "old"}})
        self.assertEqual(self.decide()["counts"]["global"]["in_flight"], 1)

    def test_a_previous_closure_cannot_erase_an_unsettled_native_reservation(self):
        recovery._event(self.state["recovery"], AT, "task_closed", "old", {"outcome": "merged"})
        for status in ("prepared", "unknown"):
            with self.subTest(status=status):
                self.state["recovery"]["dispatches"] = []
                self.reserve(status=status)
                self.assertEqual(self.decide()["counts"]["global"]["in_flight"], 1)

    def test_ambiguous_foreign_closure_stays_counted_without_freezing_available_capacity(self):
        self.reserve(status="applied")
        for _ in range(2):
            recovery._event(self.state["recovery"], LATER, "task_closed", "old", {"outcome": "merged"})
        result = self.decide()
        self.assertEqual(result["counts"]["global"]["in_flight"], 1)
        self.assertTrue(result["allowed"])

    def test_integration_congestion_stops_new_starts_below_the_global_work_limit(self):
        self.reserve(role="reviewer")
        result = self.decide()
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "global_integration_limit")
        self.assertEqual(result["counts"]["global"], {"in_flight": 1, "integration": 1})

    def test_existing_corrections_and_integration_can_drain_a_saturated_queue(self):
        self.reserve(role="reviewer")
        self.reserve("another", identifier="d2")
        result = self.decide("old")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "drain_existing_task")
        self.assertFalse(result["authorizes_progression"])

    def test_draining_does_not_require_loading_unrelated_repository_inputs(self):
        self.reserve(role="reviewer")
        self.configuration["backpressure"]["repositories"]["fixture/repository"] = {"in_flight": 1, "integration": 1}
        def unavailable(_task):
            raise AssertionError("Draining must not depend on unrelated family inputs.")
        result = capacity.evaluate(self.state, self.supervised, "old", "fixture/repository",
            capacity.parse_policy(self.configuration), AT, family=unavailable)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["limits"]["repository"], {"in_flight": 1, "integration": 1})
        self.assertIsNone(result["counts"]["repository"])
        self.assertIsNone(result["counts"]["unverified_repositories"])

    def test_repository_limit_does_not_consume_another_repositorys_capacity(self):
        self.configuration["backpressure"]["repositories"]["fixture/repository"] = {"in_flight": 1, "integration": 1}
        self.reserve()
        self.assertTrue(self.decide(families={"old": "other/repository"})["allowed"])
        result = self.decide(families={"old": "Fixture/Repository"})
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "repository_in_flight_limit")

    def test_unknown_repository_is_reported_before_applying_a_family_limit(self):
        self.reserve()
        self.configuration["backpressure"]["repositories"]["fixture/repository"] = {"in_flight": 1, "integration": 1}
        result = self.decide()
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "repository_scope_unverified")
        self.assertEqual(result["counts"]["unverified_repositories"], 1)

    def test_expired_exception_cannot_open_work_but_is_visible(self):
        self.reserve(role="reviewer")
        exception = {"task": "new", "until": "2026-10-19T11:59:00Z", "reason": "Fixture exception."}
        self.configuration["backpressure"]["exceptions"] = [exception]
        result = self.decide()
        self.assertFalse(result["allowed"])
        self.assertFalse(result["exception"]["active"])
        self.configuration["backpressure"]["exceptions"][0]["until"] = LATER
        self.assertTrue(self.decide()["allowed"])
        self.assertEqual(self.decide()["reason"], "explicit_capacity_exception")

    def test_readback_cannot_mutate_the_captured_policy(self):
        policy = capacity.parse_policy(self.configuration)
        original = copy.deepcopy((self.state, self.supervised, policy))
        result = capacity.evaluate(self.state, self.supervised, "new", "fixture/repository", policy, AT, family=lambda _: None)
        result["limits"]["global"]["in_flight"] = 999
        self.assertEqual((self.state, self.supervised, policy), original)

    def test_large_task_references_keep_counts_without_flooding_the_context(self):
        for index in range(40):
            self.reserve("task-{}-{}".format(index, "雪" * 800), identifier="d-{}".format(index))
        result = self.decide()
        self.assertEqual(result["blocking_tasks"]["total"], 40)
        self.assertEqual(result["blocking_tasks"]["omitted"], 40)
        self.assertLess(len((json.dumps(result, indent=2) + "\n").encode()), 16384)


if __name__ == "__main__":
    unittest.main()
