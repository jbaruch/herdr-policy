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
import stat
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
    required = ("foreman/remote_owner.py", "classify/extract-answer.py",
                "foreman/coordination_metrics.py", "measurements.py", "references/coordination-metrics.md",
                "native-hook.sh", "foreman/session_start_hook.py", "foreman/role_context.py",
                "references/foreman-context.md", "references/worker-context.md",
                "references/context-recovery.md", "references/workflow-worker.md",
                "references/foreman-workflow.md", "references/bootstrap.md",
                "references/team-scope.md", "references/coding-policy-integration.md")
    if any(not (skill / name).is_file() for name in required) or (skill / "tests").exists():
        raise BehaviorFailure("incomplete runtime or installed development test tree; repair the package inventory")
    misplaced = [name for name in ("adversarial.py", "evaluate.sh", "scoring.py")
                 if (skill / "classify" / name).exists()]
    if misplaced:
        raise BehaviorFailure("development calibration tools remain installed: {}; move them outside declared skill trees".format(
            ", ".join(misplaced)))


def verify_role_context(project, skill, hook, environment, adapter: str | None = None):
    """Run shipped role checks and hook envelopes with private real owner records.

    Only the external pane observation is a fixture. It rejects every other
    Herdr command, so this cannot launch, prompt, close or resume a real worker.
    A Cursor envelope is not evidence of a native Cursor foreman capability.
    """
    fixture = project / "role-context-fixture"
    fixture.mkdir()
    binary = fixture / "bin"
    binary.mkdir()
    pane_file = binary / "pane.json"
    (binary / "herdr").write_text(
        "#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
        "if sys.argv[1:] != ['pane','get','private-fixture-pane']: raise SystemExit(64)\n"
        "pane=json.loads(Path(__file__).with_name('pane.json').read_text())\n"
        "if pane.get('unavailable'): raise SystemExit(75)\n"
        "print(json.dumps({'result':{'pane':pane}}))\n")
    (binary / "herdr").chmod(0o755)
    environment = {**environment, "PATH": str(binary) + os.pathsep + environment.get("PATH", ""),
                   "XDG_STATE_HOME": str(fixture / "state"), "XDG_CONFIG_HOME": str(fixture / "config"),
                   "HERDR_ENV": "private-conformance", "HERDR_PANE_ID": "private-fixture-pane"}
    selected_adapter = adapter
    if selected_adapter is None:
        selected_adapter = "claude-code" if ".claude" in hook.parts else "codex"
    kind = {"claude-code": "claude", "grok": "grok"}.get(selected_adapter, "codex")
    native = {"source": "herdr:" + kind, "agent": kind, "kind": "id", "value": "private-foreman"}
    setup = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from foreman import supervision
from foreman.state import default_state_path, empty_state, save_state
owner = default_state_path()
at = '2026-10-19T00:00:00+00:00'
if sys.argv[2] in ('foreman', 'native-id', 'native-path'):
    if sys.argv[2] == 'foreman':
        save_state(owner, empty_state())
    kind = 'path' if sys.argv[2] == 'native-path' else 'id'
    value = str(owner.parent / 'foreman-native.jsonl') if kind == 'path' else 'private-foreman'
    supervision.bind(owner, supervision.identity(value, str(Path.cwd()),
        'private-conformance', kind=kind, pane_id='private-fixture-pane'), at)
elif sys.argv[2] == 'hold':
    evidence = owner.parent / 'private-hold.md'
    evidence.write_text('Private conformance hold; never a live operator decision.')
    supervision.hold(owner, {'id':'private-hold','kind':'waiting_for_user',
        'resume_condition':'Private explicit fixture resume','evidence':[str(evidence)],
        'dispositions':[{'member':row['id'],'outcome':'Private fixture held', 'evidence':[str(evidence)]}
                        for row in supervision.load(owner)['members'] if row['active']]}, at)
elif sys.argv[2] == 'worker':
    kind = sys.argv[3]
    supervision.enroll(owner, {'id':'private-assignment','agent':'private-worker','task':'private-task',
        'report':str(owner.parent / 'worker-report.md'),'pane_id':'private-fixture-pane',
        'native_session':{'source':'herdr:'+kind,'agent':kind,'kind':'id','value':'private-worker'}}, at)
