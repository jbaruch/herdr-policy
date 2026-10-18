#!/usr/bin/env bash
# Install the published extraction baseline outside the checkout for CI tests.
# argv: absolute private install root. stdout: {"policy_root":"..."}; stderr:
# Tessl diagnostics. Exit 0 installed, 2 invalid root or failed installation.
set -euo pipefail

main() {
  if (( $# != 1 )) || [[ "$1" != /* ]]; then
    echo 'usage: install-test-policy.sh <absolute-private-install-root>' >&2
    return 2
  fi
  mkdir -p "$1" || return 2
  # This immutable monolith is the relocation oracle. Review monthly alongside
  # the extracted pair; change the baseline only in a dedicated compatibility PR.
  if ! (cd -- "$1" && tessl install jbaruch/coding-policy@0.3.406 --agent codex --yes --strict --accept-warnings >&2); then
    echo 'install-test-policy: restore Tessl registry access before running the suites' >&2
    return 2
  fi
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path
print(json.dumps({"policy_root": str(Path(sys.argv[1]) / ".tessl/plugins/jbaruch/coding-policy")}))
PY
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
