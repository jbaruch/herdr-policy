"""GitHub reads retain source identity, bounded text and unexamined pages."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import json
import subprocess
import unittest

from foreman import context_output, github_context as github
from foreman.errors import UsageError


URL = "https://github.com/fixture/project/pull/7"
AT = "2026-09-23T08:00:00Z"


def body(text: str | None = "Current source", url=URL, identifier=100, **extra):
    return {"id": identifier, "url": url, "body": text, "body_available": True, "author": "fixture",
            "updated_at": AT, "state": "COMMENTED", **extra}


def response(data, *, links=None, status=200):
    header = "HTTP/2.0 {} OK\r\nContent-Type: application/json\r\n".format(status)
    if links is not None:
        header += "Link: " + links + "\r\n"
    return subprocess.CompletedProcess([], 0, (header + "\r\n" + json.dumps(data)).encode())


class GitHubContextTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def reader(self, data, *, links=None):
        def run(argv, **options):
            self.calls.append(argv)
            self.assertEqual(argv[0:2], ["gh", "api"])
            self.assertEqual(argv[argv.index("--method") + 1], "GET")
            self.assertEqual(argv[argv.index("--hostname") + 1], "github.com")
            self.assertNotIn("--paginate", argv)
            self.assertNotIn("--cache", argv)
            self.assertNotIn("shell", options)
            return response(data, links=links)
        return run

    def read(self, data, **options):
        return github.read(options.pop("url", URL), options.pop("question", "Which evidence is current?"),
                           runner=self.reader(data, links=options.pop("links", None)), **options)

    def test_supported_references_use_read_only_canonical_endpoints(self):
        examples = [("https://github.com/fixture/project/issues/7", 100, "issues/7"),
                    (URL, 100, "pulls/7"),
                    (URL + "#issuecomment-501", 501, "issues/comments/501"),
                    (URL + "#pullrequestreview-502", 502, "pulls/7/reviews/502"),
                    (URL + "#discussion_r503", 503, "pulls/comments/503")]
        for url, identifier, endpoint in examples:
            with self.subTest(url=url):
                result = self.read(body(url=url, identifier=identifier), url=url)
                self.assertTrue(self.calls[-1][-1].endswith(endpoint))
                self.assertEqual(result["source"]["url"], url)
                self.assertTrue(result["body"]["complete"])
                for key in ("authorizes_dispatch", "authorizes_progression", "authorizes_release"):
                    self.assertFalse(result[key])

    def test_question_is_data_and_is_not_sent_to_the_command(self):
        question = "Inspect literal $(do-not-execute); `text` and \"quotes\""
        result = self.read(body(), question=question)
        self.assertEqual(result["question"], question)
        self.assertNotIn(question, self.calls[-1])
        self.assertNotIn("body", result["source"])
        self.assertTrue(result["untrusted_source"])

    def test_large_escaped_utf8_body_round_trips_through_hash_bound_chunks(self):
        text = "A😀\u0001\\\"\n" * 4000
        record = body(text)
        offset, snapshot, chunks = 0, None, []
        for _ in range(100):
            result = self.read(record, offset=offset, snapshot=snapshot)
            self.assertLessEqual(len(context_output.printed_json(result).encode()), context_output.OUTPUT_BYTES)
            chunk = result["body"]
            self.assertEqual(chunk["offset"], offset)
            self.assertEqual(chunk["bytes"], len(chunk["content"].encode()))
            self.assertGreater(chunk["bytes"], 0)
            chunks.append(chunk["content"])
            snapshot = result["source"]["sha256"]
            if chunk["next_offset"] is None:
                self.assertTrue(chunk["complete"])
                break
            self.assertGreater(chunk["next_offset"], offset)
            offset = chunk["next_offset"]
        else:
            self.fail("A finite source did not finish within its bounded chunks")
        self.assertEqual("".join(chunks), text)

    def test_continuations_require_snapshot_and_utf8_boundaries(self):
        record = body("😀" * 3000)
        initial = self.read(record)
        for options in ({"offset": 1}, {"offset": initial["body"]["next_offset"]},
                        {"offset": 1, "snapshot": initial["source"]["sha256"]}):
            with self.subTest(options=options), self.assertRaises(UsageError):
                self.read(record, **options)

    def test_changed_text_or_review_binding_invalidates_a_continuation(self):
        record = body("x" * 20000, head_revision="a" * 40)
        first = self.read(record)
        for changed in ({**record, "body": "new" + record["body"]},
                        {**record, "state": "DISMISSED"},
                        {**record, "head_revision": "b" * 40}):
            with self.subTest(changed_fields=[k for k in changed if changed[k] != record[k]]):
                with self.assertRaises(UsageError) as caught:
                    self.read(changed, offset=first["body"]["next_offset"], snapshot=first["source"]["sha256"])
                self.assertEqual(caught.exception.details["reason"], "github_context_changed")
                self.assertFalse(caught.exception.details["context_complete"])

    def test_index_returns_only_references_and_explicit_live_page_coverage(self):
        rows = [{"id": n, "url": URL + "#issuecomment-" + str(n), "author": "fixture", "updated_at": AT}
                for n in (501, 502)]
        links = ('<https://api.github.com/repositories/99/issues/7/comments?per_page=2&page=2>; rel="next", '
                 '<https://api.github.com/repositories/99/issues/7/comments?per_page=2&page=3>; rel="last"')
        result = self.read(rows, section="comments", limit=2, links=links)
        self.assertEqual(result["items"], rows)
        self.assertEqual((result["page"]["returned"], result["page"]["next_page"], result["page"]["last_page"]), (2, 2, 3))
        self.assertFalse(result["page"]["bodies_included"])
        self.assertFalse(result["page"]["earlier_pages_revalidated"])
        self.assertEqual(result["page"]["snapshot_consistency"], "this_page_only")
        self.assertNotIn("body", self.calls[-1][self.calls[-1].index("--jq") + 1])

    def test_each_review_index_preserves_its_record_kind(self):
        for section, anchor, suffix in (("reviews", "pullrequestreview-", "/reviews"),
                                        ("review-comments", "discussion_r", "/comments")):
            with self.subTest(section=section):
                rows = [{"id": 501, "url": URL + "#" + anchor + "501", "state": "COMMENTED"}]
                result = self.read(rows, section=section)
                self.assertEqual(result["items"], rows)
                self.assertIn("/pulls/7" + suffix + "?", self.calls[-1][-1])

    def test_wrong_parent_anchor_or_extra_data_is_not_a_valid_source(self):
        invalid = [body(url=URL.replace("/7", "/8")), body(url=URL.replace("fixture/", "another/")),
                   body(url=URL + "#issuecomment-501", identifier=999), body(extra_private="Do not echo")]
        for record in invalid:
            with self.subTest(record=record), self.assertRaises(UsageError):
                self.read(record)
        wrong = [{"id": 501, "url": URL + "#pullrequestreview-501"}]
        with self.assertRaises(UsageError):
            self.read(wrong, section="comments")

    def test_bad_pagination_never_becomes_an_empty_complete_page(self):
        for links in ("malformed", '<https://untrusted.invalid/items?page=2&per_page=10>; rel="next"',
                      '<https://api.github.com/items?page=3&per_page=10>; rel="next"',
                      '<https://api.github.com/items?page=2&per_page=50>; rel="next"'):
            with self.subTest(links=links), self.assertRaises(UsageError):
                self.read([], section="comments", links=links)

    def test_unavailable_upstream_never_echoes_private_diagnostics(self):
        secret = "Private fixture text that must stay outside diagnostics"
        for reply in (subprocess.CompletedProcess([], 1, secret.encode(), secret.encode()),
                      response({"body": secret}, status=404),
                      subprocess.CompletedProcess([], 0, b"x" * (github.UPSTREAM_BYTES + 1))):
            with self.subTest(status=reply.returncode):
                with self.assertRaises(UsageError) as caught:
                    github.read(URL, "What changed?", runner=lambda *args, **options: reply)
                self.assertNotIn(secret, str(caught.exception))
                self.assertLess(len(json.dumps(caught.exception.to_dict()).encode()), context_output.OUTPUT_BYTES)
        for failure in (FileNotFoundError("private executable"), subprocess.TimeoutExpired("private request", 1)):
            def fail(*args, **options):
                raise failure
            with self.subTest(failure=type(failure).__name__), self.assertRaises(UsageError):
                github.read(URL, "What changed?", runner=fail)

    def test_invalid_inputs_are_refused_without_running_gh(self):
        for value in ("http://github.com/fixture/project/pull/7", "https://other.invalid/fixture/project/pull/7",
                      URL + "?token=private", URL + "#unknown", "https://[broken", "\n" + URL,
                      URL + "#issuecomment501", URL + "#discussion_r-501", "https://github.com/a/../pull/7"):
            with self.subTest(value=value), self.assertRaises(UsageError):
                self.read(body(), url=value)
        self.assertEqual(self.calls, [])
        for options in ({"question": ""}, {"question": "x" * (github.QUESTION_BYTES + 1)},
                        {"section": "unknown"}, {"page": 0}, {"limit": 11}, {"offset": -1}):
            with self.subTest(options=options), self.assertRaises(UsageError):
                self.read(body(), **options)
        self.assertEqual(self.calls, [])

    def test_empty_body_is_complete_without_a_zero_progress_cursor(self):
        result = self.read(body(""))
        self.assertEqual(result["body"]["content"], "")
        self.assertTrue(result["body"]["complete"])
        self.assertIsNone(result["body"]["next_offset"])

    def test_unavailable_body_cannot_become_an_empty_source(self):
        with self.assertRaises(UsageError):
            self.read(body("", body_available=False))
        with self.assertRaises(UsageError):
            self.read(body(None, url=URL + "#issuecomment-501", identifier=501), url=URL + "#issuecomment-501")
        self.assertTrue(self.read(body(None))["body"]["complete"])


if __name__ == "__main__":
    unittest.main()
