#!/usr/bin/env python3
"""Inspect the suite selected by one test script without executing its bodies.

argv: one test-script path. stdout: schema-1 JSON with tests (null when no
suite was built) and exit_code. stderr: script diagnostics. Exit 0 after a
successful script entrypoint; 2 on unusable input, otherwise the script status.
The repository runner separately executes every test file's actual bodies.
"""

from contextlib import redirect_stdout
import json
from pathlib import Path
import runpy
import sys
import unittest
import unittest.runner


_selected_count = None


class DiscoveryRunner(unittest.TextTestRunner):
    def run(self, test):
        global _selected_count
        _selected_count = test.countTestCases()
        result = self._makeResult()
        result.testsRun = _selected_count
        return result


def main():
    status = 2
    if len(sys.argv) != 2:
        print("entrypoint-probe: supply one test-script path and retry", file=sys.stderr)
    else:
        path = Path(sys.argv[1]).resolve()
        sys.argv = [str(path)]
        sys.path[0] = str(path.parent)
        unittest.runner.TextTestRunner = DiscoveryRunner
        try:
            with redirect_stdout(sys.stderr):
                runpy.run_path(str(path), run_name="__main__")
            status = 0
        except SystemExit as error:
            code = error.code
            status = int(code) if isinstance(code, int) else 0 if code is None else 2
        except (ImportError, OSError, SyntaxError):
            print("entrypoint-probe: cannot import the script; restore its path, imports and syntax and retry", file=sys.stderr)
        if _selected_count is None:
            print("entrypoint-probe: no suite was built; restore the script's unittest entrypoint and retry", file=sys.stderr)
            status = status or 2
    print(json.dumps({"schema_version": 1, "tests": _selected_count, "exit_code": status}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
