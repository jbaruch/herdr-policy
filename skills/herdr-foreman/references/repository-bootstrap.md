# New Repository Base

This is an owner setup operation for an explicitly authorized new repository,
before ordinary worktree provisioning. It creates no implementation content.

## Preconditions

1. The current user authorization covers creating and initializing this named
   repository. Use that authority; do not add another confirmation when it exists.
2. Select its existing shared clone and actual intended default branch. Preserve
   local files and every existing remote ref. No guessed or synthetic base SHA.
3. Use only the co-shipped bootstrap below. Its `--initialize-empty` flag encodes
   that existing setup authority; the script still rechecks the real remote.
4. Any implementation, verification and release use normal task owners afterward.
   The bootstrap receipt grants none of those responsibilities.

Every other repository edit remains developer work under the normal contract.

## Establish the Base

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
python3 "$HS/bootstrap-repository.py" --repo "<shared-clone>" --branch "<default-branch>" --initialize-empty
```

`skills/herdr-foreman/bootstrap-repository.py` owns remote checks, empty-commit
construction, race handling and push readback. Existing history takes the ordinary
base route. Conflicting origin targets and unreadable refs are refused; neither
proves an empty repository. No existing branch is forced and no shared files or
local branches are changed.

Exit 0 returns a schema-1 receipt with the actual `base_revision`, repository,
branch, creation status and ordinary-provisioning continuation. Use that real
remote commit with the normal worktree provisioner, then proceed with reviewed
development. It is not evidence that implementation, review or release occurred.

Exit 1 is an unmet bootstrap precondition; exit 2 is a tool or uncertain-effect
failure. Preserve an `attempted_base_revision` from an uncertain push in the
current task's existing evidence and obtain actual remote readback before
continuing. Do not replace the repository, create another owner, invent a base
or force a branch. Continue independent authorized lanes while this one recovers.
