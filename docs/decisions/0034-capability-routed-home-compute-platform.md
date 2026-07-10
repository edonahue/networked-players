# ADR 0034: Capability-routed home compute platform

- **Status:** Accepted
- **Date:** 2026-07-10

## Context

Networked Players now has several real execution lanes: Ansible host management,
Docker Swarm services, RQ burst jobs, Dask experiments, direct SSH/Ansible cohort
scoring, and static publication through Cloudflare. The individual slices work, but
they do not form one safe worker platform. Dispatch still names hosts or inventory
groups, job bodies are copied as standalone mirrors, remote scorer code can be stale,
and outputs are fetched from shared paths where an interrupted run can be confused
with an earlier success.

ADR 0033 also invalidated ADR 0032's central assumption. Whole-cohort bidirectional
reach scoring completes safely on a dedicated x86 worker, while the distributed
single-direction seed-BFS body retains the old unbounded Python state and is unsuitable
for the Pi fleet.

The cluster is expected to support future projects beyond this music-credit pipeline.
The reusable boundary is therefore a bounded job with declared inputs, capabilities,
resource limits, provenance, and output contracts, not a Discogs-specific traversal.

## Decision

Adopt a small capability-routed platform with the following division of responsibility:

- **Ansible configures hosts and deploys versioned worker runtimes.** It is not the
  scheduler and workload code does not contain hostnames.
- **Docker Compose/Swarm runs durable control services.** The existing dedicated Redis
  broker becomes the standing RQ control plane. Swarm remains useful for container
  services and visibility, but Swarm membership does not determine batch placement.
- **User-level systemd runs one bounded RQ worker per compute node.** It supplies cgroup
  limits, restart behavior, and direct access to verified host-local dataset caches.
- **Workers advertise capabilities.** An advertisement combines operator-declared
  policy with observed architecture, resource headroom, installed workload versions,
  and verified dataset snapshots. Scheduling filters these facts rather than matching
  a hostname.
- **The coordination host orchestrates and retains canonical state.** It is not eligible
  for normal jobs. Local heavy execution is an explicit emergency fallback.
- **Every run is immutable and provenance-bearing.** A request records a run ID,
  workload/runtime version, public commit, input hashes, dataset identity, resource
  policy, timeout, retry posture, and output contracts. Workers write to run-specific
  staging and publish only after validation. The controller fetches and hash-verifies
  completed outputs before local promotion.
- **Controller-managed SSH/Ansible transfer is the first artifact transport.** It is
  adequate for bounded control files and outputs and keeps credentials off workers.
  Revisit an object store when outputs exceed the documented transfer ceiling or a
  second project needs worker write-back independent of this controller.
- **RQ is the bounded production job path.** Dask remains an optional interactive
  analysis tool and must not place standing compute on the coordination host.
- **Public delivery remains static and independent.** `networked-players.com` is already
  deployed from this GitHub repository by Cloudflare's `main`-branch integration.
  Public assets remain under `apps/web/public/`; no home service becomes a runtime
  dependency.

ADR 0032 is superseded in full. ADR 0019's temporary/non-production broker posture and
ADR 0023's inventory-group dispatch posture are superseded for production jobs. ADR
0020 remains accepted only for optional interactive Dask use. ADRs 0024, 0025, 0031,
and 0033 remain the dataset-cache, human-review, and scoring foundations.

## Consequences

The platform adds a small runtime and contract package, a persistent broker, worker
heartbeats, and local run records. In return, all current and future workloads share one
dispatch, resource, provenance, interruption, and artifact protocol. New hardware joins
by declaring capabilities and installing workload plugins; scheduler code does not gain
a new hostname branch.

The Pi fleet performs bounded validation, cache auditing, evidence checking, and later
explicitly contracted enrichment work. The platform's built-in `artifact.validate@1`
workload is the first reusable ARM-safe capability; the older copied cohort-check lane is
kept temporarily while its controller is migrated. Whole-cohort graph scoring stays on
x86. The cluster need not maximize utilization: unchanged content is not repeatedly
processed merely to keep workers busy.

## Validation

The implementation is complete only when synthetic tests cover capability selection,
stale workers, code/dataset mismatch, resource refusal, atomic staging, tampered
outputs, and interrupted runs; the x86 scorer reproduces the retained cohort semantics;
and a Pi executes a canonical bounded validation job. Live resource measurements remain
local under ADR 0018.

## Revisit trigger

Revisit controller-pull transport when an ordinary artifact exceeds 16 MiB, workers need
independent write-back, or a second project demonstrates a real object-store need.
Revisit one-job-per-worker concurrency only after measured workloads show safe headroom.
Revisit RQ itself only when a concrete workload needs dependencies or scheduling
semantics that cannot be represented as bounded, retryable jobs.
