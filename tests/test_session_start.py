"""Startup combines owner status and exposes failures without claiming work happened."""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1] / "skills/herdr-foreman"))

import json
import shlex
import tempfile
import unittest
from pathlib import Path

from foreman.session_start_hook import OWNERS, collect


class SessionStartTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.skill = Path(holder.name) / "skill with spaces"
        (self.skill / "hooks").mkdir(parents=True)

    def owner(self, name, text, status=0):
        path = self.skill / "hooks" / name
        path.write_text("#!/bin/bash\nprintf '%s' " + shlex.quote(json.dumps({"additionalContext": text}))
                        + "\nexit " + str(status) + "\n")

    def test_all_owner_statuses_are_delivered_in_native_order(self):
        self.owner(OWNERS[0], "Session-start status — roster")
        self.owner(OWNERS[1], "Session-start status — cache result")
        payload = collect(self.skill, {})
        self.assertEqual(payload, {"hookSpecificOutput": {"hookEventName": "SessionStart",
                         "additionalContext": "Session-start status — roster\n\nSession-start status — cache result"}})

    def test_portable_defers_only_to_registered_native_agents(self):
        for agent in ("codex", "claude-code"):
            self.assertIsNone(collect(self.skill, {"TESSL_AGENT": agent}))
        self.owner(OWNERS[0], "status")
        self.owner(OWNERS[1], "more")
        self.assertEqual(collect(self.skill, {"TESSL_AGENT": "other"}), {"additionalContext": "status\n\nmore"})

    def test_missing_and_failed_owners_are_visible(self):
        self.owner(OWNERS[1], "success claim", 7)
        result = collect(self.skill, {})
        assert result is not None
        payload = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn(OWNERS[0], payload)
        self.assertIn("exited 7", payload)
        self.assertNotIn("success claim", payload)

    def test_empty_outputs_are_silent_and_invalid_payload_is_visible(self):
        for name in OWNERS:
            (self.skill / "hooks" / name).write_text("#!/bin/bash\nexit 0\n")
        self.assertIsNone(collect(self.skill, {}))
        (self.skill / "hooks" / OWNERS[0]).write_text("#!/bin/bash\nprintf '[]'\n")
        result = collect(self.skill, {})
        assert result is not None
        self.assertIn("additionalContext", result["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
