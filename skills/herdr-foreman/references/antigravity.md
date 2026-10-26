# Antigravity Subscription Workers

Use Google's native Antigravity CLI, `agy`, with its existing Google subscription
sign-in. The adapter adds no OAuth client, credential store or API proxy.
The CLI's own authentication contract is at
https://antigravity.google/docs/install?tab=cli.

## Add Capacity

1. Install native `agy` on the Herdr controller host and sign in using the CLI.
2. Read `agy models` and `agy -p /usage --output-format json` on that account.
   Missing access or subscription quota remains unavailable, not inferred.
3. Copy only the `antigravity` worker kind from
   `skills/herdr-foreman/antigravity.example.json` into the existing operator-owned
   schema-7-or-later config. Preserve existing providers, preferences, judge and
   foreman. Model IDs are examples; use the account's actual available IDs.
   A 0.16 profile with effort on Claude rows or Antigravity judgment rows is
   refused; remove those fields and rows.
4. Measure missing/failed profiles through the existing measurement command and
   plan ordinary work. Existing qualification, independence and holds apply.

`kind: agy` is the native Herdr start kind. Configured tiers use `--model`;
exact process argv and explicit `--conversation UUID` resume use the existing
launch verifier. Claude models take no `--effort`: CLI 1.4.7 answered an
unsupported effort by running Gemini instead. Omit effort on those rows; they
record none, and the effort they actually run at stays unknown. No Antigravity
row therefore fills a judgment round, and high-risk work refuses rather than
inventing an effort step. Other models still name an explicit effort. The
supported grammar and judgment pins live in `skills/herdr-foreman/foreman/tiers.py`.
A model appearing in a catalog does not prove access, qualification or
successful delivery.

Argv only requests a model. Before any task input, the worker's live footer
must show the captured native display of the requested model and effort, and
the assignment records that display proof with the effort its capture proves:
`unknown` for the no-effort Claude pairs. A substituted, missing or uncaptured
display refuses with nothing sent. Captured displays live in
`CAPTURED_DISPLAYS` in `skills/herdr-foreman/foreman/antigravity_native.py`.

Gemini rows remain supported configuration: they name an explicit effort and
launch with `--effort`. No Gemini-requested launch is captured yet, so each
Gemini pair is refused at admission until its capture is added. The Gemini
display captured under a Sonnet request proves no Gemini request and is never
mapped onto one.

No permanent pane is reserved. Assignment-scoped workers use the existing
launch, enrollment, report, verification and cleanup owners. Keep the existing
Claude/Codex/Grok foreman; Antigravity foreman reset and Stop ownership are not
enabled by this worker adapter. Keep the observer on a supported Claude, Codex or
Grok session too; Antigravity observer registration is rejected before cache
writes. Antigravity workers remain visible to the observer.
Remote-account measurement needs its native
controller adapter; a local Google account cannot establish remote capacity.

## Quota and Delivery

`skills/herdr-foreman/foreman/antigravity_native.py` owns the native usage command,
structured quota parser and conversation transcript contract. Quota lookup uses
the CLI slash command without a model turn and removes API-key/ADC overrides
from that lookup. Workers must use the same subscription sign-in; do not configure
API authentication for this profile. Provider failures stay local to its
measurement record; other eligible providers continue.

Each native quota group remains separate in the snapshot. Current planning
conservatively uses the limiting group across the profile. It does not infer
that a model family grants a separate account or usable extra headroom. Existing
account-bound billing evidence and window-group rules remain unchanged.

Herdr's installed `antigravity-cli` integration reports `agent: agy` with source
`herdr:antigravity_cli`. Native delivery reads only that conversation's official
`brain/<conversationId>/.system_generated/logs/transcript.jsonl`, the latest
completed model response and the exact bare report marker. Stable current pane,
session and source readback remain required. Arbitrary archived JSONL cannot
prove an Antigravity session; unsupported source formats remain unconfirmed.
Recovery compares the exact request inside the native `USER_REQUEST` envelope
with the preserved dispatch, accepts only the known trailing metadata and model
selection blocks, and requires that selection to name the dispatched tier's
captured label. Any other envelope, request text or selection refuses.

Tessl packages include the native Antigravity SessionStart hook using Google's
`conversationId`/`transcriptPath` input and `injectSteps` output. Both Tessl and
ACR carry the same runtime adapter and scoped worker protocol. ACR's supported
native host layouts remain unchanged; workers receive their scoped protocol in
the existing verified assignment even where no startup hook is rendered.

## Admission Capture

A pair is admitted only after one actual signed-in launch of exactly that pair
is captured and added to `CAPTURED_DISPLAYS` with regression fixtures:

1. The configured `model` and `effort`, the CLI version and Herdr's process
   argv for that launch.
2. The visible startup pane, ANSI and plain, showing no effort-substitution
   warning; its final `? for shortcuts` row supplies `footer`.
3. The byte-exact canonical `transcript.jsonl` of one completed no-tools turn
   and its sha256; its `USER_SETTINGS_CHANGE` `Model Selection` supplies
   `selection`, followed by a `DONE` model response.
4. The effort that display proves: the footer's effort text when it shows
   one, otherwise `unknown`.

Redact only the account address. A catalog entry, a quota reading, a startup
footer without a completed turn, or another pair's display admits nothing.
An assigned report and clear lifecycle remains separate acceptance evidence.
