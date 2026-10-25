"""Small Herdr adapter. Live reads require native context; writes target only self.

No shell, terminal capture, worker prompts, usage probes, or delivery mutations.
CLI diagnostics and transcript text are deliberately not copied into failures.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess

from foreman import report_delivery


TIMEOUT = 20
MAX_RESPONSE = 8 * 1024 * 1024


def identity(row):
    if not isinstance(row, dict) or not isinstance(row.get("pane_id"), str) or not row["pane_id"]:
        return None
    native = row.get("agent_session")
    if (not isinstance(native, dict)
            or native.get("pane_id", row["pane_id"]) != row["pane_id"]
            or not isinstance(native.get("agent"), str)
            or native.get("source") != report_delivery.NATIVE_SOURCES.get(native["agent"], "herdr:" + native["agent"])
            or native.get("kind") not in ("id", "path")
            or not isinstance(native.get("value"), str) or not native["value"]):
        return None
    return {"pane_id": row["pane_id"], **{k: native[k] for k in ("source", "agent", "kind", "value")}}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]


def session_key(who):
    """Telemetry follows the native session; pane identity still guards effects."""
    return fingerprint({k: who[k] for k in ("source", "agent", "kind", "value")})


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
        for row in snapshot["agents"]:
            if (not isinstance(row.get("pane_id"), str) or not row["pane_id"]
                    or not isinstance(row.get("agent_status"), str)
                    or any(row.get(field) is not None and not isinstance(row[field], str)
                           for field in ("name", "cwd", "agent"))
                    or row.get("agent_session") is not None and identity(row) is None):
                raise ValueError("Herdr agent row schema unsupported; update the observer adapter")
        return snapshot

    def prompt(self, name, *, recovery=False):
        instruction = ('Reconcile the pending observer notification. Read the original job through next; '
                       'acknowledge or report that same job once. Do not repeat completed reports or factory work. '
                       if recovery else 'Observer evidence is ready. ')
        return self.call("agent", "prompt", name,
                         instruction + 'Invoke Skill(skill: "herdr-observer") for the pending analysis. '
                         'Keep findings private; do not coordinate factory work.')

    def notify(self, *, attention=False):
        title = "Herdr observer needs attention" if attention else "Herdr observer report ready"
        body = ("A private observer analysis remains pending. Inspect observer health."
                if attention else "A private local report is available. Ask the observer to show it.")
        self.call("notification", "show", title, "--body", body, "--sound", "none")


def current(snapshot):
    pane = os.environ.get("HERDR_PANE_ID")
    matches = [row for row in snapshot["agents"] if row.get("pane_id") == pane and row.get("name")]
    if len(matches) != 1 or identity(matches[0]) is None:
        raise ValueError("current pane must have one named native agent with a verified session")
    row = matches[0]
    session = row["agent_session"]
    if (not isinstance(row["name"], str) or not isinstance(row.get("cwd"), str) or not Path(row["cwd"]).is_absolute()
            or session["agent"] not in report_delivery.DISPLAY_PREFIXES
            or session.get("pane_id", pane) != pane
            or session["kind"] == "path" and not Path(session["value"]).is_absolute()
            or session["kind"] == "id" and report_delivery.native_identity(row) is None):
        raise ValueError("launch a supported native observer with an absolute cwd and matching pane/session identity")
    return row


def matches(binding, row):
    return (identity(row) == binding.get("identity") and row.get("name") == binding.get("name")
            and row.get("cwd") == binding.get("cwd"))
