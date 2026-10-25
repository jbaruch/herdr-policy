"""Load one bounded role capsule through the shared read-only Herdr role owner.

stdin is the agent's SessionStart JSON (at most 16 KiB). stdout is at most one
agent-native or portable context envelope. Ordinary sessions are silent. No
roster/history scan, cache mutation, binding, admission or dispatch occurs here.
Startup is advisory; failures preserve obligations and never claim authority.
"""

import json
import os
import sys
from pathlib import Path

from . import context_output, role_context
from .errors import ForemanError


INPUT_BYTES = 16_384
ADAPTERS = {"auto", "portable", "claude-code", "codex", "cursor", "grok", "antigravity"}
FAILURE = ("Session-start status — Herdr role context could not be verified. "
           "Preserve existing task ownership, unknown sends and operator holds; "
           "restore the current hook/controller before continuing team work.")


def _adapter(environment):
    adapter = environment.get("HERDR_HOOK_ADAPTER", "auto")
    if adapter not in ADAPTERS:
        raise ValueError("unknown hook adapter")
    if adapter == "auto":
        adapter = "portable" if environment.get("TESSL_AGENT") else "codex"
    return adapter


def _envelope(adapter, context):
    result: dict
    if adapter == "antigravity":
        result = {"injectSteps": [{"systemMessage": {"systemMessage": context}}]}
    elif adapter == "portable":
        result = {"additionalContext": context}
    elif adapter == "cursor":
        result = {"additional_context": context}
    else:
        result = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    return context_output.enforce_budget(result, "Restore a bounded role capsule before Herdr startup.")


def collect(skill, environment, payload=None, *, context_reader=role_context.select):
    """Adapter formatting shares one role check; environment alone proves none."""
    if "HERDR_ENV" not in environment:
        return None
    adapter = _adapter(environment)
    if adapter == "portable" and environment.get("TESSL_AGENT") in ("claude-code", "codex", "antigravity"):
        return None
    try:
        result = context_reader(skill, environment=environment, payload=payload,
                                **role_context.selected_paths(environment))
        context = result["context"]
        if not context:
            return None
        if not isinstance(context, str) or len(context.encode("utf-8")) > role_context.CONTEXT_BYTES:
            raise ValueError("role capsule exceeds its budget")
        context = "Session-start status — Herdr role: {} ({}).\nSkill root: {}\n\n{}".format(
            result["role"], result["reason"], Path(skill).resolve(), context)
        return _envelope(adapter, context)
    except (ForemanError, OSError, ValueError, KeyError, TypeError) as exc:
        # Never emit a partly read contract or an unbounded owner diagnostic.
        print("herdr-session-start: {} — restore the co-shipped hook, role contract and current owner".format(
            type(exc).__name__), file=sys.stderr)
        return _envelope(adapter, FAILURE)


def _input(stream):
    raw = stream.read(INPUT_BYTES + 1)
    raw = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(raw) > INPUT_BYTES:
        raise ValueError("SessionStart input exceeds 16 KiB")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("SessionStart input must be an object")
    return payload


def main():
    if "HERDR_ENV" not in os.environ:
        return 0
    try:
        adapter = _adapter(os.environ)
        if adapter == "portable" and os.environ.get("TESSL_AGENT") in ("claude-code", "codex", "antigravity"):
            return 0
        payload = _input(getattr(sys.stdin, "buffer", sys.stdin))
        result = collect(Path(__file__).resolve().parents[1], os.environ, payload)
    except (ValueError, UnicodeDecodeError) as exc:
        print("herdr-session-start: invalid hook input ({}) — restore the agent's SessionStart payload".format(
            type(exc).__name__), file=sys.stderr)
        return 0
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
