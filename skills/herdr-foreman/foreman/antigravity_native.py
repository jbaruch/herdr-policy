"""Native agy transcript reader, verified against CLI 1.4.7 and Google hooks.

https://antigravity.google/docs/hooks?tab=cli names the conversation-bound
transcript path. Rows carry no conversation ID; only that canonical path can
bind them to a session. Archived arbitrary JSONL cannot prove delivery.
No SQLite/protobuf decoding, transcript copying or credential access.
"""

from pathlib import Path
import json
import math
import os
import re
import subprocess

from .errors import HerdrError, ParseError


SESSION = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z")
SOURCE = "herdr:antigravity_cli"
USAGE_TIMEOUT = 20
USAGE_BYTES = 65_536


def parse_usage(text):
    """Read the native slash-command JSON; remaining fractions are not usage."""
    try:
        data = json.loads(text)
        if data.get("status") != "SUCCESS" or data.get("command", {}).get("name") != "usage":
            raise ValueError("usage command failed")
        groups = data["command"]["data"]["groups"]
        if not isinstance(groups, list) or not groups:
            raise ValueError("subscription quota absent")
        windows = {}
        for group in groups:
            name = group["name"]
            if not isinstance(name, str) or not name:
                raise ValueError("quota group absent")
            buckets = group["buckets"]
            if not isinstance(buckets, list) or not buckets:
                raise ValueError("quota buckets absent")
            for bucket in buckets:
                fraction, reset = bucket["remaining_fraction"], bucket["reset_time"]
                key = name + "/" + bucket["id"]
                if (key in windows or isinstance(fraction, bool) or not isinstance(fraction, (int, float))
                        or not math.isfinite(fraction) or not 0 <= fraction <= 1
                        or not isinstance(reset, str) or not reset):
                    raise ValueError("quota reading invalid")
                remaining = round(100 * fraction, 6)
                windows[key] = {"remaining_pct": remaining, "used_pct": round(100 - remaining, 6), "resets": reset}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ParseError("Cannot read Antigravity subscription quota. Run `agy -p /usage --output-format json` under the worker's Google sign-in; restore nonempty quota groups before staffing it.", {"kind": "agy"}) from None
    return {"windows": windows, "credits": None, "plan": None}


def subscription_usage(*, run=subprocess.run):
    """Read account quota without a model turn or API-key fallback."""
    environment = {key: value for key, value in os.environ.items() if key not in {
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_APPLICATION_CREDENTIALS", "AGY_ADC_AUTH"}}
    try:
        result = run(["agy", "-p", "/usage", "--output-format", "json", "--print-timeout", "15s"],
                     capture_output=True, text=True, timeout=USAGE_TIMEOUT, check=False, env=environment)
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired):
        raise HerdrError("Antigravity quota lookup failed. Install native `agy`, sign in to the Google subscription on this controller host, then retry only this provider.", {"kind": "agy"}) from None
    if result.returncode or len(result.stdout.encode("utf-8")) > USAGE_BYTES:
        raise HerdrError("Antigravity quota lookup did not return a bounded successful result. Run `agy -p /usage --output-format json` with the worker's subscription sign-in before retrying this provider.", {"kind": "agy"})
    return parse_usage(result.stdout)


def sessions_root():
    return (Path.home() / ".gemini/antigravity-cli/brain").resolve()


def transcript_path(session):
    if not isinstance(session, str) or SESSION.fullmatch(session) is None:
        return None
    return sessions_root() / session / ".system_generated/logs/transcript.jsonl"


def main_turn(rows, session, path):
    """Return the latest explicit user turn only under its actual native path."""
    expected = transcript_path(session)
    if expected is None or path is None or Path(path) != expected or expected.resolve() != expected:
        return None
    indexed = {}
    for row in rows:
        index = row.get("step_index")
        if type(index) is not int or index < 0 or index in indexed:
            return None
        indexed[index] = row
    ordered = [indexed[index] for index in sorted(indexed)]
    start = None
    for offset, row in enumerate(ordered):
        if row.get("type") == "USER_INPUT" and row.get("source") == "USER_EXPLICIT":
            if row.get("status") != "DONE" or not isinstance(row.get("content"), str):
                return None
            start = offset
    return ordered[start:] if start is not None else None


def final_message(rows, session, path):
    turn = main_turn(rows, session, path)
    if not turn or len(turn) < 2:
        return None
    final = turn[-1]
    if (final.get("type") != "PLANNER_RESPONSE" or final.get("source") != "MODEL"
            or final.get("status") != "DONE" or not isinstance(final.get("content"), str)):
        return None
    return final["content"]


def prompt_text(rows, session, path):
    turn = main_turn(rows, session, path)
    return turn[0]["content"] if turn else None
