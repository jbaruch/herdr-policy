#!/usr/bin/env python3
"""Run each development suite in an isolated process against canonical skills.

argv: optional suite paths relative to this repository; default every test_*
directly within a tests/ directory. stdout: one JSON summary. stderr: suite
output and diagnostics. Exit 0 all pass, 1 suite failures, 2 setup failure.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    requested = sys.argv[1:] if argv is None else argv
    suites = [ROOT / name for name in requested] if requested else sorted(
        path for path in (ROOT / "tests").rglob("test_*")
        if path.is_file() and path.suffix in (".py", ".sh") and path.parent.name == "tests")
    # Startup hook shell suites reside together under tests/hooks.
    if not requested:
        suites.extend(sorted((ROOT / "tests/hooks").glob("test_*.sh")))
    failures = []
    try:
        if not suites or any(not path.is_file() or path.suffix not in (".py", ".sh") for path in suites):
            raise ValueError("suite paths must name existing Python or Bash tests")
        with tempfile.TemporaryDirectory(prefix="herdr-tests-") as scratch:
            for number, suite in enumerate(suites):
                state = Path(scratch) / str(number)
                (state / "state").mkdir(parents=True)
                (state / "config").mkdir()
                environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                               "XDG_STATE_HOME": str(state / "state"), "XDG_CONFIG_HOME": str(state / "config")}
                for key in ("HERDR_ENV", "HERDR_PANE_ID", "PYTHONPATH"):
                    environment.pop(key, None)
                print("Running {}".format(suite.relative_to(ROOT)), file=sys.stderr, flush=True)
                result = subprocess.run([sys.executable if suite.suffix == ".py" else "bash", str(suite)],
                                        cwd=ROOT, env=environment, stdout=sys.stderr, stderr=sys.stderr)
                if result.returncode:
                    failures.append(str(suite.relative_to(ROOT)))
    except (OSError, ValueError) as exc:
        print("run-tests: {} — repair the development environment and retry".format(exc), file=sys.stderr)
        print(json.dumps({"suites": 0, "passed": 0, "failed": 0, "failures": [], "error": str(exc)}))
        return 2
    print(json.dumps({"suites": len(suites), "passed": len(suites) - len(failures),
                      "failed": len(failures), "failures": failures}))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
