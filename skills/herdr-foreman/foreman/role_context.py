"""Select a small context bundle from real Herdr role evidence; never task authority.

Ordinary sessions perform no owner or controller reads. Native role selection
uses the current pane/session and existing supervision/configured launch owners.
Outages and holds retain a recovery capsule. No role ledger, prompt archive,
binding, acknowledgement or dispatch is written by this reader.
"""

import os
from pathlib import Path

from . import config, context_output, launch, progression_owner, report_delivery
from . import observer_role, supervision, tiers, workflow_capacity
from .errors import ForemanError, StateError, UsageError
from .state import default_state_path, load_state_checked


CONTEXT_BYTES = 4_096
ROLE_FILES = {"foreman": "foreman-context.md", "worker": "worker-context.md",
              "observer": "observer-context.md", "recovery": "context-recovery.md"}


SELECTION_ENV = {"state_path": "FOREMAN_CONTEXT_STATE", "config_path": "FOREMAN_CONTEXT_CONFIG"}


def selected_paths(environment, *, state_path=None, config_path=None):
    """Resolve routing locators only; native role/owner checks remain required."""
    result = {}
    for field, explicit in (("state_path", state_path), ("config_path", config_path)):
        hint = environment.get(SELECTION_ENV[field])
        value = explicit if explicit is not None else hint
        if explicit is None and hint is not None and (not isinstance(hint, str) or not Path(hint).is_absolute()):
            raise UsageError("Restore an absolute {} routing path from the current owner; a context hint grants no role.".format(SELECTION_ENV[field]), {})
        result[field] = Path(value).resolve() if value is not None else None
    return result


def startup_environment(state_path, config_path=None):
    """Pass only owner-selected locators to a fresh native workspace, never ambient env."""
    selected = selected_paths({}, state_path=state_path, config_path=config_path)
    return tuple(SELECTION_ENV[field] + "=" + str(value) for field, value in selected.items() if value is not None)


def _worker_matches(member, pane_id, native):
    if not member["active"]:
        return False
    current = supervision.expected_assignment(member)
    expected = current["native_session"]
    return (current["pane_id"] == pane_id and isinstance(expected, dict)
            and expected.get("pane_id", pane_id) == pane_id
            and all(expected.get(key) == native.get(key) for key in ("source", "agent", "kind", "value")))


class ContextBundleError(StateError):
    """A missing or oversized shipped capsule must remain a visible failure."""

    code = "context_bundle_unavailable"


def _result(role, reason, skill, *, verified=False, owner=None):
    context, reference = "", None
    if role in ROLE_FILES:
        path = Path(skill) / "references" / ROLE_FILES[role]
        try:
            with path.open("rb") as stream:
                raw = stream.read(CONTEXT_BYTES + 1)
            if len(raw) > CONTEXT_BYTES:
                raise ContextBundleError("Restore the bounded co-shipped role contract before loading Herdr context.", {})
            context = raw.decode("utf-8")
            reference = str(path.resolve())
        except (OSError, UnicodeDecodeError):
            raise ContextBundleError("Restore the co-shipped role contract as readable UTF-8 before loading Herdr context.", {}) from None
    result = {"schema_version": 1, "role": role, "verified": verified, "reason": reason,
              "context": context, "reference": reference, "state_path": str(owner) if owner else None,
              "obligations_preserved": True, "authorizes_dispatch": False,
              "authorizes_progression": False, "authorizes_release": False}
    return context_output.enforce_budget(result, "Restore a bounded role contract; preserve unresolved ownership instead of truncating its recovery instructions.")


def _binding(who, root):
    path = supervision.binding_path(who, root)
    binding = supervision.read_json(path)
    if binding is None:
        return None
    if (not isinstance(binding, dict) or binding.get("schema_version") != 1
            or binding.get("identity") != who or not isinstance(binding.get("state_path"), str)
            or not Path(binding["state_path"]).is_absolute()
            or type(binding.get("generation")) is not int or binding["generation"] < 1):
        raise StateError("Restore this session's original supervision binding before selecting Herdr context.", {})
    return binding


def _payload_identities(payload, environment, cwd):
    if not isinstance(payload, dict):
        return []
    if "cwd" in payload and (not isinstance(payload["cwd"], str)
                             or not Path(payload["cwd"]).is_absolute()
                             or str(Path(payload["cwd"]).resolve()) != cwd):
        return []
    # Native hooks may carry an opaque ID and transcript path together. The
    # live controller chooses the binding kind; input field order cannot do so.
    identities = []
    session = payload.get("session_id") or payload.get("conversation_id")
    for kind, value in (("id", session), ("path", payload.get("transcript_path"))):
        if (not isinstance(value, str) or not value
                or kind == "path" and not Path(value).is_absolute()):
            continue
        identities.append(supervision.identity(value, cwd, environment["HERDR_ENV"], kind=kind,
                                               pane_id=environment["HERDR_PANE_ID"]))
    return identities


