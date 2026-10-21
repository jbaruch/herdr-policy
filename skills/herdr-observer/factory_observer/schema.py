"""Store's migration-1 record formats. Pure validation; no migration or I/O."""

import math
from pathlib import Path
import re


def text(value):
    return isinstance(value, str) and bool(value)


def number(value):
    return type(value) in (int, float) and 0 <= value <= 10**20 and math.isfinite(value)


def count(value):
    return type(value) is int and value >= 0


def path(value):
    return text(value) and "\0" not in value and Path(value).is_absolute()


def nullable(check):
    return lambda value: value is None or check(value)


def items(check):
    return lambda value: isinstance(value, list) and all(check(item) for item in value)


def mapping(check):
    return lambda value: isinstance(value, dict) and all(check(item) for item in value.values())


def fields(value, required, optional=None):
    return (isinstance(value, dict) and all(key in value and check(value[key]) for key, check in required.items())
            and all(key not in value or check(value[key]) for key, check in (optional or {}).items()))


def digest(value, width=24):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(width) + "}", value) is not None


def identity(value):
    return (fields(value, {key: text for key in ("pane_id", "source", "agent", "kind", "value")})
            and value["source"] == "herdr:" + value["agent"] and value["kind"] in ("id", "path")
            and (value["kind"] != "path" or path(value["value"])))


def agent(value):
    return fields(value, {"key": text, "session_key": text, "name": text, "pane_id": text,
                          "provider": text, "role": text,
                          "status": lambda item: item in ("idle", "working", "blocked", "unknown")},
                  {"task": nullable(lambda item: isinstance(item, str)), "log_coverage": items(text),
                   "model": nullable(lambda item: isinstance(item, str)), "effort": nullable(lambda item: isinstance(item, str))})


def valid(table, key, value, home, version):
    """Required fields are strict; additional compatible projection fields survive."""
    strings = items(text)
    numbers = mapping(number)
    label = nullable(lambda item: isinstance(item, str))
    objects = items(lambda item: isinstance(item, dict))
    receipt = lambda item: fields(item, {"at": number, "status": lambda state: state in ("sending", "sent", "unknown")})
    if table == "reports":
        return (fields(value, {"id": digest, "kind": lambda item: item in ("weekly", "urgent"), "path": path,
                               "at": number, "sha256": lambda item: digest(item, 64),
                               "notification": lambda item: item in ("sent", "unknown")})
                and value["id"] == key and Path(value["path"]) == home / "reports" / (key + ".md"))
    if table == "bins":
        profile = lambda item: fields(item, {"model": label, "effort": label, "metrics": numbers})
        locator = lambda item: (fields(item, {"path": path, "start": count, "end": count})
                                and item["start"] <= item["end"])
        return fields(value, {"at": number, "key": text, "name": text, "provider": text, "role": text,
                              "metrics": numbers, "profiles": mapping(profile), "locators": items(locator)},
                      {"session_key": text, "task": label})
    if table == "sources":
        if not fields(value, {"key": text}) or value["key"] != key:
            return False
        if value.get("kind") == "quota":
            return fields(value, {"profile": text, "provider": label, "window_group": label, "history": objects})
        gap = lambda item: fields(item, {"at": number, "gaps": strings})
        return ("kind" not in value and fields(value, {"provider": text, "coverage": strings, "gap_history": items(gap)},
                    {"path": path, "retry_at": number, "discovery_gap": text, "offset": count, "backlog_bytes": count,
                     "file_id": lambda item: isinstance(item, list) and len(item) == 2 and all(count(part) for part in item),
                     "skip_line": lambda item: type(item) is bool, "watermark": number, "replay_through": number,
                     "usage": nullable(numbers), "messages": mapping(numbers), "call_ids": items(digest),
                     "recent_tools": items(digest), "model": label, "effort": label}))
    if table != "meta":
        return False
    if key == "binding":
        return fields(value, {"identity": identity, "name": text, "cwd": path, "at": number})
    if key == "config":
        options = {"started_at": number, "states": items(path), "owner_root": path, "binary": text}
        return (fields(value, {"enabled": lambda item: type(item) is bool}, options)
                and (not value["enabled"] or fields(value, options)))
    if key == "current":
        return fields(value, {"at": number, "healthy": lambda item: type(item) is bool,
                              "agents": items(agent), "coverage": strings},
                      {"stall_since": nullable(number), "rotation": count, "quota_omitted": count,
                       "log_bytes_read": count, "reporter_present": lambda item: type(item) is bool,
                       "quota": objects, "factories": objects, "duplicates": objects, "unverified_agents": objects})
    if key == "heartbeat":
        return (fields(value, {"at": number}, {"collection_seconds": number, "error": text})
                and ("collection_seconds" in value or "error" in value))
    if key == "schedule":
        return fields(value, {"last_analysis": number, "last_anomaly": digest}, {"last_weekly": number})
    if key == "pending":
        if set(value) == {"schema_version"}:
            return True
        payload = lambda item: fields(item, {"schema_version": lambda stamp: type(stamp) is int and stamp == version,
                                             "as_of": number, "current": lambda item: isinstance(item, dict),
                                             "total_metrics": numbers})
        return fields(value, {"id": digest, "created_at": number, "reasons": lambda item: strings(item) and bool(item),
                              "data": payload, "send_status": lambda item: item in ("new", "sending", "sent", "unknown"),
                              "anomaly": digest},
                      {"last_wake_at": number, "recovery": receipt, "attention": receipt})
    if key == "acknowledgements":
        return fields(value, {"jobs": items(lambda item: fields(item, {"id": digest, "at": number}))})
    if key == "closures":
        return fields(value, {"by_owner": mapping(count)}, {"evicted_through": number})
    if key == "retention":
        return fields(value, {"bins_evicted": count, "sources_evicted": count, "telemetry_floor": number, "at": number})
    return False
