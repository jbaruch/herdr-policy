"""Deterministic Antigravity UUID/transcript and final-marker contracts."""

import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills/herdr-foreman"))

from foreman import agy_native, report_delivery
from foreman.errors import UsageError


SESSION = "11111111-1111-4111-8111-111111111111"
REPORT = "/private/reports/agy.md"


def rows(final="REPORT: " + REPORT):
    return [
        {"step_index": 1, "source": "SYSTEM", "type": "SYSTEM_MESSAGE",
         "status": "COMPLETED", "content": "bounded context"},
        {"step_index": 2, "source": "USER_EXPLICIT", "type": "USER_INPUT",
         "status": "COMPLETED", "content": "assigned prompt"},
        {"step_index": 3, "source": "MODEL", "type": "GENERIC",
         "status": "COMPLETED", "content": "working"},
        {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE",
         "status": "COMPLETED", "content": final},
    ]


class AgyTranscriptTest(unittest.TestCase):
    def test_latest_completed_user_binds_the_subsequent_planner_final(self):
        body = "\n".join(json.dumps(row) for row in rows()) + "\n"
        self.assertEqual(report_delivery.source_prompt(body, "agy", SESSION), "assigned prompt")
        final = report_delivery.source_final(body, "agy", SESSION)
        self.assertTrue(report_delivery.bare_final(final, REPORT))

    def test_reordered_duplicate_incomplete_and_later_user_rows_fail_closed(self):
        cases = []
        reordered = rows()
        reordered[2]["step_index"] = 1
        cases.append(reordered)
        duplicate = rows()
        duplicate[2]["step_index"] = 2
        cases.append(duplicate)
        for status in ("RUNNING", "FAILED"):
            incomplete = rows()
            incomplete[-1]["status"] = status
            cases.append(incomplete)
        later = rows()
        later.append({"step_index": 5, "source": "USER_EXPLICIT", "type": "USER_INPUT",
                      "status": "COMPLETED", "content": "later prompt"})
        cases.append(later)
        malformed = rows()
        malformed[-1]["content"] = {"text": "REPORT: " + REPORT}
        cases.append(malformed)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                body = "\n".join(json.dumps(row) for row in candidate) + "\n"
                self.assertIsNone(report_delivery.source_final(body, "agy", SESSION))

    def test_wrapped_quoted_fenced_and_nonfinal_markers_are_not_delivery(self):
        for final in ("> REPORT: " + REPORT, "```\nREPORT: " + REPORT,
                      "REPORT: " + REPORT + "\nmore", "REPORT: " + REPORT + ".old"):
            with self.subTest(final=final):
                body = "\n".join(json.dumps(row) for row in rows(final)) + "\n"
                self.assertFalse(report_delivery.bare_final(
                    report_delivery.source_final(body, "agy", SESSION), REPORT))


class AgyIdentityTest(unittest.TestCase):
    def setUp(self):
        self.holder = tempfile.TemporaryDirectory()
        self.addCleanup(self.holder.cleanup)
        self.root = Path(self.holder.name) / "brain"
        self.source = self.root / SESSION / ".system_generated" / "logs" / "transcript_full.jsonl"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("{}\n")

    def identity(self, value=SESSION):
        return {"source": "herdr:agy", "agent": "agy", "kind": "id", "value": value}

    def test_identity_requires_exact_herdr_agy_uuid(self):
        self.assertEqual(report_delivery.native_identity({"agent_session": self.identity()}), self.identity())
        for change in ({"value": "not-a-uuid"}, {"kind": "path"}, {"source": "agy"}, {"agent": "antigravity"}):
            with self.subTest(change=change):
                self.assertIsNone(report_delivery.native_identity(
                    {"agent_session": {**self.identity(), **change}}))

    def test_source_locator_accepts_only_the_exact_regular_unlinked_path(self):
        with patch.object(agy_native, "sessions_root", return_value=self.root):
            self.assertEqual(report_delivery.source_path(self.identity()), self.source)
            self.source.unlink()
            target = self.root / "target.jsonl"
            target.write_text("{}\n")
            self.source.symlink_to(target)
            self.assertIsNone(report_delivery.source_path(self.identity()))

    def test_source_reader_refuses_oversized_bytes(self):
        with patch.object(Path, "read_bytes", return_value=b"x" * (report_delivery.MAX_NATIVE_SOURCE_BYTES + 1)):
            with self.assertRaisesRegex(UsageError, "source bound"):
                report_delivery.read_native_source(self.source)

    def test_unobserved_display_decoration_does_not_fake_delivery(self):
        self.assertIsNone(report_delivery.decorated_row("REPORT: " + REPORT, "agy", REPORT))


if __name__ == "__main__":
    unittest.main()
