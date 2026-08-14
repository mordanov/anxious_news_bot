"""Typed digest errors for retry classification."""

from __future__ import annotations


class DigestError(Exception):
    """Base digest error."""

    def __init__(self, message: str, *, code: str = "unknown") -> None:
        super().__init__(message)
        self.code = code


class TransientDigestError(DigestError):
    """Transient failure eligible for bounded retry."""

    pass


class PermanentDigestError(DigestError):
    """Permanent failure; no automatic retry."""

    pass


class CompositionTransientError(TransientDigestError):
    """Transient content composition failure."""

    pass


class CompositionPermanentError(PermanentDigestError):
    """Permanent content composition failure."""

    pass


class DefiniteTransientDeliveryError(TransientDigestError):
    """Definite transient delivery failure (rate-limit, temporary connectivity)."""

    pass


class PermanentDeliveryError(PermanentDigestError):
    """Permanent delivery failure (invalid chat, blocked, forbidden)."""

    pass


class AmbiguousDeliveryError(DigestError):
    """Ambiguous delivery outcome; must not retry automatically."""

    def __init__(self, message: str, *, code: str = "ambiguous_delivery") -> None:
        super().__init__(message, code=code)


class ExecutionTerminalError(DigestError):
    """Execution is in a terminal state and cannot be modified."""

    pass


class ExecutionBusyError(DigestError):
    """Execution has a concurrent active attempt."""

    pass


class StaleAttemptError(DigestError):
    """Attempt claim is stale or rejected."""

    pass
