"""Versioned, JSON-serializable platform contracts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def _identifier(value: str, field_name: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must match {_IDENTIFIER_RE.pattern!r}")
    return value


def _sha256(value: str, field_name: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    name: str
    snapshot: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.name, "dataset name")
        _identifier(self.snapshot, "dataset snapshot")
        _sha256(self.manifest_sha256, "dataset manifest_sha256")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    name: str
    contract: str
    relative_path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _identifier(self.name, "artifact name")
        _identifier(self.contract, "artifact contract")
        if (
            not self.relative_path
            or self.relative_path.startswith("/")
            or ".." in self.relative_path.split("/")
        ):
            raise ValueError("artifact relative_path must be a safe relative path")
        _sha256(self.sha256, "artifact sha256")
        if self.size_bytes < 0:
            raise ValueError("artifact size_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    architectures: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    min_memory_mb: int = 0
    datasets: tuple[DatasetIdentity, ...] = ()

    def __post_init__(self) -> None:
        if self.min_memory_mb < 0:
            raise ValueError("min_memory_mb must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    workload_id: str
    version: str
    default_timeout_seconds: int
    max_retries: int
    capabilities: CapabilityRequirement = field(default_factory=CapabilityRequirement)

    def __post_init__(self) -> None:
        _identifier(self.workload_id, "workload_id")
        _identifier(self.version, "workload version")
        if self.default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkerAdvertisement:
    schema_version: int
    worker_id: str
    observed_at: str
    architecture: str
    tags: tuple[str, ...]
    total_memory_mb: int
    max_job_memory_mb: int
    runtime_commit: str
    workloads: dict[str, str]
    datasets: tuple[DatasetIdentity, ...] = ()
    active_jobs: int = 0
    last_assigned_at: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("worker advertisement schema_version must be 1")
        _identifier(self.worker_id, "worker_id")
        _identifier(self.architecture, "architecture")
        if self.total_memory_mb <= 0 or self.max_job_memory_mb <= 0:
            raise ValueError("worker memory values must be positive")
        if self.max_job_memory_mb > self.total_memory_mb:
            raise ValueError("max_job_memory_mb cannot exceed total_memory_mb")
        if self.active_jobs < 0:
            raise ValueError("active_jobs must be non-negative")
        _parse_datetime(self.observed_at, "observed_at")
        if self.last_assigned_at is not None:
            _parse_datetime(self.last_assigned_at, "last_assigned_at")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkerAdvertisement:
        payload = dict(value)
        payload["tags"] = tuple(payload.get("tags", ()))
        payload["datasets"] = tuple(DatasetIdentity(**item) for item in payload.get("datasets", ()))
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class RunRequest:
    schema_version: int
    run_id: str
    workload_id: str
    workload_version: str
    submitted_at: str
    runtime_commit: str
    timeout_seconds: int
    max_retries: int
    capabilities: CapabilityRequirement
    inputs: tuple[ArtifactDescriptor, ...]
    expected_outputs: tuple[str, ...]
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("run request schema_version must be 1")
        _identifier(self.run_id, "run_id")
        _identifier(self.workload_id, "workload_id")
        _identifier(self.workload_version, "workload_version")
        _parse_datetime(self.submitted_at, "submitted_at")
        if self.timeout_seconds <= 0 or self.max_retries < 0:
            raise ValueError("run timeout/retry policy is invalid")
        for output in self.expected_outputs:
            _identifier(output, "expected output")


@dataclass(frozen=True, slots=True)
class RunResult:
    schema_version: int
    run_id: str
    worker_id: str
    status: str
    started_at: str
    ended_at: str
    runtime_commit: str
    outputs: tuple[ArtifactDescriptor, ...]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("run result schema_version must be 1")
        _identifier(self.run_id, "run_id")
        _identifier(self.worker_id, "worker_id")
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("run result status must be succeeded or failed")
        _parse_datetime(self.started_at, "started_at")
        _parse_datetime(self.ended_at, "ended_at")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("a succeeded run cannot carry an error")


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)
