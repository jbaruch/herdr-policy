"""Behavioral observation tests; no live factories, accounts or model calls."""

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import io
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
from factory_observer.store import MAX_REPORT_SWEEP, Store, private_directory, private_file
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
        self.attentions = 0
        self.recoveries = 0
        self.unavailable = False
        self.uncertain = False

    def snapshot(self):
        if self.unavailable:
            raise ValueError("unavailable")
        return {"agents": self.agents}

    def agent_get(self, name):
        matches = [row for row in self.agents if row.get("name") == name]
        if len(matches) != 1:
            raise ValueError("named agent unavailable")
        return matches[0]

    def prompt(self, name, *, recovery=False):
        self.prompts.append(name)
        self.recoveries += int(recovery)
        if self.uncertain:
            raise ValueError("response lost")

    def notify(self, *, attention=False):
        self.notifications += 1
        self.attentions += int(attention)


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
                                              "states": [str(self.owner)], "owner_root": str(self.owner.parent), "binary": "fixture"})
            self.store.put("meta", "binding", {"identity": native.identity(self.observer),
                                               "name": "observer", "cwd": "/factory", "at": self.now})

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

    def test_claude_discovery_ignores_unrelated_transcript_counts(self):
        worker = agent("claude-worker", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", kind="claude")
        self.client.agents.append(worker)
        root = self.root / ".claude/projects"
        for name in ("zzz-old", "yyy-old", "xxx-old", "aaa-live"):
            project = root / name
            project.mkdir(parents=True)
            for index in range(20):
                (project / ("unrelated-" + str(index) + ".jsonl")).write_text("not a native record")
        path = root / "aaa-live" / (worker["agent_session"]["value"] + ".jsonl")
        path.touch()
        with patch.object(sources, "MAX_DISCOVERY_FILES", 8):
            self.tick()
            path.write_text(json.dumps({"timestamp": stamp(self.now + 1), "type": "assistant",
                "message": {"id": "message", "model": "claude-small", "usage": {"input_tokens": 5, "output_tokens": 2},
                            "content": [{"type": "tool_use", "id": "call", "name": "Read", "input": {}}]}}) + "\n")
            self.tick(self.now + 60)
        view = collect.evidence(self.store, self.now + 60, agent="claude-worker")
        self.assertEqual(view["total_metrics"]["tool_calls"], 1)
        self.assertEqual(view["total_metrics"]["input_tokens"], 5)
        self.assertEqual(view["profiles"][0]["model"], "claude-small")
        self.assertEqual(view["log_coverage"][0]["backlog_bytes"], 0)

    def test_discovery_truncation_remains_distinct_from_a_missing_log(self):
        worker = agent("claude-worker", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", kind="claude")
        self.client.agents.append(worker)
        for name in ("one", "two"):
            (self.root / ".claude/projects" / name).mkdir(parents=True)
        with patch.object(sources, "MAX_DISCOVERY_FILES", 1):
            self.tick()
        with patch.object(sources, "locate", side_effect=AssertionError("retry delay must be retained")):
            self.tick(self.now + 60)
        selected = next(row for row in self.record("current")["agents"] if row["name"] == "claude-worker")
        self.assertEqual(selected["log_coverage"], ["native_log_discovery_truncated"])

    def test_discovered_paths_survive_a_deferred_read_budget(self):
        path = self.log(self.worker)
        with patch.object(sources, "LOG_BUDGET", 0):
            self.tick()
        cursor = self.store.get("sources", native.session_key(native.identity(self.worker)))
        assert cursor is not None
        self.assertEqual(cursor["path"], str(path))
        self.assertEqual(cursor["coverage"], ["native_log_deferred_by_cycle_budget"])
        self.log(self.worker, [self.event("response_item", {"type": "function_call", "call_id": "new", "name": "exec"})])
        with patch.object(sources, "locate", side_effect=AssertionError("cached path must be reused")):
            self.tick(self.now + 60)
        self.assertEqual(collect.evidence(self.store, self.now + 60, agent="developer")["total_metrics"]["tool_calls"], 1)

    def test_agent_focus_excludes_other_agents_and_shared_factory_context(self):
        self.log()
        self.log(self.worker)
        self.tick()
        self.log(records=[self.event("response_item", {"type": "function_call", "call_id": "foreman", "name": "exec"})])
        self.log(self.worker, [self.event("response_item", {"type": "function_call", "call_id": "worker", "name": "exec"})])
        self.tick(self.now + 60)
        view = collect.evidence(self.store, self.now + 60, agent="developer")
        self.assertEqual(view["total_metrics"]["tool_calls"], 1)
        self.assertEqual(view["scope"], {"kind": "agent", "name": "developer", "matched": True})
        self.assertEqual([r["name"] for r in view["current"]["agents"]], ["developer"])
        self.assertEqual([r["key"] for r in view["log_coverage"]], [native.session_key(native.identity(self.worker))])
        self.assertEqual(view["quota_history"], [])
        self.assertNotIn("factories", view["current"])
        self.assertNotIn("quota", view["current"])
        self.assertTrue(view["omitted"]["shared_fleet_context"])
        self.assertNotIn(str(self.owner), json.dumps(view))
        self.assertNotIn(self.foreman["agent_session"]["value"], json.dumps(view))
        missing = collect.evidence(self.store, self.now + 60, agent="typo")
        self.assertFalse(missing["scope"]["matched"])
        for field in ("total_metrics", "log_coverage", "quota_history", "profiles", "source_locators"):
            self.assertFalse(missing[field])
        self.assertEqual(missing["current"]["agents"], [])

    def test_short_views_never_present_unqueried_comparison_periods_as_zero(self):
        row = {"key": "comparison", "session_key": "comparison-session", "name": "comparison-agent",
               "provider": "codex", "role": "worker", "task": None}
        with self.store.transaction():
            collect.bin_update(self.store, row, self.now - 8 * 86400, {"tool_calls": 7})
            collect.bin_update(self.store, row, self.now - 2 * 3600, {"tool_calls": 3})
        week = collect.evidence(self.store, self.now, hours=168)
        day = collect.evidence(self.store, self.now, hours=24)
        full = collect.evidence(self.store, self.now, hours=336)
        self.assertNotIn("previous_week", week["comparisons"])
        self.assertEqual(week["comparison_omitted"]["previous_week"], "outside_requested_window")
        self.assertEqual(week["comparisons"]["recent_week"]["tool_calls"], 3)
        self.assertEqual(set(day["comparisons"]), {"recent_day"})
        self.assertEqual(day["comparisons"]["recent_day"]["tool_calls"], 3)
        self.assertEqual(set(day["comparison_omitted"]), {"previous_day", "recent_week", "previous_week"})
        self.assertEqual(full["comparisons"]["previous_week"]["tool_calls"], 7)
        self.assertFalse(full["comparison_omitted"])

    def test_acknowledgement_retry_preserves_a_newer_pending_job(self):
        job = self.due()["data"]["job"]
        with self.store.transaction():
            first = cli.acknowledge(self.store, job["id"], self.now + 1000)
        self.assertFalse(first["already_acknowledged"])
        schedule = self.record("schedule")
        with self.store.transaction():
            self.store.put("meta", "pending", {**job, "id": native.fingerprint("newer-job")})
            repeated = cli.acknowledge(self.store, job["id"], self.now + 2000)
        self.assertTrue(repeated["already_acknowledged"])
        self.assertEqual(self.record("pending")["id"], native.fingerprint("newer-job"))
        self.assertEqual(self.record("schedule"), schedule)
        with self.store.transaction():
            self.store.db.execute("UPDATE meta SET value=? WHERE key='acknowledgements'",
                                  (json.dumps({"schema_version": 1, "jobs": [{}]}),))
        with self.assertRaisesRegex(ValueError, "restore"):
            cli.acknowledge(self.store, job["id"], self.now + 3000)
        self.assertEqual(self.record("pending")["id"], native.fingerprint("newer-job"))

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

    def test_future_log_records_cannot_poison_baselines_deduplication_or_rotation(self):
        records = [self.event("turn_context", {"model": "small", "effort": "low"}, 0),
                   self.event("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100}}}, 1),
                   self.event("turn_context", {"model": "future-big", "effort": "max"}, 3600),
                   self.event("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 999999}}}, 3600),
                   self.event("response_item", {"type": "function_call", "call_id": "reused", "name": "exec"}, 3600),
                   self.event("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 120}}}, 2),
                   self.event("response_item", {"type": "function_call", "call_id": "reused", "name": "exec"}, 3)]
        path = self.log(records=records)
        self.tick(self.now + 60)
        first = collect.evidence(self.store, self.now + 60, agent="coordinator")
        self.assertEqual(first["total_metrics"]["input_tokens"], 20)
        self.assertEqual(first["total_metrics"]["tool_calls"], 1)
        self.assertEqual({row["model"] for row in first["profiles"]}, {"small"})
        path.rename(path.with_suffix(".old"))
        self.log(records=records + [self.event("response_item", {"type": "function_call", "call_id": "later", "name": "exec"}, 61)])
        self.tick(self.now + 120)
        view = collect.evidence(self.store, self.now + 120, agent="coordinator")
        self.assertEqual(view["total_metrics"]["tool_calls"], 2)
        self.assertEqual(view["total_metrics"]["input_tokens"], 20)
        gaps = next(row["log_coverage"] for row in self.record("current")["agents"] if row["name"] == "coordinator")
        self.assertIn("native_log_timestamp_outside_collection_clock", gaps)

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
        self.assertFalse(observer_role.matches(who, self.observer["agent_session"], env, client=self.client))
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
        self.assertEqual(spawn.call_args.args[0], [sys.executable, "-B", "-I", str(ROOT / "skills/herdr-observer/observer.py"), "serve"])
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        self.assertNotEqual(spawn.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(result["diagnostic_path"], str(self.cache / "collector.stderr"))
        self.assertEqual((self.cache / "collector.stderr").stat().st_mode & 0o777, 0o600)

    def test_collector_stderr_is_bounded_and_fatal_import_keeps_a_private_diagnostic(self):
        source = ROOT / "skills/herdr-observer/observer.py"
        spec = importlib.util.spec_from_file_location("observer_entry", source)
        assert spec is not None and spec.loader is not None
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        stream = io.StringIO()
        bounded = entry.BoundedDiagnostics(stream)
        bounded.write("é" * entry.MAX_DIAGNOSTIC_BYTES)
        bounded.write("extra")
        self.assertLessEqual(len(stream.getvalue().encode()), entry.MAX_DIAGNOSTIC_BYTES)

        installed = self.root / "installed/herdr-observer"
        (installed / "factory_observer").mkdir(parents=True)
        script = installed / "observer.py"
        script.write_text(source.read_text())
        (installed / "factory_observer/__init__.py").write_text("")
        secret = "PRIVATE_EXCEPTION_VALUE_NEVER_LOG"
        (installed / "factory_observer/cli.py").write_text("raise RuntimeError(" + repr(secret) + ")\n")
        peer = installed.parent / "herdr-foreman/foreman/observer_role.py"
        peer.parent.mkdir(parents=True)
        peer.write_text("")
        diagnostic = self.cache / "collector.stderr"
        private_file(diagnostic)
        with diagnostic.open("w") as errors:
            failed = subprocess.run([sys.executable, "-B", "-I", str(script), "serve"],
                                    stdout=subprocess.PIPE, stderr=errors, timeout=10)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("collector failed (RuntimeError)", diagnostic.read_text())
        self.assertIn("before restarting", diagnostic.read_text())
        self.assertNotIn(secret, diagnostic.read_text())
        self.assertLessEqual(diagnostic.stat().st_size, entry.MAX_DIAGNOSTIC_BYTES)
        self.assertEqual(diagnostic.stat().st_mode & 0o777, 0o600)

    def test_reporter_admission_rejects_unreadable_role_formats_before_writes(self):
        for change in ({"cwd": None}, {"cwd": "relative"}, {"provider": "unsupported"}, {"pane": "other-pane"}):
            with self.subTest(change=change):
                row = deepcopy(self.observer)
                if "cwd" in change:
                    row["cwd"] = change["cwd"]
                if "provider" in change:
                    assert isinstance(change["provider"], str)
                    row["agent_session"]["agent"] = change["provider"]
                    row["agent_session"]["source"] = "herdr:" + change["provider"]
                if "pane" in change:
                    row["agent_session"]["pane_id"] = change["pane"]
                before = self.record("binding")
                with patch.dict(os.environ, {"HERDR_PANE_ID": self.observer["pane_id"]}):
                    with self.assertRaises(ValueError):
                        cli.start(self.store, Client([row]), [], self.now)
                self.assertEqual(self.record("binding"), before)

    def test_service_retries_collision_with_short_lived_health_probe(self):
        guard = cli.lock(self.cache, "service.lock")
        self.assertIsNotNone(guard)
        with self.store.transaction():
            config = self.record("config")
            config["enabled"] = False
            self.store.put("meta", "config", config)
        with patch("factory_observer.cli.lock", side_effect=[None, guard]), patch("factory_observer.cli.time.sleep") as sleep:
            self.assertTrue(cli.serve(self.store)["stopped"])
        sleep.assert_called_once_with(cli.SERVICE_LOCK_RETRY_SECONDS)

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

    def test_stale_wake_gets_bounded_reconciliation_and_private_attention(self):
        checked = self.due()
        created = checked["data"]["job"]["created_at"]
        self.client.uncertain = True
        collect.dispatch(self.store, self.client, checked, created)
        self.assertEqual(self.record("pending")["send_status"], "unknown")
        later = created + collect.STALE_PENDING_SECONDS + 60
        ready = self.tick(later)
        self.assertTrue(ready["wake_agent"])
        self.assertTrue(ready["recovery"])
        collect.signal_pending(self.store, self.client, later)
        collect.signal_pending(self.store, self.client, later)
        self.assertEqual(self.client.attentions, 1)
        self.client.uncertain = False
        collect.dispatch(self.store, self.client, ready, later)
        self.assertEqual(self.client.recoveries, 1)
        self.assertEqual(self.record("pending")["send_status"], "unknown")
        self.assertEqual(self.record("pending")["recovery"]["status"], "sent")
        self.assertFalse(self.tick(later + collect.STALE_PENDING_SECONDS + 60)["wake_agent"])
        with self.store.transaction():
            cli.finish(self.store, ready["data"]["job"]["id"], later + 60)
        weekly = self.tick(self.now + collect.WEEK_SECONDS)
        self.assertIn("weekly_report_due", weekly["data"]["job"]["reasons"])

    def test_lost_turn_after_successful_send_has_the_same_recovery_path(self):
        checked = self.due()
        created = checked["data"]["job"]["created_at"]
        collect.dispatch(self.store, self.client, checked, created)
        self.assertEqual(self.record("pending")["send_status"], "sent")
        ready = self.tick(created + collect.STALE_PENDING_SECONDS + 60)
        self.assertTrue(ready["recovery"])
        self.observer["agent_status"] = "working"
        self.assertFalse(collect.dispatch(self.store, self.client, ready)["wake_agent"])

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

    def test_nonweekly_job_cannot_postpone_weekly_cadence(self):
        job = self.due()["data"]["job"]
        with self.assertRaisesRegex(ValueError, "not a due weekly report"), self.store.transaction():
            cli.finish(self.store, job["id"], self.now + collect.MIN_WAKE_SECONDS, "weekly")
        self.assertEqual(self.record("pending")["id"], job["id"])
        self.assertIsNone(self.store.get("meta", "schedule"))
        self.assertEqual(cli.status(self.store, job["created_at"] + 600)["pending"]["age_seconds"], 600)

    def test_outage_and_long_gaps_do_not_invent_idle_duration(self):
        self.tick()
        self.client.unavailable = True
        self.tick(self.now + 60)
        self.client.unavailable = False
        self.tick(self.now + 86400)
        metrics = collect.evidence(self.store, self.now + 86400)["total_metrics"]
        self.assertNotIn("idle_seconds", metrics)
        self.assertIn("sample_gap_not_extrapolated", self.record("current")["coverage"])

    def test_malformed_native_rows_become_recoverable_snapshot_gaps(self):
        with patch.dict(os.environ, {"HERDR_ENV": "1", "HERDR_PANE_ID": self.observer["pane_id"]}):
            adapter = native.Native()
        for field, value in (("pane_id", 12), ("pane_id", ["pane"]), ("pane_id", ""),
                             ("agent_status", []), ("name", {}), ("cwd", []), ("agent", 42),
                             ("agent_session", []), ("agent_session", {"value": "session"}),
                             ("agent_session", {**self.worker["agent_session"], "pane_id": "other-pane"})):
            with self.subTest(field=field, value=value):
                bad = {**self.worker, field: value}
                if field in ("pane_id", "agent_session"):
                    self.assertIsNone(native.identity(bad))
                with patch.object(adapter, "call", return_value={"snapshot": {"agents": [bad]}}):
                    with self.assertRaisesRegex(ValueError, "agent row schema unsupported"):
                        adapter.snapshot()
                    with self.store.transaction():
                        result = collect.tick(self.store, adapter, self.now, self.root)
                self.assertFalse(result["wake_agent"])
                self.assertFalse(self.record("current")["healthy"])
        unknown = {"pane_id": "unknown-pane", "agent_status": "idle", "agent_session": None}
        with patch.object(adapter, "call", return_value={"snapshot": {"agents": [unknown]}}):
            self.assertEqual(adapter.snapshot()["agents"], [unknown])

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

    def test_abandoned_closure_does_not_hide_a_stall_or_count_as_merged(self):
        self.tick()
        for offset in range(60, collect.MIN_WAKE_SECONDS, 60):
            self.tick(self.now + offset)
        self.data["recovery"]["events"].append({"kind": "task_closed", "sequence": 1, "task": "work",
                                                "at": stamp(self.now + collect.MIN_WAKE_SECONDS - 1),
                                                "details": {"outcome": "abandoned"}})
        self.save_owner()
        checked = self.tick(self.now + collect.MIN_WAKE_SECONDS)
        self.assertTrue(checked["wake_agent"])
        metrics = collect.evidence(self.store, self.now + collect.MIN_WAKE_SECONDS)["total_metrics"]
        self.assertEqual(metrics["abandoned_task_closures"], 1)
        self.assertNotIn("merged_task_closures", metrics)

    def test_factory_churn_preserves_active_watermarks_and_never_replays_evicted_history(self):
        roles, quota, _, contexts, gaps = sources.owners([str(self.owner)], self.client.agents)
        def receipt(owner, sequence=1, offset=10):
            return {"owner": owner, "sequence": sequence, "at": stamp(self.now + offset),
                    "task": owner, "outcome": "merged"}
        def sample(receipts, offset):
            with patch.object(sources, "MAX_FACTORIES", 2), \
                    patch.object(sources, "owners", return_value=(roles, quota, receipts, contexts, gaps)):
                self.tick(self.now + offset)
            return collect.evidence(self.store, self.now + offset)["total_metrics"]["merged_task_closures"]
        self.assertEqual(sample([receipt("a"), receipt("b")], 60), 2)
        self.assertEqual(sample([receipt("a"), receipt("c")], 120), 3)
        self.assertEqual(set(self.record("closures")["by_owner"]), {"a", "c"})
        self.assertEqual(sample([receipt("a"), receipt("b")], 180), 3)
        self.assertIn("closure_history_before_eviction_floor_excluded", self.record("current")["coverage"])
        self.assertEqual(sample([receipt("a"), receipt("b"), receipt("b", 2, 181)], 240), 4)
        self.assertEqual(sample([receipt("a"), receipt("c")], 300), 4)
        self.assertEqual(sample([receipt("a"), receipt("c")], 360), 4)

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
        self.assertTrue(observer_role.matches(who, self.observer["agent_session"], env, client=self.client))
        self.assertFalse(observer_role.matches(who, self.observer["agent_session"], env, client=Client([{**self.observer, "name": "renamed"}])))
        self.assertFalse(observer_role.matches(who, self.observer["agent_session"], env, client=Client([])))
        row = self.observer
        class PaneClient:
            def pane_get(self, pane):
                return row
            def agent_get(self, name):
                return row if row["name"] == name else {}
        with patch("foreman.progression_owner.verify_foreman", side_effect=AssertionError("observer must not run foreman workflow")):
            selected = role_context.select(ROOT / "skills/herdr-foreman", client=PaneClient(),
                                           environment=env, cwd="/factory", binding_root=self.root / "empty-bindings")
        self.assertEqual(selected["role"], "observer")
        self.assertLess(len(selected["context"].encode()), 4096)
        altered = {**who, "value": "other"}
        self.assertFalse(observer_role.matches(altered, self.observer["agent_session"], {**env, "XDG_STATE_HOME": str(self.root / "missing")}, client=self.client))
        self.store.db.execute("PRAGMA user_version=99")
        self.store.db.commit()
        self.assertFalse(observer_role.matches(who, self.observer["agent_session"], env, client=self.client))
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

    def test_record_formats_refuse_partial_receipts_and_malformed_projections_without_rewriting(self):
        job = self.due()["data"]["job"]
        source = next(row for row in self.store.rows("sources") if row.get("kind") != "quota")
        bucket = self.store.rows("bins")[0]
        report = {"id": job["id"], "kind": "urgent", "path": str(self.cache / "reports" / (job["id"] + ".md")),
                  "at": self.now, "sha256": "a" * 64, "notification": "sent"}
        cases = [("reports", job["id"], {"id": job["id"]}),
                 ("reports", job["id"], {**report, "path": "/unrelated/report.md"}),
                 ("reports", job["id"], {**report, "sha256": "invalid"}),
                 ("meta", "acknowledgements", {"jobs": [{"id": job["id"]}]}),
                 ("meta", "binding", {**self.record("binding"), "at": "yesterday"}),
                 ("meta", "config", {**self.record("config"), "states": ["relative"]}),
                 ("meta", "current", {**self.record("current"), "agents": [{"role": "worker"}]}),
                 ("meta", "pending", {**job, "id": "../../escape"}),
                 ("meta", "heartbeat", {"at": float("nan"), "collection_seconds": 1}),
                 ("meta", "schedule", {"last_analysis": self.now, "last_anomaly": True}),
                 ("meta", "closures", {"by_owner": {"owner": False}}),
                 ("meta", "retention", {"at": self.now, "bins_evicted": 0, "sources_evicted": 0, "telemetry_floor": []}),
                 ("sources", source["key"], {**source, "offset": "100"}),
                 ("bins", "malformed-bin", {**bucket, "metrics": {"tool_calls": "100"}})]
        for table, key, value in cases:
            with self.subTest(table=table, key=key, value=value), self.store.transaction():
                self.store.db.execute("SAVEPOINT malformed")
                try:
                    with self.assertRaisesRegex(ValueError, "record shape"):
                        self.store.put(table, key, value, self.now)
                    raw = json.dumps({**value, "schema_version": 1})
                    if table == "meta":
                        self.store.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, raw))
                    else:
                        self.store.db.execute("INSERT OR REPLACE INTO " + table + " VALUES (?,?,?)", (key, self.now, raw))
                    with self.assertRaisesRegex(ValueError, "record shape"):
                        self.store.get(table, key)
                    if table != "meta":
                        with self.assertRaisesRegex(ValueError, "record shape"):
                            self.store.rows(table)
                    if table == "reports":
                        with patch.dict(os.environ, {"HERDR_PANE_ID": self.observer["pane_id"]}):
                            with self.assertRaisesRegex(ValueError, "record shape"):
                                cli.report(self.store, self.client, key, "urgent", "/unused", self.now)
                    self.assertEqual(self.store.db.execute("SELECT value FROM " + table + " WHERE key=?", (key,)).fetchone()[0], raw)
                finally:
                    self.store.db.execute("ROLLBACK TO malformed")
                    self.store.db.execute("RELEASE malformed")
        self.assertEqual(self.client.notifications, 0)

    def test_role_reader_refuses_malformed_consumed_meta_fields_without_writes(self):
        who = {"kind": "id", "value": self.observer["agent_session"]["value"], "cwd": "/factory",
               "pane_id": self.observer["pane_id"], "herdr_env": "1"}
        env = {"XDG_STATE_HOME": str(self.cache.parent)}
        originals = {key: self.record(key) for key in ("binding", "config")}
        cases = [("binding", []), ("config", []), ("binding", {**originals["binding"], "cwd": []}),
                 ("binding", {k: v for k, v in originals["binding"].items() if k != "name"}),
                 ("binding", {**originals["binding"], "name": ""}), ("binding", {**originals["binding"], "name": []}),
                 ("binding", {**originals["binding"], "identity": []}),
                 ("config", {**originals["config"], "states": {}}),
                 ("config", {**originals["config"], "states": [1]}),
                 ("config", {**originals["config"], "states": ["relative"]})]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                for name, original in originals.items():
                    self.store.put("meta", name, original)
                self.store.db.execute("UPDATE meta SET value=? WHERE key=?", (json.dumps(value), key))
                self.store.db.commit()
                before = (self.cache / "observer.sqlite3").read_bytes()
                self.assertFalse(observer_role.matches(who, self.observer["agent_session"], env, client=self.client))
                self.assertEqual((self.cache / "observer.sqlite3").read_bytes(), before)

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

    def test_byte_pressure_reclaims_space_before_a_new_insert(self):
        row = {"at": self.now, "key": "pressure", "name": "pressure", "provider": "codex", "role": "worker",
               "metrics": {}, "profiles": {}, "locators": []}
        self.store.db.execute("PRAGMA max_page_count=128")
        filled = False
        for index in range(200):
            try:
                with self.store.transaction():
                    self.store.put("bins", str(index), {**row, "payload": "x" * 8192}, self.now + index)
            except sqlite3.OperationalError:
                filled = True
                break
        self.assertTrue(filled)
        with self.store.transaction():
            self.store.prune(self.now + 200)
        with self.store.transaction():
            self.store.put("bins", "fresh", {**row, "payload": "y" * 8192}, self.now + 201)
        fresh = self.store.get("bins", "fresh")
        assert fresh is not None
        self.assertEqual(fresh["payload"], "y" * 8192)
        self.assertGreater(self.record("retention")["bins_evicted"], 0)
        self.assertEqual(self.record("binding")["name"], "observer")

    def test_pruning_validates_all_candidates_before_deleting_any_file(self):
        job_id = native.fingerprint("valid-report")
        directory = private_directory(self.cache / "reports")
        valid = directory / (job_id + ".md")
        private_file(valid)
        valid.write_text("keep valid report")
        outside = self.cache.parent / "target.md"
        outside.write_text("keep outside file")
        receipt = {"id": job_id, "kind": "urgent", "path": str(valid), "at": self.now,
                   "sha256": "a" * 64, "notification": "sent"}
        with self.store.transaction():
            self.store.put("reports", job_id, receipt, self.now)
            bad = {**receipt, "id": "../../target", "path": str(outside), "schema_version": 1}
            self.store.db.execute("INSERT INTO reports VALUES (?,?,?)", (bad["id"], self.now - 1, json.dumps(bad)))
        before = [tuple(row) for row in self.store.db.execute("SELECT * FROM reports ORDER BY key")]
        with patch("factory_observer.store.MAX_REPORTS", 0):
            with self.assertRaisesRegex(ValueError, "record shape"), self.store.transaction():
                self.store.prune(self.now)
        self.assertEqual(valid.read_text(), "keep valid report")
        self.assertEqual(outside.read_text(), "keep outside file")
        self.assertEqual([tuple(row) for row in self.store.db.execute("SELECT * FROM reports ORDER BY key")], before)
        with self.store.transaction():
            self.store.db.execute("DELETE FROM reports WHERE key=?", (bad["id"],))
        saved = self.cache / "saved-reports"
        directory.rename(saved)
        external = self.root / "outside-reports"
        external.mkdir()
        external_report = external / valid.name
        external_report.write_text("keep linked target")
        directory.symlink_to(external)
        with patch("factory_observer.store.MAX_REPORTS", 0):
            with self.assertRaisesRegex(ValueError, "owned directory"), self.store.transaction():
                self.store.prune(self.now)
        self.assertEqual(external_report.read_text(), "keep linked target")
        self.assertEqual((saved / valid.name).read_text(), "keep valid report")
        self.assertIsNotNone(self.store.get("reports", job_id))

    def test_evicted_source_baseline_does_not_replay_old_log_costs(self):
        self.log(records=[self.event("response_item", {"type": "function_call", "call_id": "old", "name": "exec"})])
        self.tick(self.now + 60)
        with self.store.transaction():
            self.store.db.execute("DELETE FROM sources WHERE key=?", (native.session_key(native.identity(self.foreman)),))
            self.store.put("meta", "retention", {"telemetry_floor": self.now + 120, "at": self.now + 120,
                                                  "bins_evicted": 0, "sources_evicted": 1})
        self.log(records=[self.event("response_item", {"type": "function_call", "call_id": "fresh", "name": "exec"}, 121)])
        self.tick(self.now + 180)
        self.assertEqual(collect.evidence(self.store, self.now + 180)["total_metrics"]["tool_calls"], 2)

    def test_report_expiry_survives_commit_failure_and_orphan_cleanup_retry(self):
        directory = private_directory(self.cache / "reports")
        job_id = native.fingerprint("expiry-report")
        report = directory / (job_id + ".md")
        private_file(report)
        report.write_text("durable report")
        receipt = {"id": job_id, "kind": "urgent", "path": str(report), "at": self.now,
                   "sha256": "a" * 64, "notification": "sent"}
        with self.store.transaction():
            self.store.put("reports", job_id, receipt, self.now)
        self.store.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE parent_commit (id INTEGER PRIMARY KEY);
            CREATE TABLE child_commit (parent INTEGER,
                FOREIGN KEY(parent) REFERENCES parent_commit(id) DEFERRABLE INITIALLY DEFERRED);
        """)
        with patch("factory_observer.store.MAX_REPORTS", 0):
            with self.assertRaises(sqlite3.IntegrityError), self.store.transaction():
                self.store.prune(self.now)
                self.store.db.execute("INSERT INTO child_commit VALUES (1)")
        self.assertEqual(report.read_text(), "durable report")
        self.assertIsNotNone(self.store.get("reports", job_id))
        with self.store.transaction():
            with self.assertRaisesRegex(ValueError, "commit observer state"):
                self.store.collect_report_files()
        with patch("factory_observer.store.MAX_REPORTS", 0), self.store.transaction():
            self.store.prune(self.now)
        self.assertIsNone(self.store.get("reports", job_id))
        self.assertTrue(report.exists())
        temporary = directory / (native.fingerprint("partial-write") + ".tmp")
        private_file(temporary)
        temporary.write_text("uncommitted partial report")
        unlink = Path.unlink
        removed = []
        def fail_after_one(path, *, missing_ok=False):
            if removed:
                raise OSError("injected cleanup failure")
            unlink(path, missing_ok=missing_ok)
            removed.append(path)
        with patch.object(Path, "unlink", new=fail_after_one):
            with self.assertRaises(OSError):
                self.store.collect_report_files()
        self.assertEqual(sum(path.exists() for path in (report, temporary)), 1)
        self.assertIsNone(self.store.get("reports", job_id))
        restarted = Store(self.cache)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.collect_report_files(), 1)
        self.assertEqual(restarted.collect_report_files(), 0)
        self.assertFalse(report.exists())
        self.assertFalse(temporary.exists())

    def test_report_file_backlog_is_bounded_and_recovers_after_cleanup(self):
        job = self.due()["data"]["job"]
        directory = private_directory(self.cache / "reports")
        for index in range(MAX_REPORT_SWEEP):
            private_file(directory / (native.fingerprint(["orphan", index]) + ".md"))
        draft = private_directory(self.cache / "drafts") / (job["id"] + ".md")
        private_file(draft)
        draft.write_text("private report after cleanup")
        with patch.dict(os.environ, {"HERDR_PANE_ID": self.observer["pane_id"]}):
            with self.assertRaisesRegex(ValueError, "restore private report cleanup"):
                cli.report(self.store, self.client, job["id"], "urgent", str(draft), self.now + 1000)
            self.assertEqual(self.record("pending")["id"], job["id"])
            self.assertIsNone(self.store.get("reports", job["id"]))
            self.assertEqual(self.store.collect_report_files(), MAX_REPORT_SWEEP)
            self.assertTrue(cli.report(self.store, self.client, job["id"], "urgent", str(draft), self.now + 1000)["ok"])
        self.assertEqual(len(list(directory.glob("*.md"))), 1)


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
