#!/usr/bin/env bash
# Execute only the installed observer package; stdout is its JSON result.
set -euo pipefail

main() {
  local skill_dir skill_src
  case "${BASH_SOURCE[0]}" in
    */*) skill_src="${BASH_SOURCE[0]%/*}" ;;
    *) skill_src=. ;;
  esac
  skill_dir="$(CDPATH='' cd -- "$skill_src" && pwd -P && printf x)"
  skill_dir="${skill_dir%x}"
  skill_dir="${skill_dir%$'\n'}"
  if ! command -v python3 >/dev/null 2>&1; then
    echo 'herdr-observer: install Python 3.11+ before starting observation' >&2
    return 1
  fi
  exec python3 -B -I "$skill_dir/observer.py" "$@"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
