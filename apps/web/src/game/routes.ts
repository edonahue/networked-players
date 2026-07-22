// Client controller for Record Routes (ADR 0046, docs/WEB_PRODUCT_PLAN.md §7
// of the post-Phase-1 plan). Lighter than the Connection Guesser: no chip
// tray of contributors, no clue ladder, no five-round sittings. A round shows
// two real albums; the player guesses the documented-credit path length
// (one or two hops), and -- only when the path is two hops, since a one-hop
// path's "connection" is already the two named endpoints -- optionally names
// the hidden bridging artist. The full path, with evidence at every hop,
// always reveals afterward.

import { fetchAlbumArt, type ResolvedArt } from "./albumArt";
import { createRng } from "./prng";
import { renderSleeve } from "./sleeveRender";
import type {
  RecordRoute,
  RouteEvidenceRelease,
  RoutesRounds,
  RoutesUniverse,
} from "./routesTypes";

const $ = <T extends HTMLElement>(testid: string): T => {
  const el = document.querySelector<T>(`[data-testid="${testid}"]`);
  if (!el) throw new Error(`missing [data-testid="${testid}"]`);
  return el;
};

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`failed to load ${path}: ${response.status}`);
  }
  return (await response.json()) as T;
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
 * a one-hop route (nothing hidden left to name) or if the invariant the
 * generator guarantees ever failed to hold. */
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

export async function initRoutes(): Promise<void> {
  let universe: RoutesUniverse;
  let roundsArtifact: RoutesRounds;
  try {
    [universe, roundsArtifact] = await Promise.all([
      fetchJson<RoutesUniverse>("/data/routes/universe.v1.json"),
      fetchJson<RoutesRounds>("/data/routes/rounds.v1.json"),
    ]);
  } catch {
    showRoutesError(
      "Could not load the route pool right now — try refreshing the page.",
    );
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const route = pickRoute(roundsArtifact.rounds, params);
  const albumById = new Map(universe.albums.map((a) => [a.id, a]));
  const fromAlbum = albumById.get(route.from_album_id);
  const toAlbum = albumById.get(route.to_album_id);
  if (!fromAlbum || !toAlbum) {
    showRoutesError(
      "This route's endpoints could not be verified — try refreshing the page.",
    );
    return;
  }

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
  const nameFor = (id: number) => artistById.get(id) ?? `Artist ${id}`;

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

    const releaseById = new Map(
      roundsArtifact.releases.map((r) => [r.release_id, r]),
    );
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

    const pathLabel =
      route.kind === "one_hop"
        ? `${nameFor(route.from_artist_id)} connects both records directly`
        : `${nameFor(route.from_artist_id)} → ${bridge !== null ? nameFor(bridge) : "an artist"} → ${nameFor(route.to_artist_id)}`;

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
    for (const artistId of options) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.dataset.artist = String(artistId);
      chip.textContent = nameFor(artistId);
      artistTray.append(chip);
    }
    artistStep.hidden = false;
    livePolite.textContent =
      "Path length confirmed. Optionally name the connecting artist.";
  }

  lengthTray.addEventListener("click", (event) => {
    const chip = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "button.chip",
    );
    if (!chip || chip.disabled) return;
    lengthGuess = chip.dataset.length ?? null;
    for (const c of lengthTray.querySelectorAll<HTMLButtonElement>(
      "button.chip",
    )) {
      c.disabled = true;
      c.dataset.chipState =
        c.dataset.length === route.kind
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
    for (const c of artistTray.querySelectorAll<HTMLButtonElement>(
      "button.chip",
    )) {
      c.disabled = true;
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
