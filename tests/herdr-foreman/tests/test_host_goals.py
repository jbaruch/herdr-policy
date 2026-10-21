"""Host scheduler transfer outcomes, recovery and chained budget accounting."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import unittest

from foreman import host_goals as transfer
from foreman.codex_goals import GoalError, unavailable
from tests.goal_fakes import GoalHost, goal


class HostGoalTest(unittest.TestCase):
    def setUp(self):
        self.host = GoalHost({"old": goal()})
        self.saved = []
        self.receipt = transfer.prepare("codex", {"kind": "id", "value": "old"},
                                        connect=self.host.connect, discover=lambda: "/fixture/codex.sock")

    def persist(self):
        self.saved.append(copy.deepcopy(self.receipt))

    def deliver(self, **options):
        transfer.transfer(self.receipt, "new", self.persist, connect=self.host.connect, **options)

    def test_transfer_retires_before_activation_and_preserves_the_objective_and_remaining_budget(self):
        self.host.goals["old"].update(tokensUsed=350, timeUsedSeconds=15)
        self.deliver()
        self.assertIsNone(self.host.goal("old"))
        self.assertEqual(self.host.goals["new"]["objective"], "Ship the authorized work")
        self.assertEqual(self.host.goals["new"]["tokenBudget"], 650)
        self.assertEqual((self.receipt["carried_tokens"], self.receipt["carried_seconds"]), (350, 15))
        mutations = [(method, params) for method, params in self.host.calls if method != "thread/read"]
        self.assertEqual([method for method, _ in mutations], ["thread/goal/clear", "thread/goal/set"])
        self.assertEqual(mutations[1][1]["status"], "active")
        self.assertEqual(self.receipt["phase"], "verified")

    def test_exact_objective_text_survives_without_prompt_rewriting(self):
        self.host.goals["old"]["objective"] = "Ship A; retain B's hold.\nDo not change C."
        self.receipt = transfer.prepare("codex", {"kind": "id", "value": "old"},
                                        connect=self.host.connect, discover=lambda: "/fixture/codex.sock")
        self.deliver()
        self.assertEqual(self.host.goals["new"]["objective"], self.receipt["source_goal"]["objective"])

    def test_unbudgeted_goal_and_existing_inactive_status_are_preserved(self):
        for status in ("active", "paused", "blocked", "usageLimited", "budgetLimited"):
            with self.subTest(status=status):
                self.host = GoalHost({"old": goal(budget=None, status=status)})
                self.receipt = transfer.prepare("codex", {"kind": "id", "value": "old"},
                                                connect=self.host.connect, discover=lambda: "/fixture/codex.sock")
                self.deliver()
                self.assertEqual((self.host.goals["new"]["status"], self.host.goals["new"]["tokenBudget"]), (status, None))

    def test_no_goal_creates_no_new_goal_and_never_completes_or_pauses_work(self):
        self.host = GoalHost()
        self.receipt = transfer.prepare("codex", {"kind": "id", "value": "old"},
                                        connect=self.host.connect, discover=lambda: "/fixture/codex.sock")
        self.deliver()
        self.assertEqual(self.host.goals, {})
        self.assertFalse(any(method in ("thread/goal/set", "thread/goal/clear") for method, _ in self.host.calls))

    def test_changed_source_or_existing_target_refuses_before_retirement(self):
        for edit in (lambda: self.host.goals["old"].update(objective="New operator objective"),
                     lambda: self.host.goals["old"].update(tokenBudget=2000),
                     lambda: self.host.goals["old"].update(status="paused"),
                     lambda: self.host.goals.update(new=goal("new"))):
            self.setUp()
            edit()
            before = copy.deepcopy(self.host.goals)
            with self.assertRaises(GoalError):
                self.deliver()
            self.assertEqual(self.host.goals, before)
            self.assertEqual(self.receipt["phase"], "prepared")

    def test_lost_clear_response_recovers_by_reading_without_a_second_clear(self):
        self.host.lost = "thread/goal/clear"
        with self.assertRaises(GoalError):
            self.deliver()
        self.assertEqual(self.receipt["phase"], "retiring")
        self.assertEqual(self.host.goals, {})
        self.deliver()
        self.assertEqual(self.receipt["phase"], "verified")
        self.assertEqual(sum(method == "thread/goal/clear" for method, _ in self.host.calls), 1)

    def test_lost_restore_response_does_not_reset_usage_on_reconciliation(self):
        self.host.lost = "thread/goal/set"
        with self.assertRaises(GoalError):
            self.deliver()
        self.host.goals["new"]["tokensUsed"] = 50
        self.deliver()
        self.assertEqual(self.host.goals["new"]["tokensUsed"], 50)
        self.assertEqual(sum(method == "thread/goal/set" for method, _ in self.host.calls), 1)

    def test_two_successive_resets_preserve_cumulative_usage_and_reduce_the_budget(self):
        self.deliver()
        self.host.goals["new"].update(tokensUsed=200, timeUsedSeconds=7)
        second = transfer.prepare("codex", {"kind": "id", "value": "new"}, [self.receipt],
                                  connect=self.host.connect, discover=lambda: "/fixture/codex.sock")
        transfer.transfer(second, "third", lambda: None, connect=self.host.connect)
        self.assertEqual((second["carried_tokens"], second["carried_seconds"]), (500, 19))
        self.assertEqual(self.host.goals["third"]["tokenBudget"], 500)
        self.host.end_turn("old")
        self.host.end_turn("new")
        self.host.end_turn("third")
        self.assertEqual(self.host.continuations, ["third"])

    def test_a_new_goal_generation_does_not_inherit_old_accounting(self):
        self.deliver()
        self.host.goals["new"].update(createdAt=300, tokensUsed=5)
        second = transfer.prepare("codex", {"kind": "id", "value": "new"}, [self.receipt],
                                  connect=self.host.connect, discover=lambda: "/fixture/codex.sock")
        self.assertEqual(second["carried_tokens"], 5)

    def test_busy_outgoing_turn_is_interrupted_by_exact_id_and_final_usage_is_carried(self):
        self.host.active.add("old")
        def end():
            self.assertIn("old", self.host.goals)
            self.host.goals["old"].update(tokensUsed=400, timeUsedSeconds=20)
        self.host.on_interrupt = end
        self.deliver()
        self.assertEqual(self.receipt["carried_tokens"], 400)
        self.assertEqual(self.host.goals["new"]["tokenBudget"], 600)
        self.assertEqual(self.host.goals["new"]["status"], "active")
        interrupted = [params for method, params in self.host.calls if method == "turn/interrupt"]
        self.assertEqual(interrupted, [{"threadId": "old", "turnId": "outgoing-turn"}])

    def test_a_turn_that_does_not_end_refuses_without_clearing_or_creating_goals(self):
        self.host.active.add("old")
        self.host.ignore_interrupt = True
        clock = iter((0, 31))
        with self.assertRaises(GoalError):
            self.deliver(sleep=lambda _: None, clock=lambda: next(clock))
        self.assertIsNotNone(self.host.goal("old"))
        self.assertIsNone(self.host.goal("new"))

    def test_lost_interrupt_response_recovers_without_another_turn_or_fake_goal_pause(self):
        self.host.active.add("old")
        self.host.lost = "turn/interrupt"
        with self.assertRaises(GoalError):
            self.deliver()
        self.assertEqual(self.receipt["phase"], "quiescing")
        self.assertEqual(self.receipt["retiring_turn"], "outgoing-turn")
        self.deliver()
        self.assertEqual(self.host.goals["new"]["status"], "active")
        self.assertEqual(sum(method == "turn/interrupt" for method, _ in self.host.calls), 1)

    def test_missing_host_control_refuses_preflight(self):
        with self.assertRaises(GoalError):
            transfer.prepare("codex", {"kind": "id", "value": "old"},
                             discover=lambda: (_ for _ in ()).throw(unavailable("fixture_unavailable")))

    def test_malformed_receipt_values_refuse_without_an_unhandled_type_error(self):
        for field, value in (("phase", []), ("schema_version", True), ("carried_tokens", -1)):
            with self.subTest(field=field):
                self.assertFalse(transfer.valid({**self.receipt, field: value}))
        invalid = copy.deepcopy(self.receipt)
        invalid["source_goal"]["status"] = []
        self.assertFalse(transfer.valid(invalid))

    def test_native_runtimes_without_codex_goals_do_not_start_an_external_goal(self):
        for runtime in ("claude", "grok"):
            receipt = transfer.prepare(runtime, {"kind": "id", "value": "native"},
                                       discover=lambda: self.fail("must not connect to another runtime"))
            transfer.transfer(receipt, "incoming", lambda: None,
                              connect=lambda _: self.fail("must not control another runtime"))
            self.assertEqual(receipt["phase"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
