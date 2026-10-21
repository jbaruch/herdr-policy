"""Schema owner for observer.sqlite3; migration 1 creates a private bounded cache.

All JSON records contain schema_version=1. This cache never grants task authority.
Only Store writes/migrates it. Foreman's observer_role reader accepts migration 1
read-only and reads meta.binding and meta.config; incompatible/missing data means no role.
Table/key-specific field formats live in schema.py and gate every read and write.
See references/storage.md for lifecycle and the public CLI's writer/reader contract.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat

from . import schema


SCHEMA = 1
RETENTION_SECONDS = 28 * 86400
MAX_BINS = 20000
MAX_SOURCES = 2048
MAX_REPORTS = 64
MAX_ACKNOWLEDGEMENTS = 128
MAX_DB_PAGES = 8192
MAX_REPORT_BYTES = 65536
CACHE_PRESSURE_RATIO = 0.75
EVICTION_BATCH = 64


def default_home():
    root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    if not root.is_absolute():
        raise ValueError("set XDG_STATE_HOME to an absolute private directory, or unset it")
    return root / "herdr-observer"


def private_directory(path):
    path = Path(path).absolute()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("observer storage must be an owned directory, not a link")
    path.chmod(0o700)
    return path


def private_file(path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("observer storage must contain owned regular files without links")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


class Store:
    def __init__(self, home=None):
        self.home = private_directory(home or default_home())
        path = self.home / "observer.sqlite3"
        private_file(path)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA):
            self.db.close()
            raise ValueError("observer cache schema is unsupported; update the plugin before restarting")
        self.db.execute("PRAGMA max_page_count = {}".format(MAX_DB_PAGES))
        if version == 0:
            self.db.executescript("""
                PRAGMA auto_vacuum = INCREMENTAL;
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE sources (key TEXT PRIMARY KEY, at REAL NOT NULL, value TEXT NOT NULL);
                CREATE TABLE bins (key TEXT PRIMARY KEY, at REAL NOT NULL, value TEXT NOT NULL);
                CREATE TABLE reports (key TEXT PRIMARY KEY, at REAL NOT NULL, value TEXT NOT NULL);
                CREATE INDEX sources_at ON sources(at);
                CREATE INDEX bins_at ON bins(at);
                CREATE INDEX reports_at ON reports(at);
                PRAGMA user_version = 1;
            """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            yield self

    def get(self, table, key, default=None):
        if table not in ("meta", "sources", "bins", "reports"):
            raise ValueError("unknown observer table")
        row = self.db.execute("SELECT value FROM " + table + " WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        return self.decode(row[0], table, key)

    def decode(self, raw, table, key):
        return self.validate(json.loads(raw), table, key)

    def validate(self, value, table, key):
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA:
            raise ValueError("observer record schema is unsupported; update the plugin")
        if not schema.valid(table, key, value, self.home, SCHEMA):
            raise ValueError("observer record shape is unsupported; restore the original private " + table + " cache before retrying")
        return value

    def put(self, table, key, value, at: float = 0):
        if table not in ("meta", "sources", "bins", "reports"):
            raise ValueError("unknown observer table")
        raw = json.dumps(self.validate({**value, "schema_version": SCHEMA}, table, key), separators=(",", ":"))
        if table == "meta":
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, raw))
        else:
            self.db.execute("INSERT OR REPLACE INTO " + table + " VALUES (?,?,?)", (key, at, raw))

    def rows(self, table, since=0):
        if table not in ("sources", "bins", "reports"):
            raise ValueError("unknown observer table")
        return [self.decode(row[1], table, row[0]) for row in self.db.execute(
            "SELECT key,value FROM " + table + " WHERE at>=? ORDER BY at", (since,))]

    def prune(self, now):
        candidates = self.db.execute(
            "SELECT key,value FROM reports ORDER BY at DESC LIMIT -1 OFFSET ?", (MAX_REPORTS,)).fetchall()
        # Validate the complete deletion set before any file or cache mutation.
        reports = [self.decode(row[1], "reports", row[0]) for row in candidates]
        if reports:
            private_directory(self.home / "reports")
        removed_counts = {"bins": 0, "sources": 0}
        for table, maximum in (("bins", MAX_BINS), ("sources", MAX_SOURCES), ("reports", MAX_REPORTS)):
            if table == "reports":
                for receipt in reports:
                    Path(receipt["path"]).unlink(missing_ok=True)
            removed = self.db.execute("DELETE FROM " + table + " WHERE key IN (SELECT key FROM " + table
                                      + " ORDER BY at DESC LIMIT -1 OFFSET ?)", (maximum,)).rowcount
            if table in removed_counts:
                removed_counts[table] += removed
            if table != "reports":
                removed_counts[table] += self.db.execute("DELETE FROM " + table + " WHERE at<?", (now - RETENTION_SECONDS,)).rowcount
        limit = self.db.execute("PRAGMA max_page_count").fetchone()[0] * CACHE_PRESSURE_RATIO
        # Preserve schedules, uncertain jobs and report receipts. Bins and source
        # projections are cache; evict oldest data before the next write burst.
        while self.used_pages() > limit:
            for table in ("bins", "sources"):
                count = self.db.execute("DELETE FROM " + table + " WHERE key IN (SELECT key FROM " + table
                                        + " ORDER BY at LIMIT ?)", (EVICTION_BATCH,)).rowcount
                if count:
                    removed_counts[table] += count
                    break
            else:
                break
        if any(removed_counts.values()):
            retention = self.get("meta", "retention", {"bins_evicted": 0, "sources_evicted": 0, "telemetry_floor": 0})
            retention["bins_evicted"] += removed_counts["bins"]
            retention["sources_evicted"] += removed_counts["sources"]
            retention["at"] = now
            if removed_counts["sources"]:
                # A resumed session whose cursor was evicted must not charge its
                # old transcript again. Fresh cursors start at this coverage floor.
                retention["telemetry_floor"] = now
            self.put("meta", "retention", retention)
        self.db.execute("PRAGMA incremental_vacuum(32)")

    def used_pages(self):
        return self.db.execute("PRAGMA page_count").fetchone()[0] - self.db.execute("PRAGMA freelist_count").fetchone()[0]
