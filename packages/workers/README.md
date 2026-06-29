# Workers

Planned responsibility: bounded background jobs such as validation, challenge generation, score calculation, and path batches.

Worker tasks must declare their input snapshot version, memory expectations, timeout, retry policy, and output contract. Raspberry Pi 3B nodes are constrained 1 GB ARM64 workers; jobs should be small, independent, and safe to repeat.
