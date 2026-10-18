# Team Release Integration

This contract governs verified Herdr team rounds. General review, release and publication requirements come from the selected coding-policy release skill.

## Team Weighing


With `HERDR_ENV` set, the release worker asks nobody and nominates nothing:

1. Report the blocking findings to the foreman under `## BLOCKED`, with the JSON `dismiss-ruled-review.sh` prints without `--ruling`.
2. The foreman nominates from them; the pinned judge weighs the nominations, and its weighing report is the ruling file.
3. The next release brief names that report, the follow-up issue and the task. Run the team-round invocation from Step 6, with `--task`; the script binds the report to the judge's weighing through `foreman verify-ruling`.

The question and the standalone ruling file below do not apply in a team round.

The generic `dismiss-ruled-review.sh` consumes the report through the optional team-ruling interface. Its owner verification must succeed before the parsed bytes can authorize dismissal. A missing Herdr package or unknown verification result never degrades to an operator ruling.

## Review Exceptions



- A weighing asks whether fixing a finding is worth its cost, never whether the finding is real
- The ruling file follows the format the `skills/release/dismiss-ruled-review.sh` header names
- In a Herdr team round the pinned judge weighs under `skills/herdr-foreman/references/team-operation.md` Judge Seat
- The question never blocks the round
- The agent keeps fixing until the answer arrives
- No answer means `fix`
- Preconditions (all required):
  1. The ruling rules the finding `defer` or `decline`
  2. In standalone mode, the ruling file carries `AUTHORITY: operator` and quotes the operator's answer verbatim
  3. In a team round, the ruling file carries `AUTHORITY: judge` and `foreman verify-ruling` binds it to the report supervision enrolled for the pinned judge's weighing
  4. The ruling names the finding at its `HEAD:`, and the finding's file is unchanged from that commit to the head
  5. The finding is under no floor
  6. The finding is entered in the task's follow-up issue citing the ruling, a `decline` labelled won't-fix
  7. Every other release gate holds
- Floors:
  - a failing test, lint, diagnostic or required check
  - a security or data-loss defect reachable by normal inputs
  - a `no-secrets` or `ci-safety` finding
  - a carve-out's unmet precondition
  - an unmet acceptance criterion the operator stated
- The judge rules `fix` on every floor
- `skills/release/dismiss-ruled-review.sh` refuses the rule-id floors and a failing check
- A ruling never skips, disables or removes a test
- A gating policy review the ruling covers is dismissed per `rules/ci-safety.md` Judge-Ruled-Review Dismissal Carve-Out

## Source Changes

The release worker reports source defects under `## BLOCKED`; the foreman routes authorized corrections to their writer. Release workers never edit source to satisfy a review. Advisory comments need no follow-up issue or reference and never enter the merge predicate.
