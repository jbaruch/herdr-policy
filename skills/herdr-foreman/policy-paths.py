#!/usr/bin/env python3
"""Look up installed policy bundles. See foreman.policy_paths.main for argv and JSON output.

Exit 0 on a complete selection, 2 on an invalid argument or unreadable installation.
No project or owner-state writes. Native identity uses ACR's public read-only
list/check operations; a full check can fetch locked dependencies into temporary
storage and needs registry access in a fresh process.
"""

import sys
sys.dont_write_bytecode = True

from foreman.policy_paths import main


if __name__ == "__main__":
    raise SystemExit(main())
