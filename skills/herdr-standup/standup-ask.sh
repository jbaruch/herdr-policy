#!/usr/bin/env bash
# Check one worker's readiness for a standup without sending unsafe input.
#
# Herdr 0.9.2's protocol-22 AgentPromptParams has no readiness precondition.
# A read followed by agent prompt cannot prove the worker stayed idle. This
# entrypoint retains its readiness/path/width diagnostics but refuses delivery
# with exit 5 until a tested atomic transport exists. Use the round log for the
# row; never fall back to an unguarded prompt or direct pane input.
#
# Contract:
#   argv  : <agent-name> <report-path>
#           report-path must be absolute; checked without writing a report.
#   stdout: one JSON object on exits 3, 4 and 5 —
#           {"agent":"<n>","report_path":"<p>","state":"<s>","sent":false}
#           exit 4 adds "pane_width" and "needed" (columns) with sent false.
#   stderr: diagnostics only.
#   exit  : 1 precondition unmet (usage, relative, over-long or control-character
#             path, not inside Herdr,
#             `herdr`, `jq` or the sibling foreman.sh absent),
#           2 a herdr failure, an unreadable `agent get` payload, or a failed
#             or unreadable `foreman marker-fit` measurement,
#           3 the worker is not idle or done at the first read, at the
#             measurement, or at the last read just before the send — nothing
#             was sent. A standup
#             never interrupts a turn (`skills/herdr-foreman/references/team-operation.md`
#             Dispatch Safety),
#           4 the worker's live pane is too narrow for its `REPORT: <path>`
#             line — nothing was sent. A wrapped marker is one the wait can
#             never confirm.
#           5 readiness was observed, but atomic readiness-guarded delivery is
#             unavailable; reason=atomic_prompt_unavailable, nothing sent.
#   env   : HERDR_BIN overrides the herdr binary; the tests point it at a fake.
#           It reaches `foreman marker-fit` as --herdr-bin, and PY_BIN passes
#           through to the foreman launcher. marker-fit reads no foreman home.
#           STANDUP_REPORT_PATH_MAX_COLS overrides the report path length
#           limit; a non-integer or zero value is a precondition failure.
set -euo pipefail

HERDR_BIN="${HERDR_BIN:-herdr}"

# States that may receive a message. Anything else is left alone.
READY_STATES="idle done"
# Longest report path the prompt may name; the same coarse bound
# compose-briefs.sh applies to a brief's REPORT. It rejects hopeless paths
# before Herdr is touched and never proves fit: the worker's live pane width
# decides that, measured by `foreman marker-fit` against the fit rule in
# skills/herdr-foreman/foreman/report_delivery.py (`marker_columns`).
STANDUP_REPORT_PATH_MAX_COLS="${STANDUP_REPORT_PATH_MAX_COLS:-100}"

# Command substitution strips every trailing newline, so the script directory
# never passes through one bare: parameter expansion derives it (#487), and a
# sentinel carries `pwd` across the strip (#466).
case "${BASH_SOURCE[0]}" in
  */*) _skill_src="${BASH_SOURCE[0]%/*}" ;;
  *) _skill_src=. ;;
esac
if ! SKILL_DIR="$(CDPATH='' cd -- "${_skill_src:-/}" && pwd && printf x)"; then
  echo "standup-ask: cannot enter the script directory ${_skill_src:-/} — restore read and search access to the plugin directory, or reinstall the plugin, then re-run" >&2
  exit 1
fi
SKILL_DIR="${SKILL_DIR%x}"
SKILL_DIR="${SKILL_DIR%$'\n'}"
FOREMAN_SKILL=herdr-foreman
if [[ "${SKILL_DIR##*/}" == acr__jbaruch__herdr-policy__herdr-standup ]]; then
  FOREMAN_SKILL=acr__jbaruch__herdr-policy__herdr-foreman
fi
FOREMAN="${SKILL_DIR}/../${FOREMAN_SKILL}/foreman.sh"

ERRFILE=""
AGENT=""
REPORT_PATH=""

warn() { printf 'standup-ask: %s\n' "$1" >&2; }

cleanup() {
  if [[ -n "$ERRFILE" ]] && ! rm -f "$ERRFILE"; then
    warn "could not remove temp file ${ERRFILE} — remove it by hand"
  fi
  return 0
}

