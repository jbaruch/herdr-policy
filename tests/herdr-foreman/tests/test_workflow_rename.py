"""Actual filesystem outcomes for the platform's exclusive rename primitive."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from foreman import workflow_rename
from foreman.errors import StateError, UsageError


class ExclusiveRenameTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_file_move_retains_original_inode_and_bytes(self):
        source, target = self.root / "source", self.root / "target"
        source.write_bytes(b"Owned bytes.\n")
        inode = source.stat().st_ino
        workflow_rename.exclusive(source, target)
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(), b"Owned bytes.\n")
        self.assertEqual(target.stat().st_ino, inode)

    def test_directory_move_accepts_relative_names_and_directory_descriptors(self):
        source = self.root / "source"
        source.mkdir()
        (source / "owned").write_bytes(b"Owned bytes.\n")
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            workflow_rename.exclusive("source", "target", src_dir_fd=descriptor, dst_dir_fd=descriptor)
        finally:
            os.close(descriptor)
        self.assertFalse(source.exists())
        self.assertEqual((self.root / "target/owned").read_bytes(), b"Owned bytes.\n")

    def test_existing_file_is_preserved_with_its_source(self):
        source, target = self.root / "source", self.root / "target"
        source.write_bytes(b"Source.\n")
        target.write_bytes(b"Foreign.\n")
        inodes = source.stat().st_ino, target.stat().st_ino
        with self.assertRaises(UsageError):
            workflow_rename.exclusive(source, target)
        self.assertEqual((source.read_bytes(), target.read_bytes()), (b"Source.\n", b"Foreign.\n"))
        self.assertEqual((source.stat().st_ino, target.stat().st_ino), inodes)

    def test_existing_empty_directory_is_preserved_with_its_source(self):
        source, target = self.root / "source", self.root / "target"
        source.mkdir()
        target.mkdir()
        inodes = source.stat().st_ino, target.stat().st_ino
        with self.assertRaises(UsageError):
            workflow_rename.exclusive(source, target)
        self.assertEqual((source.stat().st_ino, target.stat().st_ino), inodes)

    def test_unsupported_platform_preserves_both_paths(self):
        source, target = self.root / "source", self.root / "target"
        source.write_bytes(b"Keep.\n")
        with patch.object(workflow_rename.sys, "platform", "unsupported"):
            with self.assertRaises(StateError):
                workflow_rename.exclusive(source, target)
        self.assertEqual(source.read_bytes(), b"Keep.\n")
        self.assertFalse(target.exists())

    def test_embedded_nul_does_not_move_a_truncated_path(self):
        source, target = self.root / "source", self.root / "target"
        source.write_bytes(b"Keep.\n")
        with self.assertRaises(UsageError):
            workflow_rename.exclusive(str(source) + "\0ignored", target)
        self.assertEqual(source.read_bytes(), b"Keep.\n")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
