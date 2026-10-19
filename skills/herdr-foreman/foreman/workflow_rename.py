"""Move private cleanup entries without replacing a concurrent destination."""

import ctypes
import errno
import os
import sys

from .errors import StateError, UsageError


def exclusive(source, destination, *, src_dir_fd=None, dst_dir_fd=None):
    """Require the platform's atomic no-replace rename; never emulate it."""
    if sys.platform == "darwin":
        symbol, flag, current_directory = "renameatx_np", 4, -2
    elif sys.platform == "linux":
        symbol, flag, current_directory = "renameat2", 1, -100
    else:
        raise StateError("Atomic exclusive rename is unavailable on this platform; preserve the cleanup intent and both paths.", {})
    try:
        function = getattr(ctypes.CDLL(None, use_errno=True), symbol)
    except (AttributeError, OSError):
        raise StateError("Atomic exclusive rename is unavailable in this runtime; preserve the cleanup intent and both paths.", {}) from None
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    paths = [os.fsencode(path) for path in (source, destination)]
    if any(b"\0" in path for path in paths):
        raise UsageError("Restore cleanup paths without embedded NUL bytes before moving either entry.", {})
    result = function(current_directory if src_dir_fd is None else src_dir_fd, paths[0],
                      current_directory if dst_dir_fd is None else dst_dir_fd, paths[1], flag)
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise UsageError("The cleanup destination already exists; preserve both entries and reconcile their owners before resuming.", {})
    raise StateError("Atomic exclusive rename failed; preserve the cleanup intent and both paths and restore filesystem support or access.",
                     {"errno": error})
