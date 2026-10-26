#!/usr/bin/env python3
"""Prepare selected-plan briefs; invoke with python3 -I and --plan FILE.

Optional --values FILE supplies semantic shared/role inputs; --output DIR writes
only after all roles validate. Stdout is a bounded paginated JSON view. Exit 1
prints field diagnostics there, or a source/tool error as JSON on stderr. No
native input, reservations or task acceptance are performed.
"""

import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from foreman.brief_inputs import main

    sys.exit(main(sys.argv[1:]))
