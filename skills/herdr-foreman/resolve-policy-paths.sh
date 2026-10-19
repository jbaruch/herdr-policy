#!/usr/bin/env bash
# Resolve readable inputs for worker briefs from the executing installation.
# argv: <absolute-shared-checkout> [absolute-global-tessl-root]
# stdout: one JSON object with POLICY_INDEX, RELEASE_SKILL, TEAM_OPERATION.
# stderr: actionable failure; stdout empty on failure. Exit 0 success, 1 usage,
# 2 missing interpreter, installation or inputs. No writes or network calls.
set -euo pipefail

main() {
  if (( $# < 1 || $# > 2 )); then
    echo 'resolve-policy-paths: usage: resolve-policy-paths.sh <absolute-shared-checkout> [absolute-global-tessl-root]' >&2
    return 1
  fi
  local global_root="${2:-$HOME/.tessl}"
  if [[ "$1" != /* || ! -d "$1" || "$global_root" != /* || "$1$global_root" == *[[:cntrl:]]* ]]; then
    echo 'resolve-policy-paths: pass an existing absolute shared checkout and an absolute global Tessl root' >&2
    return 1
  fi
  local src here
  case "${BASH_SOURCE[0]}" in
    */*) src="${BASH_SOURCE[0]%/*}" ;;
    *) src=. ;;
  esac
  if ! here="$(CDPATH='' cd -- "$src" && pwd -P && printf x)"; then
    echo 'resolve-policy-paths: cannot enter the installed skill — repair its directory access' >&2
    return 2
  fi
  here="${here%x}"
  here="${here%$'\n'}"
  if ! command -v python3 >/dev/null 2>&1; then
    echo 'resolve-policy-paths: install Python 3.11+ before composing briefs' >&2
    return 2
  fi
  PYTHONPATH='' PYTHONDONTWRITEBYTECODE=1 python3 -s "$here/policy-paths.py" brief-inputs \
    --shared "$1" --global-tessl "$global_root"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
