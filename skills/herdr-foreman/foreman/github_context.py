"""Targeted GitHub context through projected GETs; never a history mirror.

One explicit issue/PR/comment/review body or one metadata index page is read
per request. Body continuations bind the complete projected source by hash.
Index pages are live observations, not a consistent whole-thread snapshot.
CLI owns the shared exposure debit before any result reaches model stdout.

API contracts: https://cli.github.com/manual/gh_api and
https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api
No --paginate, HTTP mutation, shell interpolation, upstream diagnostic echo,
cache flag or durable response body is used.
"""

import hashlib
import json
import re
import subprocess
from urllib.parse import parse_qs, urlsplit

from . import context_output
from .errors import UsageError

UPSTREAM_BYTES = 1_048_576
BODY_BYTES = 8_192
MAX_PAGE_ITEMS = 10
QUESTION_BYTES = 512
REQUEST_SECONDS = 30
SECTIONS = ("body", "comments", "reviews", "review-comments")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PATH = re.compile(r"/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})/(issues|pull)/([1-9][0-9]{0,18})\Z")
ANCHOR = re.compile(r"(issuecomment-|pullrequestreview-|discussion_r)([1-9][0-9]{0,18})\Z")
BODY_PROJECTION = ('{id,url:.html_url,title,body,body_available:has("body"),author:.user.login,'
                   'created_at,updated_at,submitted_at,state,'
                   'head_revision:(.commit_id // .head.sha // null),original_commit_id,path,line,original_line}')
INDEX_PROJECTION = ('[.[] | {id,url:.html_url,author:.user.login,created_at,updated_at,'
                    'submitted_at,state,head_revision:(.commit_id // null)}]')
BODY_FIELDS = frozenset({"id", "url", "title", "body", "body_available", "author", "created_at", "updated_at",
                         "submitted_at", "state", "head_revision", "original_commit_id", "path", "line", "original_line"})
INDEX_FIELDS = frozenset({"id", "url", "author", "created_at", "updated_at", "submitted_at", "state", "head_revision"})


def _unavailable():
    return UsageError("GitHub context is unavailable or its response is unsupported. Restore gh authentication and access to the selected repository, verify its current canonical reference, then retry this one read. Unexamined evidence remains unresolved.",
                      {"reason": "github_context_unavailable", "context_complete": False})


def reference(value):
    try:
        valid = isinstance(value, str) and len(value.encode("utf-8")) <= 1_024 and all(0x20 < ord(c) < 0x7F for c in value)
        parsed = urlsplit(value) if valid else None
    except (ValueError, UnicodeError):
        parsed = None
    if parsed is None:
        raise UsageError("Provide one canonical https://github.com issue, pull request, comment or review reference of at most 1024 bytes.", {})
    match = PATH.fullmatch(parsed.path)
    anchor = ANCHOR.fullmatch(parsed.fragment) if parsed.fragment else None
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or parsed.query
            or match is None or match[2] in (".", "..") or parsed.fragment and anchor is None):
        raise UsageError("Use a canonical https://github.com/<owner>/<repo>/issues/<n> or pull/<n> reference, optionally naming an issuecomment, pullrequestreview or discussion_r anchor; remove query strings.", {})
    owner, repository, kind, number = match.groups()
    anchor_kind = anchor[1].rstrip("-") if anchor else None
    if anchor_kind is not None and anchor_kind != "issuecomment" and kind != "pull":
        raise UsageError("Pull-request review references require their canonical pull/<n> URL.", {})
    return {"owner": owner, "repo": repository, "kind": kind, "number": int(number),
            "anchor": anchor_kind, "id": int(anchor[2]) if anchor else None,
            "url": "https://github.com" + parsed.path + ("#" + parsed.fragment if parsed.fragment else "")}


def _endpoint(selected, section):
    root = "repos/{}/{}".format(selected["owner"], selected["repo"])
    number = selected["number"]
    if selected["anchor"] is not None:
        if section != "body":
            raise UsageError("Read the named comment/review body, or use its parent issue/PR URL for an index page.", {})
        paths = {"issuecomment": "issues/comments/{}".format(selected["id"]),
                 "pullrequestreview": "pulls/{}/reviews/{}".format(number, selected["id"]),
                 "discussion_r": "pulls/comments/{}".format(selected["id"])}
        return root + "/" + paths[selected["anchor"]]
    if section == "body":
        return root + ("/issues/{}" if selected["kind"] == "issues" else "/pulls/{}").format(number)
    if section == "comments":
        return root + "/issues/{}/comments".format(number)
    if selected["kind"] != "pull":
        raise UsageError("Review indexes require a canonical pull/<n> reference.", {})
    return root + "/pulls/{}/{}".format(number, "reviews" if section == "reviews" else "comments")