else:
    raise SystemExit('Unsupported private fixture setup')
"""

    def seed(action):
        command("python3", "-c", setup, str(skill), action, kind,
                env=environment, cwd=project, check_behavior=True, quiet=True)

    def observe(session, expected, *, absent=(), transcript=None):
        before = {str(path.relative_to(fixture)): path.read_bytes()
                  for path in fixture.rglob("*") if path.is_file()}
        arguments = (adapter,) if adapter else ()
        raw = command("bash", str(hook), "session-start", *arguments,
                      env=environment, cwd=project, check_behavior=True,
                      input_text=json.dumps({"session_id": session, "cwd": str(project), "transcript_path": transcript}))
        if expected is None:
            if raw:
                raise BehaviorFailure("Unverified installed session loaded a role contract")
        else:
            result = json.loads(raw)
            if adapter == "portable":
                context = result.get("additionalContext")
            elif adapter == "cursor" or adapter is None and ".cursor" in hook.parts:
                context = result.get("additional_context")
            else:
                context = result.get("hookSpecificOutput", {}).get("additionalContext")
            if (len(raw.encode()) > 16_384 or not isinstance(context, str)
                    or expected not in context or any(text in context for text in absent)):
                raise BehaviorFailure("Installed role hook failed its bounded role-specific native envelope")
        after = {str(path.relative_to(fixture)): path.read_bytes()
                 for path in fixture.rglob("*") if path.is_file()}
        if after != before:
            raise BehaviorFailure("Installed role observation modified its private owner or binding")

    seed("foreman")
    pane_file.write_text(json.dumps({"pane_id": "private-fixture-pane", "agent_session": native}))
    observe("private-foreman", "Herdr Foreman Operating Context", absent=("## Step 17", "Herdr Worker Context"))
    observe("another-session", None)
    seed("native-path")
    transcript = str(fixture / "state/foreman/foreman-native.jsonl")
    pane_file.write_text(json.dumps({"pane_id": "private-fixture-pane", "agent_session": {
        **native, "kind": "path", "value": transcript}}))
    observe("private-foreman", "Herdr Foreman Operating Context", transcript=transcript)
    pane_file.write_text('{"unavailable":true}')
    observe("private-foreman", "Herdr Context Recovery", transcript=transcript)
    seed("native-id")
    pane_file.write_text('{"unavailable":true}')
    observe("private-foreman", "Herdr Context Recovery", absent=("Herdr Foreman Operating Context",))
    pane_file.write_text(json.dumps({"pane_id": "private-fixture-pane", "agent_session": native}))
    seed("worker")
    native["value"] = "private-worker"
    pane_file.write_text(json.dumps({"pane_id": "private-fixture-pane", "agent_session": native}))
    observe("private-worker", "Herdr Worker Context", absent=("Herdr Foreman Operating Context", "## Step 17"))
    seed("hold")
    observe("private-worker", "Herdr Context Recovery", absent=("Herdr Worker Context", "Herdr Foreman Operating Context"))
    native["value"] = "private-foreman"
    pane_file.write_text(json.dumps({"pane_id": "private-fixture-pane", "agent_session": native}))
    observe("private-foreman", "Herdr Context Recovery", absent=("Herdr Foreman Operating Context",))
    native["value"] = "unbound-session"
    pane_file.write_text(json.dumps({"pane_id": "private-fixture-pane", "agent_session": native}))
    observe("unbound-session", None)


def verify_workflow_readiness(project, skill, environment):
    """Exercise the installed read-only CLI without creating task authority."""
    owner = project / "readiness-owner.json"
    raw = command("bash", str(skill / "foreman.sh"), "workflow-readiness", "--state", str(owner),
                  "--config", str(project / "absent-readiness-config.json"),
                  "--now", "2026-10-19T00:00:00Z", env=environment, cwd=project, check_behavior=True)
    result = json.loads(raw)
    if (len(raw.encode()) > 16_384 or result.get("schema_version") != 2
            or result.get("counts_scope") != "returned_items" or result.get("items") != []
            or result.get("pagination", {}).get("total") != 0
            or result.get("counts", {}).get("dispatchable") != 0
            or result.get("authorizes_dispatch") is not False
            or result.get("authorizes_progression") is not False or owner.exists()):
        raise BehaviorFailure("Installed workflow readiness failed its bounded read-only observation contract")


def verify_skill_commands(project, host, package, variable, names, environment):
    """Run installed selectors alone; never execute their release/team operations."""
    roots = {(project / host / "skills" / ("acr__jbaruch__" + package + "__" + name)).resolve(): name for name in names}
    counts = dict.fromkeys(names, 0)
    for skill in roots:
        count = 0
        for file in sorted(skill.rglob("*.md")):
            for block in re.findall(r"```bash\n(.*?)```", file.read_text(), re.S):
                if "$" + variable + "/" not in block:
                    continue
                lines = block.strip().splitlines()
                if not lines or not lines[0].startswith(variable + "="):
                    raise BehaviorFailure("{}: installed skill command lacks its selector; repair the Markdown bootstrap".format(package))
                code = 'set -euo pipefail\n' + lines[0] + '\nprintf "%s" "$' + variable + '"'
                selected = Path(command("bash", "-c", code, env=environment, cwd=project, check_behavior=True))
                if not selected.is_absolute():
                    selected = project / selected
                selected = selected.resolve()
                if selected not in roots:
                    raise BehaviorFailure("{}: selector chose another installation; repair owned native references".format(package))
                calls = re.findall(r'\b(bash|python3) "\$' + variable + r'/([^"\n]+)"', block)
                if not calls:
                    raise BehaviorFailure("{}: selector has no quoted script target; repair the installed command".format(package))
                for interpreter, relative in calls:
                    target = (selected / relative).resolve()
                    if not target.is_relative_to(selected) or not target.is_file():
                        raise BehaviorFailure("{}: installed command target is absent or outside its skill; repair the payload".format(package))
                    if target.suffix != {"bash": ".sh", "python3": ".py"}[interpreter]:
                        raise BehaviorFailure("{}: installed command has the wrong interpreter; repair the Markdown invocation".format(package))
                count += 1
                counts[roots[selected]] += 1
        if not count:
            raise BehaviorFailure("{}: installed skill has no exercised command selectors; restore conformance coverage".format(package))
    if not all(counts.values()):
        raise BehaviorFailure("{}: a required skill root was never selected; restore command coverage".format(package))
    return counts


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
    # Run the installed identity reader with development sources absent from
    # its interpreter path. The old package-root assumption failed here even
    # though the package had realized successfully.
    identity = json.loads(command("python3", str(skill / "policy-paths.py"), "identity", env=environment,
                                  cwd=project, check_behavior=True))
    if (identity.get("schema_version") != 1 or identity.get("policy_root") != str(skill)
            or not isinstance(identity.get("version"), str) or not isinstance(identity.get("digest"), str)
            or re.fullmatch(r"[a-f0-9]{64}", identity["digest"]) is None
            or identity.get("authorizes_dispatch") is not False):
        raise BehaviorFailure("{}: installed policy has no verified native identity".format(agent))
    snapshot = project / "measurement-snapshot.json"
    snapshot.write_text(json.dumps({"schema": 2, "window": {"start": "2026-10-10T00:00:00Z", "end": "2026-10-10T01:00:00Z"},
                                    "tasks": [], "assignments": []}))
    measurement_environment = {key: value for key, value in environment.items() if key != "PYTHONDONTWRITEBYTECODE"}
    measurement_payload = {str(path.relative_to(skill)) for path in skill.rglob("*")}
    measured = json.loads(command("python3", str(skill / "measurements.py"), str(snapshot),
                                  env=measurement_environment, cwd=project, check_behavior=True))
    if (measured.get("schema") != 2 or measured.get("authorizes_progression") is not False
            or measured.get("coverage", {}).get("tasks") != 0
            or set(measured.get("waiting", {})) != {"assessment", "resolution"}):
        raise BehaviorFailure("{}: installed measurement command failed its read-only summary contract".format(agent))
    report = project.parent / ("measurement-report-" + agent + ".json")
    receipt = json.loads(command("python3", str(skill / "measurements.py"), str(snapshot), "--output", str(report),
                                 env=measurement_environment, cwd=project, check_behavior=True))
    saved_report = json.loads(report.read_text())
    if (receipt.get("kind") != "measurement_report_receipt" or receipt.get("path") != str(report.resolve())
            or receipt.get("authorizes_progression") is not False or stat.S_IMODE(report.stat().st_mode) != 0o600
            or saved_report.get("schema_version") != 1 or saved_report.get("summary") != measured):
        raise BehaviorFailure("{}: installed measurement output failed its private report contract".format(agent))
    forbidden = skill / "measurement-report.json"
    try:
        command("python3", str(skill / "measurements.py"), str(snapshot), "--output", str(forbidden),
                env=measurement_environment, cwd=project, check_behavior=True)
    except BehaviorFailure:
        pass
    else:
        raise BehaviorFailure("{}: installed measurement output accepted an owned package path".format(agent))
    if forbidden.exists():
        raise BehaviorFailure("{}: measurement output modified its installed payload".format(agent))
    if {str(path.relative_to(skill)) for path in skill.rglob("*")} != measurement_payload:
        raise BehaviorFailure("{}: measurement imports created files inside the installed payload".format(agent))
    repeated_identity = json.loads(command("python3", str(skill / "policy-paths.py"), "identity", env=environment,
                                           cwd=project, check_behavior=True))
    if repeated_identity != identity:
        raise BehaviorFailure("{}: installed policy identity changed during measurement".format(agent))
    # Reach the installed progression entrypoint's policy-selection boundary.
    # The fixture reads the selected policy and exits before any grant/lease.
    progression_probe = """
