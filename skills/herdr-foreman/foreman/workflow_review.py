"""Bind a release worker's reading to all current review and inline bodies.

This digest is an identity, never proof that a person or worker read anything
and never a readiness predicate. The independently delivered release claim
attests the reading; the canonical watcher still supplies merge readiness.
"""

import hashlib
import json
import re

from .errors import UsageError


REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"})


def premerge_evidence(snapshot):
    """Validate a stored canonical watch receipt, never resolve live readiness.

    Only the watcher supplies `ready`. These checks reject incomplete receipts
    or fields contradicting that result; the file receipt binds every byte.
    """
    binding = identity(snapshot)
    error = UsageError("Restore the complete unchanged pre-merge watch-pr-reviews.sh output, including its actual CI, current reviewer, merge and watcher receipt fields; a self-labelled ready object is not release evidence.", {})
    ci, reviews = snapshot.get("ci"), snapshot.get("reviews")
    merge, watch = snapshot.get("merge_state"), snapshot.get("watch")
    counts = snapshot.get("inline_comments")
    if (not isinstance(ci, dict) or ci.get("status") not in ("success", "none")
            or not isinstance(ci.get("checks"), list)
            or not isinstance(reviews, dict) or not {"codex", "claude"}.issubset(reviews)
            or not isinstance(merge, dict) or not isinstance(merge.get("status"), str)
            or not merge["status"] or merge["status"] == "DIRTY" or merge.get("mergeable") != "MERGEABLE"
            or not isinstance(watch, dict) or watch.get("result") != "ready"
            or type(watch.get("attempts")) is not int or watch["attempts"] < 1
            or type(watch.get("elapsed_seconds")) is not int or watch["elapsed_seconds"] < 0
            or not isinstance(counts, dict)
            or any(type(counts.get(bot)) is not int or counts[bot] < 0 for bot in ("codex", "copilot"))):
        raise error
    for check in ci["checks"]:
        if (not isinstance(check, dict) or not isinstance(check.get("name"), str) or not check["name"]
                or not isinstance(check.get("bucket"), str) or not check["bucket"]):
            raise error
    fields = {"state", "submitted_at", "body", "commit_id", "stale", "requested"}
    for bot, states in (("codex", {"APPROVED", "COMMENTED", "RULED"}),
                        ("claude", {"APPROVED", "COMMENTED"})):
        row = reviews[bot]
        if (not isinstance(row, dict) or not fields.issubset(row)
                or not isinstance(row["state"], str) or row["state"] not in states
                or row["stale"] is not False or row["requested"] is not False
                or row["commit_id"] != binding["head_sha"]
                or not isinstance(row["submitted_at"], str) or not row["submitted_at"]
                or row["body"] is not None and not isinstance(row["body"], str)):
            raise error
    for field, required in (("review_bodies", {"submitted_at", "commit_id", "html_url"}),
                            ("inline_comment_bodies", {"in_reply_to_id", "path", "line", "html_url"})):
        if any(not required.issubset(row) for row in snapshot[field]):
            raise error
    return binding


def identity(snapshot):
    if (not isinstance(snapshot, dict) or type(snapshot.get("pr_number")) is not int
            or snapshot["pr_number"] < 1 or not isinstance(snapshot.get("head_sha"), str)
            or re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", snapshot["head_sha"]) is None
            or not isinstance(snapshot.get("review_bodies"), list)
            or not isinstance(snapshot.get("inline_comment_bodies"), list)):
        raise UsageError("Capture the canonical complete PR review snapshot before binding the release reading.", {})
    bodies = {}
    for field in ("review_bodies", "inline_comment_bodies"):
        rows, seen = [], set()
        for row in snapshot[field]:
            if (not isinstance(row, dict) or type(row.get("id")) is not int
                    or row["id"] < 1 or not isinstance(row.get("body"), str) or row["id"] in seen
                    or not isinstance(row.get("author"), str) or not row["author"].strip()
                    or len(row["author"].encode("utf-8")) > 256
                    or any(ord(char) < 32 for char in row["author"])
                    or field == "review_bodies" and (not isinstance(row.get("state"), str) or row["state"] not in REVIEW_STATES)):
                raise UsageError("Retain each complete review/inline body with its unique ID and author, plus canonical state for review rows; missing or unsupported evidence cannot bind a release reading.", {})
            seen.add(row["id"])
            rows.append(row)
        bodies[field] = sorted(rows, key=lambda row: row["id"])
    value = {"schema_version": 1, "pr_number": snapshot["pr_number"], "head_sha": snapshot["head_sha"], **bodies}
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > 2_097_152:
        raise UsageError("The current review exceeds the bounded workflow input; retain its source and request a task-local reading decision.", {})
    return {"schema_version": 1, "pr_number": value["pr_number"], "head_sha": value["head_sha"],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "reviews": len(bodies["review_bodies"]), "inline_comments": len(bodies["inline_comment_bodies"])}
