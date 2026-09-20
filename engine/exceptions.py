"""Custom structured exceptions for PlanReview."""

from typing import Any


class PlanReviewError(ValueError):
    """Base exception for PlanReview domain errors."""

    def __init__(
        self,
        message: str,
        code: str = "GENERIC_ERROR",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class UnsupportedOperationError(PlanReviewError):
    """Raised when the requested operation is not in the genuinely supported capability set."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="UNSUPPORTED_OPERATION",
            status_code=400,
            details=details,
        )


class AmbiguousRequestError(PlanReviewError):
    """Raised when the task description is contradictory, compound, or ambiguous."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="AMBIGUOUS_REQUEST",
            status_code=400,
            details=details,
        )


class ModelUnavailableError(PlanReviewError):
    """Raised when the requested local AI model is unreachable or uninstalled."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="MODEL_UNAVAILABLE",
            status_code=503,
            details=details,
        )



# --- Hardening: stable, machine-readable API errors (HTTP semantics live here) ---

class NotFoundError(PlanReviewError):
    """A task or evidence record does not exist."""

    def __init__(self, message="Task not found", code="TASK_NOT_FOUND", details=None):
        super().__init__(message, code=code, status_code=404, details=details)


class InvalidRequestError(PlanReviewError):
    """The request or contract data is invalid (HTTP 422)."""

    def __init__(self, message, code="INVALID_REQUEST", details=None):
        super().__init__(message, code=code, status_code=422, details=details)


class StateConflictError(PlanReviewError):
    """The request is valid but the task is in the wrong state for it (HTTP 409)."""

    def __init__(self, message, code="STATE_CONFLICT", details=None):
        super().__init__(message, code=code, status_code=409, details=details)


class IntegrityError(StateConflictError):
    """Stored evidence failed an integrity check. Never silently continues."""

    def __init__(self, message, code="INTEGRITY_CHECK_FAILED", details=None):
        super().__init__(message, code=code, details=details)


class GuardRejectedError(StateConflictError):
    """The pre-plan guard rejected the prepared workspace."""

    def __init__(self, message, details=None):
        super().__init__(message, code="PREPLAN_GUARD_REJECTED", details=details)


class DependencyError(PlanReviewError):
    """A local dependency (Terraform binary, fixtures, Ollama) is unavailable (HTTP 503)."""

    def __init__(self, message, code="DEPENDENCY_UNAVAILABLE", details=None):
        super().__init__(message, code=code, status_code=503, details=details)


class TerraformError(PlanReviewError):
    """Terraform ran and failed or timed out. Raw output stays in server logs."""

    def __init__(self, message, code="TERRAFORM_FAILED", status_code=502, details=None):
        super().__init__(message, code=code, status_code=status_code, details=details)


class ModelResponseInvalidError(PlanReviewError):
    """The local model answered, but not with a usable structured intent (HTTP 502)."""

    def __init__(self, message, details=None):
        super().__init__(message, code="MODEL_RESPONSE_INVALID", status_code=502, details=details)
