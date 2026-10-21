"""Behavioral observation tests; no live factories, accounts or model calls."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills/herdr-observer"))
sys.path.insert(0, str(ROOT / "skills/herdr-foreman"))

from factory_observer import cli, collect, native, sources
from factory_observer.store import Store, private_directory, private_file
from foreman import observer_role, role_context, supervision


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def agent(name, value, status="idle", kind="codex"):
    return {"name": name, "pane_id": "pane-" + name, "cwd": "/factory",
            "agent_status": status, "agent": kind,
            "agent_session": {"source": "herdr:" + kind, "agent": kind, "kind": "id", "value": value}}


class Client:
    binary = "herdr"

    def __init__(self, agents):
        self.agents = agents
        self.prompts = []
        self.notifications = 0
        self.unavailable = False
        self.uncertain = False

    def snapshot(self):
        if self.unavailable:
            raise ValueError("unavailable")
        return {"agents": self.agents}

    def prompt(self, name):
        self.prompts.append(name)
        if self.uncertain:
            raise ValueError("response lost")

    def notify(self):
        self.notifications += 1


class ObserverTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.cache = self.root / "state/herdr-observer"
        self.store = Store(self.cache)
        self.addCleanup(self.store.close)
        environment = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.cache.parent)})
        environment.start()
        self.addCleanup(environment.stop)
        self.now = 1760000000.0
        self.foreman = agent("coordinator", "11111111-1111-4111-8111-111111111111", "working")
        self.worker = agent("developer", "22222222-2222-4222-8222-222222222222")
        self.other = agent("reviewer", "33333333-3333-4333-8333-333333333333")
        self.observer = agent("observer", "44444444-4444-4444-8444-444444444444")
        self.client = Client([self.foreman, self.worker, self.other, self.observer])
        self.owner = self.root / "owners/state.json"
        self.owner.parent.mkdir()
        self.data = {"schema_version": 11, "recovery": {"schema_version": 19, "events": []},
                     "assignments": [{"agent": "developer", "role": "developer", "task": "work"}],
                     "snapshots": [{"schema_version": 6, "measured_at": stamp(self.now), "agents": {
                         "grok": {"kind": "grok", "window_group": "account-a", "headroom_pct": 90,
                                  "windows": {"weekly": {"used_pct": 10, "remaining_pct": 90, "resets": "cycle-a"}}}}}]}
        supervision.bind(self.owner, supervision.identity(self.foreman["agent_session"]["value"], "/factory", "1",
                         pane_id=self.foreman["pane_id"]), stamp(self.now))
        supervision.enroll(self.owner, {"id": "assignment", "agent": "developer", "task": "work",
                          "report": str(self.root / "worker-report.md"), "pane_id": self.worker["pane_id"],
                          "native_session": self.worker["agent_session"]}, stamp(self.now))
        self.supervised = supervision.load(self.owner)
        self.save_owner()
        with self.store.transaction():
            self.store.put("meta", "config", {"enabled": True, "started_at": self.now,
                                              "states": [str(self.owner)], "owner_root": str(self.owner.parent)})
            self.store.put("meta", "binding", {"identity": native.identity(self.observer),
                                               "name": "observer", "cwd": "/factory"})

    def record(self, key):
        value = self.store.get("meta", key)
        assert value is not None
        return value

    def save_owner(self):
        self.owner.write_text(json.dumps(self.data))
        Path(str(self.owner) + ".supervision.json").write_text(json.dumps(self.supervised))

    def tick(self, at=None):
        with self.store.db:
            return collect.tick(self.store, self.client, self.now if at is None else at, self.root)

    def log(self, row=None, records=()):
        row = self.foreman if row is None else row
        path = self.root / ".codex/sessions/2025/10/09" / ("rollout-" + row["agent_session"]["value"] + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")
        return path

    def event(self, kind, payload, seconds=1):
        return {"timestamp": stamp(self.now + seconds), "type": kind, "payload": payload}

    def due(self):
        self.tick()
        # Keep contiguous sampling so candidate continuity is real evidence.
        result = None
        for offset in range(60, collect.MIN_WAKE_SECONDS + 60, 60):
            result = self.tick(self.now + offset)
        assert result is not None
        return result

    def test_incremental_costs_profiles_repetition_and_no_transcript_replica(self):
        self.log()
        self.tick()
        private = "PRIVATE_PAYLOAD_NEVER_CACHE"
        self.log(records=[self.event("turn_context", {"model": "gpt-6.1-sol", "effort": "max"}),
                          self.event("response_item", {"type": "function_call", "call_id": "a", "name": "exec", "arguments": private}, 2),
                          self.event("response_item", {"type": "function_call", "call_id": "b", "name": "exec", "arguments": private}, 3),
                          self.event("response_item", {"type": "function_call_output", "output": private}, 4),
                          self.event("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "output_tokens": 10}}}, 5),
                          self.event("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 120, "output_tokens": 25}}}, 6),
                          self.event("compacted", {"summary": private}, 7)])
        self.tick(self.now + 60)
        view = collect.evidence(self.store, self.now + 60)
        self.assertEqual(view["total_metrics"]["tool_calls"], 2)
        self.assertEqual(view["total_metrics"]["repeated_tool_fingerprints"], 1)
        self.assertEqual(view["total_metrics"]["input_tokens"], 20)
        self.assertEqual(view["total_metrics"]["output_tokens"], 15)
        self.assertEqual(view["total_metrics"]["compactions"], 1)
        self.assertEqual(view["profiles"][0]["effort"], "max")
        self.tick(self.now + 120)
        self.assertEqual(collect.evidence(self.store, self.now + 120)["total_metrics"]["tool_calls"], 2)
        self.assertNotIn(private.encode(), (self.cache / "observer.sqlite3").read_bytes())

    def test_healthy_parallel_delivery_does_not_fire_stall_candidate(self):
        self.worker["agent_status"] = "working"
        self.assertFalse(self.due()["wake_agent"])
        self.assertIsNone(self.record("current")["stall_since"])

    def test_native_session_moves_panes_without_replaying_log_costs(self):
        self.log()
        self.tick()
        self.log(records=[self.event("response_item", {"type": "function_call", "call_id": "a", "name": "exec"}),
                          self.event("compacted", {}, 2)])
        self.tick(self.now + 60)
        self.foreman["pane_id"] = "replacement-pane"
        self.supervised["binding"]["identity"]["pane_id"] = "replacement-pane"
        self.save_owner()
        self.tick(self.now + 120)
        metrics = collect.evidence(self.store, self.now + 120)["total_metrics"]
        self.assertEqual(metrics["tool_calls"], 1)
        self.assertEqual(metrics["compactions"], 1)
        self.log(records=[self.event("response_item", {"type": "function_call", "call_id": "b", "name": "exec"}, 121)])
        self.tick(self.now + 180)
        self.assertEqual(collect.evidence(self.store, self.now + 180)["total_metrics"]["tool_calls"], 2)

    def test_running_start_merges_explicit_state_sources(self):
        additional = self.root / "additional/state.json"
        with patch.dict(os.environ, {"HERDR_PANE_ID": self.observer["pane_id"]}), patch("factory_observer.cli.running", return_value=True):
            result = cli.start(self.store, self.client, [str(additional)], self.now)
        self.assertTrue(result["already_running"])
        self.assertEqual(set(result["states"]), {str(self.owner), str(additional)})
        self.assertEqual(set(self.record("config")["states"]), {str(self.owner), str(additional)})

    def test_worker_admission_refused_when_its_foreman_is_offline(self):
        self.client.agents.remove(self.foreman)
        with patch.dict(os.environ, {"HERDR_PANE_ID": self.worker["pane_id"]}):
            with self.assertRaisesRegex(ValueError, "delivery ownership"):
                cli.start(self.store, self.client, [str(self.owner)], self.now)
        self.assertEqual(self.record("binding")["name"], "observer")

    def test_later_worker_enrollment_takes_precedence_over_observer_registration(self):
        pending = self.due()
        supervision.enroll(self.owner, {"id": "observer-reassigned", "agent": "observer", "task": "other-work",
                          "report": str(self.root / "other-report.md"), "pane_id": self.observer["pane_id"],
                          "native_session": self.observer["agent_session"]}, stamp(self.now))
        who = {"kind": "id", "value": self.observer["agent_session"]["value"], "cwd": "/factory",
               "pane_id": self.observer["pane_id"], "herdr_env": "1"}
        env = {"XDG_STATE_HOME": str(self.cache.parent)}
        self.assertFalse(observer_role.matches(who, self.observer["agent_session"], env))
        self.assertFalse(collect.dispatch(self.store, self.client, pending)["wake_agent"])
        self.assertEqual(self.client.prompts, [])
        with patch.dict(os.environ, {"HERDR_PANE_ID": self.observer["pane_id"]}):
            with self.assertRaisesRegex(ValueError, "delivery ownership"):
                cli.verify(self.store, self.client)

    def test_service_lifecycle_uses_explicit_ticks_and_stop_signal(self):
        def stop_after_sample(_seconds):
            self.assertEqual(self.record("heartbeat")["at"], self.now)
            self.assertTrue(self.record("current")["healthy"])
            with self.store.transaction():
                config = self.record("config")
                config["enabled"] = False
                self.store.put("meta", "config", config)
        with self.store.transaction():
            config = self.record("config")
            config["binary"] = "fixture"
            self.store.put("meta", "config", config)
        with patch("factory_observer.cli.native.Native", return_value=self.client), \
                patch("factory_observer.cli.time.time", return_value=self.now), \
                patch("factory_observer.cli.time.sleep", side_effect=stop_after_sample), \
                patch("factory_observer.collect.sources.locate", return_value=None):
            result = cli.serve(self.store)
        self.assertTrue(result["stopped"])
        self.assertFalse(cli.running(self.cache))

    def test_start_launches_the_isolated_co_shipped_service(self):
        with patch.dict(os.environ, {"HERDR_PANE_ID": self.observer["pane_id"]}), \
                patch("factory_observer.cli.shutil.which", return_value="/fixture/herdr"), \
                patch("factory_observer.cli.subprocess.Popen") as spawn:
            spawn.return_value.pid = 4242
            result = cli.start(self.store, self.client, [], self.now)
        self.assertEqual(result["status"], "starting")
        self.assertEqual(spawn.call_args.args[0], [sys.executable, "-I", str(ROOT / "skills/herdr-observer/observer.py"), "serve"])
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])

    def test_collector_records_recoverable_io_failures_and_keeps_its_loop(self):
        def stop_after_tick(_seconds):
            with self.store.transaction():
                config = self.record("config")
                config["enabled"] = False
                self.store.put("meta", "config", config)
        for error in (OSError("unreadable"), sqlite3.OperationalError("locked")):
            with self.subTest(error=type(error).__name__):
                with self.store.transaction():
                    config = self.record("config")
                    config.update(enabled=True, binary="fixture")
                    self.store.put("meta", "config", config)
                with patch("factory_observer.cli.native.Native", return_value=self.client), \
                        patch("factory_observer.cli.collect.tick", side_effect=error), \
                        patch("factory_observer.cli.time.time", return_value=self.now), \
                        patch("factory_observer.cli.time.sleep", side_effect=stop_after_tick):
                    result = cli.serve(self.store)
                self.assertTrue(result["stopped"])
                self.assertIn("collection_or_wake_failed", self.record("heartbeat")["error"])

    def test_blocked_coordinator_with_open_work_gets_an_early_analysis(self):
        self.foreman["agent_status"] = "blocked"
        checked = self.due()
        self.assertIn("idle_factory_with_open_work_check", checked["data"]["job"]["reasons"])

    def test_stall_is_a_question_with_holds_unknown_backlog_and_quota_age(self):
        self.supervised["holds"] = [{"resumed_at": None}]
        self.save_owner()
        checked = self.due()
        self.assertTrue(checked["wake_agent"])
        job = checked["data"]["job"]
        self.assertIn("coordinator_only_activity_check", job["reasons"])
        current = job["data"]["current"]
        self.assertEqual(current["factories"][0]["holds"], 1)
        self.assertIsNone(current["factories"][0]["eligible_backlog"])
        self.assertEqual(current["quota"][0]["measured_at"], stamp(self.now))
        self.assertNotIn("waste", job)

    def test_uncertain_send_is_not_repeated_and_data_collection_continues(self):
        checked = self.due()
        self.client.uncertain = True
        collect.dispatch(self.store, self.client, checked)
        self.assertEqual(self.client.prompts, ["observer"])
        self.assertEqual(self.record("pending")["send_status"], "unknown")
        later = self.tick(self.now + collect.MIN_WAKE_SECONDS + 60)
        self.assertFalse(later["wake_agent"])
        collect.dispatch(self.store, self.client, later)
        self.assertEqual(self.client.prompts, ["observer"])
        self.assertEqual(self.record("current")["at"], self.now + collect.MIN_WAKE_SECONDS + 60)

    def test_identity_change_busy_observer_and_stop_never_prompt_workers(self):
        checked = self.due()
        self.observer["agent_session"]["value"] = "55555555-5555-4555-8555-555555555555"
        self.assertFalse(collect.dispatch(self.store, self.client, checked)["wake_agent"])
        self.assertEqual(self.client.prompts, [])
        self.observer["agent_session"]["value"] = "44444444-4444-4444-8444-444444444444"
        self.observer["agent_status"] = "working"
        self.assertFalse(collect.dispatch(self.store, self.client, checked)["wake_agent"])
        with self.store.transaction():
            config = self.record("config")
            config["enabled"] = False
            self.store.put("meta", "config", config)
        self.assertFalse(collect.dispatch(self.store, self.client, checked)["wake_agent"])

    def test_weekly_report_saves_privately_notifies_generically_and_is_idempotent(self):
        self.tick()
        self.worker["agent_status"] = "working"
        checked = self.tick(self.now + collect.WEEK_SECONDS)
        job = checked["data"]["job"]
        self.assertIn("weekly_report_due", job["reasons"])
        with self.assertRaises(ValueError), self.store.transaction():
            cli.finish(self.store, job["id"], self.now + collect.WEEK_SECONDS)
        draft = private_directory(self.cache / "drafts") / (job["id"] + ".md")
        private_file(draft)
        draft.write_text("Private factory findings; sparse coverage, no unsupported conclusion.\n")
        with patch.dict(os.environ, {"HERDR_PANE_ID": self.observer["pane_id"]}):
            receipt = cli.report(self.store, self.client, job["id"], "weekly", draft, self.now + collect.WEEK_SECONDS)
            duplicate = cli.report(self.store, self.client, job["id"], "weekly", draft, self.now + collect.WEEK_SECONDS)
        final = Path(receipt["path"])
        self.assertEqual(final.stat().st_mode & 0o777, 0o600)
        self.assertEqual(final.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(draft.exists())
        self.assertTrue(duplicate["already_reported"])
        self.assertEqual(self.client.notifications, 1)
        self.assertFalse(self.record("pending").get("id"))

    def test_same_anomaly_is_suppressed_after_analysis_until_periodic_review(self):
        checked = self.due()
        with self.store.transaction():
            cli.finish(self.store, checked["data"]["job"]["id"], self.now + collect.MIN_WAKE_SECONDS)
        for offset in range(collect.MIN_WAKE_SECONDS + 60, 2 * collect.MIN_WAKE_SECONDS + 60, 60):
            checked = self.tick(self.now + offset)
        self.assertFalse(checked["wake_agent"])

    def test_outage_and_long_gaps_do_not_invent_idle_duration(self):
        self.tick()
        self.client.unavailable = True
        self.tick(self.now + 60)
        self.client.unavailable = False
        self.tick(self.now + 86400)
        metrics = collect.evidence(self.store, self.now + 86400)["total_metrics"]
        self.assertNotIn("idle_seconds", metrics)
        self.assertIn("sample_gap_not_extrapolated", self.record("current")["coverage"])

    def test_duplicate_native_sessions_excluded_and_unknown_runtime_visible(self):
        duplicate = deepcopy(self.worker)
        duplicate["pane_id"] = "other-pane"
        self.client.agents.extend([duplicate, {"name": "antigravity", "agent": "antigravity", "agent_session": None}])
        self.tick()
        current = self.record("current")
        self.assertTrue(current["duplicates"])
        self.assertNotIn("developer", [row["name"] for row in current["agents"]])
        self.assertEqual(current["unverified_agents"][0]["provider"], "antigravity")

    def test_closures_count_once_but_not_lifecycle_completions(self):
        self.tick()
        self.worker["completion_seq"] = 999
        self.data["recovery"]["events"].append({"kind": "task_closed", "sequence": 1, "task": "work", "at": stamp(self.now + 10)})
        self.save_owner()
        self.tick(self.now + 60)
        self.tick(self.now + 120)
        self.assertEqual(collect.evidence(self.store, self.now + 120)["total_metrics"]["recorded_task_closures"], 1)

    def test_claude_usage_stream_updates_and_tool_ids_are_not_double_counted(self):
        cursor = {"provider": "claude"}
        message = {"id": "response", "model": "claude-model", "usage": {"input_tokens": 10, "output_tokens": 4},
                   "content": [{"type": "tool_use", "id": "call", "name": "exec", "input": {"command": "private"}}]}
        first = sources.event_metrics({"type": "assistant", "message": message, "effort": "medium"}, cursor)
        self.assertEqual(first["input_tokens"], 10)
        message["usage"]["output_tokens"] = 9
        second = sources.event_metrics({"type": "assistant", "message": message}, cursor)
        self.assertEqual(second["output_tokens"], 5)
        self.assertNotIn("tool_calls", second)
        self.assertEqual(second["input_tokens"], 0)

    def test_quota_observations_keep_reuse_time_and_reset_cycle_instead_of_inventing_usage(self):
        self.tick()
        self.tick(self.now + 60)
        rows = [r for r in self.store.rows("sources") if r.get("kind") == "quota"]
        self.assertEqual(len(rows[0]["history"]), 1)
        self.assertEqual(rows[0]["history"][0]["measured_at"], stamp(self.now))
        latest = self.data["snapshots"][-1]
        latest["measured_at"] = stamp(self.now + 120)
        latest["agents"]["grok"]["windows"]["weekly"] = {"used_pct": 1, "remaining_pct": 99, "resets": "cycle-b"}
        self.save_owner()
        self.tick(self.now + 120)
        history = collect.evidence(self.store, self.now + 120)["quota_history"][0]["observations"]
        self.assertEqual([r["windows"]["weekly"]["resets"] for r in history], ["cycle-a", "cycle-b"])

    def test_rotated_log_with_copied_history_does_not_double_charge(self):
        path = self.log(records=[self.event("response_item", {"type": "function_call", "call_id": "x", "name": "exec"})])
        cursor = {"provider": "codex"}
        first, _, _ = sources.read_log(path, cursor, now=self.now + 10, since=self.now)
        self.assertEqual(first[0]["metrics"]["tool_calls"], 1)
        raw = path.read_bytes()
        path.rename(path.with_suffix(".old"))
        path.write_bytes(raw)
        self.log(records=[self.event("response_item", {"type": "function_call", "call_id": "y", "name": "exec"}, 2)])
        second, gaps, _ = sources.read_log(path, cursor, now=self.now + 10, since=self.now)
        self.assertIn("native_log_rotated_or_truncated", gaps)
        self.assertEqual(sum(r["metrics"].get("tool_calls", 0) for r in second), 1)

    def test_native_notifications_have_no_report_or_factory_data(self):
        with patch.dict(os.environ, {"HERDR_ENV": "1", "HERDR_PANE_ID": "observer"}):
            adapter = native.Native()
        with patch.object(adapter, "call") as call:
            adapter.notify()
        self.assertEqual(call.call_args.args[:2], ("notification", "show"))
        text = json.dumps(call.call_args.args)
        self.assertNotIn(str(self.owner), text)
        self.assertNotIn("Private factory findings", text)
        self.assertNotIn("work", text)

    def test_partial_line_resumes_without_replaying_complete_records(self):
        path = self.log()
        cursor = {"provider": "codex"}
        raw = json.dumps(self.event("response_item", {"type": "function_call", "call_id": "x", "name": "exec"})).encode()
        path.write_bytes(raw[:-5])
        batches, _, _ = sources.read_log(path, cursor, now=self.now + 10, since=self.now)
        self.assertEqual(batches, [])
        with path.open("ab") as stream:
            stream.write(raw[-5:] + b"\n")
        batches, _, _ = sources.read_log(path, cursor, now=self.now + 10, since=self.now)
        self.assertEqual(sum(b["metrics"].get("tool_calls", 0) for b in batches), 1)
        self.assertEqual(sources.read_log(path, cursor, now=self.now + 10, since=self.now)[0], [])

    def test_role_hook_exact_binding_no_foreman_workflow_and_no_schema_migration(self):
        who = {"kind": "id", "value": self.observer["agent_session"]["value"], "cwd": "/factory",
               "pane_id": self.observer["pane_id"], "herdr_env": "1"}
        env = {"XDG_STATE_HOME": str(self.cache.parent), "HERDR_ENV": "1", "HERDR_PANE_ID": who["pane_id"]}
        self.assertTrue(observer_role.matches(who, self.observer["agent_session"], env))
        row = self.observer
        class PaneClient:
            def pane_get(self, pane):
                return row
        with patch("foreman.progression_owner.verify_foreman", side_effect=AssertionError("observer must not run foreman workflow")):
            selected = role_context.select(ROOT / "skills/herdr-foreman", client=PaneClient(),
                                           environment=env, cwd="/factory", binding_root=self.root / "empty-bindings")
        self.assertEqual(selected["role"], "observer")
        self.assertLess(len(selected["context"].encode()), 4096)
        altered = {**who, "value": "other"}
        self.assertFalse(observer_role.matches(altered, self.observer["agent_session"], {**env, "XDG_STATE_HOME": str(self.root / "missing")}))
        self.store.db.execute("PRAGMA user_version=99")
        self.store.db.commit()
        self.assertFalse(observer_role.matches(who, self.observer["agent_session"], env))
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_all_row_readers_refuse_newer_and_nonobject_records(self):
        for value in ({"schema_version": 99}, [], {"schema_version": True}):
            with self.subTest(value=value):
                self.store.db.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", ("invalid", self.now, json.dumps(value)))
                self.store.db.commit()
                with self.assertRaises(ValueError):
                    self.store.rows("reports")
                with self.assertRaises(ValueError):
                    cli.status(self.store, self.now)

    def test_private_storage_refuses_links_and_has_database_ceiling(self):
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.cache / "observer.sqlite3").stat().st_mode & 0o777, 0o600)
        target = self.root / "target"
        target.write_text("leave unchanged")
        link = self.root / "linked"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            private_file(link)
        self.assertEqual(target.read_text(), "leave unchanged")
        self.assertLessEqual(self.store.db.execute("PRAGMA max_page_count").fetchone()[0], 8192)


class EntryPointTest(unittest.TestCase):
    def test_isolated_entrypoint_reports_initial_health_without_live_services(self):
        with tempfile.TemporaryDirectory(prefix="private observer ") as name:
            root = Path(name)
            environment = {**os.environ, "XDG_STATE_HOME": str(root / "state")}
            environment.pop("HERDR_ENV", None)
            environment.pop("HERDR_PANE_ID", None)
            result = subprocess.run(["bash", str(ROOT / "skills/herdr-observer/observer.sh"), "status"],
                                    env=environment, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            status = json.loads(result.stdout)
            self.assertFalse(status["running"])
            self.assertFalse(status["enabled"])
            self.assertEqual(status["heartbeat"], {})


if __name__ == "__main__":
    unittest.main()
