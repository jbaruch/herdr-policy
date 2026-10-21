"""Independent native assignments start without waiting for another task's report."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import io
import json
import tempfile
import unittest

from foreman import cli, supervision
from tests.test_cli import AT, SNAPSHOT, FreshOwnerNative


class ParallelDispatchTest(unittest.TestCase):
    def test_three_independent_tasks_run_before_any_report_is_delivered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, config, snapshot, common = (root / name for name in
                                               ("state.json", "config.json", "snapshot.json", "common.md"))
            shipped = Path(__file__).resolve().parents[3] / "skills/herdr-foreman/config.example.json"
            payload = json.loads(shipped.read_text())
            payload["worker_kinds"] = [row for row in payload["worker_kinds"] if row["kind"] == "codex"]
            payload.pop("foreman")
            payload["judge"] = {"worker_kind": "codex", "model": "gpt-6-astra", "effort": "high"}
            config.write_text(json.dumps(payload))
            snapshot.write_text(json.dumps(SNAPSHOT))
            common.write_text("Preserve the task's bounded authority.\n")
            supervision.bind(state, supervision.identity("foreman", str(root), "fixture", pane_id="foreman-pane"),
                             AT, root=root / "bindings")
            native = FreshOwnerNative()
            native.frames = [native.EMPTY]

            def invoke(arguments, client=None):
                out, err = io.StringIO(), io.StringIO()
                code = cli.main(["--state", str(state), "--config", str(config), *arguments],
                                stdout=out, stderr=err, client=client)
                self.assertEqual(code, 0, err.getvalue())
                return json.loads(out.getvalue())

            for index in range(3):
                task = "independent-{}".format(index)
                report, brief = root / (task + "-report.md"), root / (task + "-brief.md")
                brief.write_text("Implement only the authorized independent scope.\nREPORT: {}\n".format(report))
                plan = invoke(["plan", "--roles", "developer", "--task", task, "--snapshot", str(snapshot)])
                invoke(["apply", "--assignments", json.dumps(plan), "--task", task, "--now", AT,
                        "--common", str(common), "--brief", "developer=" + str(brief),
                        "--report", "developer=" + str(report), "--composer-settle", "0"], client=native)
                native.agents[plan["assignments"]["developer"]]["agent_status"] = "working"
                self.assertFalse(report.exists())
            members = supervision.load(state)["members"]
            self.assertEqual({row["assignment"]["task"] for row in members if row["active"]},
                             {"independent-0", "independent-1", "independent-2"})
            self.assertEqual(len([event for event in native.events if event[0] == "start"]), 3)
            self.assertEqual(len([event for event in native.events if event[0] == "prompt"]), 3)
            self.assertEqual({worker["agent_status"] for worker in native.agents.values()}, {"working"})


if __name__ == "__main__":
    unittest.main()
