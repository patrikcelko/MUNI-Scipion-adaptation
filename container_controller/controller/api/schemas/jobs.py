"""
Job schemas
===========
"""

from pydantic import BaseModel, Field


class SubmitResponse(BaseModel):
    """Returned after a successful `POST /submit`."""

    jobId: str = Field(
        ...,
        description='Full Kubernetes Job name.',
    )
    """RFC 1123 compliant name, e.g. `scipion-job-1710000000123-a1b2c3`."""

    jobNumber: str = Field(
        ...,
        description='Job identifier (timestamp-ms + random hex suffix).',
    )
    """Same value as jobId without the `scipion-job-` prefix."""


class CancelResponse(BaseModel):
    """Returned by `POST /cancel/{job_id}`."""

    ok: bool = Field(
        ...,
        description='Whether the cancellation succeeded.',
    )
    """`True` when the backend successfully deleted the job."""

    error: str | None = Field(
        default=None,
        description='Error message when ok is `False`.',
    )
    """Contains the exception text (e.g. `'invalid job id'`), or
    `None` on success."""


class ErrorResponse(BaseModel):
    """Generic error envelope used across endpoints."""

    error: str = Field(
        ...,
        description='Human-readable error description.',
    )
    """Free-form text describing what went wrong."""
