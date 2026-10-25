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
import struct
import sys

from .errors import StateError, UsageError


_live = {}


def _owner_path(path):
    return Path(str(path) + ".owner")


class _Lease:
    """A process-local capability; not a serializable authority receipt."""

    def __init__(self, path, descriptor, owner_descriptor):
        self._path = path
        self._descriptor = descriptor
        self._pid = os.getpid()
        info = os.fstat(descriptor)
        self._identity = (info.st_dev, info.st_ino)
        self._owner_descriptor = owner_descriptor
        owner = os.fstat(owner_descriptor)
        self._owner_identity = (owner.st_dev, owner.st_ino)
        self._active = True

    def require_current(self):
        """Refuse inherited, released, unlinked or replaced capabilities."""
        if not self._active or self._pid != os.getpid() or _live.get(self._path) is not self:
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
        try:
            owner = os.fstat(self._owner_descriptor)
            current_owner = _owner_path(self._path).lstat()
            if (not stat.S_ISREG(current_owner.st_mode) or current_owner.st_size != 0
                    or (owner.st_dev, owner.st_ino) != self._owner_identity
                    or (current_owner.st_dev, current_owner.st_ino) != self._owner_identity):
                raise StateError("The process-lock ownership path changed; preserve the original intent and recover through its actual task owner.", {})
            # Kept on a separate empty inode: POSIX locks are dropped by any
            # close on that inode in this process. Occupancy readers open the
            # original flock inode instead. No PID is written into a file.
            fcntl.lockf(self._owner_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise StateError("Cannot prove this process's current lock ownership; stop effects and restore its original kernel lease before recovery.", {}) from None

    def proof(self):
        self.require_current()
        return {"schema_version": 1, "lease": list(self._identity), "owner": list(self._owner_identity)}


def validate_proof(value):
    if (not isinstance(value, dict) or set(value) != {"schema_version", "lease", "owner"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or any(not isinstance(value[key], list) or len(value[key]) != 2
                   or any(type(number) is not int or number < 0 for number in value[key]) for key in ("lease", "owner"))):
        raise UsageError("Restore the actual kernel lease inode identities; saved PID or lock-file contents are not ownership proof.", {})


def owned_by(path, pid, proof):
    """Join the actual inode's kernel lock owner PID to the current watcher.

    F_GETLK reports a process-associated lock's owner, unlike flock occupancy.
    ABI layouts: apple-oss-distributions/xnu bsd/sys/fcntl.h; Linux's 64-bit
    struct flock (man7.org/linux/man-pages/man2/F_GETLK.2const.html).
    A same-process check uses its actual live capability, never F_GETLK, whose
    result excludes this process's locks. The external reader creates nothing.
    """
    validate_proof(proof)
    path = Path(path)
    if type(pid) is not int or pid < 1:
        return False
    descriptor = None
    try:
        current = path.lstat()
        owner_path = _owner_path(path).lstat()
        if (not stat.S_ISREG(current.st_mode) or current.st_size != 0
                or [current.st_dev, current.st_ino] != proof["lease"]
                or not stat.S_ISREG(owner_path.st_mode) or owner_path.st_size != 0
                or [owner_path.st_dev, owner_path.st_ino] != proof["owner"]):
            return False
        live = next((lease for lease in tuple(_live.values())
                     if lease._pid == os.getpid() and list(lease._identity) == proof["lease"]), None)
        if live is not None:
            return pid == os.getpid() and live.proof() == proof
        if pid == os.getpid():
            return False
        descriptor = os.open(_owner_path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size != 0
                or [opened.st_dev, opened.st_ino] != proof["owner"]):
            return False
        if sys.platform == "darwin":
            layout = struct.Struct("@qqihh")
            value = fcntl.fcntl(descriptor, fcntl.F_GETLK, layout.pack(0, 0, 0, fcntl.F_WRLCK, os.SEEK_SET))
            _start, _length, owner_pid, kind, _whence = layout.unpack(value)
        elif sys.platform.startswith("linux") and sys.maxsize > 2**32:
            layout = struct.Struct("@hhqqi4x")
            value = fcntl.fcntl(descriptor, fcntl.F_GETLK, layout.pack(fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0))
            kind, _whence, _start, _length, owner_pid = layout.unpack(value)
        else:
            raise StateError("This platform cannot prove kernel lock ownership; retain foreground supervision until its process-owner adapter is supported.", {})
        current, owner = path.lstat(), _owner_path(path).lstat()
        return (kind == fcntl.F_WRLCK and owner_pid == pid
                and [current.st_dev, current.st_ino] == proof["lease"]
                and [owner.st_dev, owner.st_ino] == proof["owner"])
    except FileNotFoundError:
        return False
    except (OSError, ValueError, struct.error):
        raise StateError("Cannot read the exact process owning this kernel lease; restore lock visibility before delegating supervision.", {}) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def held(path):
    """Read current kernel occupancy without creating or replacing a lease.

    Occupancy supplies no task or process identity. Callers must join it with
    the current owner generation and a live process proof before delegation.
    """
    path = Path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    except OSError:
        raise StateError("Cannot inspect the progression lease; restore process-lock visibility before transferring supervision.", {}) from None
    try:
        opened, current = os.fstat(descriptor), path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size != 0
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise StateError("The progression lease identity changed; reconcile its current owner before transferring supervision.", {})
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            raise StateError("Cannot verify kernel lease occupancy; restore a supported lock filesystem before delegating supervision.", {}) from None
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    except OSError:
        raise StateError("Cannot verify the unchanged lease path; preserve it and inspect its current owner before delegation.", {}) from None
    finally:
        os.close(descriptor)


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
    owner_descriptor = None
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
        try:
            owner_descriptor = os.open(_owner_path(path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            owner = os.fstat(owner_descriptor)
            if not stat.S_ISREG(owner.st_mode) or owner.st_size != 0:
                raise StateError("Use a dedicated empty process-lock ownership path; preserve existing records at the .owner sibling.", {})
            fcntl.lockf(owner_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise StateError("Cannot acquire the kernel process-owner lock; preserve its current holder and restore the original owner path before progression.", {}) from None
        capability = _Lease(path, descriptor, owner_descriptor)
        _live[path] = capability
        capability.require_current()
        yield capability
    finally:
        if capability is not None:
            capability._active = False
            if _live.get(path) is capability:
                del _live[path]
        primary = sys.exc_info()[1]
        close_failed = False
        for opened_descriptor in (owner_descriptor, descriptor):
            if opened_descriptor is not None:
                try:
                    os.close(opened_descriptor)
                except OSError:
                    close_failed = True
        if close_failed:
            message = "Cannot confirm process-lease descriptor closure; preserve the original intent and inspect its actual process before replacement."
            if primary is not None:
                primary.add_note(message)
            else:
                raise StateError(message, {})
