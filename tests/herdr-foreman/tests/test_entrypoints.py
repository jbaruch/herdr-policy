"""Guard: every test file must run as a script and run ALL of its tests.

Two defects this file exists to catch, both of which shipped:

1. `unittest.main()` landing mid-file. Appending a class after the entry-point
   guard silently strands it: as a script, `unittest.main()` runs against the
   globals defined so far and then exits, so nothing below the guard is even
   defined. Three files had 87, 122, and 404 stranded lines and the suite
   stayed green, because `-m unittest` imports the whole module first and
   never executes the guard.
2. A test file that cannot run as a script at all. `python3 tests/test_x.py`
   puts tests/ on sys.path rather than the repo root, so `foreman` does not
   import. Every file failed that way while `discover` passed.

The repository runner executes every file as a script. This guard separately
compares script suite selection with library discovery. A child replaces only
the test runner, retaining actual imports and unittest.main() selection without
executing the entire regression suite a second time.
"""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import ast
import importlib.util
import json
import os as _os
import sys as _sys

# Run as a script (`python3 tests/test_x.py`), Python puts tests/ on sys.path
# rather than the repo root, so neither `foreman` nor `tests.fakes` would
# resolve. Under `-m unittest` from the root this is already true and the
# insert is a no-op. The consuming repo's runner executes files as scripts.
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../../../skills/herdr-foreman"))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent

#: Bound import and discovery even when a test module has broken startup.
SCRIPT_TIMEOUT_SEC = 120


def test_files():
    """Every test module in tests/, this one included."""
    return sorted(TESTS_DIR.glob("test_*.py"))


def is_entrypoint_guard(node):
    """True when `node` is `if __name__ == "__main__":`."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


#: One subprocess per file per run, shared by every assertion below.
_SCRIPT_RESULTS = {}


def script_test_count(path):
    """Inspect `path` as a script and return `(suite_count, exit_code)`."""
    key = str(path)
    if key not in _SCRIPT_RESULTS:
        _SCRIPT_RESULTS[key] = _run_script(path)
    return _SCRIPT_RESULTS[key]


def _run_script(path):
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "entrypoint_probe.py"), str(path)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SCRIPT_TIMEOUT_SEC,
        check=False,
        text=True,
    )
    try:
        value = json.loads(completed.stdout)
    except ValueError:
        value = {}
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or type(value.get("tests")) is not int or value["tests"] < 0
            or value.get("exit_code") != completed.returncode):
        raise AssertionError(
            "`{} {}` reported no suite count. Repair its script entrypoint. Diagnostics:\n{}".format(
                sys.executable, path.name, (completed.stderr or "")[-2000:]
            )
        )
    return value["tests"], completed.returncode


def loader_test_count(path):
    """How many tests `python3 -m unittest tests.<module>` would run."""
    suite = unittest.TestLoader().loadTestsFromName("tests." + path.stem)
    return suite.countTestCases()


class GuardPlacementTest(unittest.TestCase):
    """Cheap, no subprocesses: the guard must be the last top-level statement."""

    def test_every_test_file_has_exactly_one_guard(self):
        for path in test_files():
            with self.subTest(file=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                guards = [node for node in tree.body if is_entrypoint_guard(node)]
                self.assertEqual(len(guards), 1, "expected one entry-point guard")

    def test_the_guard_is_the_last_top_level_statement(self):
        for path in test_files():
            with self.subTest(file=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertTrue(
                    is_entrypoint_guard(tree.body[-1]),
                    "the entry-point guard must come last, or every class "
                    "defined after it is stranded when the file runs as a "
                    "script",
                )

    def test_no_class_is_defined_after_the_guard(self):
        # The same rule stated the way it actually bites.
        for path in test_files():
            with self.subTest(file=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                guard_at = next(
                    index
                    for index, node in enumerate(tree.body)
                    if is_entrypoint_guard(node)
                )
                after = [
                    node.name
                    for node in tree.body[guard_at + 1 :]
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef))
                ]
                self.assertEqual(after, [], "stranded after the guard")

    def test_this_file_is_covered_by_its_own_check(self):
        self.assertIn(Path(__file__).resolve(), test_files())

    def test_there_is_something_to_check(self):
        # A glob that silently matched nothing would make every test above
        # vacuously true.
        self.assertGreaterEqual(len(test_files()), 2)


class ScriptExecutionTest(unittest.TestCase):
    """Execute each real entrypoint and compare its selected suite."""

    def test_each_file_runs_the_same_tests_as_a_script(self):
        for path in test_files():
            with self.subTest(file=path.name):
                ran, _code = script_test_count(path)
                self.assertGreater(ran, 0, "a test script must select actual cases")
                self.assertEqual(
                    ran,
                    loader_test_count(path),
                    "running {} as a script ran a different number of tests "
                    "than `-m unittest tests.{}` -- something after the "
                    "entry-point guard is stranded".format(path.name, path.stem),
                )

    def test_each_file_imports_and_builds_its_suite_as_a_script(self):
        for path in test_files():
            with self.subTest(file=path.name):
                _ran, code = script_test_count(path)
                self.assertEqual(code, 0, "{} failed script discovery".format(path.name))

    def test_probe_does_not_execute_test_bodies(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "test_probe_fixture.py"
            marker = Path(scratch) / "body-ran"
            path.write_text("import unittest\nfrom pathlib import Path\n"
                "class A(unittest.TestCase):\n"
                "    def test_body(self):\n"
                "        Path({!r}).write_text('unexpected')\n".format(str(marker))
                + 'if __name__ == "__main__":\n    unittest.main()\n')
            self.assertEqual(script_test_count(path), (1, 0))
            self.assertFalse(marker.exists())

    def test_probe_detects_missing_script_imports(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "test_missing_import.py"
            path.write_text("import entrypoint_probe_missing_dependency\n")
            with self.assertRaisesRegex(AssertionError, "cannot import the script"):
                script_test_count(path)

    def test_probe_normalizes_python_311_boolean_exit_codes_and_rejects_other_payloads(self):
        for payload, expected in ((False, 0), (True, 1), (None, 0), ("unsupported", 2)):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as scratch:
                path = Path(scratch) / "test_boolean_exit.py"
                path.write_text("import unittest\nclass A(unittest.TestCase):\n"
                    "    def test_body(self):\n        pass\n"
                    "if __name__ == '__main__':\n    unittest.main(exit=False)\n"
                    "    raise SystemExit({!r})\n".format(payload))
                self.assertEqual(script_test_count(path), (1, expected))

    def test_a_stranded_class_would_be_caught(self):
        # Prove the check has teeth: a file whose guard sits mid-body reports
        # fewer tests than the loader finds.
        stranded = ast.parse(
            "import unittest\n"
            "class A(unittest.TestCase):\n"
            "    def test_a(self):\n        pass\n"
            'if __name__ == "__main__":\n    unittest.main()\n'
            "class B(unittest.TestCase):\n"
            "    def test_b(self):\n        pass\n"
        )
        guard_at = next(
            index for index, node in enumerate(stranded.body) if is_entrypoint_guard(node)
        )
        after = [
            node.name
            for node in stranded.body[guard_at + 1 :]
            if isinstance(node, ast.ClassDef)
        ]
        self.assertEqual(after, ["B"])
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "test_stranded.py"
            path.write_text(ast.unparse(stranded))
            self.assertEqual(script_test_count(path), (1, 0))
            spec = importlib.util.spec_from_file_location("entrypoint_stranded_fixture", path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(unittest.TestLoader().loadTestsFromModule(module).countTestCases(), 2)


if __name__ == "__main__":
    unittest.main()