import json, sys
from pathlib import Path
from types import SimpleNamespace
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from foreman import progression_owner, progression_service
from foreman.remote_owner import loaded_policy
def inspect_only(state_path, task, generation, service_id, plugin_root):
    version, digest = loaded_policy(plugin_root)
    print(json.dumps({"schema_version": 1, "version": version, "digest": digest, "authority_entered": False}))
    raise SystemExit(0)
progression_owner.service_session = inspect_only
args = SimpleNamespace(interval=1, task="unadmitted-fixture", generation=1, service_id="fixture")
progression_service.run_command(args, Path(sys.argv[2]), None, sleeper=lambda _: None)
raise SystemExit("Installed progression did not reach its policy-selection boundary")
"""
    progression = json.loads(command("python3", "-c", progression_probe, str(skill), str(state / "unadmitted.json"),
                                     env=environment, cwd=project, check_behavior=True))
    if progression != {"schema_version": 1, "version": identity["version"], "digest": identity["digest"], "authority_entered": False}:
        raise BehaviorFailure("{}: installed progression selects a different policy identity".format(agent))
    skill_commands = {"herdr-policy": verify_skill_commands(
        project, host, "herdr-policy", "HS", ("herdr-foreman", "herdr-standup"), environment)}
    if coding_source:
        skill_commands["coding-policy"] = verify_skill_commands(
            project, host, "coding-policy", "KS", ("release", "adopt-fork-pr", "onboard-repo", "migrate-to-plugin"), environment)
    foreign = project / "foreign"
    foreign.mkdir()
    for path in paths:
        if "reset-input" in path.parent.name:
            event = "reset-input"
        elif "supervision-stop" in path.parent.name:
            event = "supervision-stop"
        elif "session-start" in path.parent.name:
            event = "session-start"
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
        if event != "session-start":
            command("bash", str(path), event, env={**environment, "HERDR_ENV": "1"}, cwd=project, check_behavior=True, quiet=True,
                    input_text='{"session_id":"isolated-fixture","prompt":"Ordinary prompt"}\n')
    startup = next(path for path in paths if "session-start" in path.parent.name)
    verify_role_context(project, skill, startup, environment)
    # Execute the installed owner with development trees physically absent.
    json.loads(command("bash", str(skill / "foreman.sh"), "state", env=environment, cwd=project, check_behavior=True))
    verify_workflow_readiness(project, skill, environment)
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
        if inputs["TEAM_OPERATION"] != str(skill / "references/worker-context.md"):
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
            "measurements": "pass", "private_measurement_report": "pass", "workflow_readiness": "pass",
            "role_context": "pass",
            "skill_commands": skill_commands,
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
