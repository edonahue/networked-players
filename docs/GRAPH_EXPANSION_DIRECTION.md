# Graph Expansion Direction

Status: product direction for the next major Networked Players phase  
Date: 2026-09-02

This document records the product direction that should guide the next major expansion of Networked Players. It is intentionally not an implementation plan. It supplements `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, the performer-graph ADRs, and the existing operator/data documentation.

If implementation requires changing a settled architectural direction, add or update the appropriate ADR rather than treating this brief as an architectural decision record.

## Why this direction exists

Networked Players has crossed an important threshold. The project is no longer primarily proving that an evidence-bearing music-credit graph can be built and served. It now has a credible public product, multiple playable modes, an explorable graph, a real Discogs-derived catalog, a reproducible artifact pipeline, and a home-compute build environment.

The recent performer-only graph migration materially changed what is possible next. Public graph edges now have a much clearer meaning: a connection is grounded in documented musical performance rather than any shared behind-the-glass credit. That migration roughly halved the bounded published graph while preserving connectivity across the full 179-album catalog, and it shifted many routes toward longer but more musically intelligible paths.

That result is more than cleanup. It makes a larger graph safer to expose. Scaling the previous broad-credit graph would have scaled noise and hub distortion along with coverage. Scaling the performer graph can instead increase discovery while preserving an immediate explanation for why two people or records are connected.

The next phase should therefore focus on turning the current curated island into a substantially larger, explorable performer universe without sacrificing evidence quality, legibility, or static-first reliability.

## North-star product direction

Networked Players should become an **evidence-first performer graph built from a growing universe of studio albums, with Explore as the primary discovery surface and games as approachable entry points into the same underlying data**.

The intended user reaction is, in priority order:

1. “I had no idea those records or musicians were connected.”
2. “This is an impressively engineered data product.”
3. “This is a fun music game.”
4. “I want to try this with records I already know.”

The product should reward wandering and curiosity. The graph itself is the central object of interest; games remain valuable, but they should increasingly feel like ways to enter and learn the graph rather than the sole organizing principle of the site.

## Near-term scale target

The current catalog contains 179 albums. The next major milestone should target approximately **500 public studio albums in total**.

This is not an eventual ceiling. A much larger repository could be compelling, but the immediate goal is to become large enough that the site no longer feels like a toy while remaining bounded enough to audit musical quality, visual legibility, build performance, and evidence correctness.

The project should not jump directly to “all of Discogs.” Expansion should be treated as an architectural and product-quality experiment, not a race to maximize row counts.

## Public universe model

The next phase should separate the idea of a hand-featured catalog from the larger public graph universe.

### Featured albums

Featured albums are intentionally selected records that may receive richer presentation, human-written copy, prominent placement, game participation, curated routes, or other editorial attention.

The owner wants the site’s voice and meaningful editorial framing to include human-authored work, but does **not** want a product model that requires bespoke writing for every album. Editorial work should therefore be sparse and high-leverage rather than a prerequisite for publication.

### Graph records

The larger public universe may include eligible studio albums that are not hand-featured. These should be first-class, browsable destinations with deliberately data-forward presentation rather than pretending that every page is editorially curated.

A graph-record page may be generated from canonical data and can emphasize things such as:

- master/album identity and release metadata;
- performer roster;
- strongest or most structurally meaningful performer relationships;
- local graph neighborhood;
- evidence-bearing credits/releases;
- graph-native statistics when they are genuinely informative;
- interesting routes or next steps generated from the graph;
- provenance or an explanation of how the record entered the published universe.

Featured albums and graph records should be visually or semantically distinguishable in a tasteful way. The distinction should celebrate the project’s dataset rather than making generated pages feel like inferior placeholders.

### Performer nodes

Performers remain first-class graph entities. The performer graph may need to contain people whose evidence extends beyond the public studio-album universe.

The exact rule for performers who are not attached to an eligible public album is intentionally unresolved. Implementation planning should investigate a middle path in which performers can remain legitimate graph nodes and evidence can reference non-public releases without automatically promoting every single, compilation, reissue, or other Discogs object into a public album destination.

Do not resolve this by silently broadening the public record universe beyond the album constraints below.

### Evidence objects

Release-, track-, and credit-level evidence can be broader than the public album universe. These objects prove relationships; they do not all need to become browsable top-level musical destinations.

A useful conceptual separation is:

- **public musical object:** eligible studio album represented at the master level;
- **graph entity:** performer;
- **evidence object:** release/track/credit proving documented participation.

The implementation plan should test whether this model maps cleanly onto the current schemas and artifacts before proposing new ones.

## Album scope boundary

The larger public universe should remain centered on **standard studio albums represented at the Discogs master-release level**.

Do not make singles, EPs, compilations, arbitrary pressings, reissues, or every release-level artifact peers of studio albums merely to increase graph size. Discogs release complexity can remain beneath the public experience as evidence and normalization input.

This boundary is important to keeping Networked Players legible and album-centered rather than turning it into a general Discogs browser.

Any automatic eligibility rule for “standard studio album” must be conservative, auditable, and explicit about ambiguity. Do not invent unsupported metadata certainty when Discogs does not provide it.

## Explore should become the primary discovery surface

Explore is the current feature the owner most wants to use outside testing. The next phase should therefore prioritize making exploration delightful at larger scale.

The desired interaction priorities are:

1. a genuine spatial network that can be panned and zoomed;
2. a strong, bounded nearby view that emphasizes the most useful performers and relationships;
3. arbitrary album/performer search that can land the user in a graph neighborhood;
4. guided suggestions or editorial “follow this path” prompts as a later enhancement rather than the primary interface.

This does not require immediately replacing the current Explore implementation. The plan should first determine what can be evolved safely, what performance/UX limits exist, and what the smallest credible large-graph prototype is.

## Visual clutter is a product problem, not a reason to hide the graph

Obscure performers can be fascinating when they create surprising or structurally important bridges. They can also create clutter when their participation is mundane.

The public graph should therefore avoid a binary “famous people visible / obscure people hidden” rule. Prefer graph-derived prominence and progressive disclosure.

Potential signals worth evaluating include:

- local degree and repeated collaboration;
- cross-album participation;
- shortest-path participation;
- local or approximated betweenness;
- community membership and cross-community bridging;
- role diversity or repeated substantive performance roles;
- distance from the current anchor;
- album/era diversity.

These are candidates, not requirements. Earlier global betweenness work on the smaller graph was not sufficiently informative; do not assume the same metric will become useful simply because the graph grows. Measure it again only where the larger topology justifies the cost.

The guiding principle is that **the graph may contain more truth than the screen can show at once**. The interface should reveal detail as the user zooms, expands, filters, or recenters rather than deleting legitimate nodes from the underlying public model solely for visual convenience.

## Discovery should remain explainable

For the next phase, discovery intelligence should prioritize:

1. direct graph facts;
2. classical graph analysis.

Do not make embeddings, opaque recommendation systems, or LLM-generated relevance the authority for what is important in the graph. They may be investigated later for descriptive or assistive work, but the core ranking and discovery logic should remain inspectable and grounded in the same graph the user can see.

A strong outcome is a system that can explain why an entity is being emphasized, for example because a performer bridges otherwise distinct album communities or appears across several records in the local neighborhood.

## Arbitrary search is now a desired capability

The current product brief correctly lists unrestricted arbitrary-artist search as not yet promised. The next expansion phase should treat broader album/performer search as a desired capability to design toward.

Search must remain honest about coverage. The public site will still be a bounded universe at approximately 500 albums, not a claim of exhaustive recorded-music coverage.

A successful search experience should distinguish among:

- a performer or album present in the published universe;
- a known Discogs/master candidate that is not yet published;
- a query that cannot be resolved confidently.

Where feasible and privacy-safe, unresolved or out-of-universe searches can become a useful operator signal for future expansion. Do not make public runtime availability depend on a home-hosted Discogs lookup service merely to support search.

## Expansion selection should blend taste and graph utility

The first major expansion should not be purely hand-curated and should not be delegated entirely to an algorithm.

Candidate selection should blend three motives:

- **editorial/personal interest:** albums the owner genuinely wants represented;
- **graph expansion value:** records that add useful performers, bridges, communities, eras, genres, or meaningful overlap;
- **coverage repair:** records that improve sparse neighborhoods, satisfy obvious search gaps, or address measured imbalances in the current universe.

A provisional weighting such as 40% editorial interest / 40% graph-expansion value / 20% coverage repair is reasonable for experimentation, but it is not a fixed product requirement.

The selection system itself can become a useful internal data product. Candidate albums may receive auditable scores or diagnostics based on new performers, overlap with existing nodes, structural contribution, era/genre coverage where reliable, and operator preference. Human review should remain in the loop for publication decisions.

The first expansion slice should be small enough to inspect—on the order of tens of albums rather than hundreds—before the pipeline is trusted to approach the ~500-album milestone.

## Games remain important, but are not the next bottleneck

Connection Guesser is the owner’s second-most personally appealing current feature, and the existing games are valuable entry points.

The next major phase should not center on another broad game redesign. Instead:

- preserve current games and their quality;
- let them consume the larger published universe where appropriate;
- keep Daily/Guesser/Routes as approachable ways to encounter the graph;
- avoid forcing every newly published graph record into game rotation before it is suitable.

The graph-expansion work should not destabilize working game contracts without a measured need and an ADR where required.

## The home cluster is part of the project, not a production dependency

Building a functioning modest compute cluster is a core interest of this project. The next phase should give the ZimaBoard/Raspberry Pi fleet meaningful work rather than treating it as decorative infrastructure.

At the same time, preserve the existing static-first architectural rule: **the public site must not require the home cluster to be online**.

The intended relationship is:

Discogs data -> bounded ingest/normalization -> performer extraction -> graph construction -> graph analysis -> validation -> publication artifacts -> static public deployment.

The cluster should increasingly participate in the build, analysis, validation, and publication-preparation portions of that pipeline where the work is technically appropriate.

The x600 workstation should not become the identity of this production pipeline. It can remain useful for development, experiments, and exceptional operator work, but the next planning phase should prefer meaningful Zima/Pi responsibilities when they are safe and efficient.

Do not distribute work across constrained nodes purely for theater. Respect the repository’s existing Pi limits: bounded memory, immutable/checksummed partitions, sensible job duration, and no full raw Discogs dump parsing on a Pi.

Potential cluster directions worth evaluating include:

- fan-out of bounded graph analysis/validation jobs;
- partitioned candidate-album scoring;
- scheduled/incremental monthly refresh workflows;
- community or neighborhood analysis;
- publication validation and artifact checks;
- measurable distributed jobs that would otherwise be serial operator work.

The plan should identify which work genuinely benefits from the fleet and which should remain on the coordination/x86 node.

## Celebrate the build system publicly, with restraint

The site should include a tasteful public explanation of how the graph is built.

This should not become a homelab dashboard or expose private infrastructure details. A restrained “How the graph is built” treatment can explain the pipeline and modest-hardware constraint using safe, public facts and aggregate metrics such as:

- published albums;
- performers represented;
- performer relationships;
- evidence rows/releases processed;
- participating hardware classes or node count when safe;
- artifact/build duration from an intentionally published build manifest;
- last published graph/data version.

The core story is that a modest self-hosted compute fleet produces and validates a polished evidence-bearing graph while the public application remains static and independent of that fleet’s availability.

This is both part of the project’s technical identity and part of what makes the work worth showing publicly.

## Product hierarchy implication

The existing site has accumulated many peer surfaces. This phase should use the expansion as an opportunity to clarify hierarchy rather than add another equally weighted destination.

The likely conceptual hierarchy is:

- **Explore** — primary open-ended discovery surface;
- **Connect/Search** — deliberate queries into the graph;
- **Play** — Daily, Connection Guesser, Record Routes, and related games;
- **Browse/Data** — featured albums, graph records, performers, and dataset-oriented views;
- **About/Build** — evidence model, methodology, and cluster/build story.

These are conceptual groupings, not final navigation labels. Any navigation redesign should be driven by actual information architecture work rather than mechanically applying this list.

## Semantic rule to preserve

The performer migration established the clearest public ontology the project has had so far:

> **Connections are musical performances. Credits are the evidence.**

Public copy, graph contracts, generated pages, search, and future features should preserve this distinction.

Non-performance credits may remain valuable source evidence or private research material, but they must not silently recreate public graph edges that contradict the performer-only model.

## Success criteria for the next major milestone

The next major phase should prove that:

1. the public universe can grow well beyond 179 albums without manual editorial effort scaling linearly;
2. a realistic path exists to approximately 500 public studio albums;
3. Explore remains understandable and useful as the graph becomes denser;
4. legitimate obscure performers can remain discoverable without overwhelming ordinary views;
5. featured albums and autogenerated graph records can coexist intentionally;
6. album/performer search can address the larger bounded universe honestly;
7. generated relationships remain explainable from graph facts and evidence;
8. the Zima/Pi fleet performs real, measured work in producing, analyzing, or validating the graph;
9. the static public experience remains independent of home-cluster uptime;
10. the site can publicly communicate the scale, provenance, and build process of the data product without leaking private infrastructure information;
11. existing games continue to work and can benefit from the larger universe without becoming the primary focus of the phase.

## Explicit non-goals for this phase

Do not make these the center of the next plan:

- exhaustive Discogs coverage;
- exposing every Discogs release type as a public destination;
- bespoke editorial writing for every album;
- a live home-hosted API required by the public site;
- another broad visual/copy cleanup pass without a concrete expansion-related need;
- another wholesale game redesign;
- LLM-authored graph truth or opaque recommendation ranking;
- distributed-compute work whose only purpose is demonstrating that multiple machines can participate;
- premature replacement of stable storage, queueing, parser, or graph components without measured evidence.

## Questions the implementation plan must investigate

The product direction is settled enough to begin planning, but several technical/product questions should remain open until the current repository and data are inspected:

1. What should be the precise schema distinction among featured albums, graph records, performer nodes, and evidence-only releases?
2. How should performers whose useful evidence lies outside eligible public studio albums appear in the public graph?
3. What conservative signals can identify a standard studio album/master automatically, and which cases require review?
4. How should candidate expansion scoring balance editorial preference, structural graph value, and coverage gaps?
5. What graph size can the current static artifacts and browser Explore implementation handle before new projections/indexes are necessary?
6. Which layout/rendering approach can support real pan/zoom plus progressive disclosure without producing an unreadable hairball or an unnecessarily heavy client bundle?
7. Which graph metrics remain useful at the larger scale, and which are expensive vanity calculations?
8. How should search be indexed and delivered statically while clearly representing bounded coverage?
9. Which build/analysis/validation stages are best suited to the Zima/Pi fleet, and what measurements prove the distribution is useful?
10. What public build manifest or aggregate telemetry can safely support the restrained cluster/data-story page?
11. What is the safest incremental expansion experiment before committing to the full ~500-album target?

## Planning instruction

The first implementation-planning pass after this document should **investigate before coding**.

It should read the repository’s required architectural/product documents, inspect the current graph/catalog/artifact contracts and recent performer-migration work, measure current Explore/static-artifact limits, inspect the cluster job model, and then propose an incremental sequence that makes the expanded universe real without sacrificing the evidence and static-first principles that already work.

The preferred first deliverable is a rigorous plan with explicit contracts, experiments, measurements, migration boundaries, validation gates, and stop/go criteria—not a large speculative implementation begun in one pass.
