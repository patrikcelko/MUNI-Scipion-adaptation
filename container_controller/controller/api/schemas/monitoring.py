"""
Monitoring schemas
==================
"""

from pydantic import BaseModel, Field


class ContainerInfo(BaseModel):
    """Status of a single container inside a pod."""

    name: str = Field(
        ...,
        description='Container name as defined in the pod spec.',
    )
    """Matches the `spec.containers[].name` value in K8s."""

    image: str = Field(
        ...,
        description='Full container image reference.',
    )
    """E.g. `'cerit.io/scipion/relion:4.0'`."""

    ready: bool = Field(
        ...,
        description='Whether the container readiness probe passes.',
    )
    """`True` when the container is fully started and healthy."""

    restarts: int = Field(
        ...,
        description='Cumulative restart count for this container.',
    )
    """Sourced from `container_statuses[].restart_count`."""

    state: str = Field(
        ...,
        description="Runtime state: 'waiting', 'running', or 'terminated (<reason>)'.",
    )
    """Terminated reason is extracted from
    `container_statuses[].state.terminated.reason`.
    """


class ResourceInfo(BaseModel):
    """Requested / limited resources of a container."""

    req_cpu: str = Field(
        default='-',
        description="Requested CPU (e.g. '500m', '2').",
    )
    """Omitted when the container has no resource requests."""

    req_mem: str = Field(
        default='-',
        description="Requested memory (e.g. '512Mi', '4Gi').",
    )
    """Omitted when the container has no resource requests."""

    lim_cpu: str = Field(
        default='-',
        description="CPU limit (e.g. '4', '1000m').",
    )
    """Omitted when the container has no resource limits."""

    lim_mem: str = Field(
        default='-',
        description="Memory limit (e.g. '4096Mi', '8Gi').",
    )
    """Omitted when the container has no resource limits."""


class PodInfo(BaseModel):
    """Summary of a single pod."""

    name: str = Field(
        ...,
        description='Pod name from `metadata.name`.',
    )
    """Unique within the namespace."""

    phase: str = Field(
        ...,
        description='Pod phase: Pending, Running, Succeeded, Failed, or Unknown.',
    )
    """Raw value from `pod.status.phase`."""

    age: str = Field(
        ...,
        description="Human-readable age (e.g. '5m30s', '2h15m').",
    )
    """Computed from `metadata.creation_timestamp`; `'-'` if unknown."""

    node: str = Field(
        ...,
        description='Node the pod is scheduled on.',
    )
    """`'-'` when no node has been assigned yet."""

    labels: dict[str, str] = Field(
        ...,
        description='Filtered pod labels (app, tool, job).',
    )
    """Only labels relevant to Scipion are included."""

    containers: list[ContainerInfo] = Field(
        ...,
        description='Status of each container in the pod.',
    )
    """One entry per container (init containers excluded)."""

    resources: dict[str, ResourceInfo] = Field(
        ...,
        description='Resource requests / limits keyed by container name.',
    )
    """Keys match `ContainerInfo.name` values."""


class PodListResponse(BaseModel):
    """`GET /api/pods` response."""

    pods: list[PodInfo] = Field(
        ...,
        description='All pods in the configured namespace.',
    )
    """Sorted by Kubernetes default ordering."""


class JobInfo(BaseModel):
    """Summary of a single Job."""

    name: str = Field(
        ...,
        description='Job name from `metadata.name`.',
    )
    """E.g. `'scipion-job-1710000000123-a1b2c3'`."""

    phase: str = Field(
        ...,
        description='Computed phase: RUNNING, DONE, or FAILED.',
    )
    """DONE when `succeeded >= 1`; FAILED when `failed >= 1` and
    no active pods; RUNNING otherwise."""

    age: str = Field(
        ...,
        description="Human-readable age (e.g. '45s', '3m12s').",
    )
    """Computed from `metadata.creation_timestamp`."""

    tool: str = Field(
        ...,
        description="Tool label (e.g. 'xmipp', 'relion').",
    )
    """Extracted from the `tool` label; `'-'` if absent."""

    active: int = Field(
        ...,
        description='Number of actively running pods.',
    )
    """From `job.status.active`; 0 when the job has finished."""

    succeeded: int = Field(
        ...,
        description='Number of pods that completed successfully.',
    )
    """From `job.status.succeeded`."""

    failed: int = Field(
        ...,
        description='Number of pods that have failed.',
    )
    """From `job.status.failed`."""


