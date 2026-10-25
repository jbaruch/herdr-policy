"""Keep an owner-format upgrade from stranding an unfinished admitted service.

The state owner calls this before persisting a delivery-format migration. No
authority is transferred, no grant is rewritten and no native history is read.
Completed workflows need no further executor; every other service retains its
admitted policy until it is drained or explicitly returned by that owner.
"""

from .errors import StateError


def delivery_migration_pending(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("recovery"), dict):
        return False
    tasks = payload["recovery"].get("tasks")
    if not isinstance(tasks, dict):
        return False
    for task in tasks.values():
        progress = task.get("progression") if isinstance(task, dict) else None
        delivery = progress.get("delivery") if isinstance(progress, dict) else None
        if (isinstance(progress, dict) and progress.get("schema_version") == 2
                and isinstance(delivery, dict) and type(delivery.get("schema_version")) is int
                and delivery["schema_version"] == 1):
            return True
    return False


def require_compatible_services(state, path):
    """Validated state only; refuse the whole-file format commit on a mismatch."""
    from .native_policy import executing_policy_root
    from .remote_owner import loaded_policy

    services = []
    for name, task in state["recovery"]["tasks"].items():
        grant, progress = task.get("authority"), task.get("progression")
        if grant is None or grant["mode"] != "service":
            continue
        if isinstance(progress, dict) and progress.get("phase") == "complete" and progress.get("pending") is None:
            continue
        services.append((name, grant["policy"]))
    if not services:
        return
    version, digest = loaded_policy(executing_policy_root())
    current = {"version": version, "digest": digest}
    blocked = [(name, admitted) for name, admitted in services if admitted != current]
    if blocked:
        name, admitted = blocked[0]
        raise StateError(
            "Preserve this owner file before upgrading its delivery format: unfinished task {!r} still needs its admitted policy {}. Restore that exact policy and drain or explicitly return its service under the original owner, then retry the upgrade. Do not edit the grant or downgrade migrated obligations.".format(name, admitted["version"]),
            {"path": str(path), "blocked_tasks": len(blocked), "task": name,
             "admitted_policy": admitted, "executing_policy": current})
