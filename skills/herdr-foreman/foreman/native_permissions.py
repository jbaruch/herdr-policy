"""Verify the operator's effective Codex full-access coordination profile.

No config writes or turn starts. Resume the already bound, materialized thread
without overrides to read its effective settings; first-turn admission instead
uses the authenticated native hook's permission_mode. Hook trust is separate.
"""

from pathlib import Path

from .codex_goals import AppServer, GoalError, control_socket
from .errors import UsageError


def refusal(reason):
    return UsageError(
        "The foreman's effective native permissions are not verified ({}). Preserve the current session and work. "
        "Restore the operator-approved noninteractive full-access profile through the native CLI before preparing "
        "a maintenance handoff; this check changes no permission and grants no broader task authority.".format(reason),
        {"reason": reason, "phase": "native_permission_preflight"})


def source(session, cwd, *, connect=None, discover=None):
    """Read this bound Codex thread's actual approvals, sandbox and write scope."""
    if not isinstance(session, dict) or session.get("kind") != "id" or not isinstance(session.get("value"), str) or not session["value"]:
        raise refusal("native_permission_session_unproved")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise refusal("native_permission_workspace_unproved")
    try:
        expected = Path(cwd).resolve(strict=True)
        with (connect or AppServer)((discover or control_socket)()) as host:
            live = host.call("thread/read", {"threadId": session["value"]}).get("thread", {})
            if live.get("id") != session["value"] or live.get("status", {}).get("type") not in ("active", "idle"):
                raise refusal("native_permission_source_not_loaded")
            value = host.call("thread/resume", {"threadId": session["value"], "excludeTurns": True})
        actual_cwd = value.get("cwd")
        if (value.get("thread", {}).get("id") != session["value"]
                or not isinstance(actual_cwd, str) or not Path(actual_cwd).is_absolute()
                or Path(actual_cwd).resolve(strict=True) != expected):
            raise refusal("native_permission_workspace_changed")
        if value.get("approvalPolicy") != "never" or value.get("sandbox") != {"type": "dangerFullAccess"}:
            raise refusal("native_permission_profile_interactive_or_restricted")
    except GoalError:
        raise refusal("native_permission_host_unavailable") from None
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        raise refusal("native_permission_evidence_unavailable") from None
    return {"approval_policy": "never", "sandbox": "danger-full-access", "write_roots": "unrestricted",
            "cwd": str(expected), "source": "bound_native_thread_without_overrides"}


def incoming(payload):
    """A startup argv is not proof of the first turn's effective mode."""
    return payload.get("permission_mode") == "bypassPermissions"
