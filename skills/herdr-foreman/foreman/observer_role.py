"""Read observer migration 1's binding without migrating or scanning telemetry.

Schema owner/contract: skills/herdr-observer/references/storage.md; migration 1
is owned by factory_observer/store.py. A missing, incompatible or insecure cache
establishes no observer role. This reader creates no files or SQLite journals.
"""

from contextlib import closing
import json
from itertools import islice
import os
from pathlib import Path
import sqlite3
import stat

from . import supervision
from .errors import ForemanError, StateError


MAX_BINDINGS = 4096
MAX_RECEIPT_BYTES = 16384


def delivery_owner(pane_id, state_paths=(), environment=None):
    """Current ownership, even when the foreman is offline; never migrate it.

The supervision owner validates leases/enrollments. Index files are only
locators. A reserved pane, including an unresolved native handoff, cannot be
repurposed by registering an observer. No live foreman is required to retain it.
"""
    environment = os.environ if environment is None else environment
    root = Path(environment.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "foreman"
    paths = {Path(path) for path in state_paths} | {root / "state.json"}
    hint = environment.get("FOREMAN_CONTEXT_STATE")
    if hint:
        if not Path(hint).is_absolute():
            raise StateError("Restore the absolute current owner locator before registering an observer.", {})
        paths.add(Path(hint))
    index = root / "supervision-bindings"
    if index.exists():
        entries = list(islice(index.iterdir(), MAX_BINDINGS + 1))
        if len(entries) > MAX_BINDINGS:
            raise StateError("Resolve the supervision binding index coverage before registering an observer.", {})
        for entry in entries:
            if entry.suffix != ".json":
                continue
            descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise StateError("Restore regular supervision binding receipts before registering an observer.", {})
                raw = stream.read(MAX_RECEIPT_BYTES + 1)
            if len(raw) > MAX_RECEIPT_BYTES:
                raise StateError("Restore bounded supervision binding receipts before registering an observer.", {})
            receipt = json.loads(raw)
            if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int
                    or receipt["schema_version"] != 1 or not isinstance(receipt.get("state_path"), str)
                    or not Path(receipt["state_path"]).is_absolute()):
                raise StateError("Restore versioned supervision binding receipts before registering an observer.", {})
            paths.add(Path(receipt["state_path"]))
    for path in sorted(paths):
        data = supervision.load(path)
        if data["binding"] is not None and data["binding"]["identity"].get("pane_id") == pane_id:
            return {"role": "foreman", "state_path": str(path)}
        for member in data["members"]:
            if member["active"] and supervision.expected_assignment(member)["pane_id"] == pane_id:
                return {"role": "worker", "state_path": str(path)}
    return None


def matches(who, native, environment, *, client):
    if any(who.get(field) != native.get(field) for field in ("kind", "value")):
        return False
    root = Path(environment.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "herdr-observer"
    path = root / "observer.sqlite3"
    try:
        for target, directory in ((root, True), (path, False)):
            info = target.lstat()
            expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
            if not expected or info.st_uid != os.getuid() or info.st_mode & 0o077 or (not directory and info.st_nlink != 1):
                return False
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                return False
            rows = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('binding','config')"))
        binding, config = (json.loads(rows[key]) for key in ("binding", "config"))
        if not isinstance(binding, dict) or not isinstance(config, dict):
            return False
        if (type(binding.get("schema_version")) is not int or binding["schema_version"] != 1
                or type(config.get("schema_version")) is not int or config["schema_version"] != 1
                or config.get("enabled") is not True):
            return False
        saved = binding.get("identity")
        paths = config.get("states")
        if (not isinstance(saved, dict)
                or not isinstance(binding.get("name"), str) or not binding["name"]
                or any(not isinstance(saved.get(field), str) or not saved[field] for field in ("pane_id", "source", "agent", "kind", "value"))
                or saved["source"] != "herdr:" + saved["agent"] or saved["kind"] not in ("id", "path")
                or saved["kind"] == "path" and not Path(saved["value"]).is_absolute()
                or not isinstance(binding.get("cwd"), str) or not Path(binding["cwd"]).is_absolute()
                or not isinstance(paths, list) or any(not isinstance(path, str) or not Path(path).is_absolute() for path in paths)):
            return False
        identity = {"pane_id": who["pane_id"], **{k: native[k] for k in ("source", "agent", "kind", "value")}}
        if binding.get("identity") != identity or binding.get("cwd") != who["cwd"]:
            return False
        if delivery_owner(who["pane_id"], paths, environment) is not None:
            return False
        # PaneInfo has a label, not the registered agent name. Resolve only the
        # saved name through AgentInfo and match it to this exact pane/session.
        live = client.agent_get(binding["name"])
        if not isinstance(live, dict) or live.get("name") != binding["name"] or live.get("pane_id") != who["pane_id"]:
            return False
        live_native = live.get("agent_session")
        return (isinstance(live_native, dict) and live_native.get("pane_id", who["pane_id"]) == who["pane_id"]
                and all(live_native.get(field) == native[field] for field in ("source", "agent", "kind", "value")))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, ForemanError):
        return False
