// Client controller for Record Routes (ADR 0046, docs/WEB_PRODUCT_PLAN.md §7
// of the post-Phase-1 plan). Lighter than the Connection Guesser: no chip
// tray of contributors, no clue ladder, no five-round sittings. A round shows
// two real albums; the player guesses the documented-credit path length
// (one or two hops), and -- only when the path is two hops, since a one-hop
// path's "connection" is already the two named endpoints -- optionally names
// the hidden bridging artist. The full path, with evidence at every hop,
// always reveals afterward.
//
// Every fetched value is untrusted input: `validateRoutesPool`/
// `resolveSelectedRoute` (routesResolver.ts) verify the whole pool and the
// one route actually dealt before anything renders. A malformed fetch,
// wrong-mode artifact, version mismatch, or unresolved reference always
// produces the typed integrity-error state below -- never a substituted
// route, never a thrown exception, never "Artist <id>" standing in for a
// name the resolver failed to verify.

import { fetchAlbumArt, type ResolvedArt } from "./albumArt";
import { createRng } from "./prng";
import {
  resolveSelectedRoute,
  validateRoutesPool,
  type PoolValidation,
  type RouteValidation,
} from "./routesResolver";
import { renderSleeve } from "./sleeveRender";
import type { RecordRoute, RouteEvidenceRelease } from "./routesTypes";

const $ = <T extends HTMLElement>(testid: string): T => {
  const el = document.querySelector<T>(`[data-testid="${testid}"]`);
  if (!el) throw new Error(`missing [data-testid="${testid}"]`);
  return el;
};

async function fetchJson(path: string): Promise<unknown> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`failed to load ${path}: ${response.status}`);
  }
  return await response.json();
}

type PoolFailureReason = Extract<PoolValidation, { ok: false }>["reason"];
type RouteFailureReason = Extract<RouteValidation, { ok: false }>["reason"];

/** User-facing, spoiler-free text per integrity-failure reason. Distinct
 * internally (tests can tell them apart) even where the UI text is
 * deliberately similar -- a player never needs to know WHICH check failed,
 * only that the round on screen can't be trusted. */
function poolIntegrityMessage(reason: PoolFailureReason): string {
  switch (reason) {
    case "malformed-pool":
      return "Could not load the route pool right now — try refreshing the page.";
    case "wrong-mode":
      return "The fetched route pool isn't the Record Routes contract — try refreshing the page.";
    case "version-mismatch":
      return "The route pool's two files don't agree with each other — try refreshing the page.";
    case "empty-pool":
      return "No routes are available right now — try refreshing the page.";
  }
}

function routeIntegrityMessage(reason: RouteFailureReason): string {
  switch (reason) {
    case "missing-endpoint-album":
      return "This route's endpoints could not be verified — try refreshing the page.";
    case "unresolved-hop-reference":
      return "This route's evidence could not be verified — try refreshing the page.";
    case "ambiguous-bridge":
      return "This route's connecting artist could not be verified — try refreshing the page.";
  }
}

function showRoutesError(message: string): void {
  const stage = document.querySelector('[data-testid="routes-stage"]');
  const question = document.querySelector('[data-testid="routes-question"]');
  if (question) question.textContent = message;
  stage?.setAttribute("data-phase", "error");
  for (const testid of ["routes-length-tray", "routes-artist-step"]) {
    const el = document.querySelector<HTMLElement>(`[data-testid="${testid}"]`);
    // `.chip-tray` sets `display:flex` unconditionally in game.css, which
    // (unlike the Guesser's initially-EMPTY chip tray) outranks the bare
    // `[hidden]` UA rule for this tray's non-empty static markup -- set the
    // inline style too so it's actually hidden, not just marked as such.
    el?.setAttribute("hidden", "");
    if (el) el.style.display = "none";
  }
  const liveAssertive = document.querySelector(
    '[data-testid="routes-live-assertive"]',
  );
  if (liveAssertive) liveAssertive.textContent = message;
}

