"""Bounded read-only evidence adapters. Raw prompts/output never enter the cache.

Native JSONL adapters: Codex rollout records and Claude project transcripts.
Other runtimes remain visible in Herdr samples but their log costs are unknown.
Sources are selected by live native identities, never by recursively reading .hr.
Owner readers accept state 11/recovery 19, snapshot 5/6, supervision 1 and binding
receipts 1 (their in-tree owners define migrations). They never migrate them.
"""

from datetime import datetime
from itertools import islice
import json
import os
from pathlib import Path
import stat
import time

from .native import fingerprint, identity


MAX_JSON_BYTES = 8 * 1024 * 1024
LOG_CHUNK = 256 * 1024
LOG_BUDGET = 4 * 1024 * 1024
MAX_LOG_LINE = 1024 * 1024
MAX_DISCOVERY_FILES = 4096
MAX_FACTORIES = 32
MAX_AGENTS = 128
MAX_OWNER_ROWS = 10000
SUPPORTED_LOGS = frozenset({"codex", "claude"})


def instant(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def read_json(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
            raise ValueError("evidence must be a bounded regular JSON file")
        return json.load(stream)


def owner_paths(root, explicit):
    paths, gaps = {str(Path(p).absolute()) for p in explicit}, []
    receipts = root / "supervision-bindings"
    if receipts.is_dir():
        entries = sorted(islice(receipts.iterdir(), MAX_DISCOVERY_FILES))
        if len(entries) > MAX_FACTORIES:
            gaps.append("factory_discovery_truncated")
        for entry in entries[:MAX_FACTORIES]:
            try:
                receipt = read_json(entry)
                if (receipt.get("schema_version") != 1 or not isinstance(receipt.get("state_path"), str)
                        or not Path(receipt["state_path"]).is_absolute()):
                    continue
                supervision = read_json(Path(receipt["state_path"] + ".supervision.json"))
                binding = supervision.get("binding") or {}
                if (supervision.get("schema_version") == 1 and binding.get("identity") == receipt.get("identity")
                        and binding.get("generation") == receipt.get("generation")):
                    paths.add(receipt["state_path"])
            except (OSError, ValueError, TypeError, AttributeError):
                gaps.append("factory_receipt_unreadable")
    if (root / "state.json").exists():
        paths.add(str(root / "state.json"))
    if len(paths) > MAX_FACTORIES:
        gaps.append("factory_sources_truncated")
    return sorted(paths)[:MAX_FACTORIES], gaps


def owners(paths, live):
    """Current metadata, not planning authority. Stale factories cannot assign roles."""
    roles, quota, closures, contexts, gaps = {}, [], [], [], []
    live_ids = {fingerprint(identity(row)): row for row in live if identity(row)}
    for path in paths:
        try:
            data = read_json(path)
            supervised = read_json(path + ".supervision.json")
            if (data.get("schema_version") != 11 or supervised.get("schema_version") != 1
                    or data.get("recovery", {}).get("schema_version") != 19):
                gaps.append("owner_schema_unsupported")
                continue
            bound = (supervised.get("binding") or {}).get("identity") or {}
            pane = bound.get("pane_id")
            foremen = [row for row in live if row.get("pane_id") == pane and (current := identity(row)) is not None
                       and current["kind"] == bound.get("kind")
                       and current["value"] == bound.get("value")
                       and row.get("cwd") == bound.get("cwd")]
            if not foremen:
                continue
            key = fingerprint(identity(foremen[0]))
            roles[key] = {"role": "foreman", "task": None, "owner": path}
            held = sum(1 for row in supervised.get("holds", []) if row.get("resumed_at") is None)
            assignments = data.get("assignments", [])
            if len(assignments) > MAX_OWNER_ROWS:
                gaps.append("assignment_history_truncated")
            profiles = {row.get("agent"): row for row in assignments[-MAX_OWNER_ROWS:]}
            for member in supervised.get("members", [])[-MAX_OWNER_ROWS:]:
                if not member.get("active"):
                    continue
                assignment = member.get("assignment", {})
                refined = member.get("refinements", [])
                session = refined[-1] if refined else assignment
                native = session.get("native_session")
                candidate = identity({"pane_id": session.get("pane_id"), "agent_session": native})
                if candidate is None or fingerprint(candidate) not in live_ids:
                    continue
                profile = profiles.get(assignment.get("agent"), {})
                roles[fingerprint(candidate)] = {"role": profile.get("role", "worker"),
                                                 "task": assignment.get("task"), "owner": path,
                                                 "assigned_at": instant(profile.get("at") or member.get("at"))}
            snapshots = data.get("snapshots", [])
            latest = snapshots[-1] if snapshots else {}
            if latest.get("schema_version") in (5, 6):
                for name, row in latest.get("agents", {}).items():
                    windows = {str(key)[:128]: {"used_pct": percent(value.get("used_pct")),
                                               "remaining_pct": percent(value.get("remaining_pct")), "resets": label(value.get("resets"))}
                               for key, value in list(row.get("windows", {}).items())[:16] if isinstance(value, dict)}
                    quota.append({"profile": name, "provider": row.get("kind"), "owner": path,
                                  "measured_at": latest.get("measured_at"),
                                  "window_group": label(row.get("window_group")), "windows": windows,
                                  "headroom_pct": percent(row.get("headroom_pct")), "skipped": bool(row.get("skipped"))})
            else:
                gaps.append("quota_snapshot_missing_or_unsupported")
            recovery = data["recovery"]
            events = recovery.get("events", [])
            if len(events) > MAX_OWNER_ROWS:
                gaps.append("closure_history_truncated")
            for event in events[-MAX_OWNER_ROWS:]:
                if event.get("kind") == "task_closed":
                    closures.append({"owner": path, "task": event.get("task"), "at": event.get("at"),
                                     "sequence": event.get("sequence"),
                                     "outcome": (event.get("details") or {}).get("outcome"),
                                     "id": fingerprint([path, event.get("sequence"), event.get("at")])})
            contexts.append({"owner": path, "holds": held,
                             "active_assignments": sum(1 for m in supervised.get("members", []) if m.get("active")),
                             "eligible_backlog": None,
                             "closure_semantics": "merged, abandoned and unknown task_closed outcomes are separate; user value and deployment unverified"})
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            gaps.append("owner_evidence_unavailable")
    return roles, quota, closures, contexts, sorted(set(gaps))


class DiscoveryLimit(ValueError):
    """Filename discovery was bounded before the session could be established."""


def locate(native, user_home):
    """Find only the live session's file; bounded filename search, no unrelated bodies."""
    provider = native["agent"]
    if provider not in SUPPORTED_LOGS:
        return None
    root = user_home / (".codex/sessions" if provider == "codex" else ".claude/projects")
    if native["kind"] == "path":
        path = Path(native["value"])
        return path if path.resolve().is_relative_to(root.resolve()) else None
    value = native["value"]
    if not value or len(value) > 128 or any(c not in "0123456789abcdefABCDEF-" for c in value):
        return None
    if not root.is_dir():
        return None
    if provider == "claude":
        # Claude's filename is the native ID. Probe that exact filename once
        # per project; unrelated transcript counts consume no discovery budget.
        for index, project in enumerate(islice(root.iterdir(), MAX_DISCOVERY_FILES + 1)):
            if index >= MAX_DISCOVERY_FILES:
                raise DiscoveryLimit("native log discovery budget exhausted")
            if not project.is_symlink() and project.is_dir():
                candidate = project / (value + ".jsonl")
                if not candidate.is_symlink() and candidate.is_file():
                    return candidate
        return None
    count = 0
    # Codex uses year/month/day directories.
    directories = [root]
    for _ in range(3):
        next_level = []
        for parent in directories:
            for entry in sorted(islice(parent.iterdir(), MAX_DISCOVERY_FILES - count + 1), reverse=True):
                count += 1
                if count > MAX_DISCOVERY_FILES:
                    raise DiscoveryLimit("native log discovery budget exhausted")
                if entry.is_dir() and not entry.is_symlink():
                    next_level.append(entry)
        directories = next_level
    for directory in directories:
        for path in sorted(islice(directory.iterdir(), MAX_DISCOVERY_FILES - count + 1), reverse=True):
            count += 1
            if count > MAX_DISCOVERY_FILES:
                raise DiscoveryLimit("native log discovery budget exhausted")
            if path.name.endswith(value + ".jsonl") and not path.is_symlink():
                return path
    return None


def size(value):
    return len((value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).encode("utf-8"))


def number(value) -> float | int:
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) and 0 <= value <= 10**18 else 0


def label(value):
    return value if isinstance(value, str) and len(value) <= 128 and all(ord(c) >= 32 for c in value) else None


def percent(value):
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) and 0 <= value <= 100 else None


