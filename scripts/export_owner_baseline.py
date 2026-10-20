#!/usr/bin/env python3
"""Export a frozen baseline using the packaged measurement producer.

argv: owner/supervision JSON, fixed window, trusted reader and private provenance
path. stdout: schema-2 snapshot. stderr: setup failures. Exit 0 success, 2 unusable
input/output. Source evidence and owners remain unchanged.
"""

import argparse
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# This namespace stays separate from an explicitly selected older owner reader.
from scripts.coordination_baseline import namespace

producer = import_module(namespace + ".measurement_capture")
assert producer.__file__ is not None
PRODUCER_SOURCE = Path(producer.__file__)
EvidenceReader, export = producer.EvidenceReader, producer.export
native_times, opaque, instant = producer.native_times, producer.opaque, producer.instant


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--supervision", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--herdr-source", type=Path, default=ROOT)
    parser.add_argument("--provenance-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.provenance_output.resolve().is_relative_to(ROOT):
            raise ValueError("keep provenance outside the repository; select a private --provenance-output")
        owner_bytes, supervision_bytes = args.owner.read_bytes(), args.supervision.read_bytes()
        reader = EvidenceReader(args.herdr_source)
        snapshot = export(json.loads(owner_bytes), json.loads(supervision_bytes), instant(args.start), instant(args.end),
                          reader.native, reader.assessment, closure=reader.closed)
        sys.path.insert(0, str(ROOT))
        from scripts.coordination_baseline import summarize
        summarize(snapshot)
        runtime = args.herdr_source / "skills/herdr-foreman/foreman"
        provenance = {"schema_version": 3, "window": snapshot["window"],
                      "python_version": ".".join(str(part) for part in sys.version_info[:3]),
                      "owner_sha256": hashlib.sha256(owner_bytes).hexdigest(),
                      "supervision_sha256": hashlib.sha256(supervision_bytes).hexdigest(),
                      "exporter_sha256": hashlib.sha256(PRODUCER_SOURCE.read_bytes()).hexdigest(),
                      "reader_source_sha256": {str(path.relative_to(runtime)): hashlib.sha256(path.read_bytes()).hexdigest()
                                               for path in sorted(runtime.rglob("*.py"))},
                      "evidence_sha256": sorted(reader.source_digests), "exclusions": dict(reader.exclusions)}
        body = json.dumps(provenance, sort_keys=True, indent=2) + "\n"
        if args.provenance_output.exists():
            if args.provenance_output.read_text() != body:
                raise ValueError("provenance output already differs; choose a fresh output path")
        else:
            with os.fdopen(os.open(args.provenance_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as target:
                target.write(body)
    except (OSError, OverflowError, UnicodeError, ValueError, KeyError, TypeError, ImportError, AttributeError) as exc:
        print("export-owner-baseline: {} — restore frozen inputs and the trusted reader, then retry".format(exc), file=sys.stderr)
        return 2
    print(json.dumps(snapshot, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