function pickRoute(
  rounds: RecordRoute[],
  params: URLSearchParams,
): RecordRoute {
  const pinned = params.get("route");
  if (pinned) {
    const match = rounds.find((r) => r.id === pinned);
    if (match) return match;
  }
  const seed = params.get("seed") ?? String(Date.now());
  const ordered = createRng(`routes-${seed}`).shuffle(rounds);
  return ordered[0];
}

/** The artist shared between a two-hop route's two hops -- the hidden
 * bridging identity, distinct from either named endpoint artist. `null` for
 * a one-hop route (nothing hidden left to name). Callers only reach this
 * after `resolveSelectedRoute` has already proven exactly one such artist
 * exists for a two-hop route, so the `?? null` fallback here is defensive,
 * not a real code path. */
function bridgeArtistId(route: RecordRoute): number | null {
  if (route.kind !== "two_hop" || route.hops.length !== 2) return null;
  const [hop0, hop1] = route.hops;
  const sideA = new Set([hop0.artist_a_id, hop0.artist_b_id]);
  const sideB = new Set([hop1.artist_a_id, hop1.artist_b_id]);
  const shared = [...sideA].find(
    (id) =>
      sideB.has(id) && id !== route.from_artist_id && id !== route.to_artist_id,
  );
  return shared ?? null;
}

/** Roving-tabindex arrow-key navigation for a `role="radio"` chip tray --
 * mirrors flagship.ts's `makeChip`/tray keydown handler exactly, so both
 * game modes share one keyboard model. */
function wireRadioTray(tray: HTMLElement, chips: HTMLButtonElement[]): void {
  tray.addEventListener("keydown", (event) => {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const enabled = chips.filter((chip) => !chip.disabled);
    if (enabled.length === 0) return;
    const current = document.activeElement as HTMLButtonElement | null;
    const index = Math.max(0, enabled.indexOf(current as HTMLButtonElement));
    const delta =
      event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
    const next = enabled[(index + delta + enabled.length) % enabled.length];
    for (const chip of chips) chip.tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
  });
}