class JobListResponse(BaseModel):
    """`GET /api/jobs` response."""

    jobs: list[JobInfo] = Field(
        ...,
        description='All jobs in the configured namespace.',
    )
    """Sorted: running jobs first, then alphabetically by name."""


class EventInfo(BaseModel):
    """Single event."""

    type: str = Field(
        ...,
        description="Event type: 'Normal' or 'Warning'.",
    )
    """Kubernetes event severity level."""

    reason: str = Field(
        ...,
        description="Short machine-readable reason (e.g. 'Pulling', 'BackOff').",
    )
    """Provided by the K8s component that emitted the event."""

    object: str = Field(
        ...,
        description='Name of the involved Kubernetes object.',
    )
    """`'-'` when the involved object reference is missing."""

    message: str = Field(
        ...,
        description='Human-readable event message (max 200 chars).',
    )
    """Truncated to 200 characters to keep payloads small."""

    age: str = Field(
        ...,
        description='Human-readable age of the event.',
    )
    """Based on `last_timestamp`, `event_time`, or
    `creation_timestamp` (first available)."""


class EventListResponse(BaseModel):
    """`GET /api/events` response."""

    events: list[EventInfo] = Field(
        ...,
        description='Most recent events (up to 50), newest first.',
    )
    """Sorted by descending timestamp."""


class NodeMetric(BaseModel):
    """Resource usage of a single cluster node."""

    name: str | None = Field(
        default=None,
        description='Node name.',
    )
    """`None` only in error entries."""

    cpu_used_m: int | None = Field(
        default=None,
        description='Current CPU usage in millicores.',
    )
    """Parsed from metrics-server `usage.cpu` (e.g. '250m' -> 250)."""

    cpu_capacity_m: int | None = Field(
        default=None,
        description='Total CPU capacity in millicores.',
    )
    """From `node.status.capacity.cpu`."""

    cpu_pct: float | None = Field(
        default=None,
        description='CPU utilisation percentage (0 - 100, 1 dp).',
    )
    """Formula: `cpu_used_m / cpu_capacity_m * 100`."""

    mem_used_mi: int | None = Field(
        default=None,
        description='Current memory usage in MiB.',
    )
    """Parsed from metrics-server `usage.memory`."""

    mem_capacity_mi: int | None = Field(
        default=None,
        description='Total memory capacity in MiB.',
    )
    """From `node.status.capacity.memory`."""

    mem_pct: float | None = Field(
        default=None,
        description='Memory utilisation percentage (0 - 100, 1 dp).',
    )
    """Formula: `mem_used_mi / mem_capacity_mi * 100`."""

    error: str | None = Field(
        default=None,
        description='Error message when metrics-server is unavailable.',
    )
    """Present only in error-placeholder entries."""


class PodMetric(BaseModel):
    """Resource usage of a single pod (summed across containers)."""

    name: str | None = Field(
        default=None,
        description='Pod name.',
    )
    """`None` only in error entries."""

    cpu_m: int | None = Field(
        default=None,
        description='Total CPU usage in millicores (all containers).',
    )
    """Sum of per-container `usage.cpu`."""

    mem_mi: int | None = Field(
        default=None,
        description='Total memory usage in MiB (all containers).',
    )
    """Sum of per-container `usage.memory`."""

    error: str | None = Field(
        default=None,
        description='Error message when metrics-server is unavailable.',
    )
    """Present only in error-placeholder entries."""


class MetricsResponse(BaseModel):
    """`GET /api/metrics` response."""

    nodes: list[NodeMetric] = Field(
        ...,
        description='Per-node resource usage from metrics-server.',
    )
    """Contains a single error entry if metrics-server is down."""

    pods: list[PodMetric] = Field(
        ...,
        description='Per-pod resource usage in the configured namespace.',
    )
    """Contains a single error entry if metrics-server is down."""


class LogsResponse(BaseModel):
    """`GET /api/logs/{pod_name}` response."""

    pod: str = Field(
        ...,
        description='Name of the pod whose logs were fetched.',
    )
    """Echoed from the URL path parameter."""

    lines: list[str] = Field(
        ...,
        description='Log lines (last tail lines, with timestamps).',
    )
    """Each line is prefixed with an RFC 3339 timestamp by K8s."""

    error: str | None = Field(
        default=None,
        description='Error message if the log fetch failed.',
    )
    """`None` on success; contains the exception text on failure."""
