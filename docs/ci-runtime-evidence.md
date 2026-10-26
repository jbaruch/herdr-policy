# Identical-tree runtime evidence

The publisher may reuse the runtime regression result of the merged PR. Every
PR still runs the entire suite. Reuse affects only `scripts/run-tests.py`;
secret scanning, diagnostics, package validation, the published policy baseline,
actual ACR install/upgrade/native execution/removal, skill review, Tessl and ACR
publication, and moderation/channel confirmation retain their independent gates.
This CI optimization grants no runtime, installation or publication authority.

`scripts/ci-runtime-gate.py` owns the producer and consumer contract. The producer
records a successful complete suite result in `runtime-evidence.json`, uploaded
as an immutable GitHub artifact named by run id and attempt. Only the exact
successful attempt of a same-repository PR in `tests.yml` can be consumed, and
only by a `main` push whose commit is GitHub's recorded merge of that PR.

The consumer checks the active workflow identity, latest PR head, complete and
unambiguous run/artifact enumeration, terminal success, run attempt, repository
ids, artifact expiry/size/digest, and tested checkout commit through GitHub's API.
The tested commit must be the PR head or its merge checkout, with the publisher's
exact Git tree. The server-resolved PR head must also have that tree, binding the
producer workflow and verifier to the reviewed source. That whole tree includes source, tests, workflows, dependency
pins and the evidence verifier itself. Artifacts are bounded JSON data, never
extracted or executed; archive redirects do not receive the GitHub API token.

The fingerprint additionally binds the hosted image OS/version and architecture,
actual tool versions and executable hashes, the complete installed policy oracle
digest, and the environment passed to the runtime suites. The runtime environment
has a finite allowlist with private HOME/TMPDIR, fixed locale/timezone and no
GitHub/Tessl credentials or native role variables. Workspace/runner-temp prefixes
are normalized; other values must match exactly. Input changes during a producing
run prevent evidence creation. A current-attempt terminal check closes the lookup.

Missing, stale, failed, ambiguous, forked, malformed, expired or mismatched proof
runs the full runtime suites normally. A missing runner/tool fingerprint also
runs the suites without producing reusable evidence. A suite failure still fails
CI; a cache miss never converts failure into success. No label, human statement,
absent check, approval receipt or model verdict can authorize reuse.

The JSON step result reports whether evidence was reused, its source run/attempt
and artifact, runtime duration when fresh, and gate elapsed time. Compare these
with the separate installation and publication steps when measuring release
latency. Historical #76 has no artifact and therefore takes the full-run path;
its measured duplicate runtime execution was 11m56s. New identical-tree merges
can avoid that runtime execution while retaining the distinct coverage above.

GitHub documents the server-owned [artifact metadata and digest](https://docs.github.com/en/rest/actions/artifacts)
and [workflow run state/attempt metadata](https://docs.github.com/en/rest/actions/workflow-runs).
