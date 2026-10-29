"""Custom exception types for NexaFreight Control Tower."""

from __future__ import annotations


class NexaFreightException(Exception):
    """Base exception for all application-level errors.

    Service layer and business logic should raise subclasses of this
    exception for well-understood, expected error conditions that should
    be translated into clean HTTP error responses.

    Attributes:
        message: Human-readable error message (safe to expose to clients)
        status_code: HTTP status code to return (default 400)
        details: Optional structured error details (dict, safe to serialize)
    """

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ResourceNotFoundError(NexaFreightException):
    """Requested resource does not exist."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(
            message=f"{resource_type} not found: {resource_id}",
            status_code=404,
            details={"resource_type": resource_type, "resource_id": resource_id},
        )


class ValidationError(NexaFreightException):
    """Request data failed validation."""

    def __init__(self, message: str, field_errors: dict[str, str] | None = None) -> None:
        super().__init__(
            message=message,
            status_code=422,
            details={"field_errors": field_errors or {}},
        )


class UnauthorizedError(NexaFreightException):
    """Authentication required but not provided or invalid."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message=message, status_code=401)


class ForbiddenError(NexaFreightException):
    """Authenticated user lacks required permissions."""

    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message=message, status_code=403)


class AuthenticationError(NexaFreightException):
    """Invalid credentials or authentication token.

    Generic authentication failure that does not reveal whether
    the email exists or the password was incorrect, to prevent
    user enumeration.
    """

    def __init__(self, message: str = "Invalid credentials") -> None:
        super().__init__(message=message, status_code=401)


class TokenExpiredError(AuthenticationError):
    """JWT token has expired."""

    def __init__(self) -> None:
        super().__init__(message="Token has expired")


class InvalidTokenError(AuthenticationError):
    """JWT token is malformed or has invalid signature."""

    def __init__(self) -> None:
        super().__init__(message="Invalid authentication token")


class ConflictError(ValidationError):
    """State conflict — the request is valid but violates a uniqueness/
    idempotency constraint (e.g. approving a decision twice).

    Subclasses ValidationError so handlers built for 422-style re-validation
    contract stay compatible; overrides the status to HTTP 409 Conflict
    (Definitive Plan — decision approve exactly-once semantics).
    """

    def __init__(self, message: str) -> None:
        ValidationError.__init__(self, message=message)
        self.status_code = 409

class RateLimitExceededError(NexaFreightException):
    """Raised when a user or client exceeds an endpoint rate limit."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please try again later.",
        retry_after: int = 60,
    ) -> None:
        super().__init__(
            message=message,
            status_code=429,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after

