# Workers

Planned responsibility: bounded background jobs such as validation, challenge generation, score calculation, and path batches.

Worker tasks must declare their input snapshot version, memory expectations, timeout, retry policy, and output contract. Raspberry Pi 3B nodes are constrained 1 GB ARM64 workers; jobs should be small, independent, and safe to repeat.

## Future: task routing (not decided, not implemented)

Once real jobs exist here, heavier ones may eventually be worth routing
preferentially to ZimaBoard-class nodes (Docker Swarm placement
constraints, e.g. `node.labels.class==zimaboard`, are the likely
mechanism) rather than the constrained Pi 3B workers. This is explicitly
not a decision yet — no placement logic exists, and none should be added
without real evidence. `infra/ansible/playbooks/benchmark.yml` (see
`docs/HARDWARE.md`'s "Measured capability" section) exists to produce that
evidence once all node types are reachable; revisit this note once it
does.
