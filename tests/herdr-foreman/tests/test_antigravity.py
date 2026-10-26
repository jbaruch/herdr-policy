"""Native Antigravity subscription, launch and session-bound delivery fixtures."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from foreman import antigravity_native as native, config, launch, measure, planner, report_delivery, session_start_hook, tiers
from foreman import assign, composer, lifecycle, recovery, supervision
from foreman.assign import native_context_session
from foreman.diagnostics import PREFIX as DIAGNOSTIC_PREFIX
from foreman.errors import ConfigError, HerdrError, ParseError
from foreman.state import load_state_checked
from tests import agy_capture as capture
from tests.test_cli import CliCase, FreshOwnerNative


SESSION = capture.SONNET_SESSION
AT = "2026-09-01T12:00:00Z"
#: The prompts the native probes actually submitted, as their displays echo them.
OPUS_REQUEST = ("Account/model diagnostic only. Reply exactly ACCESS_OPUS_OK. Do not use tools, read files, "
                "create any report, or perform any external action.")
FALLBACK_REQUEST = "Reply exactly ACCESS_OK. Do not use tools or read or write files."
SONNET_REQUEST = ("For a display-only diagnostic, reply exactly REPORT: "
                  "/private/tmp/herdr-agy-adapter-probe-20261025-4ksz1nvx/display-only.txt . "
                  "Omit the trailing space and dot. Do not create any file, use tools, or read or write files.")
SONNET_REPORT = "/private/tmp/herdr-agy-adapter-probe-20261025-4ksz1nvx/display-only.txt"


def usage():
    return {"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "buckets": [{"id": "gemini-weekly", "remaining_fraction": .8, "reset_time": AT}]},
        {"name": "Claude and GPT models", "buckets": [{"id": "3p-weekly", "remaining_fraction": .4, "reset_time": AT}]},
    ]}}}


def rows():
    """The captured no-effort Sonnet turn, whose final is a bare report marker."""
    return copy.deepcopy(capture.SONNET_ROWS)


def transcript_rows(body):
    return [json.loads(line) for line in body.splitlines()]


def with_request(content, original, request):
    """A captured envelope carrying another request; every other byte is native."""
    if content.count(original) != 1:
        raise AssertionError("The captured request must occur exactly once in its envelope.")
    return content.replace(original, request)


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
        with self.assertRaisesRegex(HerdrError, "subscription"):
            native.subscription_usage(run=lambda *a, **kw: (_ for _ in ()).throw(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")))

    def test_a_relocated_brain_root_works_but_a_linked_conversation_cannot_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "user"
            parent = home / ".gemini/antigravity-cli"
            parent.mkdir(parents=True)
            actual = root / "native"
            actual.mkdir()
            (parent / "brain").symlink_to(actual, target_is_directory=True)
            with patch.object(Path, "home", return_value=home):
                self.assertEqual(native.sessions_root(), actual)
                path = native.transcript_path(SESSION)
                self.assertEqual(native.final_message(rows(), SESSION, path), rows()[-1]["content"])
                outside = root / "outside"
                outside.mkdir()
                (actual / SESSION).symlink_to(outside, target_is_directory=True)
                self.assertIsNone(native.final_message(rows(), SESSION, path))

    def test_profile_enters_normal_planning_with_exact_native_flags(self):
        raw = json.loads((Path(__file__).resolve().parents[3] / "skills/herdr-foreman/config.example.json").read_text())
        raw["worker_kinds"].append(json.loads((Path(__file__).resolve().parents[3] / "skills/herdr-foreman/antigravity.example.json").read_text()))
        agents = config.parse_config(raw)
        worker = next(agent for agent in agents if agent.kind == "agy")
        tier = tiers.select_tier(worker, "developer")
        self.assertIsNotNone(tier)
        assert tier is not None
        self.assertIsNone(tier["effort"])
        self.assertTrue(all(row["effort"] is None and row["model"] in native.NO_EFFORT_MODELS
                            for row in worker.tiers.values()))
        self.assertFalse(set(worker.tiers) & tiers.JUDGMENT_ROUNDS)
        expected = ["agy", "--dangerously-skip-permissions", "--model", tier["model"]]
        tiers.verify_argv("agy", tier, expected, tiers.worker_launch_args("agy"))
        tiers.verify_worker_permissions("agy", [*expected, "--conversation", SESSION])
        for role in ("reviewer", "tester"):
            with self.subTest(role=role), self.assertRaises(tiers.MissingTierError):
                tiers.select_tier(worker, role)
        snapshot = {"agents": {worker.name: {"kind": "agy", "state": "idle", "headroom_pct": 40},
                               "codex": {"kind": "codex", "state": "idle", "headroom_pct": 10}}}
        result = planner.plan(["developer"], snapshot)
        self.assertEqual(result["assignments"]["developer"], worker.name)

    def test_native_display_proves_only_the_model_it_shows(self):
        opus, sonnet = ({"model": model, "effort": None} for model in ("claude-opus-4-6-thinking", "claude-sonnet-4-6"))
        proof = {"source": "native_display", "effort": "unknown"}
        self.assertEqual(native.admit_model(opus, capture.OPUS_DISPLAY), {**proof, "label": "Claude Opus 4.6 (Thinking)"})
        self.assertEqual(native.admit_model(sonnet, capture.SONNET_DISPLAY), {**proof, "label": "Claude Sonnet 4.6 (Thinking)"})
        self.assertEqual(native.displayed_model(capture.FALLBACK_DISPLAY), "Gemini 3.8 Flash · high")
        for tier, display in ((sonnet, capture.FALLBACK_DISPLAY), (sonnet, capture.OPUS_DISPLAY), (opus, capture.SONNET_DISPLAY)):
            with self.subTest(tier=tier["model"], display=native.displayed_model(display)), \
                    self.assertRaisesRegex(HerdrError, "not the requested"):
                native.admit_model(tier, display)

    def test_unproven_requests_or_missing_footers_are_refused_before_input(self):
        for tier in ({"model": "claude-sonnet-4-6", "effort": "high"}, {"model": "gemini-fixture-model", "effort": "high"},
                     {"model": "claude-opus-4-6-thinking", "effort": "high"}):
            with self.subTest(tier=tier), self.assertRaisesRegex(HerdrError, "no captured native display"):
                native.admit_model(tier, capture.OPUS_DISPLAY)
        startup = capture.OPUS_DISPLAY.rsplit("? for shortcuts", 1)[0]
        for display in (startup, "", capture.OPUS_DISPLAY.replace("shortcuts    ", "shortcuts\n   ")):
            with self.subTest(display=display[-40:]), self.assertRaisesRegex(HerdrError, "footer is not visible"):
                native.admit_model({"model": "claude-opus-4-6-thinking", "effort": None}, display)

    def test_each_captured_pair_admits_its_own_footer_and_recovers_by_its_selection(self):
        displays = {"claude-opus-4-6-thinking": (capture.OPUS_DISPLAY, capture.OPUS_SESSION,
                                                 transcript_rows(capture.OPUS_TRANSCRIPT)),
                    "claude-sonnet-4-6": (capture.SONNET_DISPLAY, capture.SONNET_SESSION, rows())}
        self.assertEqual(set(native.CAPTURED_DISPLAYS), {(model, None) for model in displays})
        for (model, effort), captured in native.CAPTURED_DISPLAYS.items():
            display, session, data = displays[model]
            tier = {"model": model, "effort": effort}
            with self.subTest(model=model):
                self.assertEqual(native.admit_model(tier, display), {"source": "native_display",
                    "label": captured["footer"], "effort": captured["effort"]})
                body = "\n".join(json.dumps(row) for row in data)
                path = native.transcript_path(session)
                self.assertEqual(native.model_selection(data, session, path), captured["selection"])
                self.assertTrue(report_delivery.native_model_matches(body, session, path, tier))
                self.assertFalse(report_delivery.native_model_matches(body, session, path, {**tier, "effort": "high"}))

    def test_a_configured_gemini_pair_names_its_missing_capture_instead_of_an_alias(self):
        # The 0.16 Gemini profile still parses and launches with its explicit
        # effort. Only Gemini's fallback rendering is captured, under a Sonnet
        # request; it proves no Gemini request, so admission returns the
        # capture contract rather than mapping that footer onto the pair.
        tier = tiers.parse_tiers({"build": {"model": "gemini-3.8-flash-medium", "effort": "medium"}}, "agy")["build"]
        self.assertEqual(tiers.launch_flags("agy", tier), ["--model", "gemini-3.8-flash-medium", "--effort", "medium"])
        for display in (capture.FALLBACK_DISPLAY, capture.SONNET_DISPLAY):
            with self.subTest(display=native.displayed_model(display)), self.assertRaises(HerdrError) as raised:
                native.admit_model({"model": tier["model"], "effort": tier["effort"]}, display)
            self.assertIn("'gemini-3.8-flash-medium' at effort medium", str(raised.exception))
            self.assertIn("references/antigravity.md Admission Capture", str(raised.exception))
        selection = transcript_rows(capture.FALLBACK_TRANSCRIPT)
        body = "\n".join(json.dumps(row) for row in selection)
        path = native.transcript_path(capture.FALLBACK_SESSION)
        self.assertEqual(native.model_selection(selection, capture.FALLBACK_SESSION, path), "Gemini 3.8 Flash (High)")
        for effort in ("high", "medium"):
            self.assertFalse(report_delivery.native_model_matches(body, capture.FALLBACK_SESSION, path,
                                                                  {"model": "gemini-3.8-flash-medium", "effort": effort}))

    def test_the_raw_effort_warning_capture_is_refused_through_the_live_reader(self):
        worker = SimpleNamespace(kind="agy")
        reads = []
        client = SimpleNamespace(pane_read=lambda pane, lines: reads.append((pane, lines)) or capture.FALLBACK_WARNING_ANSI)
        with self.assertRaises(HerdrError) as raised:
            launch.verify_native_model(client, worker, "worker-pane", {"model": "claude-sonnet-4-6", "effort": None})
        self.assertEqual(raised.exception.details["displayed"], "Gemini 3.8 Flash · high")
        self.assertEqual(reads, [("worker-pane", launch.NATIVE_MODEL_LINES)])
        self.assertIsNone(launch.verify_native_model(client, SimpleNamespace(kind="claude"), "worker-pane", {}))
        self.assertEqual(len(reads), 1)

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
            self.assertTrue(report_delivery.bare_final(final, SONNET_REPORT))
            self.assertEqual(report_delivery.source_prompt(body, "agy", SESSION, path=path), SONNET_REQUEST)
            self.assertIsNone(report_delivery.source_final(body, "agy", SESSION))
            self.assertIsNone(report_delivery.source_final(body, "agy", SESSION, path=Path(directory)/"archive.jsonl"))
            self.assertIsNone(report_delivery.source_prompt(body, "agy", SESSION, path=Path(directory)/"archive.jsonl"))

    def test_captured_transcripts_are_the_byte_exact_native_files(self):
        self.assertEqual(hashlib.sha256(capture.OPUS_TRANSCRIPT.encode("utf-8")).hexdigest(),
                         "87da888f17d6ff169cb824e39c8a3304703dc7f96dd002c5083b03f61fcde491")
        self.assertEqual(hashlib.sha256(capture.FALLBACK_TRANSCRIPT.encode("utf-8")).hexdigest(),
                         capture.FALLBACK_TRANSCRIPT_SHA256)

    def test_native_envelope_yields_the_exact_dispatched_request_and_model_selection(self):
        captured = (
            (transcript_rows(capture.OPUS_TRANSCRIPT), capture.OPUS_SESSION, OPUS_REQUEST, "Claude Opus 4.6 (Thinking)"),
            (transcript_rows(capture.FALLBACK_TRANSCRIPT), capture.FALLBACK_SESSION, FALLBACK_REQUEST, "Gemini 3.8 Flash (High)"),
            (rows(), capture.SONNET_SESSION, SONNET_REQUEST, "Claude Sonnet 4.6 (Thinking)"),
        )
        for data, session, request, selection in captured:
            with self.subTest(request=request):
                envelope = native.user_request(data[0]["content"])
                self.assertEqual(envelope, {"request": request, "model_selection": selection})
                body = "\n".join(json.dumps(row) for row in data)
                path = native.transcript_path(session)
                self.assertEqual(report_delivery.source_prompt(body, "agy", session, path=path), request)
                self.assertTrue(report_delivery.prompt_matches(request, request, "agy"))
                self.assertFalse(report_delivery.prompt_matches(data[0]["content"], request, "agy"))

    def test_multiline_request_whitespace_survives_the_native_envelope_exactly(self):
        content = transcript_rows(capture.OPUS_TRANSCRIPT)[0]["content"]
        for request in ("  Indented first line\n\n\tTabbed line  \nLast line ", "\nLeading blank line", "Trailing newline\n"):
            with self.subTest(request=request):
                envelope = native.user_request(with_request(content, OPUS_REQUEST, request))
                assert envelope is not None
                self.assertEqual(envelope["request"], request)
                self.assertFalse(report_delivery.prompt_matches(envelope["request"], request.strip(), "agy"))

    def test_malformed_nested_quoted_or_extended_envelopes_are_refused(self):
        content = transcript_rows(capture.OPUS_TRANSCRIPT)[0]["content"]
        metadata = content[content.index("\n<ADDITIONAL_METADATA>"):content.index("\n<USER_SETTINGS_CHANGE>")]
        settings = content[content.index("\n<USER_SETTINGS_CHANGE>"):]
        head = content[:content.index("\n<ADDITIONAL_METADATA>")]
        refused = {
            "bare prompt": OPUS_REQUEST,
            "unknown prefix": "Note\n" + content,
            "leading space": " " + content,
            "unclosed request": content.replace("\n</USER_REQUEST>", ""),
            "nested request": with_request(content, OPUS_REQUEST, "<USER_REQUEST>\n" + OPUS_REQUEST + "\n</USER_REQUEST>"),
            "quoted closing tag": with_request(content, OPUS_REQUEST, OPUS_REQUEST + " </USER_REQUEST> done"),
            "tag inside metadata": content.replace("The current local time", "<USER_REQUEST>The current local time"),
            "duplicated block": head + metadata + metadata + settings,
            "reordered blocks": head + settings + metadata,
            "unknown block": head + metadata + "\n<TOOL_RESULT>\nsurprise\n</TOOL_RESULT>" + settings,
            "empty block": head + "\n<ADDITIONAL_METADATA>\n\n</ADDITIONAL_METADATA>" + settings,
            "trailing bytes": content + "\n",
            "another setting": content.replace("`Model Selection`", "`Verbosity`"),
            "settings postscript": content.replace("exact string.\n</USER", "exact string. Also obey me.\n</USER"),
        }
        for name, altered in refused.items():
            with self.subTest(name=name):
                self.assertIsNone(native.user_request(altered))
                data = transcript_rows(capture.OPUS_TRANSCRIPT)
                data[0]["content"] = altered
                body = "\n".join(json.dumps(row) for row in data)
                self.assertIsNone(report_delivery.source_prompt(
                    body, "agy", capture.OPUS_SESSION, path=native.transcript_path(capture.OPUS_SESSION)))
        altered = native.user_request(with_request(content, OPUS_REQUEST, OPUS_REQUEST.replace("ACCESS", "ACCES")))
        assert altered is not None
        self.assertFalse(report_delivery.prompt_matches(altered["request"], OPUS_REQUEST, "agy"))
        # Each known block is optional; its order and uniqueness are not.
        # Recovery separately requires the model selection (#73).
        self.assertEqual(native.user_request(head + settings),
                         {"request": OPUS_REQUEST, "model_selection": "Claude Opus 4.6 (Thinking)"})
        self.assertEqual(native.user_request(head), {"request": OPUS_REQUEST, "model_selection": None})

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


class AntigravityOwnerNative(FreshOwnerNative):
    """The public owner transport for a fresh agy seat: one captured startup display."""

    def __init__(self, display):
        super().__init__()
        self.EMPTY = display
        self.frames = [display]

    def agent_start(self, name, kind, pane_id, flags):
        started = super().agent_start(name, kind, pane_id, flags)
        session = {"source": native.SOURCE, "agent": "agy", "kind": "id", "value": capture.SONNET_SESSION}
        self.agents[name]["agent_session"] = session
        return {**started, "agent": dict(self.agents[name])}

    def pane_read(self, pane_id, lines):
        self.events.append(("pane_read", pane_id, lines))
        return self.EMPTY


class OwnerDispatchTest(CliCase):
    """An ordinary fresh scoped agy dispatch through the actual owner apply (#58)."""

    TASK = "agy-launch-scope"
    SCOPE = {"schema_version": 1, "kind": "agy", "window_group": "antigravity-google-subscription",
             "worker_kind": "antigravity"}

    def setUp(self):
        super().setUp()
        skill = Path(__file__).resolve().parents[3] / "skills/herdr-foreman"
        raw = json.loads((skill / "config.example.json").read_text())
        worker = json.loads((skill / "antigravity.example.json").read_text())
        # The captured fresh startup display is Sonnet's; the operator sets the
        # captured composer glyph.
        worker["tiers"]["build"] = {"model": "claude-sonnet-4-6", "multiplier": 1.0}
        worker["composer_glyph"] = "> "
        raw["worker_kinds"].append(worker)
        self.config.write_text(json.dumps(raw))
        snapshot = json.loads(self.snapshot.read_text())
        snapshot["measured_at"] = AT
        snapshot["agents"]["antigravity"] = {"kind": "agy", "state": "idle", "headroom_pct": 95.049697}
        self.snapshot.write_text(json.dumps(snapshot))
        record = self.tmp / "task.json"
        record.write_text(json.dumps({"task": self.TASK, "base_revision": "a" * 40, "scope": "Antigravity launch scope",
            "allowed_paths": ["src/*"], "authorization": {"source": "fixture operator", "quote": "Implement this task."}}))
        code, _, error = self.invoke(["task", "--record", str(record), "--now", AT])
        self.assertEqual(code, 0, error)
        supervision.bind(self.state, {"kind": "id", "value": "fixture-foreman", "cwd": str(self.tmp),
            "herdr_env": "fixture", "pane_id": "foreman-pane"}, AT, root=self.tmp / "bindings")
        self.report = self.tmp / "report.md"
        self.assign_report(self.briefs["developer"], self.report)
        with patch("foreman.lifecycle.identity", return_value="developer-agy"):
            code, output, error = self.invoke(["plan", "--roles", "developer", "--task", self.TASK,
                "--snapshot", str(self.snapshot), "--exclude", "developer=claude,codex,grok", "--now", AT])
        self.assertEqual(code, 0, error)
        self.plan = json.loads(output)

    def invoke(self, args, client=None):
        self.out, self.err = io.StringIO(), io.StringIO()
        return self.run_cli(self.base() + args, client=client)

    def apply(self, client):
        real_spawn, real_apply, real_ready = lifecycle.spawn, assign.apply, composer.ensure_ready
        with patch("foreman.cli.lifecycle.spawn", side_effect=lambda *a, **kw: real_spawn(*a, **kw, sleep=lambda _: None)), \
                patch("foreman.cli.apply_assignments", side_effect=lambda *a, **kw: real_apply(*a, **kw, sleep=lambda _: None)), \
                patch("foreman.cli.ensure_ready", side_effect=lambda *a, **kw: real_ready(*a, **kw, sleep=lambda _: None)):
            return self.invoke(["apply", "--assignments", json.dumps(self.plan), "--task", self.TASK,
                "--common", str(self.common), "--brief", "developer=" + str(self.briefs["developer"]),
                "--report", "developer=" + str(self.report), "--now", AT, "--composer-settle", "0"], client)

    def test_fresh_dispatch_records_its_agy_launch_scope_and_sends_once(self):
        client = AntigravityOwnerNative(capture.SONNET_DISPLAY)
        code, output, error = self.apply(client)
        self.assertEqual(code, 0, error)
        applied = json.loads(output)["applied"][0]
        self.assertEqual(applied["launch_scope"], self.SCOPE)
        self.assertEqual(applied["tier"]["native_model"], {"source": "native_display",
            "label": "Claude Sonnet 4.6 (Thinking)", "effort": "unknown"})
        self.assertEqual(client.agents["developer-agy"]["argv"], capture.SONNET_ARGV)
        self.assertEqual(len([event for event in client.events if event[0] == "prompt"]), 1)
        saved, usable = load_state_checked(self.state)
        self.assertTrue(usable)
        dispatch = saved["recovery"]["dispatches"][0]
        self.assertEqual((dispatch["status"], dispatch["provider"], dispatch["worker_kind"]), ("applied", "agy", "antigravity"))
        self.assertEqual((dispatch["launch_scope"], dispatch["result"]["launch_scope"]), (self.SCOPE, self.SCOPE))
        self.assertEqual([row["agent"] for row in saved["assignments"]], ["developer-agy"])
        recovery.validate_store(copy.deepcopy(saved["recovery"]), saved["assignments"])

    def test_a_refused_admission_keeps_the_scoped_attempt_and_the_identical_apply_recovers(self):
        refused = AntigravityOwnerNative(capture.FALLBACK_DISPLAY)
        code, output, error = self.apply(refused)
        self.assertEqual((code, output), (1, ""), error)
        failure = json.loads("\n".join(line for line in error.splitlines() if not line.startswith(DIAGNOSTIC_PREFIX)))
        self.assertEqual(failure["details"]["displayed"], "Gemini 3.8 Flash · high")
        evidence = failure["details"]["recovery"]["evidence"]
        self.assertEqual(failure["details"]["recovery"]["outcome"], "retryable")
        self.assertEqual((evidence["closed_agents"], evidence["retained_agents"], evidence["sending_agents"],
                          evidence["state_saved"]), (["developer-agy"], [], [], True))
        self.assertFalse(any(event[0] == "prompt" for event in refused.events))
        self.assertEqual(refused.panes, {})
        saved, usable = load_state_checked(self.state)
        self.assertTrue(usable)
        attempt = copy.deepcopy(saved["recovery"]["dispatches"][0])
        self.assertEqual(evidence["dispatches"], [attempt["id"]])
        self.assertEqual((attempt["status"], attempt["launch_scope"], attempt["agent"], attempt["provider"]),
                         ("not_sent", self.SCOPE, "developer-agy", "agy"))
        self.assertEqual(saved["assignments"], [])

        client = AntigravityOwnerNative(capture.SONNET_DISPLAY)
        code, output, error = self.apply(client)
        self.assertEqual(code, 0, error)
        self.assertEqual(len([event for event in client.events if event[0] == "prompt"]), 1)
        final, usable = load_state_checked(self.state)
        self.assertTrue(usable)
        previous, relaunch = final["recovery"]["dispatches"]
        self.assertEqual(previous, attempt)
        self.assertEqual((relaunch["status"], relaunch["launch_scope"], relaunch["task"], relaunch["role"]),
                         ("applied", self.SCOPE, self.TASK, "developer"))
        self.assertEqual([row["agent"] for row in final["assignments"]], ["developer-agy"])
        recovery.validate_store(copy.deepcopy(final["recovery"]), final["assignments"])


if __name__ == "__main__":
    unittest.main()
