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

