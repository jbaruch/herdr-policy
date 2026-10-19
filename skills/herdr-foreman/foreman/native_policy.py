"""Read ACR's actual native installation identity through its public owner.

ACR renders skills/rules/hooks rather than a Tessl package root. Its read-only
list/check contracts supply the locked package identity and owned targets.
The full check can fetch locked dependencies; only verified in-process metadata
is cached, so fresh native readers require that verification access.
The checked target hashes are cached only in process memory by current lock
bytes; actual target bytes must still match on every authority check. No native
metadata, hook, user instruction or registry record is written or synthesized.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from .errors import StateError


SKILL = "acr__jbaruch__herdr-policy__herdr-foreman"
SOURCE = "github:jbaruch/herdr-policy"
ADAPTERS = {".codex": "codex", ".claude": "claude-code", ".cursor": "cursor"}
LIMIT = 2_097_152
_checked = {}


def executing_policy_root():
    skill = Path(__file__).resolve().parents[1]
    if skill.name == SKILL:
        return skill
    return skill.parent.parent


def _fail():
    return StateError("Cannot verify the executing ACR Herdr installation; restore its current acr CLI, locked dependency and unchanged realized rules/skill/hooks before admitting or continuing task authority.", {})


def _read(path, limit=LIMIT):
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise _fail()
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise _fail()
        return raw
    except OSError:
        raise _fail() from None


def _cli(project, command, agent=None, *, run):
    argv = ["acr", command, "--project", str(project), "--json"]
    if agent is not None:
        argv += ["--agent", agent]
    environment = {key: value for key, value in os.environ.items() if key in {
        "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "XDG_CACHE_HOME"}}
    try:
        result = run(argv, capture_output=True, text=True, timeout=30, check=False, env=environment)
        if result.returncode or not isinstance(result.stdout, str) or len(result.stdout.encode("utf-8")) > LIMIT:
            raise _fail()
        value = json.loads(result.stdout)
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        raise _fail() from None
    if not isinstance(value, dict) or value.get("ok") is not True or value.get("command") != command or not isinstance(value.get("result"), dict):
        raise _fail()
    return value["result"]


def _selection(project, lock, agent, *, run):
    key = (str(project), hashlib.sha256(lock).hexdigest(), agent)
    if key in _checked:
        return _checked[key]
    listed = _cli(project, "list", run=run).get("dependencies")
    if not isinstance(listed, list):
        raise _fail()
    selected = [row.get("locked") for row in listed if isinstance(row, dict)
                and isinstance(row.get("declaration"), dict) and row["declaration"].get("source") == SOURCE]
    if len(selected) != 1 or not isinstance(selected[0], dict):
        raise _fail()
    package = selected[0]
    version, content, commit = package.get("packageVersion"), package.get("contentHash"), package.get("commit")
    if (package.get("source") != SOURCE or not isinstance(version, str) or re.fullmatch(r"\d+\.\d+\.\d+", version) is None
            or not isinstance(content, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", content) is None
            or not isinstance(commit, str) or re.fullmatch(r"[a-f0-9]{40}", commit) is None):
        raise _fail()
    checked = _cli(project, "check", agent, run=run)
    plan = checked.get("plan")
    if (not isinstance(plan, dict) or plan.get("operations") not in (None, []) or plan.get("ledgerChanged") is not False
            or not isinstance(plan.get("ledger"), dict) or plan["ledger"].get("schemaVersion") not in (1, 2)
            or not isinstance(plan["ledger"].get("targets"), list)):
        raise _fail()
    targets = {}
    for target in plan["ledger"]["targets"]:
        if not isinstance(target, dict) or not isinstance(target.get("entries"), list):
            raise _fail()
        if target.get("owner") == "coordinator":
            continue
        owned = [entry for entry in target["entries"] if isinstance(entry, dict) and entry.get("source") == SOURCE and entry.get("adapter") == agent]
        if not owned:
            continue
        relative = target.get("path")
        output_hash = target.get("outputHash")
        if (not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts
                or relative in targets or not relative or any(ord(char) < 32 for char in relative)
                or not isinstance(output_hash, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", output_hash) is None):
            raise _fail()
        targets[relative] = output_hash
    if not targets or _read(project / ".agents/registry.lock") != lock:
        raise _fail()
    value = {"version": version, "commit": commit, "content": content, "targets": dict(sorted(targets.items()))}
    if len(_checked) >= 8:
        _checked.pop(next(iter(_checked)))
    _checked[key] = value
    return value


def loaded_policy(skill, *, run=subprocess.run):
    skill = Path(skill)
    if (skill.name != SKILL or skill.parent.name != "skills" or skill.parent.parent.name not in ADAPTERS
            or skill.resolve() != skill):
        raise _fail()
    project = skill.parents[2]
    lock = _read(project / ".agents/registry.lock")
    selected = _selection(project, lock, ADAPTERS[skill.parent.parent.name], run=run)
    prefix = str(skill.relative_to(project)) + "/"
    owned = {relative for relative in selected["targets"] if relative.startswith(prefix)}
    required = {prefix + name for name in ("SKILL.md", "foreman/remote_owner.py", "foreman/cli.py",
                                           "foreman/progression_service.py", "references/team-operation.md")}
    if not required.issubset(owned):
        raise _fail()
    actual = {str(path.relative_to(project)) for path in skill.rglob("*") if path.is_file()
              and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}}
    if actual != owned:
        raise _fail()
    digest = hashlib.sha256()
    digest.update(json.dumps({key: selected[key] for key in ("version", "commit", "content")}, sort_keys=True).encode("utf-8"))
    total = 0
    for relative in selected["targets"]:
        path = project / relative
        if path.resolve() != path:
            raise _fail()
        raw = _read(path)
        total += len(raw)
        if total > 8_388_608:
            raise _fail()
        target_digest = hashlib.sha256(raw).digest()
        if "sha256:" + target_digest.hex() != selected["targets"][relative]:
            raise _fail()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(target_digest)
    if _read(project / ".agents/registry.lock") != lock:
        raise _fail()
    return selected["version"], digest.hexdigest()
