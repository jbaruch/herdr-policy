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


RUNTIME_ENVIRONMENT = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL",
    "SYSTEMROOT", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "PYTHONDONTWRITEBYTECODE",
    "HERDR_ENV", "HERDR_PANE_ID",
    "WORKTREE_ROOT",
})


def runtime_environment(source=None):
    """Pass runtime settings alone, never ambient CI/provider credentials."""
    source = os.environ if source is None else source
    return {key: value for key, value in source.items() if key in RUNTIME_ENVIRONMENT}


def command(*arguments, env=None, cwd=None, input_text=None, check_behavior=False, quiet=False):
    environment = runtime_environment(env)
    # Only the pinned registry client's immutable-source fetch needs this token.
    # Installed hooks, decoders and owners never receive it.
    if arguments[:2] == ("acr", "install") and os.environ.get("GH_TOKEN"):
        environment["GH_TOKEN"] = os.environ["GH_TOKEN"]
    result = subprocess.run(arguments, input=input_text, capture_output=True, text=True, env=environment, cwd=cwd)
    if result.returncode:
        failure = BehaviorFailure if check_behavior else OSError
        raise failure("{} exited {}; inspect the selected operation without logging candidate output".format(
            arguments[0], result.returncode))
    if quiet and (result.stdout or result.stderr):
        raise BehaviorFailure("{} emitted unexpected hook output (stdout {} bytes, stderr {} bytes)".format(
            arguments[0], len(result.stdout.encode()), len(result.stderr.encode())))
    return result.stdout


def acr(operation, project, *arguments):
    return json.loads(command("acr", operation, *arguments, "--project", str(project), "--json",
                              check_behavior=operation in ("realize", "check", "uninstall")))


def revision(value):
    if re.fullmatch(r"github:jbaruch/(herdr-policy|coding-policy)@[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError("use an immutable, full Git commit reference for the selected package")
    return value


def verify_runtime_payload(skill):
    required = ("foreman/remote_owner.py", "classify/extract-answer.py")
    if any(not (skill / name).is_file() for name in required) or (skill / "tests").exists():
        raise BehaviorFailure("incomplete runtime or installed development test tree; repair the package inventory")
    misplaced = [name for name in ("adversarial.py", "evaluate.sh", "scoring.py")
                 if (skill / "classify" / name).exists()]
    if misplaced:
        raise BehaviorFailure("development calibration tools remain installed: {}; move them outside declared skill trees".format(
            ", ".join(misplaced)))


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
    verify_runtime_payload(skill)
    paths = [p for p in (project / host / "hooks").glob(IDENTITY + "*/native-hook.sh")]
    if len(paths) != 3:
        raise ValueError("{}: expected three owned hook entrypoints, got {}".format(agent, len(paths)))
    state = project / "private-state"
    environment = {**runtime_environment(), "XDG_STATE_HOME": str(state), "XDG_CONFIG_HOME": str(project / "private-config"),
                   "PYTHONDONTWRITEBYTECODE": "1", "WORKTREE_ROOT": str(project / "private-worktrees")}
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
        # This ordinary prompt/unbound Stop must reach its owner and return
        # silently; the wrapper's fail-closed fallback also exits zero.
        command("bash", str(path), event, env={**environment, "HERDR_ENV": "1"}, cwd=project, check_behavior=True, quiet=True,
                input_text='{"session_id":"isolated-fixture","prompt":"Ordinary prompt"}\n')
    # Execute the installed owner with development trees physically absent.
    json.loads(command("bash", str(skill / "foreman.sh"), "state", env=environment, cwd=project, check_behavior=True))
    # Both runtime vendor envelopes remain decodable without calibration tools.
    for kind, payload in (("claude", [{"type": "result", "structured_output": {"fixture": "decoded"}}]),
                          ("grok", {"text": '{"fixture":"decoded"}'})):
        raw, decoded = project / (kind + "-envelope.json"), project / (kind + "-answer.json")
        raw.write_text(json.dumps(payload))
        command("python3", str(skill / "classify/extract-answer.py"), kind, str(raw), str(decoded),
                env=environment, cwd=project, check_behavior=True)
        if json.loads(decoded.read_text()) != {"fixture": "decoded"}:
            raise BehaviorFailure("{}: installed {} envelope decoder changed the answer".format(agent, kind))
    if coding_source:
        environment.pop("HERDR_CODING_POLICY_ROOT", None)
        inputs = json.loads(command("python3", str(skill / "policy-paths.py"), "brief-inputs",
                                    "--shared", str(project), env=environment, cwd=project, check_behavior=True))
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
            command("bash", str(path), event, env=environment, cwd=project, check_behavior=True, input_text='{"stop_hook_active":true}\n')
    acr("check", project)
    acr("uninstall", project, "github:jbaruch/herdr-policy")
    acr("realize", project)
    if any(path.is_file() and any(part.startswith(IDENTITY) for part in path.relative_to(project / host).parts)
           for path in (project / host).rglob("*")):
        raise ValueError("{}: uninstall left owned Herdr artifacts".format(agent))
    if SENTINEL not in (project / "AGENTS.md").read_text() or user_file.read_text() != "preserve user native content\n":
        raise ValueError("{}: lifecycle modified user-owned content".format(agent))
    return {"agent": agent, "bootstrap_listed": before.get("ok") is True, "upgrade": "pass",
            "idempotence": "pass", "runtime": "pass", "envelope_decoders": "pass", "standalone_hooks": "pass",
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
