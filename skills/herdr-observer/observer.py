#!/usr/bin/env python3
"""Installed entrypoint. Only co-shipped skill roots are added to the import path."""

from pathlib import Path
import sys


def main():
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
