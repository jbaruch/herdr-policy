#!/usr/bin/env python3
"""Installed entrypoint. Only co-shipped skill roots are added to the import path."""

from pathlib import Path
import sys
import traceback


MAX_DIAGNOSTIC_BYTES = 8192


class BoundedDiagnostics:
    """One launch's private stderr; no accumulation across restarts."""

    def __init__(self, stream):
        self.stream = stream
        self.remaining = MAX_DIAGNOSTIC_BYTES

    def write(self, value):
        chunk = value.encode("utf-8")[:self.remaining]
        self.stream.write(chunk.decode("utf-8", errors="ignore"))
        self.remaining -= len(chunk)
        self.stream.flush()
        return len(value)

    def flush(self):
        self.stream.flush()


def collector_failure(kind, _value, frames):
    # Preserve nonzero process failure without copying exception values, native
    # output or local variables into the diagnostic.
    print("herdr-observer: collector failed (" + kind.__name__
          + "); inspect status and restore the plugin or private store before restarting", file=sys.stderr)
    for frame in traceback.extract_tb(frames):
        print(str(frame.filename) + ":" + str(frame.lineno) + " in " + frame.name, file=sys.stderr)


def main():
    if sys.argv[1:] == ["serve"]:
        sys.stderr = BoundedDiagnostics(sys.stderr)
        sys.excepthook = collector_failure
    root = Path(__file__).resolve().parent
    siblings = {"herdr-observer": "herdr-foreman",
                "acr__jbaruch__herdr-policy__herdr-observer": "acr__jbaruch__herdr-policy__herdr-foreman"}
    owner = root.with_name(siblings[root.name]) if root.name in siblings else None
    if owner is None or not (owner / "foreman/observer_role.py").is_file():
        print('herdr-observer: restore the complete co-shipped herdr-policy package', file=sys.stderr)
        print('{"ok":false,"error":"co-shipped supervision owner missing"}')
        return 2
    sys.path[:0] = [str(root), str(owner)]
    from factory_observer.cli import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
