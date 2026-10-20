"""Shared startup selects one small role contract in each agent's envelope."""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1] / "skills/herdr-foreman"))

import io
import json
import unittest
from unittest.mock import Mock, patch

from foreman import session_start_hook as hook
from foreman.errors import StateError


class SessionStartTest(unittest.TestCase):
    def setUp(self):
        self.skill = _TestPath("/private/fixture skill")
        self.environment = {"HERDR_ENV": "private-fixture", "HERDR_PANE_ID": "fixture-pane"}
        self.input = {"session_id": "fixture-session", "cwd": str(_TestPath.cwd())}
        self.reader = Mock(return_value={"role": "foreman", "reason": "bound_native_foreman",
                                        "context": "Private foreman contract."})

    def collect(self, adapter, **environment):
        return hook.collect(self.skill, {**self.environment, "HERDR_HOOK_ADAPTER": adapter, **environment},
                            self.input, context_reader=self.reader)

    def test_ordinary_session_needs_no_owner_or_controller(self):
        self.assertIsNone(hook.collect(self.skill, {}, context_reader=self.reader))
        self.reader.assert_not_called()

    def test_native_claude_codex_and_grok_share_the_role_owner(self):
        for adapter in ("claude-code", "codex", "grok"):
            with self.subTest(adapter=adapter):
                result = self.collect(adapter)
                assert result is not None
                self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "SessionStart")
                self.assertIn("Private foreman contract.", result["hookSpecificOutput"]["additionalContext"])
                self.assertEqual(self.reader.call_args.kwargs["payload"], self.input)

    def test_cursor_uses_its_native_context_field(self):
        result = self.collect("cursor")
        assert result is not None
        self.assertEqual(set(result), {"additional_context"})
        self.assertIn("Private foreman contract.", result["additional_context"])

    def test_portable_uses_tessl_context_and_defers_to_registered_native_hooks(self):
        for agent in ("codex", "claude-code"):
            self.assertIsNone(self.collect("portable", TESSL_AGENT=agent))
        self.reader.assert_not_called()
        result = self.collect("portable", TESSL_AGENT="other")
        assert result is not None
        self.assertIn("Private foreman contract.", result["additionalContext"])

    def test_native_adapter_does_not_defer_merely_because_tessl_is_present(self):
        self.assertIsNotNone(self.collect("codex", TESSL_AGENT="codex"))
        self.reader.assert_called_once()

    def test_unverified_or_standalone_role_loads_no_contract(self):
        for role in ("unverified", "standalone"):
            self.reader.return_value = {"role": role, "reason": "unverified", "context": ""}
            self.assertIsNone(self.collect("codex"))

    def test_worker_and_recovery_return_only_the_selected_capsule(self):
        for role in ("worker", "recovery"):
            self.reader.return_value = {"role": role, "reason": "private-fixture", "context": "Only " + role}
            payload = self.collect("codex")
            assert payload is not None
            result = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Only " + role, result)
            self.assertNotIn("Private foreman contract.", result)

    def test_failed_owner_is_visible_without_partly_loaded_context(self):
        self.reader.side_effect = StateError("private diagnostic must not leak", {})
        with patch("sys.stderr", new_callable=io.StringIO) as err:
            result = self.collect("cursor")
        assert result is not None
        self.assertEqual(result, {"additional_context": hook.FAILURE})
        self.assertIn("StateError", err.getvalue())
        self.assertNotIn("private diagnostic", err.getvalue())

    def test_oversized_context_is_refused_and_output_remains_bounded(self):
        self.reader.return_value["context"] = "x" * 4097
        with patch("sys.stderr", new_callable=io.StringIO):
            result = self.collect("portable")
        self.assertEqual(result, {"additionalContext": hook.FAILURE})
        self.assertLessEqual(len(json.dumps(result).encode()), 16_384)

    def test_invalid_oversized_and_nonobject_inputs_refuse(self):
        for raw in (b"[]", b"not json", b"x" * (hook.INPUT_BYTES + 1), b'"\\xff"'):
            with self.subTest(size=len(raw)), self.assertRaises((ValueError, UnicodeDecodeError)):
                hook._input(io.BytesIO(raw))
        self.assertEqual(hook._input(io.BytesIO(json.dumps(self.input).encode())), self.input)

    def test_ordinary_main_does_not_even_read_stdin(self):
        with patch.dict("os.environ", {}, clear=True), patch("sys.stdin") as stream:
            self.assertEqual(hook.main(), 0)
        stream.read.assert_not_called()
        stream.buffer.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