# True when the text holds a character that breaks a one-row marker: a
# Unicode Cc control (C0 and DEL through the C locale's [[:cntrl:]], C1
# U+0080..U+009F by its UTF-8 bytes C2 80..9F) or the line and paragraph
# separators U+2028/U+2029 (E2 80 A8/A9). Bytewise under LC_ALL=C, so the
# answer never depends on the caller's locale. Mirrors `cmd_marker_fit`.
has_control() { # <text>
  local LC_ALL=C
  [[ "$1" == *[[:cntrl:]]* || "$1" == *$'\xc2'[$'\x80'-$'\x9f']* \
     || "$1" == *$'\xe2\x80'[$'\xa8'$'\xa9']* ]]
}

# Read the worker's live status into READ_STATE. Returns 2 on a herdr failure
# or an unreadable payload, with the diagnostic already on stderr.
READ_STATE=""
read_state() {
  local raw rc=0
  READ_STATE=""
  raw="$("$HERDR_BIN" agent get "$AGENT" 2>"$ERRFILE")" || rc=$?
  if (( rc != 0 )); then
    warn "herdr agent get failed (exit ${rc}) — inspect herdr agent list and restore the selected owner before retrying; nothing was sent"
    return 2
  fi
  rc=0
  READ_STATE="$(printf '%s' "$raw" | jq -r '
    if (.result.agent | type) != "object" then
      error("herdr agent get payload has no .result.agent object")
    else
      .result.agent.agent_status as $status |
      if (["idle", "working", "blocked", "done", "unknown"] | index($status)) == null
      then "unknown" else $status end
    end' 2>"$ERRFILE")" || rc=$?
  if (( rc != 0 )); then
    warn "could not read the state from herdr agent get (jq exit ${rc}) — restore its supported JSON response; nothing was sent"
    return 2
  fi
  return 0
}

