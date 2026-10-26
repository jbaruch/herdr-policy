"""Native effective settings and first-turn mode preserve authorized full access."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import json
import tempfile
import unittest

from foreman import native_permissions
from foreman.errors import UsageError


class NativePermissionsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="permissions-fixture-")
        self.addCleanup(directory.cleanup)
        self.cwd = str(Path(directory.name).resolve())
        self.session = {"kind": "id", "value": "owned-materialized-session"}
        self.value = {"thread": {"id": self.session["value"]}, "cwd": self.cwd,
                      "approvalPolicy": "never", "sandbox": {"type": "dangerFullAccess"}}
        self.calls = []
        self.status = "idle"

    def connect(self, _path):
        owner = self
        class Host:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def call(self, method, parameters):
                owner.calls.append((method, deepcopy(parameters)))
                if method == "thread/read":
                    return {"thread": {"id": owner.session["value"], "status": {"type": owner.status}}}
                return deepcopy(owner.value)
        return Host()

    def verify(self):
        return native_permissions.source(self.session, self.cwd, connect=self.connect, discover=lambda: "/owned.sock")

    def test_effective_settings_are_read_without_config_or_turn_overrides(self):
        before = deepcopy(self.value)
        proof = self.verify()
        self.assertEqual(proof["approval_policy"], "never")
        self.assertEqual(proof["write_roots"], "unrestricted")
        self.assertEqual(proof["cwd"], self.cwd)
        self.assertEqual(self.value, before)
        self.assertEqual(self.calls, [("thread/read", {"threadId": self.session["value"]}),
                                     ("thread/resume", {"threadId": self.session["value"], "excludeTurns": True})])

    def test_profile_read_never_resurrects_an_unloaded_old_session(self):
        self.status = "notLoaded"
        with self.assertRaisesRegex(UsageError, "source_not_loaded"):
            self.verify()
        self.assertEqual(self.calls, [("thread/read", {"threadId": self.session["value"]})])

    def test_interactive_or_restricted_profiles_refuse_without_broadening(self):
        for approval, sandbox in (("on-request", {"type": "dangerFullAccess"}),
                                  ("never", {"type": "workspaceWrite", "writableRoots": [self.cwd]}),
                                  ("never", {"type": "readOnly"}), (None, {"type": "dangerFullAccess"}),
                                  ("never", {"type": "dangerFullAccess", "unknownRestriction": True})):
            with self.subTest(approval=approval, sandbox=sandbox):
                self.value.update(approvalPolicy=approval, sandbox=sandbox)
                before = deepcopy(self.value)
                with self.assertRaisesRegex(UsageError, "interactive_or_restricted"):
                    self.verify()
                self.assertEqual(self.value, before)

    def test_foreign_thread_or_workspace_never_supplies_profile_proof(self):
        self.value["thread"]["id"] = "foreign-session"
        with self.assertRaisesRegex(UsageError, "workspace_changed"):
            self.verify()
        self.value["thread"]["id"] = self.session["value"]
        self.value["cwd"] = str(Path(self.cwd).parent)
        with self.assertRaisesRegex(UsageError, "workspace_changed"):
            self.verify()
        self.value["cwd"] = None
        with self.assertRaises(UsageError):
            self.verify()

    def test_missing_or_relative_expected_workspace_refuses_before_rpc(self):
        for cwd in (None, "relative", ""):
            with self.subTest(cwd=cwd), self.assertRaises(UsageError):
                native_permissions.source(self.session, cwd, connect=self.connect, discover=lambda: "/owned.sock")
        self.assertEqual(self.calls, [])

    def test_captured_clear_and_first_prompt_carry_the_actual_native_permission_mode(self):
        path = Path(__file__).resolve().parents[1] / "fixtures/codex-0.164-permissions.json"
        captured = json.loads(path.read_text())
        self.assertEqual(captured["capture"]["cli_version"], "0.164.0")
        self.assertEqual(captured["SessionStart"]["source"], "clear")
        for event in ("SessionStart", "UserPromptSubmit"):
            self.assertTrue(native_permissions.incoming(captured[event]))
        for mode in (None, "default", "dontAsk", "acceptEdits", "plan", "bypasspermissions", True):
            self.assertFalse(native_permissions.incoming({"permission_mode": mode}))


if __name__ == "__main__":
    unittest.main()
