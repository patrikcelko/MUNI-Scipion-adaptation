"""
Admin schemas
=============
"""

from pydantic import BaseModel, Field


class CleanupStatusResponse(BaseModel):
    """`GET /api/cleanup` - current cleanup configuration and state."""

    thread_alive: bool = Field(
        ...,
        description='Whether the background cleanup daemon thread is alive.',
    )
    """Checked via `cleanup_thread.is_alive()` on the app state."""

    ttl_seconds: int = Field(
        ...,
        description='Seconds after a job finishes before TTL-based deletion.',
    )
    """Mirrors `Settings.jobs_ttl` (typically 300 s = 5 min)."""

    max_finished_jobs: int = Field(
        ...,
        description='Cap on finished jobs kept, -1 means unlimited.',
    )
    """When the count exceeds this cap the oldest finished jobs are
    forcibly deleted regardless of age."""

    check_interval: int = Field(
        ...,
        description='How often the cleanup thread runs, in seconds.',
    )
    """Mirrors `Settings.jobs_cleanup_interval` (typically 60 s)."""

    known_jobs: int = Field(
        ...,
        description='Number of recently submitted job IDs tracked in memory.',
    )
    """Bounded by `_MAX_KNOWN_JOBS` (10 000)."""


class DiskResponse(BaseModel):
    """`GET /api/disk` - root filesystem usage."""

    total_gi: float = Field(
        ...,
        description='Total disk space in GiB.',
    )
    """Computed from `shutil.disk_usage('/')`, rounded to 1 decimal."""

    used_gi: float = Field(
        ...,
        description='Used disk space in GiB.',
    )
    """Computed from `shutil.disk_usage('/')`, rounded to 1 decimal."""

    free_gi: float = Field(
        ...,
        description='Free disk space in GiB.',
    )
    """Computed from `shutil.disk_usage('/')`, rounded to 1 decimal."""

    percent: float = Field(
        ...,
        description='Disk usage percentage (0 - 100), 1 decimal place.',
    )
    """Formula: `(used_gi / total_gi) * 100`."""


class DeletedResponse(BaseModel):
    """Response for `DELETE /api/job/{name}` and `DELETE /api/pod/{name}`."""

    deleted: str = Field(
        ...,
        description='Name of the Kubernetes resource that was deleted.',
    )
    """Exact job or pod name passed in the URL path."""
