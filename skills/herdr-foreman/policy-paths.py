#!/usr/bin/env python3
"""Look up installed policy bundles. See foreman.policy_paths.main for argv and JSON output.

Exit 0 on a complete selection, 2 on an invalid argument or unreadable installation.
No filesystem writes, network access, or helper execution.
"""

from foreman.policy_paths import main


if __name__ == "__main__":
    raise SystemExit(main())
