"""One release-owned writer activation after both channels have the readers.

Compatibility readers accept the pending owner formats while ordinary writes
retain deployed formats. Only the following activation release changes this
constant after Tessl and ACR compatibility publication are both confirmed.
Environment, CLI input and owner records cannot activate it. Tests patch this
same constant to exercise the complete activated writer path.
"""

from .errors import UsageError

NEW_OWNER_WRITES_ENABLED = False


def enabled():
    return NEW_OWNER_WRITES_ENABLED


def require(feature):
    if not enabled():
        raise UsageError("{} writes are staged while compatible readers roll out. Preserve the current owner and pending evidence; continue supported legacy work and use the activation release only after both publication channels confirm compatibility. No per-task approval or retry command activates this writer.".format(feature),
                         {"reason": "owner_writes_staged", "authorizes_progression": False})
