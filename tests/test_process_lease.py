"""Real OS locks fence competing processes; stale lease files grant nothing."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1] / "skills/herdr-foreman"
sys.path.insert(0, str(SKILL))
from foreman.errors import StateError, UsageError
from foreman.process_lease import process_lease


CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
from foreman.errors import StateError
from foreman.process_lease import process_lease
try:
    with process_lease(sys.argv[2]) as lease:
        lease.require_current()
except StateError:
    sys.exit(7)
"""


class ProcessLeaseTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.path = Path(holder.name) / "progression.lock"

    def contender(self):
        return subprocess.run([sys.executable, "-c", CHILD, str(SKILL), str(self.path)],
                              capture_output=True, text=True, timeout=10, check=False)

    def test_live_holder_excludes_another_real_process_then_releases(self):
        with process_lease(self.path) as lease:
            lease.require_current()
            self.assertEqual(self.contender().returncode, 7)
        self.assertEqual(self.contender().returncode, 0)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_exception_releases_lock_and_invalidates_capability(self):
        lease = None
        with self.assertRaisesRegex(ValueError, "fixture"):
            with process_lease(self.path) as lease:
                raise ValueError("fixture")
        assert lease is not None
        with self.assertRaises(StateError):
            lease.require_current()
        self.assertEqual(self.contender().returncode, 0)

    def test_replaced_path_invalidates_old_holder(self):
        with process_lease(self.path) as lease:
            self.path.unlink()
            self.path.write_bytes(b"")
            with self.assertRaisesRegex(StateError, "path changed"):
                lease.require_current()

    def test_missing_path_never_gets_recreated_by_a_capability_check(self):
        with process_lease(self.path) as lease:
            self.path.unlink()
            with self.assertRaises(StateError):
                lease.require_current()
            self.assertFalse(self.path.exists())

    def test_symlink_and_nonregular_paths_are_refused_without_mutation(self):
        target = self.path.parent / "owner.json"
        target.write_text('{"preserve":true}')
        self.path.symlink_to(target)
        with self.assertRaises(StateError):
            with process_lease(self.path):
                self.fail("symlink admitted")
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(), '{"preserve":true}')
        with self.assertRaises(StateError):
            with process_lease(self.path.parent):
                self.fail("directory admitted")

    def test_relative_or_missing_parent_does_not_select_a_default_owner(self):
        with self.assertRaises(UsageError):
            with process_lease("progression.lock"):
                self.fail("relative path admitted")
        missing = self.path.parent / "absent" / "lease"
        with self.assertRaises(StateError):
            with process_lease(missing):
                self.fail("missing parent created")
        self.assertFalse(missing.parent.exists())

    def test_existing_records_cannot_be_mistaken_for_empty_lease_files(self):
        self.path.write_text('{"owner":"preserve"}')
        with self.assertRaises(StateError):
            with process_lease(self.path):
                self.fail("owner record admitted as a lease")
        self.assertEqual(self.path.read_text(), '{"owner":"preserve"}')

    def test_forked_process_cannot_use_its_parents_capability(self):
        with process_lease(self.path) as lease:
            child = os.fork()
            if child == 0:
                try:
                    lease.require_current()
                except StateError:
                    os._exit(0)
                os._exit(9)
            _pid, status = os.waitpid(child, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            lease.require_current()


if __name__ == "__main__":
    unittest.main()
