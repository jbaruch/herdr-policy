"""Observer lifecycle, private reports and sleeping native reporter.

stdout: JSON, including wake_agent/data from collect. stderr: actionable generic
diagnostics without raw native output. Exit 0 success, 2 refusal/error. No public
publishing path exists. start/next/ack/report verify the current native observer.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

from . import collect, native, sources
from .store import MAX_REPORT_BYTES, Store, default_home, private_directory, private_file


def lock(home, name):
    path = home / name
    private_file(path)
    stream = path.open("r+")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        return None
    return stream


def running(home):
    stream = lock(home, "service.lock")
    if stream is None:
        return True
    stream.close()
    return False


def verify(store, client):
    binding = store.get("meta", "binding")
    current = native.current(client.snapshot())
    config = store.get("meta", "config")
    if not binding or not config or not config["enabled"] or not native.matches(binding, current):
        raise ValueError("this is not the enabled observer session; use its original pane or explicitly start a replacement")
    return binding


def start(store, client, states, now):
    guard = lock(store.home, "launch.lock")
    if guard is None:
        raise ValueError("observer startup is already in progress; inspect status before retrying")
    try:
        snapshot = client.snapshot()
        row = native.current(snapshot)
        previous = store.get("meta", "binding")
        config = store.get("meta", "config", {})
        if running(store.home):
            if previous and native.matches(previous, row) and config.get("enabled"):
                return {"ok": True, "already_running": True, "home": str(store.home)}
            raise ValueError("another collector is running; stop it and wait for status to confirm before replacing its observer")
        if previous and not native.matches(previous, row) and config.get("enabled"):
            raise ValueError("observer identity changed; stop the old registration before starting this replacement")
        root = default_home().parent / "foreman"
        selected = [str(Path(p).expanduser().absolute()) for p in states]
        paths, _ = sources.owner_paths(root, selected)
        roles, _, _, _, _ = sources.owners(paths, snapshot["agents"])
        if native.fingerprint(native.identity(row)) in roles:
            raise ValueError("use a dedicated observer pane; this agent already owns foreman or worker delivery duties")
        binary = getattr(client, "binary", "herdr")
        executable = shutil.which(binary)
        if not executable:
            raise ValueError("install Herdr on PATH before starting the collector")
        binding = {"identity": native.identity(row), "name": row["name"], "cwd": row.get("cwd"), "at": now}
        with store.transaction():
            store.put("meta", "binding", binding)
            store.put("meta", "config", {"enabled": True, "started_at": config.get("started_at", now),
                                          "states": selected or config.get("states", []),
                                          "owner_root": str(root), "binary": executable})
            pending = store.get("meta", "pending", {})
            if pending.get("id") and (not previous or not native.matches(previous, row)):
                pending["send_status"] = "unknown"
                store.put("meta", "pending", pending)
        script = Path(__file__).resolve().parents[1] / "observer.py"
        try:
            process = subprocess.Popen([sys.executable, "-I", str(script), "serve"], cwd=store.home,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise ValueError("collector could not start; repair the Python installation and inspect status") from None
        return {"ok": True, "status": "starting", "pid": process.pid, "home": str(store.home),
                "next": "inspect status; leave the observer idle between analysis prompts"}
    finally:
        guard.close()


def serve(store):
    guard = lock(store.home, "service.lock")
    if guard is None:
        return {"ok": True, "already_running": True}
    try:
        due = 0
        while True:
            config = store.get("meta", "config", {})
            if not config.get("enabled"):
                return {"ok": True, "stopped": True}
            now = time.time()
            if now >= due:
                client = native.Native(config["binary"])
                try:
                    started = time.monotonic()
                    with store.db:
                        checked = collect.tick(store, client)
                        store.put("meta", "heartbeat", {"at": now, "collection_seconds": time.monotonic() - started})
                    collect.dispatch(store, client, checked)
                except ValueError:
                    with store.db:
                        store.put("meta", "heartbeat", {"at": now, "error": "collection_or_wake_failed; inspect status and native connectivity"})
                due = time.time() + collect.POLL_SECONDS
            time.sleep(min(5, max(0.1, due - time.time())))
    finally:
        guard.close()


def status(store, now):
    current = store.get("meta", "current", {})
    heartbeat = store.get("meta", "heartbeat", {})
    pending = store.get("meta", "pending", {})
    return {"schema_version": 1, "home": str(store.home), "running": running(store.home),
            "enabled": store.get("meta", "config", {}).get("enabled", False), "heartbeat": heartbeat,
            "reporter_present": current.get("reporter_present"),
            "sample_age_seconds": now - current["at"] if "at" in current else None,
            "coverage": current.get("coverage", []),
            "pending": {k: pending.get(k) for k in ("id", "reasons", "created_at", "send_status")},
            "reports": store.rows("reports")[-8:]}


def finish(store, job_id, now, kind=None):
    pending = store.get("meta", "pending", {})
    if pending.get("id") != job_id:
        raise ValueError("pending job changed; load next before acknowledging or reporting")
    if "weekly_report_due" in pending["reasons"] and kind != "weekly":
        raise ValueError("this job needs a private weekly report; an acknowledgement cannot replace it")
    schedule = store.get("meta", "schedule", {})
    schedule["last_analysis"] = now
    schedule["last_anomaly"] = pending["anomaly"]
    if kind == "weekly":
        schedule["last_weekly"] = now
    store.put("meta", "schedule", schedule)
    store.put("meta", "pending", {})


def report(store, client, job_id, kind, path, now):
    verify(store, client)
    prior = store.get("reports", job_id)
    if prior:
        return {"ok": True, "already_reported": True, **prior}
    expected = store.home / "drafts" / (job_id + ".md")
    if Path(path).absolute() != expected:
        raise ValueError("write the report only to next's private draft_path, then save that exact file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        import stat
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("report input must be a regular UTF-8 file")
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if not raw.strip() or len(raw) > MAX_REPORT_BYTES:
        raise ValueError("write a nonempty bounded private report; see store.MAX_REPORT_BYTES")
    raw.decode("utf-8")
    directory = private_directory(store.home / "reports")
    final = directory / (job_id + ".md")
    temporary = directory / (job_id + ".tmp")
    with store.transaction():
        pending = store.get("meta", "pending", {})
        if pending.get("id") != job_id:
            raise ValueError("load the pending job before saving its report")
        finish(store, job_id, now, kind)
        private_file(temporary)
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(final)
        receipt = {"id": job_id, "kind": kind, "path": str(final), "at": now,
                   "sha256": hashlib.sha256(raw).hexdigest(), "notification": "unknown"}
        store.put("reports", job_id, receipt, now)
        store.prune(now)
    expected.unlink(missing_ok=True)
    try:
        client.notify()
        receipt["notification"] = "sent"
    except ValueError:
        pass
    with store.transaction():
        store.put("reports", job_id, receipt, now)
    return {"ok": True, **receipt}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    actions = result.add_subparsers(dest="action", required=True)
    begin = actions.add_parser("start", help="register this dedicated observer and start its collector")
    begin.add_argument("--state", action="append", default=[], help="additional absolute foreman state path")
    for name in ("status", "stop", "next", "collect", "serve"):
        actions.add_parser(name)
    view = actions.add_parser("evidence")
    view.add_argument("--hours", type=int, default=168, choices=(1, 24, 168, 336))
    view.add_argument("--agent")
    ack = actions.add_parser("ack")
    ack.add_argument("--job", required=True)
    save = actions.add_parser("report")
    save.add_argument("--job", required=True)
    save.add_argument("--kind", choices=("weekly", "urgent"), required=True)
    save.add_argument("--file", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    store = None
    # Child database journals and private drafts inherit restrictive permissions.
    os.umask(0o077)
    try:
        store = Store()
        now = time.time()
        if args.action == "status":
            output = status(store, now)
        elif args.action == "serve":
            output = serve(store)
        elif args.action == "stop":
            with store.transaction():
                config = store.get("meta", "config", {})
                config["enabled"] = False
                store.put("meta", "config", config)
            output = {"ok": True, "enabled": False, "next": "inspect status until running is false before replacing the observer"}
        elif args.action == "evidence":
            output = collect.evidence(store, now, hours=args.hours, agent=args.agent)
        else:
            config = store.get("meta", "config", {})
            client = native.Native(config.get("binary", "herdr"))
            if args.action == "start":
                output = start(store, client, args.state, now)
            else:
                verify(store, client)
                if args.action == "next":
                    pending = store.get("meta", "pending", {})
                    draft = None
                    if pending.get("id"):
                        draft = private_directory(store.home / "drafts") / (pending["id"] + ".md")
                        private_file(draft)
                    output = {"wake_agent": False, "data": {"job": pending}, "draft_path": str(draft) if draft else None,
                              "latest_sample_at": store.get("meta", "current", {}).get("at")}
                elif args.action == "ack":
                    with store.transaction():
                        finish(store, args.job, now)
                    (store.home / "drafts" / (args.job + ".md")).unlink(missing_ok=True)
                    output = {"ok": True, "job_id": args.job, "reported": False}
                elif args.action == "report":
                    output = report(store, client, args.job, args.kind, args.file, now)
                else:
                    if running(store.home):
                        raise ValueError("the collector already owns sampling; inspect next or evidence instead")
                    with store.db:
                        output = collect.tick(store, client)
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        # External path contents and native outputs never appear in diagnostics.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, (json.JSONDecodeError, UnicodeError)) else "private storage or evidence is unavailable; inspect permissions, free space and plugin compatibility"
        print("herdr-observer: " + message, file=sys.stderr)
        print(json.dumps({"ok": False, "error": message}))
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
