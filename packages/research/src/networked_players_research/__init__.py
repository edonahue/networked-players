"""Networked Players' personal research platform (Phase 3): bounded,
reproducible topic corpora and analyses over the full canonical Discogs
data, kept strictly separate from the public/publication lane
(`docs/decisions/0054-research-lane-and-promotion-boundary.md`).

Everything this package writes lives under the git-ignored `local/research/`
tree -- never `apps/web/public/**`, never a `PUBLIC_ARTIFACT_GROUPS` entry.
Promotion of a research finding into the public product is a deliberate,
human-reviewed step that reuses the existing contract-creation workflow
(new validator + `PUBLIC_ARTIFACT_GROUPS` entry), not something this
package does automatically.
"""

from __future__ import annotations

__version__ = "0.1.0"
