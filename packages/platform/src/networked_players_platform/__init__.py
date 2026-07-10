"""Capability-routed bounded job platform."""

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

__all__ = [
    "ArtifactDescriptor",
    "CapabilityRequirement",
    "DatasetIdentity",
    "NoEligibleWorkerError",
    "RunRequest",
    "RunResult",
    "WorkerAdvertisement",
    "WorkloadSpec",
    "select_worker",
]

__version__ = "0.1.0"
