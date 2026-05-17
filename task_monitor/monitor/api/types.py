"""
API response types
==================
"""

from typing import TypedDict


class ContainerData(TypedDict):
    name: str
    image: str
    ready: bool
    restarts: int
    state: str


class ResourceInfoData(TypedDict):
    req_cpu: str
    req_mem: str
    lim_cpu: str
    lim_mem: str


class PodData(TypedDict):
    name: str
    phase: str
    age: str
    node: str
    labels: dict[str, str]
    containers: list[ContainerData]
    resources: dict[str, ResourceInfoData]


class PodListData(TypedDict):
    pods: list[PodData]


class JobData(TypedDict):
    name: str
    phase: str
    age: str
    tool: str
    active: int
    succeeded: int
    failed: int


class JobListData(TypedDict):
    jobs: list[JobData]


class EventData(TypedDict):
    type: str
    reason: str
    object: str
    message: str
    age: str


class EventListData(TypedDict):
    events: list[EventData]


class NodeMetricData(TypedDict):
    name: str | None
    cpu_used_m: int | None
    cpu_capacity_m: int | None
    cpu_pct: float | None
    mem_used_mi: int | None
    mem_capacity_mi: int | None
    mem_pct: float | None
    error: str | None


class PodMetricData(TypedDict):
    name: str | None
    cpu_m: int | None
    mem_mi: int | None
    error: str | None


class MetricsData(TypedDict):
    nodes: list[NodeMetricData]
    pods: list[PodMetricData]


class LogsData(TypedDict):
    pod: str
    lines: list[str]
    error: str | None


class DiskData(TypedDict):
    total_gi: float
    used_gi: float
    free_gi: float
    percent: float


class DeletedData(TypedDict):
    deleted: str


class CleanupRunData(TypedDict):
    deleted_ttl: int
    deleted_cap: int
    evicted: int
