#!/usr/bin/env python3
"""Compatibility entrypoint for the packaged coordination measurement owner."""

import sys

sys.dont_write_bytecode = True

import hashlib
from importlib import import_module, util
from pathlib import Path

owner = Path(__file__).resolve().parents[1] / "skills/herdr-foreman/foreman"
namespace = "_herdr_measurements_" + hashlib.sha256(str(owner).encode()).hexdigest()
if namespace not in sys.modules:
    spec = util.spec_from_file_location(namespace, owner / "__init__.py", submodule_search_locations=[str(owner)])
    if spec is None or spec.loader is None:
        raise ImportError("Restore the complete local Herdr measurement owner before summarizing a snapshot.")
    package = util.module_from_spec(spec)
    sys.modules[namespace] = package
    spec.loader.exec_module(package)
calculator = import_module(namespace + ".coordination_metrics")
main, summarize = calculator.main, calculator.summarize

__all__ = ["main", "summarize"]


if __name__ == "__main__":
    raise SystemExit(main())
