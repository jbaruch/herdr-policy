"""Antigravity's assignment transcript and exact session locator.

The native session id is a UUID and maps to one transcript under the Agy
brain directory. Transcript rows are ordered completed steps; no rendered TUI
text, fallback search, or latest-file heuristic participates in identity.
"""

from pathlib import Path
import re
import stat


SESSION_ID = re.compile(r"[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\Z")
USER_STEP = ("USER_EXPLICIT", "USER_INPUT")
MODEL_STEP = ("MODEL", "PLANNER_RESPONSE")
COMPLETED = "COMPLETED"


def sessions_root():
    """The documented account-local Antigravity brain root."""
    return Path.home() / ".gemini" / "antigravity-cli" / "brain"


def transcript_path(session):
    return sessions_root() / session / ".system_generated" / "logs" / "transcript_full.jsonl"


def locate(session):
    """Return the one exact regular, unlinked transcript, otherwise None."""
    if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
        return None
    root = sessions_root()
    candidate = transcript_path(session)
    current = root
    try:
        if root.is_symlink() or not root.is_dir():
            return None
        for part in candidate.relative_to(root).parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                return None
        return candidate if stat.S_ISREG(candidate.stat().st_mode) else None
    except (FileNotFoundError, NotADirectoryError):
        return None


def _exchange(rows):
    """Return the latest completed prompt and its subsequent completed final."""
    previous = -1
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        index = row.get("step_index")
        source, kind, status, content = (row.get("source"), row.get("type"),
                                         row.get("status"), row.get("content"))
        if (type(index) is not int or index < 0 or index <= previous
                or not all(isinstance(value, str) for value in (source, kind, status, content))
                or status != COMPLETED):
            return None
        previous = index
        normalized.append((index, source, kind, content))
    users = [row for row in normalized if row[1:3] == USER_STEP]
    if not users or not users[-1][3]:
        return None
    prompt = users[-1]
    finals = [row for row in normalized if row[0] > prompt[0] and row[1:3] == MODEL_STEP]
    if not finals or not finals[-1][3]:
        return None
    return prompt[3], finals[-1][3]


def prompt_text(rows, _session=None):
    exchange = _exchange(rows)
    return exchange[0] if exchange is not None else None


def final_message(rows, _session=None):
    exchange = _exchange(rows)
    return exchange[1] if exchange is not None else None
