#!/usr/bin/env python3
"""Establish a real empty base only for an authorized new repository.

argv: --repo existing-clone --branch default-branch [--initialize-empty].
stdout: schema-1 base receipt, never implementation/review authority. stderr:
structured actionable error. Exit 0 actual remote base, 1 unmet precondition,
2 tool failure or uncertain push. No shared files, local branches or owner
records are changed. All commit construction happens in a private scratch repo.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import sys


SHA = re.compile(r"[a-f0-9]{40}\Z")
REF_BYTES = 65_536
GIT_TIMEOUT = 30


class BootstrapError(ValueError):
    def __init__(self, reason, message, *, code=1, **details):
        super().__init__(message)
        self.reason, self.code, self.details = reason, code, details


def git(repo, *arguments, run=subprocess.run):
    try:
        return run(["git", "-C", str(repo), *arguments], capture_output=True, text=True,
                   timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise BootstrapError("git_unavailable", "Restore Git and origin connectivity before retrying; no Git stderr is retained.", code=2) from None


def checked(repo, *arguments, run=subprocess.run):
    result = git(repo, *arguments, run=run)
    if result.returncode:
        raise BootstrapError("git_failed", "The repository bootstrap Git operation failed. Restore repository access and Git author identity; preserve existing history and files. Git stderr is withheld.", code=2)
    return result.stdout.strip()


def refs(repo, *, run=subprocess.run):
    output = checked(repo, "ls-remote", "--refs", "origin", run=run)
    if len(output.encode("utf-8")) > REF_BYTES:
        raise BootstrapError("remote_not_empty", "Origin has existing history beyond this bootstrap reader's bound. Use ordinary worktree provisioning from its actual default branch.")
    result = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or SHA.fullmatch(fields[0]) is None or not fields[1].startswith("refs/"):
            raise BootstrapError("remote_refs_invalid", "Origin did not return usable Git refs. Restore its read access; an unreadable remote is not an empty repository.", code=2)
        result[fields[1]] = fields[0]
    return result


def receipt(repo, branch, revision, *, created=False, status="existing_base"):
    return {"schema_version": 1, "repository": str(repo), "branch": branch, "base_revision": revision,
            "created": created, "status": status, "next": "ordinary_worktree_provisioning",
            "authorizes_implementation": False, "authorizes_release": False}


def existing(repo, branch, found):
    revision = found.get("refs/heads/" + branch)
    if revision:
        return receipt(repo, branch, revision)
    raise BootstrapError("different_remote_history", "Origin already has refs but lacks the selected default branch. Preserve that history and use its actual branch with ordinary provisioning.")


def bootstrap(repo, branch, *, initialize=False, run=subprocess.run):
    repo = Path(repo).resolve()
    if Path(checked(repo, "rev-parse", "--show-toplevel", run=run)).resolve() != repo:
        raise BootstrapError("repository_root_required", "Pass the authorized repository's clone root; a directory inside another repository cannot establish a new repository base.")
    checked(repo, "check-ref-format", "refs/heads/" + branch, run=run)
    remote = checked(repo, "remote", "get-url", "origin", run=run)
    pushes = checked(repo, "remote", "get-url", "--push", "--all", "origin", run=run).splitlines()
    if pushes != [remote]:
        raise BootstrapError("origin_targets_differ", "Bootstrap needs one matching origin fetch/push target. Restore the authorized new repository's origin; no alternate remote was initialized.")
    found = refs(repo, run=run)
    if found:
        return existing(repo, branch, found)
    if not initialize:
        raise BootstrapError("empty_origin", "Origin has no refs. For an explicitly authorized new repository, rerun with --initialize-empty to create only an empty initial base; then use normal reviewed development.")
    with tempfile.TemporaryDirectory(prefix="herdr-empty-base-") as directory:
        scratch = Path(directory)
        checked(scratch, "init", "--quiet", "--initial-branch", branch, run=run)
        checked(scratch, "remote", "add", "origin", remote, run=run)
        checked(scratch, "commit", "--quiet", "--allow-empty", "-m", "Initialize repository", run=run)
        revision = checked(scratch, "rev-parse", "HEAD", run=run)
        if SHA.fullmatch(revision) is None or checked(scratch, "ls-tree", "-r", "--name-only", "HEAD", run=run):
            raise BootstrapError("base_not_empty", "The scratch base was not a verified empty commit. Preserve the target repository and repair the bootstrap tool.", code=2)
        found = refs(scratch, run=run)
        if found:
            return existing(repo, branch, found)
        uncertain = None
        try:
            pushed = git(scratch, "push", "--porcelain", "origin", revision + ":refs/heads/" + branch, run=run)
            if pushed.returncode:
                uncertain = "push_failed"
        except BootstrapError:
            uncertain = "push_outcome_unknown"
        try:
            found = refs(scratch, run=run)
        except BootstrapError:
            raise BootstrapError("push_readback_unavailable", "The initial-base push may have written origin. Preserve this attempted base and restore actual remote readback before continuing; never force a branch or assume nothing was written.",
                                 code=2, attempted_base_revision=revision) from None
        if found.get("refs/heads/" + branch) == revision:
            return receipt(repo, branch, revision, created=True, status="created")
        if found:
            return existing(repo, branch, found)
        raise BootstrapError(uncertain or "push_unconfirmed", "No remote base was confirmed. Preserve the attempted base and inspect origin connectivity before retrying; do not force a branch.", code=2,
                             attempted_base_revision=revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--initialize-empty", action="store_true")
    args = parser.parse_args()
    try:
        result = bootstrap(args.repo, args.branch, initialize=args.initialize_empty)
    except BootstrapError as exc:
        print(json.dumps({"error": exc.reason, "message": str(exc), "details": exc.details}), file=sys.stderr)
        return exc.code
    except (OSError, UnicodeError):
        print(json.dumps({"error": "bootstrap_io_unavailable", "message": "Restore readable UTF-8 Git metadata and private scratch storage. A push may have occurred; read actual origin refs before any continuation or retry."}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
