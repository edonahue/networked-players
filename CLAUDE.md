@AGENTS.md

## Claude Code notes

The guidance above is imported from `AGENTS.md`, which is the canonical, tool-agnostic
source of truth for both Claude Code and Codex — keep it authoritative and edit it there,
not here.

- Run `make check` before reporting a change complete, and report what you did not exercise.
- Use plan mode for changes to a settled direction, and add an ADR in `docs/decisions/`.
- Start points: `README.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/PUBLIC_PRIVATE_BOUNDARY.md`.
- Nested `AGENTS.md` (with a matching `CLAUDE.md`) exist for `apps/web/` (Node/npm, not `uv`)
  and `packages/catalog/`; read them when working in those areas.
