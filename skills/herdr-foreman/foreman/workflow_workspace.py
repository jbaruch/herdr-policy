"""Bound current task inputs and Git facts, without a local history archive.

The admitted private artifact directory contains current dispatch inputs and
still-required reports. Writers refuse links/foreign entries. No Git command
changes the checkout; implementation and release effects have separate owners.
"""

from fnmatch import fnmatchcase
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Literal, overload

from .errors import StateError, UsageError


CURRENT_FILES = frozenset({"plan.json", "common.md", "developer.md", "reviewer.md", "tester.md", "release.md"})
ARTIFACT_NAME = re.compile(r"(?:report|brief|delivery|reviews)-[0-9]+-(?:developer|reviewer|tester|release)\.(?:md|json)")
INPUT_LIMIT = 2_097_152
REPORT_LIMIT = 524_288


@overload
def git(worktree: str | Path, *arguments: str, allow_absent: Literal[False] = False) -> str: ...


@overload
def git(worktree: str | Path, *arguments: str, allow_absent: Literal[True]) -> str | None: ...


def git(worktree, *arguments, allow_absent=False):
    try:
        result = subprocess.run(["git", "--no-pager", "-C", str(worktree), *arguments],
                                capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise StateError("Cannot inspect this task's Git checkout; restore its selected worktree and Git access before progression.", {}) from None
    if allow_absent and result.returncode == 1:
        return None
    if result.returncode or len(result.stdout) > INPUT_LIMIT:
        raise StateError("Git inspection failed or exceeded the workflow budget; inspect this task's checkout without discarding its work.", {})
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise StateError("The task's Git facts are not supported UTF-8; inspect the affected paths before progression.", {}) from None


def origin_identity(value):
    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", value)
    return match[1] if match else None


def verify_origin(root, expected):
    """Bind fetch and every effective push URL to the admitted repository."""
    urls = [git(root, "remote", "get-url", "origin").strip(),
            *git(root, "remote", "get-url", "--push", "--all", "origin").splitlines()]
    identities = [origin_identity(url) for url in urls]
    if len(urls) < 2 or any(identity is None or identity.casefold() != expected.casefold() for identity in identities):
        raise UsageError("The actual fetch or push repository differs from this task's admitted origin; preserve its refs and reconcile the configured targets.", {})


def base_checkout(contract):
    root = Path(contract["repository"]["worktree"]).resolve()
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    private = Path(git(root, "rev-parse", "--absolute-git-dir").strip())
    base = common.parent
    verify_origin(base, contract["repository"]["github"])
    if (private == common or common.name != ".git" or base == root
            or Path(git(base, "rev-parse", "--show-toplevel").strip()).resolve() != base
            or origin_identity(git(base, "remote", "get-url", "origin").strip()) != contract["repository"]["github"]):
        raise UsageError("Provision this task as an isolated Git worktree of its verified base checkout before admission.", {})
    return base


def inspect(contract, task, *, built=False):
    """Actual checkout and change identity; a report never supplies these facts."""
    repo = contract["repository"]
    root = Path(repo["worktree"]).resolve()
    base_checkout(contract)
    actual_root = Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if actual_root != root or git(root, "branch", "--show-current").strip() != repo["branch"]:
        raise UsageError("Restore this task's provisioned writer worktree and feature branch before progression.", {})
    if origin_identity(git(root, "remote", "get-url", "origin").strip()) != repo["github"]:
        raise UsageError("The writer's origin differs from the admitted GitHub target; preserve both and reconcile repository authority.", {})
    if git(root, "merge-base", "--is-ancestor", task["base_revision"], "HEAD", allow_absent=True) is None:
        raise UsageError("The writer no longer contains the registered task base; recover its authorized base before progressing.", {})
    if git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise UsageError("The selected writer has uncommitted work; preserve it and obtain a complete built report before verification or release.", {})
    head = git(root, "rev-parse", "HEAD").strip()
    tree = git(root, "rev-parse", "HEAD^{tree}").strip()
    changed = git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z",
                  task["base_revision"], "HEAD", "--")
    paths = [path for path in changed.split("\0") if path]
    if len(paths) > 256 or any(not any(fnmatchcase(path, allowed) for allowed in task["allowed_paths"]) for path in paths):
        raise UsageError("The actual implementation exceeds this task's allowed paths or bounded change set; obtain the changed-scope decision before proceeding.", {})
    if built and not paths:
        raise UsageError("No authorized implementation change is present; reconcile the task's actual outcome instead of opening an empty release.", {})
    return {"commit": head, "tree": tree, "paths": paths}


def capture(path, *, limit=INPUT_LIMIT):
    path = Path(path)
    try:
        with path.open("rb") as stream:
            body = stream.read(limit + 1)
        if len(body) > limit:
            raise UsageError("The current workflow artifact exceeds its byte budget; retain the source and use a bounded decision rather than attaching history.", {})
        body.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise StateError("Restore this task's readable UTF-8 current artifact before progression; missing evidence is not success.", {}) from None
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(body).hexdigest()}, body


def inputs(contract):
    result, total = {}, 0
    for expected in [contract["config"], contract["common"], *contract["briefs"].values()]:
        captured, body = capture(expected["path"], limit=INPUT_LIMIT - total)
        total += len(body)
        if captured != expected:
            raise UsageError("An admitted config or brief template changed; preserve the task and obtain a new explicit authority handoff.", {})
        result[captured["path"]] = body
    return result


def prepare_directory(path, *, fresh=False):
    root = Path(path)
    if root.resolve() != root:
        raise UsageError("Use the actual private artifact path without aliases; preserve the existing target.", {})
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        if fresh:
            raise UsageError("Reserve a fresh private artifact directory for this admission; an existing directory may belong to another task and is preserved.", {}) from None
    except OSError:
        raise StateError("Cannot create the admitted private current-artifact directory; restore its parent and ownership before progression.", {}) from None
    try:
        info = root.lstat()
        entries = list(root.iterdir())
    except OSError:
        raise StateError("Cannot inspect the current-artifact directory; restore visibility before writing any task input.", {}) from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077
            or fresh and entries):
        raise UsageError("Use an empty private owner-controlled artifact directory at admission; preserve links, shared directories and existing contents.", {})
    for entry in entries:
        if entry.name not in CURRENT_FILES and ARTIFACT_NAME.fullmatch(entry.name) is None:
            raise UsageError("Unexpected files exist in the current workflow directory; preserve them and reconcile the selected owner path.", {})
        if not stat.S_ISREG(entry.lstat().st_mode):
            raise UsageError("A current workflow artifact is not a regular file; preserve the original path and restore owner-controlled inputs.", {})
    return root


def write_current(root, name, body, *, immutable=False):
    if name not in CURRENT_FILES and (not immutable or ARTIFACT_NAME.fullmatch(name) is None or name.startswith("report-")):
        raise UsageError("Write only named current workflow inputs; reports remain native-worker output.", {})
    if not isinstance(body, bytes) or len(body) > INPUT_LIMIT:
        raise UsageError("Keep current workflow input bytes bounded before dispatch.", {})
    root = prepare_directory(root)
    target = root / name
    if target.is_symlink():
        raise UsageError("Preserve the linked workflow input and restore its regular owner file before writing.", {})
    if immutable and target.exists():
        captured, prior = capture(target)
        if prior != body:
            raise UsageError("Preserve this dispatch's original brief or delivery bytes; a new outcome requires a new owner intent.", {})
        return captured, prior
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".workflow-", dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError:
        raise StateError("Cannot atomically write this task's current input; restore its private directory and retain pending intent evidence.", {}) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return capture(target)
