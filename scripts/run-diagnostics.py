#!/usr/bin/env python3
"""Run Shellcheck and Pyright on runtime and development sources.

stdout: one JSON object with ok and per-tool exit codes; error on setup failure.
stderr: tool output and actionable diagnostics. Exit 0 clean, 1 findings,
2 missing tools or unreadable source tree. No source changes.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    statuses = {}
    try:
        for name in ("shellcheck", "pyright"):
            if not shutil.which(name):
                raise ValueError("install {} before running diagnostics".format(name))
        scripts = sorted(str(path) for folder in ("skills", "tests", "scripts")
                         for path in (root / folder).rglob("*.sh"))
        if not scripts:
            raise ValueError("no shell scripts found — restore the source tree")
        for name, arguments in (("shellcheck", ["-S", "info", *scripts]), ("pyright", [])):
            result = subprocess.run([name, *arguments], cwd=root, capture_output=True,
                                    text=True, errors="replace")
            statuses[name] = result.returncode
            for output in (result.stdout, result.stderr):
                if output:
                    print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")
            if result.returncode:
                print("run-diagnostics: {} exited {} — fix the reported findings and rerun".format(
                    name, result.returncode), file=sys.stderr)
    except (OSError, ValueError) as exc:
        print("run-diagnostics: {} — repair the development environment and retry".format(exc), file=sys.stderr)
        print(json.dumps({"ok": False, "tools": statuses, "error": str(exc)}))
        return 2
    failed = any(statuses.values())
    print(json.dumps({"ok": not failed, "tools": statuses}))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
