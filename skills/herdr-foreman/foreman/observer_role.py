"""Read observer migration 1's binding without migrating or scanning telemetry.

Schema owner/contract: skills/herdr-observer/references/storage.md; migration 1
is owned by factory_observer/store.py. A missing, incompatible or insecure cache
establishes no observer role. This reader creates no files or SQLite journals.
"""

import json
import os
from pathlib import Path
import sqlite3
import stat


def matches(who, native, environment):
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
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                return False
            rows = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('binding','config')"))
        binding, config = (json.loads(rows[key]) for key in ("binding", "config"))
        if binding.get("schema_version") != 1 or config.get("schema_version") != 1 or config.get("enabled") is not True:
            return False
        identity = {"pane_id": who["pane_id"], **{k: native[k] for k in ("source", "agent", "kind", "value")}}
        return binding.get("identity") == identity and binding.get("cwd") == who["cwd"]
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return False