main() {
  if (( $# != 2 )); then
    warn "usage: standup-ask.sh <agent-name> <report-path>"
    return 1
  fi
  AGENT="$1"
  REPORT_PATH="$2"

  if [[ "$REPORT_PATH" != /* ]]; then
    warn "report path '${REPORT_PATH}' is relative — pass an absolute path; the worker resolves it in its own working directory, not yours"
    return 1
  fi
  if has_control "$REPORT_PATH"; then
    warn "report path contains a control character — the worker's \`REPORT: <path>\` line must be one printable row; pass a plain absolute path"
    return 1
  fi
  case "$STANDUP_REPORT_PATH_MAX_COLS" in
    ''|*[!0-9]*)
      warn "STANDUP_REPORT_PATH_MAX_COLS must be a positive integer, got '${STANDUP_REPORT_PATH_MAX_COLS}' — unset it to use the script's default"
      return 1
      ;;
  esac
  if (( 10#$STANDUP_REPORT_PATH_MAX_COLS < 1 )); then
    warn "STANDUP_REPORT_PATH_MAX_COLS must be a positive integer, got '${STANDUP_REPORT_PATH_MAX_COLS}' — unset it to use the script's default"
    return 1
  fi
  # Normalize to decimal once, so a validated `08` is not reparsed as octal.
  STANDUP_REPORT_PATH_MAX_COLS=$(( 10#$STANDUP_REPORT_PATH_MAX_COLS ))
  if (( ${#REPORT_PATH} > STANDUP_REPORT_PATH_MAX_COLS )); then
    warn "report path is ${#REPORT_PATH} characters; the limit is ${STANDUP_REPORT_PATH_MAX_COLS}, a coarse bound on the worker's \`REPORT: <path>\` line (the live pane width is checked before sending) — use a shorter reports directory (e.g. one under \$HOME/.local/state)"
    return 1
  fi
  if [[ "${HERDR_ENV:-}" != "1" ]]; then
    warn "not running inside Herdr (HERDR_ENV='${HERDR_ENV:-}') — run the standup from a pane Herdr manages"
    return 1
  fi
  local dep
  for dep in "$HERDR_BIN" jq; do
    if ! command -v "$dep" >/dev/null 2>&1; then
      warn "'${dep}' not found on PATH — install it to run the standup"
      return 1
    fi
  done
  if [[ ! -f "$FOREMAN" || ! -r "$FOREMAN" ]]; then
    warn "foreman.sh not found at ${FOREMAN} — herdr-standup runs beside the herdr-foreman skill; install both with \`tessl install jbaruch/herdr-policy\`"
    return 1
  fi

  ERRFILE="$(mktemp)"
  trap cleanup EXIT

  local rc=0 state
  if ! read_state; then
    return 2
  fi
  state="$READ_STATE"

  # A standup is worth less than somebody's turn. A worker that is not ready
  # keeps working, and the foreman fills its row from the round log instead.
  if [[ " $READY_STATES " != *" $state "* ]]; then
    warn "${AGENT} is '${state}' — not asking. Fill its row from the round log."
    jq -n --arg a "$AGENT" --arg p "$REPORT_PATH" --arg s "$state" \
      '{agent: $a, report_path: $p, state: $s, sent: false}'
    return 3
  fi

  # The live pane decides whether the worker's marker stays on one row; the
  # fit rule lives in the foreman package, never restated here.
  local fit verdict width needed fits
  rc=0
  fit="$(bash "$FOREMAN" marker-fit --herdr-bin "$HERDR_BIN" --agent "$AGENT" --report "$REPORT_PATH" 2>"$ERRFILE")" || rc=$?
  if (( rc != 0 )); then
    warn "foreman marker-fit failed (exit ${rc}) — inspect that owner's measurement before retrying; nothing was sent"
    return 2
  fi
  rc=0
  verdict="$(printf '%s' "$fit" | jq -r '
    if (.fits | type) != "boolean" or (.pane_width | type) != "number" or (.needed | type) != "number"
       or (.agent_status | type) != "string" or (.agent_status | test("^[a-z_]+$") | not) then
      error("marker-fit payload lacks fits, pane_width, needed or agent_status")
    else
      "\(.fits) \(.pane_width) \(.needed) \(.agent_status)"
    end' 2>"$ERRFILE")" || rc=$?
  if (( rc != 0 )); then
    warn "could not read the foreman marker-fit verdict (jq exit ${rc}) — restore its supported JSON response; nothing was sent"
    return 2
  fi
  local fresh
  read -r fits width needed fresh <<<"$verdict"
  case "$fresh" in idle|working|blocked|done|unknown) ;; *) fresh=unknown ;; esac
  # The measurement read the worker again. A turn that started since the
  # first read wins over the ask, exactly as a busy first read does.
  if [[ " $READY_STATES " != *" $fresh "* ]]; then
    warn "${AGENT} became '${fresh}' while its pane was measured — not asking. Fill its row from the round log."
    jq -n --arg a "$AGENT" --arg p "$REPORT_PATH" --arg s "$fresh" \
      '{agent: $a, report_path: $p, state: $s, sent: false}'
    return 3
  fi
  if [[ "$fits" != "true" ]]; then
    warn "${AGENT}'s pane is ${width} columns; its \`REPORT: <path>\` line needs ${needed}, so it would wrap and the wait could never confirm it. Nothing was sent — widen the pane or use a shorter reports directory, then ask again."
    jq -n --arg a "$AGENT" --arg p "$REPORT_PATH" --arg s "$state" \
      --argjson w "$width" --argjson n "$needed" \
      '{agent: $a, report_path: $p, state: $s, sent: false, pane_width: $w, needed: $n}'
    return 4
  fi

  # Preserve the final readiness diagnostic. Another read cannot turn it into
  # atomic delivery authority; even three idle reads authorize no prompt.
  if ! read_state; then
    warn "nothing was sent"
    return 2
  fi
  if [[ " $READY_STATES " != *" $READ_STATE "* ]]; then
    warn "${AGENT} became '${READ_STATE}' just before the send — not asking. Fill its row from the round log."
    jq -n --arg a "$AGENT" --arg p "$REPORT_PATH" --arg s "$READ_STATE" \
      '{agent: $a, report_path: $p, state: $s, sent: false}'
    return 3
  fi

  warn "Atomic readiness-guarded standup delivery is unavailable — fill the row from the round log. Do not retry through agent prompt or pane input."
  jq -n --arg a "$AGENT" --arg p "$REPORT_PATH" --arg s "$state" \
    '{agent: $a, report_path: $p, state: $s, sent: false, reason: "atomic_prompt_unavailable"}'
  return 5
}

# Entry-point guard (rules/file-hygiene.md Standalone Scripts).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
