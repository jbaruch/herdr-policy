#!/usr/bin/env python3
"""Run Shellcheck and Pyright on runtime and development sources.

stdout belongs to the tools. stderr carries setup failures. Exit 0 clean,
1 findings, 2 missing tools or unreadable source tree. No source changes.
"""

import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        for name in ("shellcheck", "pyright"):
            if not shutil.which(name):
                raise ValueError("install {} before running diagnostics".format(name))
        scripts = sorted(str(path) for folder in ("skills", "tests", "scripts")
                         for path in (root / folder).rglob("*.sh"))
        if not scripts:
            raise ValueError("no shell scripts found — restore the source tree")
        statuses = [subprocess.run(["shellcheck", "-S", "info", *scripts], cwd=root).returncode,
                    subprocess.run(["pyright"], cwd=root).returncode]
    except (OSError, ValueError) as exc:
        print("run-diagnostics: {} — repair the development environment and retry".format(exc), file=sys.stderr)
        return 2
    return int(any(statuses))


if __name__ == "__main__":
    raise SystemExit(main())
