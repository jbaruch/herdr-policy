"""Native Antigravity subscription, launch and session-bound delivery fixtures."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from foreman import antigravity_native as native, config, measure, planner, report_delivery, session_start_hook, tiers
from foreman.assign import native_context_session
from foreman.errors import ConfigError, HerdrError, ParseError


SESSION = "00000000-0000-4000-8000-000000000001"
AT = "2026-09-01T12:00:00Z"


def usage():
    return {"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "buckets": [{"id": "gemini-weekly", "remaining_fraction": .8, "reset_time": AT}]},
        {"name": "Claude and GPT models", "buckets": [{"id": "3p-weekly", "remaining_fraction": .4, "reset_time": AT}]},
    ]}}}


def rows():
    return [{"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": AT, "content": "Simplify the assigned module"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": AT, "content": "Implemented and checked.\nREPORT: /private/report.md"}]


class AntigravityTest(unittest.TestCase):
    def test_quota_is_remaining_and_preserves_both_subscription_pools(self):
        parsed = native.parse_usage(json.dumps(usage()))
        self.assertEqual(parsed["windows"]["Gemini Models/gemini-weekly"]["used_pct"], 20)
        self.assertEqual(parsed["windows"]["Claude and GPT models/3p-weekly"]["remaining_pct"], 40)

    def test_missing_invalid_or_api_only_quota_does_not_become_capacity(self):
        for fraction in (-.1, 1.1, True, "0.8", float("nan")):
            data = usage()
            data["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"] = fraction
            with self.subTest(fraction=fraction), self.assertRaises(ParseError):
                native.parse_usage(json.dumps(data))
        for data in ({}, {"status": "ERROR"}, {"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": []}}}):
            with self.subTest(data=data), self.assertRaises(ParseError):
                native.parse_usage(json.dumps(data))

    def test_quota_command_uses_subscription_without_a_model_prompt(self):
        seen = []
        def run(argv, **options):
            seen.append((argv, options))
            return SimpleNamespace(returncode=0, stdout=json.dumps(usage()))
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fixture-key", "GOOGLE_API_KEY": "fixture-key"}):
            native.subscription_usage(run=run)
        self.assertEqual(seen[0][0], ["agy", "-p", "/usage", "--output-format", "json", "--print-timeout", "15s"])
        self.assertNotIn("GEMINI_API_KEY", seen[0][1]["env"])
        self.assertNotIn("GOOGLE_API_KEY", seen[0][1]["env"])
        with self.assertRaises(HerdrError):
            native.subscription_usage(run=lambda *a, **kw: SimpleNamespace(returncode=1, stdout=""))
        with self.assertRaises(HerdrError):
            native.subscription_usage(run=lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("agy", 20)))

    def test_profile_enters_normal_planning_with_exact_native_flags(self):
        raw = json.loads((Path(__file__).resolve().parents[3] / "skills/herdr-foreman/config.example.json").read_text())
        raw["worker_kinds"].append(json.loads((Path(__file__).resolve().parents[3] / "skills/herdr-foreman/antigravity.example.json").read_text()))
        agents = config.parse_config(raw)
        worker = next(agent for agent in agents if agent.kind == "agy")
        tier = tiers.select_tier(worker, "developer")
        self.assertIsNotNone(tier)
        assert tier is not None
        expected = ["agy", "--dangerously-skip-permissions", "--model", tier["model"], "--effort", tier["effort"]]
        tiers.verify_argv("agy", tier, expected, tiers.worker_launch_args("agy"))
        tiers.verify_worker_permissions("agy", [*expected, "--conversation", SESSION])
        snapshot = {"agents": {worker.name: {"kind": "agy", "state": "idle", "headroom_pct": 40},
                               "codex": {"kind": "codex", "state": "idle", "headroom_pct": 10}}}
        result = planner.plan(["developer"], snapshot)
        self.assertEqual(result["assignments"]["developer"], worker.name)

    def test_foreman_adapter_is_not_inferred_from_worker_support(self):
        raw = {"schema_version": 7, "worker_kinds": [], "foreman": {"agent": "foreman", "kind": "agy"}}
        with self.assertRaisesRegex(ConfigError, "supplies workers"):
            config.parse_foreman(raw)

    def test_real_integration_identity_and_conversation_path_bind_delivery(self):
        identity = {"source": native.SOURCE, "agent": "agy", "kind": "id", "value": SESSION}
        info = {"pane_id": "worker-pane", "agent_session": identity}
        self.assertEqual(report_delivery.native_identity(info), identity)
        self.assertEqual(native_context_session(info, "agy"), {"pane_id": "worker-pane", **identity})
        self.assertIsNone(report_delivery.native_identity({"agent_session": {**identity, "source": "herdr:agy"}}))
        with tempfile.TemporaryDirectory() as directory, patch.object(native, "sessions_root", return_value=Path(directory).resolve()):
            path = native.transcript_path(SESSION)
            assert path is not None
            body = "\n".join(json.dumps(row) for row in rows())
            self.assertEqual(report_delivery.source_path(identity), path)
            final = report_delivery.source_final(body, "agy", SESSION, path=path)
            self.assertTrue(report_delivery.bare_final(final, "/private/report.md"))
            self.assertEqual(report_delivery.source_prompt(body, "agy", SESSION, path=path), rows()[0]["content"])
            self.assertIsNone(report_delivery.source_final(body, "agy", SESSION))
            self.assertIsNone(report_delivery.source_final(body, "agy", SESSION, path=Path(directory)/"archive.jsonl"))

    def test_partial_tool_or_non_model_tail_cannot_deliver_a_report(self):
        path = native.transcript_path(SESSION)
        for change in ({"status": "RUNNING"}, {"type": "GENERIC"}, {"source": "USER_EXPLICIT"}, {"step_index": 0}):
            data = copy.deepcopy(rows())
            data[-1].update(change)
            with self.subTest(change=change):
                self.assertIsNone(native.final_message(data, SESSION, path))

    def test_tool_records_use_native_step_order_and_do_not_mask_a_completed_final(self):
        data = rows()
        data[1]["step_index"] = 3
        data.insert(1, {"step_index": 2, "type": "GENERIC", "source": "MODEL", "status": "RUNNING", "content": "Background tool"})
        data.append({"step_index": 1, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE", "content": "Working"})
        self.assertEqual(native.final_message(data, SESSION, native.transcript_path(SESSION)), rows()[-1]["content"])
        data.append({"step_index": 4, "type": "GENERIC", "source": "MODEL", "status": "RUNNING", "content": "Later work"})
        self.assertIsNone(native.final_message(data, SESSION, native.transcript_path(SESSION)))

    def test_live_report_is_verified_from_the_registered_native_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            report = root / "report.md"
            report.write_text("Scoped optimization and checks completed.")
            with patch.object(native, "sessions_root", return_value=root / "native"):
                path = native.transcript_path(SESSION)
                assert path is not None
                path.parent.mkdir(parents=True)
                data = rows()
                data[-1]["content"] = "Done.\nREPORT: " + str(report)
                path.write_text("\n".join(json.dumps(row) for row in data))
                identity = {"source": native.SOURCE, "agent": "agy", "kind": "id", "value": SESSION}
                pane = {"pane_id": "worker-pane", "agent_session": identity, "terminal_id": "native-terminal",
                        "revision": 1, "scroll": {"offset_from_bottom": 0}, "agent_status": "idle"}
                visible = "Native TUI decoration: REPORT: " + str(report)
                client = SimpleNamespace(agent_get=lambda name: pane, pane_get=lambda name: pane,
                                         pane_read=lambda name, **kw: visible)
                result = report_delivery.probe(client, "worker", "worker-pane", str(report), visible, 40)
                self.assertTrue(result["found"])
                data[-1]["status"] = "RUNNING"
                path.write_text("\n".join(json.dumps(row) for row in data))
                self.assertFalse(report_delivery.probe(client, "worker", "worker-pane", str(report), visible, 40)["found"])

    def test_usage_read_does_not_write_to_the_worker_or_use_remote_account(self):
        agent = config.Agent("antigravity", "agy", "/usage", "Weekly Limit Remaining", "visible", "/clear")
        client = SimpleNamespace(agent_get=lambda name: {"pane_id": "worker-pane", "agent_status": "idle"})
        with patch.object(native, "subscription_usage", return_value=native.parse_usage(json.dumps(usage()))):
            record = measure.measure_agent(client, agent)
        self.assertEqual(record["headroom_pct"], 40)
        client.context = SimpleNamespace(mode="attested-remote")
        with self.assertRaisesRegex(HerdrError, "native controller host"):
            measure.measure_agent(client, agent)

    def test_native_startup_uses_antigravity_injection_contract(self):
        reader = lambda *a, **kw: {"role": "worker", "reason": "enrolled_native_worker", "context": "Scoped worker contract"}
        result = session_start_hook.collect(Path(__file__).resolve().parents[3] / "skills/herdr-foreman",
            {"HERDR_ENV": "1", "HERDR_HOOK_ADAPTER": "antigravity"}, {"conversationId": SESSION}, context_reader=reader)
        assert result is not None
        self.assertIn("Scoped worker contract", result["injectSteps"][0]["systemMessage"]["systemMessage"])


if __name__ == "__main__":
    unittest.main()
