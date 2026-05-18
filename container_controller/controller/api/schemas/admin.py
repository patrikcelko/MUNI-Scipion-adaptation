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
    forcibly deleted regardless of age.
    """

    check_interval: int = Field(
        ...,
        description='How often the cleanup thread runs, in seconds.',
    )
    """Mirrors `Settings.jobs_cleanup_interval` (typically 120 s)."""

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


class CleanupRunResponse(BaseModel):
    """`POST /api/cleanup/run` - results of a manual cleanup pass."""

    deleted_ttl: int = Field(
        ...,
        description='Jobs deleted because they exceeded `jobs_ttl` seconds.',
    )
    """TTL-based deletions: finished longer ago than `Settings.jobs_ttl`."""

    deleted_cap: int = Field(
        ...,
        description='Jobs deleted to stay within `max_finished_jobs` cap.',
    )
    """Cap-based deletions: oldest finished jobs pruned when count > cap."""

    evicted: int = Field(
        ...,
        description='Evicted pods deleted during this cleanup pass.',
    )
    """Pods in `Failed` phase with reason `Evicted`."""


class ImageEntry(BaseModel):
    """A single container image cached on a node."""

    names: list[str] = Field(
        ...,
        description='All known tags / digests for this image.',
    )
    """May include multiple tags pointing to the same layer set."""

    size_mb: float = Field(
        ...,
        description='Uncompressed image size in MiB, 1 decimal place.',
    )
    """Derived from `image.size_bytes` reported by the kubelet."""


class NodeImageInfo(BaseModel):
    """Image inventory for a single cluster node."""

    node: str = Field(
        ...,
        description='Node name from `metadata.name`.',
    )
    """Unique within the cluster."""

    images: list[ImageEntry] = Field(
        ...,
        description='Images cached on this node, sorted by size descending.',
    )
    """Empty list when the node has no cached images."""

    total_mb: float = Field(
        ...,
        description='Sum of all image sizes on this node in MiB.',
    )
    """Rounded to 1 decimal place."""

    count: int = Field(
        ...,
        description='Total number of distinct images on this node.',
    )
    """Equal to `len(images)`."""


class ImagesResponse(BaseModel):
    """`GET /api/images` response."""

    nodes: list[NodeImageInfo] = Field(
        ...,
        description='Per-node image inventory for every node in the cluster.',
    )
    """One entry per node returned by `list_node()`."""
