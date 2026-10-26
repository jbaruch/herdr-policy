# Antigravity Subscription Workers

Use Google's native Antigravity CLI, `agy`, with its existing Google subscription
sign-in. The adapter adds no OAuth client, credential store or API proxy.
The CLI's own authentication contract is at
https://antigravity.google/docs/install?tab=cli.

## Add Capacity

1. Install native `agy` on the Herdr controller host and sign in using the CLI.
   Keep the shipped `composer_glyph: "> "` setting; configuration validation
   refuses an omitted glyph before measurement, reservation or launch. Startup,
   clear and relaunch still require the existing ANSI and empty-composer proof.
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
must show the requested model's captured native label. Effort remains unknown;
the completed turn also needs native conversation evidence of that same model
selection before acceptance. A substituted, missing or
uncaptured label refuses with nothing sent. Captured labels live in
`skills/herdr-foreman/foreman/antigravity_native.py`; a model or effort
without one, including every Gemini row today, stays unadmitted until a
native launch of that exact pair is captured.

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
selection blocks. CLI 1.4.7 omits an unchanged selection on a second turn in
the same conversation. The reader carries forward only a preceding valid native
selection in that canonical conversation; a later change replaces it, and a
malformed or unknown user-input envelope clears that proof. The current request
still matches the preserved dispatch exactly. The effective selection must name
the dispatched tier's captured label. Missing history, any other request text or
a different selection refuses.

Tessl packages include the native Antigravity SessionStart hook using Google's
`conversationId`/`transcriptPath` input and `injectSteps` output. Both Tessl and
ACR carry the same runtime adapter and scoped worker protocol. ACR's supported
native host layouts remain unchanged; workers receive their scoped protocol in
the existing verified assignment even where no startup hook is rendered.