export async function initRoutes(): Promise<void> {
  let universeRaw: unknown;
  let roundsRaw: unknown;
  try {
    [universeRaw, roundsRaw] = await Promise.all([
      fetchJson("/data/routes/universe.v1.json"),
      fetchJson("/data/routes/rounds.v1.json"),
    ]);
  } catch {
    showRoutesError(
      "Could not load the route pool right now — try refreshing the page.",
    );
    return;
  }

  const poolResult = validateRoutesPool(universeRaw, roundsRaw);
  if (!poolResult.ok) {
    showRoutesError(poolIntegrityMessage(poolResult.reason));
    return;
  }
  const { universe, roundsArtifact, routes: pool } = poolResult;

  const params = new URLSearchParams(window.location.search);
  const route = pickRoute(pool, params);

  const routeResult = resolveSelectedRoute(route, universe, roundsArtifact);
  if (!routeResult.ok) {
    showRoutesError(routeIntegrityMessage(routeResult.reason));
    return;
  }

  // Every reference below is now guaranteed to resolve -- resolveSelectedRoute
  // already proved it. `!` reflects that guarantee, not an unchecked assumption.
  const albumById = new Map(universe.albums.map((a) => [a.id, a]));
  const fromAlbum = albumById.get(route.from_album_id)!;
  const toAlbum = albumById.get(route.to_album_id)!;

  const artMap: Map<string, ResolvedArt> = await fetchAlbumArt(
    universe.provenance.catalog_version,
  );

  const stage = $("routes-stage");
  const lengthTray = $("routes-length-tray");
  const artistStep = $("routes-artist-step");
  const artistTray = $("routes-artist-tray");
  const skipArtist = $<HTMLButtonElement>("routes-skip-artist");
  const verdict = $("routes-verdict");
  const verdictHeading = $("routes-verdict-heading");
  const verdictRating = $("routes-verdict-rating");
  const evidenceMount = $("routes-evidence-mount");
  const provenanceNote = $("routes-provenance-note");
  const nextButton = $<HTMLButtonElement>("routes-next");
  const livePolite = $("routes-live-region");
  const liveAssertive = $("routes-live-assertive");

  stage.dataset.route = route.id;
  stage.dataset.kind = route.kind;
  $("routes-difficulty-tag").textContent = route.difficulty;
  $("routes-pool-badge").textContent = "Real records";
  renderSleeve($("routes-sleeve-a"), fromAlbum, artMap);
  renderSleeve($("routes-sleeve-b"), toAlbum, artMap);
  const captionFor = (a: {
    title: string;
    artist: string;
    year: number | null;
  }): string =>
    [a.title, a.artist, a.year ? String(a.year) : null]
      .filter(Boolean)
      .join(" · ");
  $("routes-caption-a").textContent = captionFor(fromAlbum);
  $("routes-caption-b").textContent = captionFor(toAlbum);
  stage.setAttribute("data-phase", "guessing");

  const artistById = new Map(
    roundsArtifact.artists.map((a) => [a.artist_id, a.name]),
  );
  const releaseById = new Map(
    roundsArtifact.releases.map((r) => [r.release_id, r]),
  );
  // Every id this reads was already proven to resolve by resolveSelectedRoute
  // -- the fallback is unreachable in practice, kept only so a future caller
  // outside that guarantee fails loudly (a visibly wrong name) rather than
  // crashing.
  const nameFor = (id: number) =>
    artistById.get(id) ?? `Unverified artist ${id}`;

  const lengthChips = Array.from(
    lengthTray.querySelectorAll<HTMLButtonElement>("button.chip"),
  );
  wireRadioTray(lengthTray, lengthChips);

  let lengthGuess: string | null = null;
  let artistGuess: number | null = null;

  function buildEvidence(): void {
    evidenceMount.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = "The documented route";
    const stampLine = document.createElement("p");
    stampLine.className = "stamp";
    stampLine.textContent =
      "Real records · every hop is a documented liner-note credit shared on one release";
    evidenceMount.append(heading, stampLine);

    route.hops.forEach((hop, index) => {
      const release: RouteEvidenceRelease | undefined = releaseById.get(
        hop.release_id,
      );
      const section = document.createElement("div");
      section.className = "path-card";
      const summary = document.createElement("h4");
      summary.textContent = `Hop ${index + 1}: ${nameFor(hop.artist_a_id)} → ${nameFor(hop.artist_b_id)}`;
      section.append(summary);
      if (release) {
        const sub = document.createElement("p");
        sub.className = "path-card__sub";
        sub.textContent = release.title;
        section.append(sub);
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        thead.innerHTML =
          "<tr><th scope='col'>Credited as</th><th scope='col'>Role</th></tr>";
        const tbody = document.createElement("tbody");
        for (const credit of release.credits) {
          if (
            credit.artist_id !== hop.artist_a_id &&
            credit.artist_id !== hop.artist_b_id
          ) {
            continue;
          }
          const tr = document.createElement("tr");
          for (const value of [
            credit.anv || credit.name,
            credit.role_text || "",
          ]) {
            const td = document.createElement("td");
            td.textContent = value;
            tr.append(td);
          }
          tbody.append(tr);
        }
        table.append(thead, tbody);
        section.append(table);
      }
      evidenceMount.append(section);
    });
  }

  function reveal(): void {
    const lengthCorrect = lengthGuess === route.kind;
    const bridge = bridgeArtistId(route);
    const artistCorrect = bridge === null ? null : artistGuess === bridge;

    let ratingText: string;
    if (lengthCorrect && (artistCorrect === null || artistCorrect)) {
      ratingText = "Clean — every guess documented.";
    } else if (lengthCorrect) {
      ratingText = "Length confirmed — the bridging artist was different.";
    } else {
      ratingText = "Revealed — here is the documented route.";
    }

    // A one-hop route's "connection" is the two named endpoint artists
    // themselves sharing a credit -- neither is a third party "connecting"
    // the other's record, so the copy names both and the shared release
    // rather than singling one out as if it bridged the pair.
    let pathLabel: string;
    if (route.kind === "one_hop") {
      const releaseTitle =
        releaseById.get(route.hops[0].release_id)?.title ?? "one release";
      pathLabel =
        `${nameFor(route.from_artist_id)} and ${nameFor(route.to_artist_id)} ` +
        `share a documented credit on ${releaseTitle}`;
    } else {
      pathLabel = `${nameFor(route.from_artist_id)} → ${bridge !== null ? nameFor(bridge) : "an artist"} → ${nameFor(route.to_artist_id)}`;
    }

    verdictHeading.textContent =
      route.kind === "one_hop" ? "One documented hop" : "Two documented hops";
    verdictRating.textContent = `${ratingText} ${pathLabel}.`;
    verdict.hidden = false;
    verdictHeading.tabIndex = -1;
    verdictHeading.focus();

    buildEvidence();
    provenanceNote.textContent =
      "Real records: derived from the Discogs monthly data dump (CC0). A shared credit " +
      "documents participation on a recording, nothing more.";
    provenanceNote.hidden = false;
    nextButton.hidden = false;
    stage.setAttribute("data-phase", "revealed");
    liveAssertive.textContent = `${verdictHeading.textContent}. ${ratingText}`;
  }

  function startArtistStepOrReveal(): void {
    const bridge = bridgeArtistId(route);
    if (bridge === null) {
      reveal();
      return;
    }
    // Build a small tray: the real bridge plus a few plausible distractor
    // artists (other real artists in this pool, never the endpoints).
    const excluded = new Set([
      route.from_artist_id,
      route.to_artist_id,
      bridge,
    ]);
    const candidates = roundsArtifact.artists
      .map((a) => a.artist_id)
      .filter((id) => !excluded.has(id));
    const distractors = createRng(`routes-artist-${route.id}`)
      .shuffle(candidates)
      .slice(0, 3);
    const options = createRng(`routes-artist-order-${route.id}`).shuffle([
      bridge,
      ...distractors,
    ]);
    artistTray.replaceChildren();
    const artistChips: HTMLButtonElement[] = [];
    options.forEach((artistId, index) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.setAttribute("role", "radio");
      chip.setAttribute("aria-checked", "false");
      chip.tabIndex = index === 0 ? 0 : -1;
      chip.className = "chip";
      chip.dataset.artist = String(artistId);
      chip.textContent = nameFor(artistId);
      artistTray.append(chip);
      artistChips.push(chip);
    });
    wireRadioTray(artistTray, artistChips);
    artistStep.hidden = false;
    livePolite.textContent =
      "Path length confirmed. Optionally name the connecting artist.";
    artistChips[0]?.focus();
  }

  lengthTray.addEventListener("click", (event) => {
    const chip = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "button.chip",
    );
    if (!chip || chip.disabled) return;
    lengthGuess = chip.dataset.length ?? null;
    for (const c of lengthChips) {
      c.disabled = true;
      const isCorrect = c.dataset.length === route.kind;
      c.setAttribute("aria-checked", isCorrect ? "true" : "false");
      c.dataset.chipState = isCorrect
        ? "correct"
        : c === chip
          ? "struck"
          : c.dataset.chipState;
    }
    startArtistStepOrReveal();
  });

  artistTray.addEventListener("click", (event) => {
    const chip = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "button.chip",
    );
    if (!chip || chip.disabled) return;
    artistGuess = Number(chip.dataset.artist);
    const bridge = bridgeArtistId(route);
    for (const c of artistTray.querySelectorAll<HTMLButtonElement>(
      "button.chip",
    )) {
      c.disabled = true;
      c.setAttribute(
        "aria-checked",
        Number(c.dataset.artist) === bridge ? "true" : "false",
      );
    }
    reveal();
  });

  skipArtist.addEventListener("click", () => {
    artistGuess = null;
    reveal();
  });

  nextButton.addEventListener("click", () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("route");
    url.searchParams.set("seed", String(Date.now()));
    window.location.assign(url.toString());
  });
}
