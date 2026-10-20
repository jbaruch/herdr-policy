"""Execute role hooks from source and actual Tessl archives, without live teams."""

import importlib.util
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("role_installation_check", ROOT / "scripts/check-installations.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class RolePackagesTest(unittest.TestCase):
    def setUp(self):
        self.holder = tempfile.TemporaryDirectory(prefix="herdr-role-package-")
        self.addCleanup(self.holder.cleanup)
        self.root = Path(self.holder.name).resolve() / "private consumer with spaces"
        self.root.mkdir()
        self.environment = {**CHECK.runtime_environment(), "PYTHONDONTWRITEBYTECODE": "1"}
        self.environment.pop("HERDR_ENV", None)
        self.environment.pop("HERDR_PANE_ID", None)

    def test_source_hook_uses_real_role_owners(self):
        skill = ROOT / "skills/herdr-foreman"
        CHECK.verify_role_context(self.root, skill, skill / "native-hook.sh", self.environment, "codex")

    def unpack(self):
        archive = self.root / "plugin.tgz"
        CHECK.command("tessl", "plugin", "pack", str(ROOT), "--output", str(archive),
                      env=self.environment, cwd=self.root, check_behavior=True)
        package = self.root / "extracted-package"
        package.mkdir()
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                target = (package / member.name).resolve()
                self.assertTrue(target.is_relative_to(package))
                self.assertTrue(member.isfile() or member.isdir(), member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                data = stream.extractfile(member)
                self.assertIsNotNone(data)
                assert data is not None
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.read())
                target.chmod(0o644)
        return package

    def test_tessl_archive_ships_and_executes_shared_hooks_for_every_envelope(self):
        package = self.unpack()
        skill = package / "skills/herdr-foreman"
        CHECK.verify_runtime_payload(skill)
        manifest = json.loads((package / ".tessl-plugin/plugin.json").read_text())
        self.assertEqual(manifest["rules"], ["rules/herdr-scope.md"])
        self.assertLessEqual((package / manifest["rules"][0]).stat().st_size, 2048)
        for kind in ("herdr-foreman", "herdr-standup"):
            self.assertTrue((package / "skills" / kind / "references").is_dir())
        for adapter in ("claude-code", "codex"):
            command = manifest["nativeHooks"][adapter]["SessionStart"][0]["hooks"][0]["command"]
            self.assertEqual(command, 'bash "${TESSL_PLUGIN_DIR}/skills/herdr-foreman/native-hook.sh" session-start '+adapter)
        self.assertEqual(manifest["hooks"]["SessionStart"][0]["hooks"][0]["args"],
                         ["${TESSL_PLUGIN_DIR}/skills/herdr-foreman/native-hook.sh", "session-start", "portable"])
        for adapter in ("codex", "claude-code", "cursor", "grok", "portable"):
            with self.subTest(adapter=adapter):
                consumer = self.root / adapter
                consumer.mkdir()
                CHECK.verify_role_context(consumer, skill, skill / "native-hook.sh", self.environment, adapter)
                CHECK.command("/bin/bash", str(skill / "native-hook.sh"), "session-start", adapter,
                              env={**self.environment, "PATH": str(consumer)}, cwd=consumer,
                              input_text="not even JSON", check_behavior=True, quiet=True)
        self.assertFalse(any(path.name == "__pycache__" for path in package.rglob("*")))
        self.assertFalse((package / "tests").exists())


if __name__ == "__main__":
    unittest.main()
