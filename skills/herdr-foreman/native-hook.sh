#!/usr/bin/env bash
# Dispatch a native Herdr hook from a Tessl package or an ACR native hook copy.
# argv: reset-input|supervision-stop|session-start. stdin/stdout belong to the selected owner.
# Standalone sessions return silently before checking team prerequisites.
# Native owner failures retain the existing reset-block / Stop-diagnostic forms.
set -euo pipefail

hook_failure() {
  if [[ "$1" == reset-input ]]; then
    printf '%s\n' '{"decision":"block","reason":"Restore the Herdr hook installation and Python before submitting this prompt."}'
  elif [[ "$1" == supervision-stop ]]; then
    echo 'herdr-supervision-stop: restore the Herdr hook installation and Python to enable the native supervision gate' >&2
  else
    echo 'herdr-session-start: restore the Herdr hook installation and Python to enable startup status' >&2
  fi
}

main() {
  local event="${1:-}" module src here skill rc=0
  case "$event" in
    reset-input) module=foreman.reset_input_hook ;;
    supervision-stop) module=foreman.supervision_hook ;;
    session-start) module=foreman.session_start_hook ;;
    *) echo 'usage: native-hook.sh reset-input|supervision-stop|session-start' >&2; return 2 ;;
  esac
  if [[ "$event" != session-start && -z "${HERDR_ENV+x}" ]]; then
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    hook_failure "$event"
    return 0
  fi
  src="${BASH_SOURCE[0]}"
  case "$src" in
    */*) here="${src%/*}" ;;
    *) here=. ;;
  esac
  if ! here="$(CDPATH='' cd -- "$here" && pwd -P && printf x)"; then
    hook_failure "$event"
    return 0
  fi
  here="${here%x}"
  here="${here%$'\n'}"
  case "${here##*/}" in
    herdr-foreman|acr__jbaruch__herdr-policy__herdr-foreman) skill="$here" ;;
    *) skill="" ;;
  esac
  if [[ -z "$skill" ]]; then
    # ACR rebases this owned skill reference for the selected native adapter.
    # Its hook lives at <project>/<agent>/hooks/<artifact>/native-hook.sh.
    local runtime=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman
    skill="${here}/../../../${runtime}"
  fi
  if ! skill="$(CDPATH='' cd -- "$skill" && pwd -P && printf x)"; then
    hook_failure "$event"
    return 0
  fi
  skill="${skill%x}"
  skill="${skill%$'\n'}"
  if ! cd -- "$skill"; then
    hook_failure "$event"
    return 0
  fi
  # Do not load checkout modules or an inherited Python import path.
  PYTHONPATH="$skill" PYTHONDONTWRITEBYTECODE=1 \
    python3 -s -m "$module" || rc=$?
  if (( rc != 0 )); then
    hook_failure "$event"
  fi
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
