#!/usr/bin/env python3
"""Run CI runtime suites, or reuse successful identical-tree PR evidence.

argv: --evidence PATH (private runner artifact destination).
stdout: one JSON decision/result; stderr: suite output and fallback diagnostics.
Exit 0: the full suites passed or verified evidence covers them. Exit 1: suite
failure. Exit 2: execution/setup error. Unavailable reuse always runs the suites.
Only a main push with HERDR_REUSE_RUNTIME=1 may consume evidence. This helper
grants no installation, publication, moderation, merge or runtime authority.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/tests.yml"
SCHEMA = 1
MAX_ARCHIVE = 65536
MAX_RECORD = 32768
SHA = re.compile(r"[0-9a-f]{40}\Z")


class Unavailable(ValueError):
    """Evidence is unavailable or does not prove the required execution."""


def require(condition, message):
    if not condition:
        raise Unavailable(message)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        require(target.scheme == "https" and not target.username and not target.password,
                "artifact redirect is not HTTPS")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            # GitHub redirects archives to storage. Never forward the API token.
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, repository, token):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository),
                "invalid repository identity")
        self.repository = repository
        self.token = token
        self.opener = urllib.request.build_opener(SafeRedirect())

    def read(self, route, limit):
        request = urllib.request.Request(
            "https://api.github.com/repos/" + self.repository + "/" + route,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "herdr-ci-runtime-gate",
                     "X-GitHub-Api-Version": "2022-11-28",
                     **({"Authorization": "Bearer " + self.token} if self.token else {})})
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read(limit + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise Unavailable("GitHub evidence request failed ({})".format(type(exc).__name__)) from exc
        require(len(body) <= limit, "GitHub evidence exceeds its size bound")
        return body

    def get(self, route) -> Any:
        try:
            return json.loads(self.read(route, 1048576))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Unavailable("GitHub returned unreadable evidence metadata") from exc


def command(arguments, environment):
    result = subprocess.run(arguments, cwd=ROOT, env=environment, capture_output=True,
                            text=True, timeout=30, check=True)
    return result.stdout.strip()


def runtime_environment(environ):
    """Give both executions the same finite environment, without CI credentials."""
    scratch = Path(environ["RUNNER_TEMP"])
    home = scratch / "herdr-runtime-home"
    temporary = scratch / "herdr-runtime-tmp"
    home.mkdir(exist_ok=True)
    temporary.mkdir(exist_ok=True)
    return {"PATH": str(scratch / "acr-bin") + os.pathsep + environ["PATH"],
            "HOME": str(home), "TMPDIR": str(temporary), "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "TZ": "UTC", "TERM": "dumb", "CI": "true",
            "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
            "HERDR_CODING_POLICY_ROOT": environ["HERDR_CODING_POLICY_ROOT"]}


def tree_identity(environment):
    require(not command(["git", "status", "--porcelain", "--untracked-files=all"], environment),
            "checkout has changes outside its Git tree")
    return {"commit": command(["git", "rev-parse", "HEAD"], environment),
            "tree": command(["git", "rev-parse", "HEAD^{tree}"], environment)}


def directory_digest(root):
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file() or path.is_symlink())
    require(bool(files), "installed baseline has no files")
    for path in files:
        require(not path.is_symlink(), "installed baseline contains a symbolic link")
        name = path.relative_to(root).as_posix().encode()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def fingerprint(environment, environ):
    identity = tree_identity(environment)
    normalized = lambda value: value.replace(str(ROOT), "$WORKSPACE").replace(
        environ["RUNNER_TEMP"], "$RUNNER_TEMP")
    tools = {}
    for name, arguments in {"python3": ["--version"], "bash": ["--version"],
                            "git": ["--version"], "node": ["--version"], "npm": ["--version"],
                            "shellcheck": ["--version"], "pyright": ["--version"],
                            "tessl": ["--version"], "go": ["version"], "acr": ["--version"]}.items():
        executable = shutil.which(name, path=environment["PATH"])
        require(executable, "required tool unavailable: " + name)
        resolved = Path(str(executable)).resolve()
        tools[name] = {"path": normalized(str(resolved)),
                       "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
                       "version": command([str(resolved), *arguments], environment)}
    runner = {key: environ.get(key, "") for key in ("ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH")}
    require(all(runner.values()), "hosted runner image identity is unavailable")
    return {"tree": identity["tree"], "runner": runner, "tools": tools,
            "environment": {key: normalized(value) for key, value in environment.items()},
            "baseline_sha256": directory_digest(Path(environment["HERDR_CODING_POLICY_ROOT"]).resolve())}


def exactly_one(items, message):
    require(isinstance(items, list) and len(items) == 1, message)
    return items[0]


def archive_record(body, artifact):
    require(artifact.get("digest") == "sha256:" + hashlib.sha256(body).hexdigest(),
            "artifact archive digest differs from GitHub metadata")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            member = exactly_one(archive.infolist(), "artifact must contain exactly one record")
            require(member.filename == "runtime-evidence.json" and member.file_size <= MAX_RECORD
                    and not member.is_dir() and not member.flag_bits & 1
                    and (member.external_attr >> 16) & 0o170000 != 0o120000,
                    "artifact record is not a bounded regular JSON file")
            return json.loads(archive.read(member))
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError,
            OSError, EOFError, NotImplementedError, zlib.error) as exc:
        raise Unavailable("artifact record is unreadable") from exc


def reusable(api, current, identity, environ):
    repository = environ["GITHUB_REPOSITORY"]
    repository_id = int(environ["GITHUB_REPOSITORY_ID"])
    commit = environ["GITHUB_SHA"]
    require(SHA.fullmatch(commit) and identity["commit"] == commit,
            "publisher checkout does not match its event commit")
    pulls = api.get("commits/{}/pulls?per_page=100".format(commit))
    require(isinstance(pulls, list) and len(pulls) < 100, "merge association is unavailable or truncated")
    pull = exactly_one([item for item in pulls if item.get("merged_at")
                        and item.get("merge_commit_sha") == commit], "merge association is missing or ambiguous")
    require(pull["base"]["repo"]["id"] == repository_id and pull["base"]["ref"] == "main"
            and pull["head"]["repo"]["id"] == repository_id
            and pull["head"]["repo"]["full_name"] == repository, "merged PR is not from this repository")
    head = pull["head"]["sha"]
    require(SHA.fullmatch(head), "merged PR has an invalid head")
    source = api.get("git/commits/" + head)
    require(source["sha"] == head and source["tree"]["sha"] == current["tree"],
            "PR source/workflow tree differs from the publisher")
    workflow = api.get("actions/workflows/tests.yml")
    require(workflow["path"] == WORKFLOW and workflow["state"] == "active", "unexpected CI workflow")
    runs = api.get("actions/workflows/{}/runs?head_sha={}&event=pull_request&per_page=100".format(workflow["id"], head))
    require(runs["total_count"] == len(runs["workflow_runs"]) and runs["total_count"] < 100,
            "PR run enumeration is incomplete")
    run = exactly_one(runs["workflow_runs"], "PR CI run is missing or ambiguous")
    require(run["status"] == "completed" and run["conclusion"] == "success"
            and run["event"] == "pull_request" and run["head_sha"] == head
            and run["repository"]["id"] == repository_id
            and run["head_repository"]["id"] == repository_id
            and run["workflow_id"] == workflow["id"] and run["path"] == WORKFLOW,
            "PR run is not terminal successful same-repository CI")
    run_id, attempt = run["id"], run["run_attempt"]
    require(type(run_id) is int and type(attempt) is int and run_id > 0 and attempt > 0,
            "PR run identity is invalid")
    artifacts = api.get("actions/runs/{}/artifacts?per_page=100".format(run_id))
    require(artifacts["total_count"] == len(artifacts["artifacts"]) and artifacts["total_count"] < 100,
            "artifact enumeration is incomplete")
    name = "runtime-evidence-{}-{}".format(run_id, attempt)
    artifact = exactly_one([item for item in artifacts["artifacts"] if item.get("name") == name],
                           "runtime artifact is missing or ambiguous")
    binding = artifact["workflow_run"]
    require(artifact["expired"] is False and 0 < artifact["size_in_bytes"] <= MAX_ARCHIVE
            and type(artifact["id"]) is int and artifact["id"] > 0
            and binding["id"] == run_id and binding["repository_id"] == repository_id
            and binding["head_repository_id"] == repository_id and binding["head_sha"] == head,
            "artifact is expired, oversized or belongs to another run")
    record = archive_record(api.read("actions/artifacts/{}/zip".format(artifact["id"]), MAX_ARCHIVE), artifact)
    require(type(record["schema_version"]) is int and record["schema_version"] == SCHEMA
            and record["fingerprint"] == current,
            "source tree, runner, tools, dependencies or runtime environment differ")
    provenance = record["provenance"]
    require(provenance == {"repository": repository, "repository_id": repository_id,
                           "workflow_path": WORKFLOW, "run_id": run_id, "run_attempt": attempt,
                           "event": "pull_request", "pull_request": pull["number"], "head_sha": head,
                           "checkout_commit": provenance.get("checkout_commit")},
            "artifact provenance differs from its trusted run")
    checkout = provenance["checkout_commit"]
    require(isinstance(checkout, str) and SHA.fullmatch(checkout), "invalid tested checkout")
    tested = api.get("git/commits/" + checkout)
    require(tested["sha"] == checkout and tested["tree"]["sha"] == current["tree"]
            and (checkout == head or head in [item["sha"] for item in tested["parents"]]),
            "tested checkout is not this PR's identical tree")
    require(record["result"]["failed"] == 0 and record["result"]["suites"] > 0
            and record["result"]["passed"] == record["result"]["suites"]
            and not record["result"].get("error"), "artifact does not contain a complete passing suite result")
    latest = api.get("actions/runs/{}".format(run_id))
    require(all(latest.get(key) == run[key] for key in (
        "id", "run_attempt", "status", "conclusion", "head_sha", "event", "workflow_id", "path"))
        and latest.get("repository", {}).get("id") == repository_id
        and latest.get("head_repository", {}).get("id") == repository_id,
        "PR run changed while evidence was verified")
    return {"run_id": run_id, "run_attempt": attempt, "artifact_id": artifact["id"],
            "runtime_seconds": record["runtime_seconds"]}


def producer_provenance(environ, identity):
    require(environ.get("GITHUB_EVENT_NAME") == "pull_request", "only PR runs produce reusable evidence")
    event = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text())
    repository, pull = event["repository"], event["pull_request"]
    require(repository["full_name"] == environ["GITHUB_REPOSITORY"]
            and repository["id"] == int(environ["GITHUB_REPOSITORY_ID"])
            and pull["head"]["repo"]["id"] == repository["id"]
            and pull["base"]["repo"]["id"] == repository["id"]
            and pull["base"]["ref"] == "main"
            and environ["GITHUB_WORKFLOW_REF"].startswith(repository["full_name"] + "/" + WORKFLOW + "@")
            and identity["commit"] == environ["GITHUB_SHA"], "PR producer identity is unavailable")
    return {"repository": repository["full_name"], "repository_id": repository["id"],
            "workflow_path": WORKFLOW, "event": "pull_request", "pull_request": event["number"],
            "run_id": int(environ["GITHUB_RUN_ID"]), "run_attempt": int(environ["GITHUB_RUN_ATTEMPT"]),
            "head_sha": pull["head"]["sha"], "checkout_commit": identity["commit"]}


def emit(result, environ):
    if environ.get("GITHUB_OUTPUT"):
        with open(environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("evidence_written={}\n".format(str(result["evidence_written"]).lower()))
    print(json.dumps(result))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args(argv)
    environ = dict(os.environ)
    started = time.monotonic()
    try:
        environment = runtime_environment(environ)
        current = None
        try:
            current = fingerprint(environment, environ)
        except (Unavailable, OSError, subprocess.SubprocessError) as exc:
            reason = "fingerprint unavailable ({})".format(type(exc).__name__)
        else:
            reason = "fresh runtime execution required for this event"
            if (environ.get("HERDR_REUSE_RUNTIME") == "1" and environ.get("GITHUB_EVENT_NAME") == "push"
                    and environ.get("GITHUB_REF") == "refs/heads/main"):
                try:
                    proof = reusable(GitHub(environ["GITHUB_REPOSITORY"], environ.get("GH_TOKEN", "")),
                                     current, tree_identity(environment), environ)
                except (Unavailable, KeyError, TypeError, ValueError, OSError) as exc:
                    reason = str(exc) if isinstance(exc, Unavailable) else "invalid or unavailable evidence metadata"
                else:
                    emit({"reused": True, "evidence_written": False, "source": proof,
                          "elapsed_seconds": round(time.monotonic() - started, 3)}, environ)
                    return 0
        print("ci-runtime-gate: {} — running all runtime suites".format(reason), file=sys.stderr)
        run_started = time.monotonic()
        execution = subprocess.run([sys.executable, str(ROOT / "scripts/run-tests.py")], cwd=ROOT,
                                   env=environment, text=True, stdout=subprocess.PIPE)
        runtime_seconds = round(time.monotonic() - run_started, 3)
        if execution.returncode:
            print(execution.stdout, file=sys.stderr)
            emit({"reused": False, "evidence_written": False, "reason": reason,
                  "runtime_seconds": runtime_seconds, "exit_code": execution.returncode}, environ)
            return 1
        summary = json.loads(execution.stdout)
        require(summary["failed"] == 0 and summary["suites"] > 0
                and summary["passed"] == summary["suites"] and not summary.get("error"),
                "runtime driver did not return a complete success")
        written = False
        if current is not None:
            try:
                identity = tree_identity(environment)
                require(fingerprint(environment, environ) == current, "runtime inputs changed during execution")
                provenance = producer_provenance(environ, identity)
            except (Unavailable, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
                print("ci-runtime-gate: evidence not produced ({})".format(type(exc).__name__), file=sys.stderr)
            else:
                args.evidence.parent.mkdir(parents=True, exist_ok=True)
                args.evidence.write_text(json.dumps({"schema_version": SCHEMA, "provenance": provenance,
                    "fingerprint": current, "result": summary, "runtime_seconds": runtime_seconds}, sort_keys=True) + "\n")
                written = True
        emit({"reused": False, "evidence_written": written, "reason": reason, "result": summary,
              "runtime_seconds": runtime_seconds, "elapsed_seconds": round(time.monotonic() - started, 3)}, environ)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("ci-runtime-gate: {} — repair the CI environment and rerun the gate".format(type(exc).__name__), file=sys.stderr)
        print(json.dumps({"reused": False, "evidence_written": False, "error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
