# ADR 0052: Network Explorer — SVG, bounded radius, no force-directed layout

- **Status:** Accepted
- **Date:** 2026-08-03
- **Depends on:** [ADR 0050](0050-browser-pathfinding-architecture-selection.md), [ADR 0051](0051-connect-two-records.md)

## Context

Phase 2's mission asks for visual exploration of the credit network without
becoming a "giant unreadable hairball" or a generic force-directed graph
demo. The pathfinding graph artifact (ADR 0050/0051) and the contributor
index (ADR 0048) already carry everything a focused, one-hop-at-a-time
explorer needs — no new backend artifact was built for this slice.

## Decision

**SVG, not Canvas.** Three reasons, all following directly from the bounded
design below rather than a general preference:

1. The interaction model caps every view at a center plus at most
   `MAX_NEIGHBORS` (24) neighbors — tens of elements, not thousands. Canvas's
   real advantage (cheap rendering of large element counts) doesn't apply at
   this scale.
2. SVG nodes are real, focusable, `aria`-labeled DOM elements
   (`role="button"`, `tabindex`, keyboard `Enter`/`Space` activation) —
   directly serving the still-open manual accessibility pass (issue #53)
   instead of adding a second, harder accessibility problem a from-scratch
   Canvas hit-testing/focus implementation would create.
3. The project ships zero UI-framework JS bundles by design; SVG lets plain
   DOM event listeners drive the interaction (`game/explorerStage.ts`),
   matching every other game module's vanilla-TS style, where Canvas would
   need its own redraw loop reimplementing what the DOM already gives free
   at this scale.

**No force-directed layout.** Positions are deterministic: the center sits
at the SVG's middle, neighbors are placed evenly around a fixed-radius
circle in ranked order (`game/networkExplorer.ts::buildView`, ranked by the
neighbor's own `connection_count` from the contributor index, so the
most-documented, most-navigable contributors are the ones kept when a hub
has more real neighbors than the display cap). No physics simulation, no
layout-thrash risk on a low-end mobile device, and no dependency added.

**Bounded radius, not full graph.** Every center change (click-to-recenter)
*replaces* the current view rather than adding to it — clicking a neighbor
re-runs `buildView` centered on them and re-renders from scratch. This is
the direct, concrete answer to "don't let browser payload/memory become
unreasonable": memory is bounded by the already-loaded pathfinding graph
(same ~1.8MB artifact Connect Two Records uses, fetched once, cached in
`sessionStorage`) plus at most 25 rendered SVG nodes at any moment, never
growing.

**Role-filtered fading, not hiding.** Toggling a role-category chip dims
(`opacity`, via `.explorer-node--dimmed`) non-matching nodes rather than
removing them — the evidence (edges, labels) stays visible even
de-emphasized, consistent with evidence-before-inference: fading is a
presentational aid, never a claim that a dimmed connection is less real.

**Entry point**: `apps/web/src/pages/explore/[album].astro`, one static
page per catalog album (mirrors `albums/[album].astro`'s `getStaticPaths`
pattern) — centers the explorer on that album's primary artist on load.
Recentering onto any other artist happens entirely client-side (no new page
navigation), since the whole bounded neighborhood is already loaded from
the same fetched graph.

## Consequences

- A contributor who is not one of the 140 catalog's own seed artists may
  show fewer neighbors than a seed would (the pathfinding graph only
  includes edges touching at least one seed) — an honest, bounded
  limitation of reusing Slice F's artifact rather than building a second,
  larger one. Recentering on such a contributor still works; it just may
  show a smaller neighborhood, which is the correct, transparent behavior
  for a bounded-scope tool, not a bug to hide.
- `MAX_NEIGHBORS = 24` is a starting point, not a measured UX optimum — the
  revisit trigger below covers what changes if usability testing suggests a
  different cap.

## Validation

`apps/web/tests/network-explorer-state.spec.ts`: pure state derivation
(`buildView` centers correctly, ranks and caps neighbors by degree, returns
null outside the graph's scope; `isDimmed` never dims the center, respects
an empty filter, and correctly dims/undims by category) — no browser
needed. Playwright integration coverage exercises the real committed
pathfinding graph and contributor index end to end.

## Revisit trigger

If real usage shows `MAX_NEIGHBORS` needs to exceed roughly a few dozen to
feel useful, that is a signal to add a second, coarser "album-only"
zoomed-out view (per the original design brief) rather than quietly raising
the cap until SVG DOM performance degrades on a real low-end device.