def event_metrics(event, cursor):
    """Project numeric facts. Interpretation of task/model suitability stays in the agent."""
    kind, payload = event.get("type"), event.get("payload", {})
    metrics = {}
    provider = cursor["provider"]
    if provider == "codex":
        if kind == "turn_context":
            cursor["model"], cursor["effort"] = label(payload.get("model")), label(payload.get("effort"))
            metrics["turns"] = 1
        elif kind == "compacted" or kind == "event_msg" and payload.get("type") == "context_compacted":
            metrics["compactions"] = 1
        elif kind == "event_msg" and payload.get("type") == "token_count":
            usage = (payload.get("info") or {}).get("total_token_usage")
            if isinstance(usage, dict):
                previous = cursor.get("usage")
                if previous is not None:
                    for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
                        current = number(usage.get(key))
                        before = number(previous.get(key))
                        if current >= before:
                            metrics[key] = current - before
                        else:
                            metrics["token_counter_resets"] = 1
                cursor["usage"] = {key: number(usage.get(key)) for key in ("input_tokens", "output_tokens", "cached_input_tokens")}
        elif kind == "response_item":
            if payload.get("type") in ("function_call", "custom_tool_call"):
                metrics.update(tool_metrics(payload, cursor))
            elif payload.get("type") in ("function_call_output", "custom_tool_call_output"):
                metrics["tool_output_bytes"] = size(payload.get("output", ""))
            elif payload.get("type") == "message" and payload.get("role") == "assistant":
                metrics["assistant_bytes"] = size(payload.get("content", []))
    elif provider == "claude":
        message = event.get("message") or {}
        if kind == "assistant":
            cursor["model"] = label(message.get("model") or event.get("requestedModel"))
            cursor["effort"] = label(event.get("effort") or event.get("perTurnEffort"))
            content = message.get("content", [])
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    for key, count in tool_metrics(block, cursor).items():
                        metrics[key] = metrics.get(key, 0) + count
                elif isinstance(block, dict) and block.get("type") == "text":
                    metrics["assistant_bytes"] = metrics.get("assistant_bytes", 0) + size(block.get("text", ""))
            messages = cursor.setdefault("messages", {})
            key = fingerprint(message["id"]) if message.get("id") else None
            usage = message.get("usage")
            if key and isinstance(usage, dict):
                previous = messages.get(key, {})
                for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                    metrics[field] = max(0, number(usage.get(field)) - number(previous.get(field)))
                messages[key] = {field: max(number(usage.get(field)), number(previous.get(field)))
                                 for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
                while len(messages) > 64:
                    del messages[next(iter(messages))]
        elif kind == "user":
            content = message.get("content", [])
            metrics["tool_output_bytes"] = sum(size(block.get("content", "")) for block in content
                                               if isinstance(block, dict) and block.get("type") == "tool_result") if isinstance(content, list) else 0
        elif kind == "system" and event.get("subtype") == "compact_boundary":
            metrics["compactions"] = 1
    return metrics


def tool_metrics(call, cursor):
    raw_id = call.get("call_id") or call.get("id")
    call_id = fingerprint(raw_id) if raw_id else None
    recent_ids = cursor.setdefault("call_ids", [])
    if call_id and call_id in recent_ids:
        return {}
    if call_id:
        recent_ids.append(call_id)
        del recent_ids[:-64]
    digest = fingerprint([call.get("name"), call.get("arguments", call.get("input"))])
    recent = cursor.setdefault("recent_tools", [])
    metrics = {"tool_calls": 1, "repeated_tool_fingerprints": int(digest in recent)}
    recent.append(digest)
    del recent[:-32]
    return metrics


def read_log(path, cursor, *, now, since, budget=LOG_CHUNK):
    """Resume at a byte cursor; partial/oversize lines and replacement files stay explicit."""
    batches, gaps = [], []
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("native log must be a regular file")
        file_id = [info.st_dev, info.st_ino]
        if cursor.get("file_id") != file_id or info.st_size < cursor.get("offset", 0):
            if "file_id" in cursor:
                gaps.append("native_log_rotated_or_truncated")
                cursor["replay_through"] = cursor.get("watermark", 0)
            cursor.update(file_id=file_id, offset=0, usage=None, messages={}, call_ids=[], recent_tools=[])
            # Establish a bounded tail baseline. Older activity is not invented.
            if info.st_size > MAX_LOG_LINE:
                cursor["offset"] = info.st_size - MAX_LOG_LINE
                cursor["skip_line"] = True
                gaps.append("native_log_prefix_not_collected")
        stream.seek(cursor["offset"])
        consumed = 0
        while consumed < budget:
            position = stream.tell()
            raw = stream.readline(MAX_LOG_LINE + 1)
            if not raw:
                break
            consumed += len(raw)
            if cursor.get("skip_line"):
                cursor["offset"] = stream.tell()
                if raw.endswith(b"\n"):
                    cursor["skip_line"] = False
                continue
            if len(raw) > MAX_LOG_LINE:
                cursor["skip_line"] = not raw.endswith(b"\n")
                cursor["offset"] = stream.tell()
                gaps.append("oversized_native_log_line")
                continue
            if not raw.endswith(b"\n"):
                stream.seek(position)
                break
            cursor["offset"] = stream.tell()
            try:
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise ValueError("invalid record")
                at = instant(event.get("timestamp"))
                # A replacement may copy old history. Never charge that history twice.
                if at is not None and at <= cursor.get("replay_through", 0):
                    continue
                metrics = event_metrics(event, cursor)
                if at is not None:
                    cursor["watermark"] = max(at, cursor.get("watermark", at))
                ceiling = time.time() if now is None else now
                if at is not None and since <= at <= ceiling:
                    batches.append({"at": at, "metrics": metrics, "model": cursor.get("model"),
                                    "effort": cursor.get("effort"), "start": position, "end": stream.tell()})
            except (ValueError, TypeError, AttributeError):
                gaps.append("malformed_native_log_record")
        cursor["backlog_bytes"] = max(0, info.st_size - cursor["offset"])
    return batches, sorted(set(gaps)), consumed
