"""Workflow error classification (retryable vs terminal).

Used by the worker (PR-M4) to decide RETRY_SCHEDULED vs BLOCKED / DEAD_LETTER.
PR-M1 ships the taxonomy only — no worker yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorClass(str, Enum):
    RETRYABLE = "RETRYABLE"
    TERMINAL = "TERMINAL"
    ALREADY_APPLIED = "ALREADY_APPLIED"


@dataclass(frozen=True)
class ClassifiedError:
    error_class: ErrorClass
    reason: str
    original: BaseException | None = None

    @property
    def retryable(self) -> bool:
        return self.error_class == ErrorClass.RETRYABLE

    @property
    def terminal(self) -> bool:
        return self.error_class == ErrorClass.TERMINAL

    @property
    def already_applied(self) -> bool:
        return self.error_class == ErrorClass.ALREADY_APPLIED


class WorkflowError(Exception):
    """Base workflow-layer error."""


class WorkflowNotFoundError(WorkflowError):
    pass


class WorkflowStateError(WorkflowError):
    """Illegal run_status / workflow_state transition or signal."""


class WorkflowConflictError(WorkflowError):
    """Business key or concurrent lease conflict."""


# Exception type names from domain/agents we classify by module path when available.
_TERMINAL_TYPE_NAMES = frozenset(
    {
        "AuthorityError",
        "InvariantError",
        "StateError",
        "AttributionError",
        "NotFoundError",
        "PrivacySentinelError",
        "PolicyError",
        "WorkflowStateError",
        "WorkflowNotFoundError",
        "WorkflowConflictError",
    }
)

_RETRYABLE_TYPE_NAMES = frozenset(
    {
        "OperationalError",
        "TimeoutError",
        "ConnectionError",
        "ConnectionResetError",
        "BrokenPipeError",
        "InterfaceError",
    }
)

_ALREADY_APPLIED_MARKERS = (
    "already approved",
    "already imported",
    "already published",
    "duplicate",
    "already applied",
)


def classify_error(exc: BaseException) -> ClassifiedError:
    """Map an exception to Retryable | Terminal | AlreadyApplied.

    Rules (from DURABLE-WORKFLOWS.md):
    - AuthorityError, InvariantError, AttributionError, NotFoundError → TERMINAL
    - StateError → TERMINAL unless message indicates already-applied no-op
    - DB/network operational errors → RETRYABLE
    - Unknown Exception → RETRYABLE (worker caps attempts → DEAD_LETTER)
    """
    name = type(exc).__name__
    msg = str(exc).lower()

    if any(m in msg for m in _ALREADY_APPLIED_MARKERS):
        return ClassifiedError(ErrorClass.ALREADY_APPLIED, f"already_applied:{name}", exc)

    if name in _TERMINAL_TYPE_NAMES:
        if name == "StateError" and any(m in msg for m in _ALREADY_APPLIED_MARKERS):
            return ClassifiedError(ErrorClass.ALREADY_APPLIED, f"already_applied:{name}", exc)
        return ClassifiedError(ErrorClass.TERMINAL, f"terminal:{name}", exc)

    if name in _RETRYABLE_TYPE_NAMES:
        return ClassifiedError(ErrorClass.RETRYABLE, f"retryable:{name}", exc)

    # Module-based: authority / domain terminal defaults
    mod = getattr(type(exc), "__module__", "") or ""
    if "authority" in mod or "privacy" in mod or "policy" in mod:
        return ClassifiedError(ErrorClass.TERMINAL, f"terminal_module:{mod}", exc)
    if "domain" in mod and name.endswith("Error"):
        if any(m in msg for m in _ALREADY_APPLIED_MARKERS):
            return ClassifiedError(ErrorClass.ALREADY_APPLIED, f"already_applied:{name}", exc)
        return ClassifiedError(ErrorClass.TERMINAL, f"domain_terminal:{name}", exc)

    # Default: retry with attempt cap (unknown → DEAD_LETTER later)
    return ClassifiedError(ErrorClass.RETRYABLE, f"unknown_retry:{name}", exc)


def is_retryable(exc: BaseException) -> bool:
    return classify_error(exc).retryable


def is_terminal(exc: BaseException) -> bool:
    return classify_error(exc).terminal