def _request(endpoint, projection, runner):
    try:
        result = runner(["gh", "api", "--hostname", "github.com", "--method", "GET", "--include",
                         "--jq", projection, endpoint], stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, check=False, timeout=REQUEST_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        raise _unavailable() from None
    # Raw upstream diagnostics can contain private response text or credentials.
    # Replace a failed request with the actionable contract above, never stderr.
    if result.returncode or not isinstance(result.stdout, bytes) or len(result.stdout) > UPSTREAM_BYTES:
        raise _unavailable()
    try:
        text = result.stdout.decode("utf-8").replace("\r\n", "\n")
        header, body = text.split("\n\n", 1)
        lines = header.splitlines()
        if not re.fullmatch(r"HTTP/[0-9.]+ 200(?: .*)?", lines[0]):
            raise ValueError("unexpected status")
        headers = {}
        for line in lines[1:]:
            key, separator, value = line.partition(":")
            if not separator:
                raise ValueError("invalid header")
            key = key.lower()
            headers[key] = headers.get(key, "") + value.strip() + ","
        data = json.loads(body)
    except (UnicodeError, ValueError, IndexError, RecursionError):
        raise _unavailable() from None
    return data, headers


def _metadata(record, selected, *, body=False, expected_anchor=None):
    fields = BODY_FIELDS if body else INDEX_FIELDS
    if (not isinstance(record, dict) or set(record) - fields
            or type(record.get("id")) is not int or record["id"] < 1):
        raise _unavailable()
    try:
        actual = reference(record.get("url"))
    except UsageError:
        raise _unavailable() from None
    if (actual["owner"].lower() != selected["owner"].lower()
            or actual["repo"].lower() != selected["repo"].lower()
            or actual["number"] != selected["number"]
            or body and (actual["anchor"] != selected["anchor"] or actual["id"] != selected["id"])
            or not body and actual["anchor"] != expected_anchor
            or actual["anchor"] is not None and actual["id"] != record["id"]):
        raise _unavailable()
    # The client projection is fixed, but validate its scalar fields before
    # rendering; malformed upstream data is never a valid empty source.
    metadata = {key: value for key, value in record.items() if key not in ("body", "body_available")}
    for key, value in metadata.items():
        if value is not None and type(value) not in (str, int):
            raise _unavailable()
        if isinstance(value, str):
            try:
                if len(value.encode("utf-8")) > (1_024 if key in ("url", "path", "title") else 256):
                    raise _unavailable()
            except UnicodeError:
                raise _unavailable() from None
    return metadata


def _pages(headers, page, limit):
    links = headers.get("link", "").rstrip(",")
    result: dict[str, int | None] = {"next_page": None, "last_page": None}
    if not links:
        return result
    for part in links.split(","):
        match = re.fullmatch(r'\s*<([^>]+)>;\s*rel="([a-z]+)"\s*', part)
        if match is None:
            raise _unavailable()
        url = urlsplit(match[1])
        query = parse_qs(url.query)
        try:
            target, size = int(query["page"][0]), int(query["per_page"][0])
        except (KeyError, ValueError, IndexError):
            raise _unavailable() from None
        if url.scheme != "https" or url.netloc != "api.github.com" or target < 1 or size != limit:
            raise _unavailable()
        if match[2] == "next":
            if target != page + 1:
                raise _unavailable()
            result["next_page"] = target
        elif match[2] == "last":
            if target < page:
                raise UsageError("This GitHub index page is beyond the current collection. Restart from page 1 and retain earlier observations as unverified; thread history may have changed.",
                                 {"reason": "github_context_changed", "context_complete": False})
            result["last_page"] = target
    return result


def _chunk(record, selected, question, offset, snapshot):
    metadata = _metadata(record, selected, body=True)
    content = record.get("body")
    if record.get("body_available") is not True:
        raise _unavailable()
    if content is None and selected["anchor"] is None:
        content = ""
    if not isinstance(content, str):
        raise _unavailable()
    try:
        raw = content.encode("utf-8")
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    except UnicodeError:
        raise _unavailable() from None
    if snapshot is not None and (not isinstance(snapshot, str) or not SHA256.fullmatch(snapshot)):
        raise UsageError("Copy the source's exact sha256 receipt for a body continuation.", {})
    if snapshot is not None and snapshot != digest:
        raise UsageError("GitHub source changed after the earlier observation. Restart this source at offset 0 and preserve previous evidence as stale; no mixed-version excerpt is accepted.",
                         {"reason": "github_context_changed", "context_complete": False})
    if type(offset) is not int or not 0 <= offset <= len(raw) or offset < len(raw) and raw[offset] & 0xC0 == 0x80:
        raise UsageError("Use the previous next_offset byte boundary for this GitHub body, or restart at offset 0.", {})
    if offset and snapshot is None:
        raise UsageError("A GitHub body continuation requires its previous --snapshot sha256; restart at offset 0 if it is unavailable.", {})
    end = min(len(raw), offset + BODY_BYTES)
    while True:
        while end > offset and end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1
        if end == offset and offset < len(raw):
            raise UsageError("GitHub source metadata leaves no room for a body character. Narrow the evidence question or source; no zero-progress continuation is accepted.",
                             {"reason": "context_budget_exceeded", "context_complete": False})
        view = {"kind": "github_evidence", "question": question, "source": {**metadata, "sha256": digest},
                "untrusted_source": True, "authorizes_dispatch": False, "authorizes_release": False,
                "body": {"offset": offset, "bytes": end - offset, "total_bytes": len(raw),
                         "next_offset": end if end < len(raw) else None,
                         "complete": end == len(raw), "content": raw[offset:end].decode("utf-8")}}
        try:
            return context_output.bounded(view)
        except UsageError:
            if end == offset:
                raise
            end = offset + (end - offset) // 2


def read(value, question, *, section="body", page=1, limit=MAX_PAGE_ITEMS,
         offset=0, snapshot=None, runner=None):
    selected = reference(value)
    try:
        valid_question = isinstance(question, str) and bool(question.strip()) and len(question.encode("utf-8")) <= QUESTION_BYTES
    except UnicodeError:
        valid_question = False
    if not valid_question:
        raise UsageError("Name the specific GitHub evidence question in at most 512 UTF-8 bytes; do not request a whole history dump.", {})
    if section not in SECTIONS or type(page) is not int or page < 1 or type(limit) is not int or not 1 <= limit <= MAX_PAGE_ITEMS:
        raise UsageError("Select body, comments, reviews or review-comments with a positive page and limit 1–10.", {})
    if type(offset) is not int or not 0 <= offset <= UPSTREAM_BYTES:
        raise UsageError("Use the previous next_offset for a GitHub body continuation, or restart at offset 0.", {})
    if snapshot is not None and (not isinstance(snapshot, str) or not SHA256.fullmatch(snapshot)):
        raise UsageError("Copy the source's exact sha256 receipt for a body continuation.", {})
    if offset and snapshot is None:
        raise UsageError("A GitHub body continuation requires its previous --snapshot sha256; restart at offset 0 if it is unavailable.", {})
    if section == "body" and page != 1 or section != "body" and (offset or snapshot is not None):
        raise UsageError("Use page/limit for index pages, or offset/snapshot for one body; do not combine the two continuation contracts.", {})
    endpoint = _endpoint(selected, section)
    if section != "body":
        endpoint += "?per_page={}&page={}".format(limit, page)
    records, headers = _request(endpoint, BODY_PROJECTION if section == "body" else INDEX_PROJECTION,
                                subprocess.run if runner is None else runner)
    if section == "body":
        return _chunk(records, selected, question, offset, snapshot)
    if not isinstance(records, list) or len(records) > limit:
        raise _unavailable()
    anchor = {"comments": "issuecomment", "reviews": "pullrequestreview", "review-comments": "discussion_r"}[section]
    items = [_metadata(row, selected, expected_anchor=anchor) for row in records]
    return context_output.bounded({"kind": "github_index", "reference": selected["url"],
        "question": question, "section": section, "untrusted_source": True,
        "authorizes_dispatch": False, "authorizes_release": False,
        "page": {"number": page, "limit": limit, "returned": len(items), **_pages(headers, page, limit),
                 "bodies_included": False, "earlier_pages_revalidated": False,
                 "snapshot_consistency": "this_page_only"}, "items": items})


def register_parser(sub, common):
    parser = sub.add_parser("github-context", parents=[common], help="Read one bounded GitHub evidence source or index page without mirroring history.")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--section", choices=SECTIONS, default="body")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=MAX_PAGE_ITEMS)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--snapshot")