def select(skill, *, client=None, state_path=None, config_path=None, payload=None,
           environment=None, cwd=None, binding_root=None):
    """Return one current role capsule. Caller/hook input alone proves no role."""
    environment = os.environ if environment is None else environment
    cwd = str(Path.cwd()) if cwd is None else str(Path(cwd).resolve())
    if getattr(getattr(client, "context", None), "mode", None) == "attested-remote":
        authority = getattr(client, "_remote_authority", None)
        if authority is None:
            return _result("unverified", "remote_owner_unverified", skill)
        selected = Path(state_path).resolve() if state_path is not None else authority.state_path
        if selected.resolve() != Path(authority.state_path).resolve():
            from .command_context import refuse
            raise refuse("remote_owner_state_path_changed")
        try:
            data = progression_owner.verify_foreman(selected, client)
            if any(row["resumed_at"] is None for row in data["holds"]):
                return _result("recovery", "operator_hold", skill, verified=True, owner=selected)
            return _result("foreman", "attested_remote_foreman", skill, verified=True, owner=selected)
        except ContextBundleError:
            raise
        except ForemanError:
            return _result("recovery", "remote_role_unavailable", skill, owner=selected)
    if "HERDR_ENV" not in environment:
        return _result("standalone", "outside_herdr", skill)
    if not environment.get("HERDR_ENV") or not environment.get("HERDR_PANE_ID"):
        return _result("recovery", "native_context_unavailable", skill)
    selected = selected_paths(environment, state_path=state_path, config_path=config_path)
    state_path, config_path = selected["state_path"], selected["config_path"]
    incoming = _payload_identities(payload, environment, cwd)
    saved = [binding for who in incoming if (binding := _binding(who, binding_root)) is not None]
    try:
        if client is None:
            from .supervision_runtime import read_client
            client = read_client(binary=environment.get("HERDR_BIN"))
        pane_id = environment["HERDR_PANE_ID"]
        pane = client.pane_get(pane_id)
        native = pane.get("agent_session")
        if (pane.get("pane_id") != pane_id or not isinstance(native, dict)
                or native.get("agent") not in ("claude", "codex", "grok")
                or native.get("source") != "herdr:" + native["agent"]
                or native.get("kind") not in ("id", "path")
                or not isinstance(native.get("value"), str) or not native["value"]
                or native.get("pane_id", pane_id) != pane_id
                or native["kind"] == "id" and report_delivery.native_identity(pane) is None):
            return _result("unverified", "native_identity_unverified", skill)
        who = supervision.identity(native["value"], cwd, environment["HERDR_ENV"],
                                   kind=native["kind"], pane_id=pane_id)
        if payload is not None and who not in incoming:
            return _result("unverified", "hook_session_mismatch", skill)
        if observer_role.matches(who, native, environment):
            return _result("observer", "registered_native_observer", skill, verified=True)
        binding = _binding(who, binding_root)
        if binding is not None:
            selected = Path(binding["state_path"])
            if state_path is not None and Path(state_path).resolve() != selected.resolve():
                return _result("recovery", "owner_state_mismatch", skill)
        else:
            selected = Path(state_path) if state_path is not None else default_state_path()
        data = supervision.load(selected)
        state, usable = load_state_checked(selected, persist_migration=False)
        if not usable:
            return _result("recovery", "owner_state_unreadable", skill, owner=selected)
        if data["binding"] is not None and data["binding"]["identity"] == who:
            if binding is None:
                return _result("recovery", "binding_receipt_missing", skill, owner=selected)
            if binding["generation"] != data["binding"]["generation"]:
                return _result("recovery", "binding_generation_mismatch", skill, owner=selected)
            progression_owner.verify_foreman(selected, client, native_only=True, supervised=data)
            if any(row["resumed_at"] is None for row in data["holds"]):
                return _result("recovery", "operator_hold", skill, verified=True, owner=selected)
            return _result("foreman", "bound_native_foreman", skill, verified=True, owner=selected)
        if binding is not None:
            return _result("recovery", "owner_binding_changed", skill, owner=selected)
        matching = [row for row in data["members"] if _worker_matches(row, pane_id, native)]
        if len(matching) == 1:
            if any(row["resumed_at"] is None for row in data["holds"]):
                return _result("recovery", "operator_hold", skill, verified=True, owner=selected)
            return _result("worker", "enrolled_native_worker", skill, verified=True, owner=selected)
        if data["binding"] is not None:
            return _result("unverified", "caller_is_not_bound_foreman", skill)
        unfinished, _integration = workflow_capacity.work_sets(state, data)
        if unfinished:
            return _result("recovery", "unbound_existing_obligations", skill, owner=selected)
        # First launch precedes supervision binding. Prove its configured seat
        # and exact foreground model/effort instead of promoting any Herdr pane.
        seat = config.load_foreman(config_path or config.default_config_path())
        if seat is not None and seat.kind == native["agent"]:
            tier = tiers.select_tier(seat, "foreman")
            launch.verify_foreman(client, seat, pane_id, tier)
            return _result("foreman", "configured_native_foreman", skill, verified=True, owner=selected)
        return _result("unverified", "role_not_established", skill)
    except ContextBundleError:
        raise
    except ForemanError:
        if not saved and incoming:
            # An outage cannot verify a worker, but its current enrollment can
            # retain recovery instructions. Read only the selected owner and
            # use its refinements; no new discovery binding is created.
            selected = Path(state_path) if state_path is not None else default_state_path()
            data = supervision.load(selected)
            matching = []
            for member in data["members"]:
                assignment = supervision.expected_assignment(member)
                native = assignment["native_session"]
                if (isinstance(native, dict) and native.get("agent") in ("claude", "codex", "grok")
                        and native.get("source") == "herdr:" + native["agent"]
                        and native.get("kind") in ("id", "path")
                        and _worker_matches(member, environment["HERDR_PANE_ID"], native)
                        and supervision.identity(native["value"], cwd, environment["HERDR_ENV"],
                            kind=native["kind"], pane_id=environment["HERDR_PANE_ID"]) in incoming):
                    matching.append(member)
            if len(matching) == 1:
                return _result("recovery", "enrolled_role_unavailable", skill, owner=selected)
        owners = {row["state_path"] for row in saved}
        return _result("recovery" if saved else "unverified",
                       "current_role_unavailable", skill,
                       owner=Path(next(iter(owners))) if len(owners) == 1 else None)
