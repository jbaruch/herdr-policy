#!/usr/bin/env python3
"""Exercise ACR lifecycle operations on immutable package revisions in private consumers.

argv: --herdr-source github:owner/repo@COMMIT [--coding-source github:owner/repo@COMMIT]
stdout: JSON with per-adapter outcomes. stderr: actionable failures. Exit 0 pass,
1 behavior failure, 2 CLI/setup failure. No workers or operator projects are used.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


SENTINEL = "Operator-owned instruction sentinel: preserve this line.\n"
# The scope-only bootstrap is the immutable upgrade oracle. Review monthly;
# replace only in a dedicated baseline PR with recorded migration coverage.
BOOTSTRAP = "github:jbaruch/herdr-policy@8c7ab1f2182033fdc7de3c6dcb4624d1f31f5988"
IDENTITY = "acr__jbaruch__herdr-policy__"


class BehaviorFailure(RuntimeError):
    """An installed operation failed after its tooling and source were prepared."""


def command(*arguments, env=None, input_text=None, check_behavior=False):
    result = subprocess.run(arguments, input=input_text, capture_output=True, text=True, env=env)
    if result.returncode:
        failure = BehaviorFailure if check_behavior else OSError
        raise failure("{} exited {}: {}".format(arguments[0], result.returncode, result.stderr.strip()))
    return result.stdout


def acr(operation, project, *arguments):
    return json.loads(command("acr", operation, *arguments, "--project", str(project), "--json",
                              check_behavior=operation in ("realize", "check", "uninstall")))


def revision(value):
    if re.fullmatch(r"github:jbaruch/(herdr-policy|coding-policy)@[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError("use an immutable, full Git commit reference for the selected package")
    return value


def exercise(project, agent, host, herdr_source, coding_source):
    project.mkdir()
    (project / "AGENTS.md").write_text(SENTINEL)
    user_file = project / host / "operator-owned.txt"
    user_file.parent.mkdir()
    user_file.write_text("preserve user native content\n")
    acr("init", project, "--agent", agent, "--freshness", "none", "--non-interactive")
    if coding_source:
        acr("install", project, coding_source, "--freshness", "none", "--non-interactive")
    acr("install", project, BOOTSTRAP, "--freshness", "none", "--non-interactive")
    acr("realize", project)
    before = acr("list", project)
    acr("install", project, herdr_source, "--freshness", "none", "--non-interactive")
    acr("realize", project)
    repeat = acr("realize", project)
    if repeat["result"]["plan"]["operations"] or repeat["result"]["plan"]["ledgerChanged"]:
        raise ValueError("{}: repeated realization changed native outputs".format(agent))
    skill = project / host / "skills" / (IDENTITY + "herdr-foreman")
    if not (skill / "foreman/remote_owner.py").is_file() or (skill / "tests").exists():
        raise ValueError("{}: incomplete runtime or installed development payload".format(agent))
    paths = [p for p in (project / host / "hooks").glob(IDENTITY + "*/native-hook.sh")]
    if len(paths) != 3:
        raise ValueError("{}: expected three owned hook entrypoints, got {}".format(agent, len(paths)))
    state = project / "private-state"
    environment = {**os.environ, "XDG_STATE_HOME": str(state), "XDG_CONFIG_HOME": str(project / "private-config"),
                   "PYTHONDONTWRITEBYTECODE": "1"}
    for key in ("HERDR_ENV", "HERDR_PANE_ID", "PYTHONPATH"):
        environment.pop(key, None)
    foreign = project / "foreign"
    foreign.mkdir()
    for path in paths:
        if "reset-input" in path.parent.name:
            event = "reset-input"
        elif "supervision-stop" in path.parent.name:
            event = "supervision-stop"
        else:
            continue
        # No Python or team runtime prerequisite may be consulted in standalone mode.
        result = subprocess.run(["/bin/bash", str(path), event], cwd=foreign,
                                env={**environment, "PATH": str(foreign)}, input="{}\n",
                                text=True, capture_output=True)
        if (result.returncode, result.stdout, result.stderr) != (0, "", ""):
            raise ValueError("{}: standalone {} consulted team prerequisites".format(agent, event))
        command("bash", str(path), event, env={**environment, "HERDR_ENV": "1"}, check_behavior=True,
                input_text='{"session_id":"isolated-fixture","prompt":"Ordinary prompt"}\n')
    # Execute the installed owner with development trees physically absent.
    json.loads(command("bash", str(skill / "foreman.sh"), "state", env=environment, check_behavior=True))
    if coding_source:
        environment.pop("HERDR_CODING_POLICY_ROOT", None)
        inputs = json.loads(command("python3", str(skill / "policy-paths.py"), "brief-inputs",
                                    "--shared", str(project), env=environment, check_behavior=True))
        release = project / host / "skills/acr__jbaruch__coding-policy__release"
        if inputs["POLICY_INDEX"] != str(release / "POLICY.md"):
            raise ValueError("{}: unrelated native instructions replaced the selected general policy".format(agent))
        if inputs["TEAM_OPERATION"] != str(skill / "references/team-operation.md"):
            raise ValueError("{}: team contract came from another installation".format(agent))
        general_hooks = list((project / host / "hooks").glob("acr__jbaruch__coding-policy__*/native-hook.sh"))
        if len(general_hooks) != 2:
            raise ValueError("{}: generic hook bundle is incomplete".format(agent))
        for path in general_hooks:
            event = "session-start" if "session-start" in path.parent.name else "stop-handoff"
            command("bash", str(path), event, env=environment, check_behavior=True, input_text='{"stop_hook_active":true}\n')
    acr("check", project)
    acr("uninstall", project, "github:jbaruch/herdr-policy")
    acr("realize", project)
    if any(path.is_file() and any(part.startswith(IDENTITY) for part in path.relative_to(project / host).parts)
           for path in (project / host).rglob("*")):
        raise ValueError("{}: uninstall left owned Herdr artifacts".format(agent))
    if SENTINEL not in (project / "AGENTS.md").read_text() or user_file.read_text() != "preserve user native content\n":
        raise ValueError("{}: lifecycle modified user-owned content".format(agent))
    return {"agent": agent, "bootstrap_listed": before.get("ok") is True, "upgrade": "pass",
            "idempotence": "pass", "runtime": "pass", "standalone_hooks": "pass",
            "removal": "pass", "user_content": "preserved"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--herdr-source", type=revision, required=True)
    parser.add_argument("--coding-source", type=revision)
    args = parser.parse_args()
    outcomes = []
    try:
        with tempfile.TemporaryDirectory(prefix="herdr-acr-conformance-") as scratch:
            for agent, host in (("codex", ".codex"), ("claude-code", ".claude"), ("cursor", ".cursor")):
                outcomes.append(exercise(Path(scratch).resolve() / agent, agent, host, args.herdr_source, args.coding_source))
    except (ValueError, BehaviorFailure) as exc:
        print("check-installations: {} — fix package behavior before publication".format(exc), file=sys.stderr)
        print(json.dumps({"passed": False, "adapters": outcomes, "error": str(exc)}))
        return 1
    except OSError as exc:
        print("check-installations: {} — restore CLI/network access and retry".format(exc), file=sys.stderr)
        print(json.dumps({"passed": False, "adapters": outcomes, "error": str(exc)}))
        return 2
    print(json.dumps({"passed": True, "herdr_source": args.herdr_source, "coding_source": args.coding_source,
                      "adapters": outcomes}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
