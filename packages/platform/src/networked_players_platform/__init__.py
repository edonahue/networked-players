"""Capability-routed bounded job platform."""

from .broker import publish_advertisement, queue_name, read_advertisements
from .models import (
    ArtifactDescriptor,
    CapabilityRequirement,
    DatasetIdentity,
    RunRequest,
    RunResult,
    WorkerAdvertisement,
    WorkloadSpec,
)
from .scheduler import NoEligibleWorkerError, select_worker
from .workloads import RegisteredWorkload

__all__ = [
    "ArtifactDescriptor",
    "CapabilityRequirement",
    "DatasetIdentity",
    "NoEligibleWorkerError",
    "RegisteredWorkload",
    "RunRequest",
    "RunResult",
    "WorkerAdvertisement",
    "WorkloadSpec",
    "publish_advertisement",
    "queue_name",
    "read_advertisements",
    "select_worker",
]

__version__ = "0.1.0"
