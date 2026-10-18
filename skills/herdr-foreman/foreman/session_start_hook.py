"""Compose Herdr startup status from the runtime owners, without granting authority.

stdin is unused. stdout is at most one native or portable SessionStart JSON
object; diagnostics go to stderr. Owner failures become visible status lines.
Exit 0, including best-effort failures, so startup never becomes a runtime gate.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


OWNERS = ("herdr-team-status.sh", "check-report-caches.sh")


def collect(skill, environment) -> dict | None:
    portable = bool(environment.get("TESSL_AGENT"))
    if portable and environment["TESSL_AGENT"] in ("claude-code", "codex"):
        return None
    environment = {**environment, "SESSION_START_MODE": "portable" if portable else "native"}
    statuses = []
    for name in OWNERS:
        script = Path(skill) / "hooks" / name
        try:
            result = subprocess.run(["bash", str(script)], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, env=environment)
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            if result.returncode:
                raise ValueError("exited {}".format(result.returncode))
            if not result.stdout.strip():
                continue
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict) or not isinstance(payload.get("additionalContext"), str):
                raise ValueError("returned no additionalContext string")
            statuses.append(payload["additionalContext"])
        except (OSError, ValueError) as exc:
            statuses.append("Session-start status — Herdr hook {} could not report ({}); run `bash {}` "
                            "to inspect its diagnostic.".format(name, exc, script))
    if not statuses:
        return None
    context = "\n\n".join(statuses)
    if portable:
        return {"additionalContext": context}
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}


def main():
    payload = collect(Path(__file__).resolve().parents[1], os.environ)
    if payload:
        print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
