"""Shared Camunda worker error types."""

from __future__ import annotations


class CamundaJobError(Exception):
    """Base error for user-facing Camunda job failures."""

    error_code = "CAMUNDA_JOB_ERROR"

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class CamundaJobValidationError(CamundaJobError):
    """Raised when a job payload is incomplete or invalid."""

    error_code = "CAMUNDA_JOB_VALIDATION_ERROR"


class CamundaJobBusinessError(CamundaJobError):
    """Raised for business rule violations."""

    error_code = "CAMUNDA_JOB_BUSINESS_ERROR"


class CamundaJobTechnicalError(CamundaJobError):
    """Raised for infrastructure or persistence failures."""

    error_code = "CAMUNDA_JOB_TECHNICAL_ERROR"
