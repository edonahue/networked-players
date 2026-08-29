# Research

Networked Players' personal research platform (Phase 3): bounded, reproducible topic
corpora and analyses over the full canonical Discogs data, kept strictly separate from
the public/publication lane -- see
[ADR 0054](../../docs/decisions/0054-research-lane-and-promotion-boundary.md).

Everything this package produces lives under the git-ignored `local/research/` tree.
A request (`request.json`: topic, seed artist names, questions, scope, analyses) drives
seed resolution, a bounded one-hop topic-corpus build, configured analyses, and a
report -- `networked-players-research research-run --config request.json --dataset
<parsed-snapshot-root>`, or the granular `research-resolve-seed` / `research-build-corpus`
/ `research-analyze` / `research-report` subcommands individually.

Promotion of a research finding into the public product is a deliberate, human-reviewed
step reusing the existing contract-creation workflow (new validator +
`PUBLIC_ARTIFACT_GROUPS` entry) -- this package never publishes anything automatically.

## Comparisons (Phase 7 PR D)

`compare.py` compares two albums, two artists, or two scenes (a user-authored, labelled
artist-id set) over an already-built corpus -- `research-compare --mode
albums|artists|scenes`, or the same thing from a browser via `apps/review/`'s workbench
mode (`make workbench`; see `apps/review/README.md`). Both write the same run bookkeeping
under `local/research/<topic>/runs/<run-id>/` as every other command here.
