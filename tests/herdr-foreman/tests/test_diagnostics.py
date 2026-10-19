"""Tests for foreman.diagnostics.

`stderr_warn` owns the `foreman: ` prefix. Callers hand it a bare message;
six of them used to bake the prefix into the message as well, so stderr read
`foreman: foreman: ...` on exactly the paths an operator reads most.
"""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import os as _os
import sys as _sys

# Run as a script (`python3 tests/test_x.py`), Python puts tests/ on sys.path
# rather than the repo root, so neither `foreman` nor `tests.fakes` would
# resolve. Under `-m unittest` from the root this is already true and the
# insert is a no-op. The consuming repo's runner executes files as scripts.
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../../../skills/herdr-foreman"))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

import contextlib
import io
import re
import unittest
from pathlib import Path

from foreman import diagnostics
from foreman.diagnostics import PREFIX, stderr_warn

MODULE_DIR = Path(diagnostics.__file__).resolve().parent
# A string literal that opens with the prefix. Written as a pattern rather
# than a plain substring so the assertion below can point at a line.
PREFIXED_LITERAL = re.compile(r"""["']""" + re.escape(PREFIX))


class StderrWarnTest(unittest.TestCase):
    def test_it_writes_one_prefixed_line_to_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            stderr_warn("pane read failed")
        self.assertEqual(err.getvalue(), "foreman: pane read failed\n")

    def test_the_prefix_has_one_owner(self):
        # Every other module passes a bare message. A literal that carries the
        # prefix itself would print it twice once it reaches stderr_warn.
        offenders = []
        for path in sorted(MODULE_DIR.glob("*.py")):
            if path.name == "diagnostics.py":
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if PREFIXED_LITERAL.search(line):
                    offenders.append("{}:{}".format(path.name, lineno))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
