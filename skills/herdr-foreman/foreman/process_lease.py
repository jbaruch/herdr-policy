"""One live progression process per explicit lease path.

The kernel lock lasts for this context's lifetime, independently of a model
session. The returned in-process capability cannot survive fork, close or a
replaced lock path. Empty lock files carry no durable authority or schema.

This primitive grants no task ownership or effect permission. A service still
needs an owner-verified generation/handoff, transaction fencing, policy binding
and uncertain-send recovery. Never reclaim ownership from a heartbeat timeout
or delete this file to bypass a live holder. Existing state is untouched.
"""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat

from .errors import StateError, UsageError


class _Lease:
    """A process-local capability; not a serializable authority receipt."""

    def __init__(self, path, descriptor):
        self._path = path
        self._descriptor = descriptor
        self._pid = os.getpid()
        info = os.fstat(descriptor)
        self._identity = (info.st_dev, info.st_ino)
        self._active = True

    def require_current(self):
        """Refuse inherited, released, unlinked or replaced capabilities."""
        if not self._active or self._pid != os.getpid():
            raise StateError(
                "This process no longer holds the progression lease. Stop effects and recover through the task authority owner.", {})
        try:
            opened = os.fstat(self._descriptor)
            current = self._path.lstat()
        except OSError:
            raise StateError(
                "The progression lease cannot be verified. Stop effects; preserve pending intents and restore the original lease path before owner recovery.", {}) from None
        if (not stat.S_ISREG(current.st_mode) or current.st_size != 0
                or (opened.st_dev, opened.st_ino) != self._identity
                or (current.st_dev, current.st_ino) != self._identity):
            raise StateError(
                "The progression lease path changed. Stop effects and reconcile the owner generation; do not acquire a replacement path as proof of no send.", {})


@contextmanager
def process_lease(path):
    """Acquire a nonblocking OS lease; refuse busy or unsafe paths visibly.

    The caller supplies a dedicated empty file's absolute path in an existing
    owner-controlled directory, distinct from transactional state locks. There
    is no default home and no automatic owner enrollment.
    Closing or process death releases the kernel lock; the empty file remains.
    A crashed dispatch may still have sent even after that lock is released.
    """
    path = Path(path)
    if not path.is_absolute():
        raise UsageError("Supply an absolute progression lease path in the selected owner's private directory.", {})
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError:
        raise StateError(
            "Cannot open the progression lease. Restore a writable owner directory and a regular, nonsymlink lease path; preserve existing owner state.", {}) from None
    capability = None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise StateError("Use a regular progression lease file in the selected owner's private directory.", {})
        if opened.st_size != 0:
            raise StateError("Select a dedicated empty progression lease file; preserve existing owner records and their transactional locks.", {})
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StateError(
                "Another progression process holds this lease. Use that owner or wait for verified process exit; do not delete its lock or start another dispatcher.", {}) from None
        except OSError:
            raise StateError(
                "Cannot lock the progression lease. Use a filesystem with supported process locks before enabling progression.", {}) from None
        capability = _Lease(path, descriptor)
        capability.require_current()
        yield capability
    finally:
        if capability is not None:
            capability._active = False
        os.close(descriptor)
