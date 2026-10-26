"""Shared owner-writer activation following the 0.19.0 compatibility release.

Compatibility readers accept the deployed and activated owner formats. This
activation release can land only after Tessl and ACR compatibility publication
are both confirmed; it enables the writers through this one shared constant.
Environment, CLI input and owner records cannot activate it. Tests patch this
same constant to exercise the complete activated writer path.
"""

from .errors import UsageError

NEW_OWNER_WRITES_ENABLED = True


def enabled():
    return NEW_OWNER_WRITES_ENABLED


def require(feature):
    if not enabled():
        raise UsageError("{} writes are staged while compatible readers roll out. Preserve the current owner and pending evidence; continue supported legacy work and use the activation release only after both publication channels confirm compatibility. No per-task approval or retry command activates this writer.".format(feature),
                         {"reason": "owner_writes_staged", "authorizes_progression": False})
