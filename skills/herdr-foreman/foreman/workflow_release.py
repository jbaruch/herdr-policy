"""Verify a native release outcome and tear down only its admitted worktree.

The native release responsibility runs the existing complete release skill,
including review reading, exact-head merge and each publication. This owner
does not duplicate that reasoning or reissue uncertain GitHub writes. It
independently reads source-bound remote facts through the canonical helpers.
Local teardown uses one durable current intent and conservative Git readback.
"""

import json
import os
from pathlib import Path
import re
import subprocess

from . import policy_paths, progression_owner as authority, recovery, report_gates, supervision
from . import workflow_contract as schema, workflow_dispatch, workflow_review
from . import workflow_workspace as workspace
from .errors import StateError, UsageError


class WorkflowReleaseAdapter:
    def __init__(self, *, run=subprocess.run):
        self.run = run

    def _run(self, argv, cwd, *, allow_failure=False, quiet=False):
        try:
            result = self.run(argv, cwd=str(cwd), check=False,
                              stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        except OSError:
            raise StateError("The workflow release tool could not start; restore the selected GitHub/Git/policy tools and reconcile the current intent before retrying.", {}) from None
        if len((result.stdout or "").encode("utf-8")) > workspace.INPUT_LIMIT:
            raise StateError("Release evidence exceeded the bounded input; preserve its source for a task-local decision.", {})
        if result.returncode and not allow_failure:
            raise StateError("A canonical release tool refused or could not establish its result (exit {}); inspect that tool for this task and preserve unconfirmed channel evidence.".format(result.returncode), {})
        return result

    def _json(self, argv, cwd):
        result = self._run(argv, cwd)
        try:
            value = json.loads(result.stdout)
        except (ValueError, TypeError):
            raise StateError("The release tool returned unreadable evidence; restore its JSON contract before claiming a delivery.", {}) from None
        if not isinstance(value, dict):
            raise StateError("The release tool did not return its documented evidence object; preserve the unconfirmed outcome.", {})
        return value

    def _bundle(self, service):
        explicit = os.environ.get("HERDR_CODING_POLICY_ROOT") or None
        if explicit is not None and not Path(explicit).is_absolute():
            raise UsageError("Use an absolute coding-policy package root for the complete selected release bundle.", {})
        return policy_paths.coding_release(Path(__file__).resolve().parents[1],
            workspace.base_checkout(service.document), Path.home() / ".tessl", explicit)

    def _helper(self, bundle, name, arguments, cwd, *, json_output=True):
        script = bundle / name
        if not script.is_file():
            raise UsageError("The selected coding-policy release bundle is incomplete; repair that installation before release progression.", {})
        argv = ["python3" if script.suffix == ".py" else "bash", str(script), *map(str, arguments)]
        return self._json(argv, cwd) if json_output else self._run(argv, cwd).stdout.strip()

    def _claim(self, service, state, progress):
        job = workflow_dispatch.current_job(state, supervision.load(service.path), progress["jobs"]["release"])
        evidence, raw = workspace.capture(job["report"], limit=workspace.REPORT_LIMIT)
        member = next(row for row in supervision.load(service.path)["members"] if row["id"] == job["id"])
        if (job["status"] != "closed" or member["resolution"] is None
                or not any(row["path"] == evidence["path"] and row["sha256"] == evidence["sha256"]
                           for row in member["resolution"]["evidence"])):
            raise UsageError("Restore the native release responsibility's unchanged delivered report and closed enrollment.", {})
        return schema.claim(raw.decode("utf-8"), service.capability.task, "release", service.profile,
                            progress["head"]["commit"], service.document["acceptance"]["criteria"]), evidence

    def observe(self, service, state, task, progress):
        """Read remote/helper evidence without retaining the primary owner lock."""
        repo = service.document["repository"]
        cwd = repo["worktree"] if progress["phase"] != "cleanup" else progress["delivery"]["base_checkout"]
        if progress["phase"] == "cleanup":
            return {"state": "cleanup", "step": progress["delivery"]["cleanup_step"]}
        claim, _report = self._claim(service, state, progress)
        if claim["outcome"] != "delivered":
            raise UsageError("The native release worker has not delivered the complete release outcome; preserve its preparation evidence and recover through the same task owner.", {})
        bundle = self._bundle(service)
        pr = self._json(["gh", "api", "repos/{}/pulls/{}".format(repo["github"], claim["pull_request"])], cwd)
        if (not isinstance(pr.get("base"), dict) or not isinstance(pr.get("head"), dict)
                or not isinstance(pr["base"].get("repo"), dict) or not isinstance(pr["head"].get("repo"), dict)
                or not isinstance(pr["base"]["repo"].get("full_name"), str) or not isinstance(pr["head"]["repo"].get("full_name"), str)
                or pr["base"]["repo"]["full_name"].casefold() != repo["github"].casefold()
                or pr["head"]["repo"]["full_name"].casefold() != repo["github"].casefold()
                or pr["base"].get("ref") != repo["base_branch"] or pr["head"].get("ref") != repo["branch"]
                or pr["head"].get("sha") != progress["head"]["commit"] or pr.get("merged") is not True):
            raise UsageError("The actual PR does not prove this task's exact-head merge into its admitted repository/base; preserve the native release result for reconciliation.", {})
        schema._sha(pr.get("merge_commit_sha"), "actual merge")
        merged_at = supervision.timestamp(pr.get("merged_at"))
        if progress["phase"] == "merge":
            if workspace.inspect(service.document, task, built=True) != progress["head"]:
                raise UsageError("The writer changed after verification; preserve its new work and reconcile the actual merged source before acceptance.", {})
            expected = claim["review_evidence"]
            review_path = str(Path(service.document["artifact_directory"]) / "reviews-{}-release.json".format(progress["round"]))
            captured, raw = workspace.capture(review_path)
            if captured != expected:
                raise UsageError("Restore the release worker's unchanged complete pre-merge canonical review snapshot.", {})
            try:
                snapshot = json.loads(raw)
            except ValueError:
                raise UsageError("The release review artifact is not its canonical JSON snapshot; preserve it for owner recovery.", {}) from None
            binding = workflow_review.identity(snapshot)
            watch = snapshot.get("watch")
            if (binding["pr_number"] != claim["pull_request"] or binding["head_sha"] != progress["head"]["commit"]
                    or binding["sha256"] != claim["review_snapshot"]
                    or not isinstance(watch, dict) or watch.get("result") != "ready"):
                raise UsageError("The delivered release claim does not bind its full reading to a ready current-head canonical watcher result.", {})
            publication = claim["publication"]
            channels = service.document["publication"]
            if not channels["acr"] and publication["tag"] is not None:
                raise UsageError("A release without an ACR channel cannot claim an ACR publication tag.", {})
            if channels["tessl"] is not None:
                if publication["baseline"] is None or supervision.timestamp(publication["baseline_at"]) >= merged_at:
                    raise UsageError("Preserve the actual pre-merge Tessl baseline and its capture time; a post-merge or absent read cannot confirm this publication.", {})
            elif publication["baseline"] is not None or publication["tessl_version"] is not None:
                raise UsageError("A release without a Tessl channel cannot claim Tessl publication evidence.", {})
            issues = self._helper(bundle, "check-closing-issues.py", [*repo["github"].split("/"), claim["pull_request"], "--merged"], cwd)
            if not isinstance(issues, dict) or issues.get("verdict") != "ok":
                raise UsageError("Complete the canonical merged-issue checks before claiming task delivery.", {})
            return {"state": "merged", "merge_commit": pr["merge_commit_sha"], "claim": publication}
        if pr["merge_commit_sha"] != progress["delivery"]["merge_commit"]:
            raise UsageError("The PR's actual merge differs from the recorded delivery source; reconcile it without selecting another publisher.", {})
        channels = service.document["publication"]
        if channels["tessl"] is None and not channels["acr"]:
            if any(claim["publication"][field] is not None for field in ("publisher_run", "tag", "tessl_version")):
                raise UsageError("The native release claimed a publication outside this task's admitted channels.", {})
            return {"state": "published"}
        owner, repository = repo["github"].split("/")
        delivery = progress["delivery"]
        run = delivery["publisher_run"]
        if run is None:
            resolved = self._helper(bundle, "resolve-publish-run.sh", [owner, repository, pr["merge_commit_sha"],
                channels["workflow"], repo["base_branch"]], cwd)
            run = resolved.get("database_id")
            if type(run) is not int or run < 1 or run != claim["publication"]["publisher_run"]:
                raise UsageError("The unique source/workflow/push/ref publisher differs from the native release's run; preserve both identities for reconciliation.", {})
            self._run(["gh", "run", "watch", str(run), "--repo", repo["github"], "--exit-status"], cwd, quiet=True)
            return {"state": "publishing", "publisher_run": run}
        if type(run) is not int or run < 1 or run != claim["publication"]["publisher_run"]:
            raise UsageError("The unique source/workflow/push/ref publisher differs from the native release's run; preserve both identities for reconciliation.", {})
        if channels["tessl"] is not None and not delivery["tessl_confirmed"]:
            tessl = channels["tessl"]
            landed = delivery["tessl_version"]
            if landed is None:
                landed = self._helper(bundle, "confirm-tessl-landed.sh", [tessl["workspace"], tessl["plugin"],
                    progress["publication_baseline"], run], cwd, json_output=False)
                if not isinstance(landed, str) or re.fullmatch(r"\d+\.\d+\.\d+", landed) is None:
                    raise StateError("The canonical registry confirmation returned no actual landed version; retain the unconfirmed channel.", {})
                if landed != claim["publication"]["tessl_version"]:
                    raise UsageError("The native release report and independent canonical helper observed different landed Tessl versions; preserve both for reconciliation.", {})
                return {"state": "publishing", "tessl_version": landed}
            moderation = self._helper(bundle, "verify-moderation-cleared.sh", [tessl["workspace"], tessl["plugin"], landed], cwd)
            if not isinstance(moderation, dict) or moderation.get("ok") is not True or moderation.get("version") != landed:
                raise UsageError("The canonical moderation helper did not confirm the actual landed version.", {})
            return {"state": "publishing", "tessl_confirmed": True}
        if channels["acr"] and not delivery["acr_confirmed"]:
            package = self._json(["acr", "validate", str(repo["worktree"]), "--json"], cwd)
            result = package.get("result")
            version = result.get("version") if isinstance(result, dict) else None
            if (package.get("ok") is not True or not isinstance(result, dict) or result.get("valid") is not True
                    or not isinstance(version, str) or re.fullmatch(r"\d+\.\d+\.\d+", version) is None):
                raise UsageError("Restore the validated source ACR manifest before identifying this channel's exact release tag.", {})
            tag = "v" + version
            if claim["publication"]["tag"] != tag:
                raise UsageError("The native release tag differs from this reviewed ACR source manifest; preserve the channel as unconfirmed.", {})
            confirmed = self._helper(bundle, "verify-github-release.sh", [owner, repository, tag, run], cwd)
            if confirmed.get("ok") is not True or confirmed.get("tag") != tag:
                raise UsageError("The canonical ACR channel helper did not confirm its exact published tag/assets.", {})
            reference = self._json(["gh", "api", "repos/{}/git/ref/tags/{}".format(repo["github"], tag)], cwd)
            seen = set()
            for _ in range(8):
                target = reference.get("object")
                if not isinstance(target, dict) or target.get("type") not in ("commit", "tag"):
                    raise UsageError("The actual release tag has no supported source identity; preserve this channel as unconfirmed.", {})
                schema._sha(target.get("sha"), "release tag source")
                if target["type"] == "commit":
                    if target["sha"] != delivery["merge_commit"]:
                        raise UsageError("The actual release tag points to a different commit than this task's recorded merge; preserve its source for reconciliation.", {})
                    break
                if target["sha"] in seen:
                    raise UsageError("The annotated release tag contains a cycle; preserve the unconfirmed source.", {})
                seen.add(target["sha"])
                reference = self._json(["gh", "api", "repos/{}/git/tags/{}".format(repo["github"], target["sha"])], cwd)
            else:
                raise UsageError("The annotated release tag exceeds the bounded source lookup; retain its source for a task-local decision.", {})
            return {"state": "publishing", "tag": tag, "acr_confirmed": True}
        return {"state": "published"}

    def commit(self, service, state, task, progress, observed):
        if observed["state"] != "published":
            return self._commit(service, state, task, progress, observed)
        with report_gates.holding(service.path), supervision.effect_boundary(service.path) as supervised:
            grant = authority.current_grant(state, task["task"])
            if (grant is None or authority._binding(supervised) != grant["binding"]
                    or authority._unresumed_hold(supervised)):
                raise UsageError("The current operator hold or foreman binding prevents task acceptance; preserve the unaccepted delivery and resume through its recorded owner.", {})
            authority.verify_foreman(service.path, service.client, native_only=True, supervised=supervised)
            report_gates.require_no_verdict_gate(service.path, task["task"], state["recovery"]["dispatches"])
            for identifier in progress["jobs"].values():
                job = workflow_dispatch.current_job(state, supervised, identifier)
                report_gates.require_clear(service.path, job["report"], True)
            return self._commit(service, state, task, progress, observed)

    def _commit(self, service, state, task, progress, observed):
        if observed["state"] == "merged":
            publication = observed["claim"]
            progress["delivery"]["merge_commit"] = observed["merge_commit"]
            progress.update(phase="publish", publication_baseline=publication["baseline"], at=service.clock())
        elif observed["state"] in ("publishing", "published"):
            progress["delivery"].update({key: value for key, value in observed.items() if key != "state"})
            if observed["state"] == "publishing":
                progress["at"] = service.clock()
                service._save(state)
                return service._view(progress, "advanced")
            if service.document["acceptance"]["kind"] != "merge":
                service._save(state)
                return service._exception(state, "actual_acceptance_evidence_required", [str(service.path)],
                    ("verify_deployment_or_operator_acceptance", "return_authority"))
            progress["delivery"]["accepted"] = True
            progress.update(phase="cleanup", at=service.clock())
        elif observed["state"] == "cleanup":
            return self._prepare_cleanup(service, state, task, progress)
        else:
            raise UsageError("Restore the supported source-bound release observation before committing task progress.", {})
        service._save(state)
        return service._view(progress, "advanced")

    def _cleanup_readback(self, service, progress):
        repo, delivery = service.document["repository"], progress["delivery"]
        base, step = delivery["base_checkout"], delivery["cleanup_step"]
        def git(*arguments, allow_failure=False):
            return self._run(["git", "--no-pager", "-C", base, *arguments], base, allow_failure=allow_failure)
        if workspace.origin_identity(git("remote", "get-url", "origin").stdout.strip()) != repo["github"]:
            raise UsageError("The cleanup base's actual origin changed; preserve this task's remaining local work.", {})
        workspace.verify_origin(base, repo["github"])
        if (Path(base).resolve() != Path(base)
                or Path(git("rev-parse", "--show-toplevel").stdout.strip()).resolve() != Path(base)):
            raise UsageError("The cleanup base moved or became an alias; preserve its current owner instead of mutating a substitute checkout.", {})
        if step == 0:
            source = git("rev-parse", "--verify", "--quiet", delivery["merge_commit"] + "^{commit}", allow_failure=True)
            remote = git("rev-parse", "--verify", "--quiet", "refs/remotes/origin/" + repo["base_branch"], allow_failure=True)
            if source.returncode == 1 or remote.returncode == 1:
                return False
            if source.returncode or remote.returncode:
                raise StateError("Cannot inspect cleanup source refs; preserve the current task intent and repair Git visibility.", {})
            ancestry = git("merge-base", "--is-ancestor", delivery["merge_commit"], remote.stdout.strip(), allow_failure=True)
            if ancestry.returncode not in (0, 1):
                raise StateError("Cannot prove the fetched default source; retain the cleanup intent until Git evidence is readable.", {})
            return ancestry.returncode == 0
        if step < 5:
            ancestry = git("merge-base", "--is-ancestor", delivery["merge_commit"], "refs/remotes/origin/" + repo["base_branch"], allow_failure=True)
            if ancestry.returncode:
                raise UsageError("The fetched default no longer proves this merged source; preserve remaining task branches and reconcile before teardown.", {})
        if 2 <= step < 5:
            for revision in (delivery["merge_commit"], progress["head"]["commit"]):
                if git("merge-base", "--is-ancestor", revision, "HEAD", allow_failure=True).returncode:
                    raise UsageError("The base checkout does not retain the actual reviewed and merged source; preserve the task's remaining work.", {})
        if step == 1:
            if (git("branch", "--show-current").stdout.strip() != repo["base_branch"]
                    or git("status", "--porcelain=v1", "--untracked-files=all").stdout):
                raise UsageError("The base checkout has other selected or uncommitted work; preserve it before this task's cleanup.", {})
            return git("rev-parse", "HEAD").stdout == git("rev-parse", "refs/remotes/origin/" + repo["base_branch"]).stdout
        if step == 2:
            writer = Path(repo["worktree"])
            if writer.is_symlink():
                raise UsageError("The admitted writer became a link; preserve it for its actual owner instead of removing another path.", {})
            if writer.exists():
                return False
            if "worktree " + str(writer) + "\n" in git("worktree", "list", "--porcelain").stdout:
                raise UsageError("The task writer is absent but its registration remains; reconcile that interrupted teardown before deleting its branch.", {})
            return True
        if step == 3:
            branch = git("show-ref", "--verify", "--quiet", "refs/heads/" + repo["branch"], allow_failure=True)
            if branch.returncode not in (0, 1):
                raise StateError("Cannot inspect the task's local branch; preserve cleanup as unconfirmed.", {})
            return branch.returncode == 1
        if step == 4:
            branch = git("ls-remote", "--exit-code", "--heads", "origin", "refs/heads/" + repo["branch"], allow_failure=True)
            if branch.returncode == 2:
                return True
            if branch.returncode or branch.stdout.strip() != progress["head"]["commit"] + "\trefs/heads/" + repo["branch"]:
                raise UsageError("The remote task branch is unreachable or changed since review; preserve it and reconcile before deletion.", {})
            return False
        return True

    def _prepare_cleanup(self, service, state, task, progress):
        delivery, repo = progress["delivery"], service.document["repository"]
        if not delivery["accepted"]:
            raise UsageError("Complete actual acceptance and every selected publication before task teardown.", {})
        step = delivery["cleanup_step"]
        if step == 5:
            recovery.close_task(state["recovery"], state["assignments"], {"task": task["task"], "outcome": "merged",
                "evidence": "https://github.com/{}/pull/{}#{}".format(repo["github"], delivery["pull_request"], delivery["merge_commit"])}, service.clock())
            progress.update(phase="complete", at=service.clock())
            service._save(state)
            return service._view(progress, "complete")
        if self._cleanup_readback(service, progress):
            delivery["cleanup_step"] += 1
            progress["at"] = service.clock()
            service._save(state)
            return service._view(progress, "advanced")
        service._intent(progress, "cleanup")
        progress["pending"]["id"] += "-" + str(step)
        progress["pending"]["argv"] = self._cleanup_commands(service, progress)[step]
        self._validate_cleanup_target(service, task, progress)
        service._save(state)
        return service._view(progress, "prepared")

    @staticmethod
    def _cleanup_commands(service, progress):
        repo, delivery = service.document["repository"], progress["delivery"]
        base = delivery["base_checkout"]
        return [
            ["git", "-C", base, "fetch", "origin", repo["base_branch"]],
            ["git", "-C", base, "merge", "--ff-only", "refs/remotes/origin/" + repo["base_branch"]],
            ["git", "-C", base, "worktree", "remove", repo["worktree"]],
            ["git", "-C", base, "branch", "-d", repo["branch"]],
            ["git", "-C", base, "push", "origin", "--force-with-lease=refs/heads/{}:{}".format(repo["branch"], progress["head"]["commit"]),
             ":refs/heads/" + repo["branch"]]]
    def _validate_cleanup_target(self, service, task, progress):
        repo, delivery = service.document["repository"], progress["delivery"]
        step, base = delivery["cleanup_step"], delivery["base_checkout"]
        if step == 2 and workspace.inspect(service.document, task, built=True) != progress["head"]:
            raise UsageError("The writer has new work after release; preserve it before task-local teardown.", {})
        if step == 3:
            tip = self._run(["git", "-C", base, "rev-parse", "refs/heads/" + repo["branch"]], base).stdout.strip()
            if tip != progress["head"]["commit"]:
                raise UsageError("The local branch changed after release; preserve it instead of deleting another contribution.", {})

    def resume_cleanup(self, service, state, task, progress):
        # These operations are conservative/idempotent and read back their
        # exact target before continuation. No worker prompt or remote merge
        # is retried here. Changed/unknown refs keep the original intent.
        intent = progress["pending"]
        step = progress["delivery"]["cleanup_step"]
        if step >= 5 or intent["argv"] != self._cleanup_commands(service, progress)[step]:
            raise UsageError("The pending cleanup arguments differ from this task's exact current target; preserve the intent instead of executing a substituted command.", {})
        if self._cleanup_readback(service, progress):
            progress["delivery"]["cleanup_step"] += 1
            progress.update(pending=None, at=service.clock())
            service._save(state)
            return service._view(progress, "advanced")
        with service.capability.workflow_operation(state, "cleanup", before_effect=lambda: service._before_effect(state)):
            grant = authority.current_grant(state, task["task"])
            assert grant is not None
            expected = grant["binding"]
            with supervision.effect_boundary(service.path) as current:
                if (authority._binding(current) != expected or authority._unresumed_hold(current)
                        or os.environ.get("HERDR_ENV") != current["binding"]["identity"].get("herdr_env")):
                    raise UsageError("A current hold, changed binding or native context prevents cleanup; preserve this task's intent.", {})
                service.capability.lease.require_current()
                self._validate_cleanup_target(service, task, progress)
                service._before_effect(state)
                self._run(intent["argv"], progress["delivery"]["base_checkout"])
        # Re-enter the same exact postcondition on the next tick.
        return service._view(progress, "effect_recorded")
