"""Small Herdr adapter. Live reads require native context; writes target only self.

No shell, terminal capture, worker prompts, usage probes, or delivery mutations.
CLI diagnostics and transcript text are deliberately not copied into failures.
"""

import hashlib
import json
import os
import subprocess


TIMEOUT = 20
MAX_RESPONSE = 8 * 1024 * 1024


def identity(row):
    native = row.get("agent_session")
    if (not isinstance(native, dict) or not row.get("pane_id")
            or not isinstance(native.get("agent"), str)
            or native.get("source") != "herdr:" + native["agent"]
            or native.get("kind") not in ("id", "path")
            or not isinstance(native.get("value"), str) or not native["value"]):
        return None
    return {"pane_id": row["pane_id"], **{k: native[k] for k in ("source", "agent", "kind", "value")}}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]


class Native:
    def __init__(self, binary="herdr"):
        if os.environ.get("HERDR_ENV") != "1" or not os.environ.get("HERDR_PANE_ID"):
            raise ValueError("run live observation inside a named native Herdr observer agent")
        self.binary = binary

    def call(self, *arguments):
        try:
            result = subprocess.run([self.binary, *arguments], capture_output=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("Herdr request unavailable; inspect native connectivity before retrying") from None
        if result.returncode or len(result.stdout) > MAX_RESPONSE:
            raise ValueError("Herdr request failed or exceeded its response bound; inspect native connectivity")
        try:
            body = json.loads(result.stdout)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Herdr returned invalid JSON; update or repair the native adapter") from None
        if not isinstance(body, dict) or body.get("ok") is False or body.get("error"):
            raise ValueError("Herdr refused the request; inspect native connectivity")
        value = body.get("result", body)
        if not isinstance(value, dict):
            raise ValueError("Herdr result schema unsupported; update the native adapter")
        return value

    def snapshot(self):
        data = self.call("api", "snapshot")
        snapshot = data.get("snapshot")
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("agents"), list)
                or not all(isinstance(row, dict) for row in snapshot["agents"])):
            raise ValueError("Herdr snapshot schema unsupported; update the observer adapter")
        return snapshot

    def prompt(self, name):
        return self.call("agent", "prompt", name,
                         'Observer evidence is ready. Invoke Skill(skill: "herdr-observer") for the pending analysis. '
                         'Keep findings private; do not coordinate factory work.')

    def notify(self):
        self.call("notification", "show", "Herdr observer report ready",
                  "--body", "A private local report is available. Ask the observer to show it.", "--sound", "none")


def current(snapshot):
    pane = os.environ.get("HERDR_PANE_ID")
    matches = [row for row in snapshot["agents"] if row.get("pane_id") == pane and row.get("name")]
    if len(matches) != 1 or identity(matches[0]) is None:
        raise ValueError("current pane must have one named native agent with a verified session")
    return matches[0]


def matches(binding, row):
    return (identity(row) == binding.get("identity") and row.get("name") == binding.get("name")
            and row.get("cwd") == binding.get("cwd"))
