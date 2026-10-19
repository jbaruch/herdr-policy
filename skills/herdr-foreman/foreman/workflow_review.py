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
