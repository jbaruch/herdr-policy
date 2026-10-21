"""Schema owner for observer.sqlite3; migration 1 creates a private bounded cache.

All JSON records contain schema_version=1. This cache never grants task authority.
Only Store writes/migrates it. Foreman's observer_role reader accepts migration 1
read-only and reads meta.binding and meta.config; incompatible/missing data means no role.
See references/storage.md for lifecycle and the public CLI's writer/reader contract.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat


SCHEMA = 1
RETENTION_SECONDS = 28 * 86400
MAX_BINS = 20000
MAX_SOURCES = 2048
MAX_REPORTS = 64
MAX_DB_PAGES = 8192
MAX_REPORT_BYTES = 65536


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
        return self.decode(row[0])

    @staticmethod
    def decode(raw):
        value = json.loads(raw)
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA:
            raise ValueError("observer record schema is unsupported; update the plugin")
        return value

    def put(self, table, key, value, at=0):
        if table not in ("meta", "sources", "bins", "reports"):
            raise ValueError("unknown observer table")
        raw = json.dumps({**value, "schema_version": SCHEMA}, separators=(",", ":"))
        if table == "meta":
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, raw))
        else:
            self.db.execute("INSERT OR REPLACE INTO " + table + " VALUES (?,?,?)", (key, at, raw))

    def rows(self, table, since=0):
        if table not in ("sources", "bins", "reports"):
            raise ValueError("unknown observer table")
        return [self.decode(row[0]) for row in self.db.execute(
            "SELECT value FROM " + table + " WHERE at>=? ORDER BY at", (since,))]

    def prune(self, now):
        for table, maximum in (("bins", MAX_BINS), ("sources", MAX_SOURCES), ("reports", MAX_REPORTS)):
            if table == "reports":
                removed = self.db.execute(
                    "SELECT key FROM reports ORDER BY at DESC LIMIT -1 OFFSET ?", (maximum,)).fetchall()
                for row in removed:
                    # Filenames are generated report IDs, never paths from report prose.
                    (self.home / "reports" / (row[0] + ".md")).unlink(missing_ok=True)
            self.db.execute("DELETE FROM " + table + " WHERE key IN (SELECT key FROM " + table
                            + " ORDER BY at DESC LIMIT -1 OFFSET ?)", (maximum,))
            if table != "reports":
                self.db.execute("DELETE FROM " + table + " WHERE at<?", (now - RETENTION_SECONDS,))
        self.db.execute("PRAGMA incremental_vacuum(32)")
