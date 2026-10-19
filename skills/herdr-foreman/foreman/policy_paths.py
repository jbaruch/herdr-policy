"""Locate the single coding-policy release bundle used by Herdr helpers.

Tessl keeps a package tree intact. ACR realizes each skill as a complete,
namespaced directory. Resolve the release skill as a unit; never assemble
its helpers from different installations or execute code during discovery.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .errors import ForemanError, UsageError


NATIVE_FOREMAN = "acr__jbaruch__herdr-policy__herdr-foreman"
NATIVE_RELEASE = "acr__jbaruch__coding-policy__release"
RELEASE_FILES = (
    "SKILL.md",
    "origin-repo.py",
    "lib/bounded-run.sh",
    "lib/prune-worktrees.sh",
    "lib/prune-remote-branches.sh",
    "lib/prune_result.py",
)


def refuse_combined_policy(skill_dir, shared, global_tessl):
    """An unregistered source helper is distinct from installed legacy hooks."""
    roots = {shared / ".tessl/plugins/jbaruch/coding-policy",
             global_tessl / "plugins/jbaruch/coding-policy"}
    package = skill_dir.parent.parent
    if (package.name == "herdr-policy" and package.parent.name == "jbaruch"
            and package.parent.parent.name == "plugins" and package.parent.parent.parent.name == ".tessl"):
        roots.add(package.parent / "coding-policy")
    conflicts = []
    for root in sorted(roots):
        for name in ("herdr-foreman", "herdr-standup"):
            try:
                (root / "skills" / name).lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise UsageError("Cannot verify installed policy ownership — restore access to local/global plugin trees before Herdr work") from None
            conflicts.append(str(root))
            break
    if conflicts:
        raise UsageError(
            "A combined coding-policy team runtime is still installed — keep teams stopped, reconcile active work, "
            "then upgrade to reduced coding-policy before using herdr-policy; preserve owner records and unknown deliveries",
            {"legacy_packages": conflicts},
        )


def coding_release(skill_dir, shared, global_tessl, explicit_root=None):
    """Return one complete release skill, preferring the executing installation.

    An explicit package root is exclusive. Otherwise use the same ACR native
    skill host, the peer Tessl package, project-local Tessl, then global Tessl.
    An existing but incomplete selection is an installation error, not a
    license to silently combine it with another version.
    """
    skill_dir = Path(skill_dir).resolve()
    shared = Path(shared).resolve()
    global_tessl = Path(global_tessl).resolve()
    refuse_combined_policy(skill_dir, shared, global_tessl)
    if explicit_root is not None:
        candidates = [Path(explicit_root).resolve() / "skills/release"]
    else:
        candidates = []
        if skill_dir.name == NATIVE_FOREMAN:
            candidates.append(skill_dir.parent / NATIVE_RELEASE)
        else:
            package = skill_dir.parent.parent
            candidates.append(package.parent / "coding-policy/skills/release")
        candidates.extend((
            shared / ".tessl/plugins/jbaruch/coding-policy/skills/release",
            global_tessl / "plugins/jbaruch/coding-policy/skills/release",
        ))

    visited = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in visited:
            continue
        visited.add(candidate)
        if not candidate.exists():
            continue
        missing = [name for name in RELEASE_FILES if not (candidate / name).is_file()]
        if missing:
            raise UsageError(
                "coding-policy release helpers are incomplete at {} — install the "
                "compatible coding-policy package before running Herdr cleanup".format(candidate),
                {"release_skill": str(candidate), "missing": missing},
            )
        return candidate
    raise UsageError(
        "coding-policy release helpers were not found — install the compatible "
        "coding-policy package alongside herdr-policy, or pass its package root",
        {"searched": [str(path) for path in candidates]},
    )


def brief_inputs(skill_dir, shared, global_tessl, explicit_root=None):
    """Resolve the executing team contract and the selected general policy."""
    skill_dir, shared = Path(skill_dir).resolve(), Path(shared).resolve()
    release = coding_release(skill_dir, shared, global_tessl, explicit_root)
    indexes = [shared / ".tessl/RULES.md", Path(global_tessl) / "RULES.md"]
    if release.name == NATIVE_RELEASE:
        # Native adapters may host rules in CLAUDE.md, an imported instruction
        # file, or scoped Cursor rules. A pre-existing AGENTS.md proves none of
        # those. Use the selected general package's authored native router.
        indexes = [release / "POLICY.md"]
    policy = next((path.resolve() for path in indexes if path.is_file() and path.stat().st_size), None)
    team = skill_dir / "references/team-operation.md"
    if policy is None or not team.is_file() or not team.stat().st_size:
        raise UsageError("Policy inputs are missing — repair the selected coding-policy and herdr-policy "
                         "installations before composing briefs", {"indexes": [str(p) for p in indexes],
                                                                   "team_operation": str(team)})
    return {"POLICY_INDEX": str(policy), "RELEASE_SKILL": str(release / "SKILL.md"),
            "TEAM_OPERATION": str(team)}


def main(argv=None):
    """Read paths or current installation identity; never execute team work."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("release", "brief-inputs", "identity"))
    parser.add_argument("--shared", type=Path, default=Path.cwd())
    parser.add_argument("--global-tessl", type=Path, default=Path.home() / ".tessl")
    parser.add_argument("--coding-policy-root", type=Path,
                        default=os.environ.get("HERDR_CODING_POLICY_ROOT") or None)
    args = parser.parse_args(argv)
    if not args.coding_policy_root:
        args.coding_policy_root = None
    skill = Path(__file__).resolve().parents[1]
    try:
        if not args.shared.is_absolute() or not args.shared.is_dir() or not args.global_tessl.is_absolute():
            raise UsageError("Pass an existing absolute shared checkout and an absolute global Tessl root")
        if args.coding_policy_root is not None and not Path(args.coding_policy_root).is_absolute():
            raise UsageError("HERDR_CODING_POLICY_ROOT must be an absolute package root")
        if args.operation == "identity":
            from .native_policy import executing_policy_root
            from .remote_owner import loaded_policy
            root = executing_policy_root()
            version, digest = loaded_policy(root)
            result = {"schema_version": 1, "policy_root": str(root), "version": version, "digest": digest,
                      "authorizes_dispatch": False}
        elif args.operation == "release":
            result = {"release_skill": str(coding_release(skill, args.shared, args.global_tessl,
                                                         args.coding_policy_root))}
        else:
            result = brief_inputs(skill, args.shared, args.global_tessl, args.coding_policy_root)
    except (OSError, ForemanError) as exc:
        print("policy-paths: {} — repair the selected installation before retrying".format(exc), file=sys.stderr)
        if isinstance(exc, ForemanError) and exc.details:
            print(json.dumps(exc.details), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0
