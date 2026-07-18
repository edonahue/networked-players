// Client controller for the flagship one-hop Connection Guesser
// (docs/WEB_PRODUCT_PLAN.md §5). Reads the round pool from the page's JSON
// island, drives the pure engine, and renders every phase into the static
// shells in play/connection.astro. Nothing here marks which chip is correct —
// answers are checked in memory, and verdict/evidence markup exists only
// after the round resolves.

import { createEngine, type Engine } from "./engine";
import { createRng } from "./prng";
import { ratingGlyph } from "./scoring";
import { load, recordRound, save, type StorageLike } from "./store";
import { sleeveSvg } from "./sleeves";
import type { AlbumRef, EngineState, GameRound } from "./types";

const $ = <T extends HTMLElement>(testid: string): T => {
  const el = document.querySelector<T>(`[data-testid="${testid}"]`);
  if (!el) throw new Error(`missing [data-testid="${testid}"]`);
  return el;
};

function storage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function poolLabel(round: GameRound): string {
  return round.pool === "real-records" ? "Real records" : "Synthetic universe";
}

function renderSleeve(container: HTMLElement, album: AlbumRef): void {
  container.replaceChildren();
  if (album.art && album.art.kind === "generated") {
    container.innerHTML = sleeveSvg(album);
    return;
  }
  if (album.art && album.art.kind === "hotlink") {
    const img = document.createElement("img");
    img.src = album.art.uri150;
    img.width = 150;
    img.height = 150;
    img.alt = `Cover art for ${album.title}`;
    img.loading = "eager";
    img.addEventListener("error", () => {
      container.replaceChildren(placeholderDisc());
    });
    container.append(img);
    return;
  }
  container.append(placeholderDisc());
}

function placeholderDisc(): HTMLElement {
  const span = document.createElement("span");
  span.className = "album-card__placeholder sleeve__placeholder";
  span.setAttribute("aria-hidden", "true");
  const disc = document.createElement("span");
  disc.className = "album-card__placeholder-disc";
  span.append(disc);
  return span;
}

function pickRound(rounds: GameRound[], params: URLSearchParams): GameRound {
  const pinned = params.get("round");
  if (pinned) {
    const match = rounds.find((r) => r.id === pinned);
    if (match) return match;
  }
  const seed = params.get("seed") ?? String(Date.now());
  const ordered = createRng(`flagship-${seed}`).shuffle(rounds);
  const seen = new Set(load(storage()).seenRounds);
  return ordered.find((r) => !seen.has(r.id)) ?? ordered[0];
}

export function initFlagship(): void {
  const island = document.getElementById("np-round-data");
  if (!island?.textContent) throw new Error("round data island missing");
  const rounds = (JSON.parse(island.textContent) as GameRound[]).filter(
    (round) => round.kind === "one_hop",
  );
  const params = new URLSearchParams(window.location.search);
  if (
    params.get("motion") === "off" ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    document.documentElement.dataset.motion = "off";
  }

  const round = pickRound(rounds, params);
  const stage = $("stage");
  const tray = $("chip-tray");
  const clueButton = $<HTMLButtonElement>("clue-button");
  const giveUp = $<HTMLButtonElement>("give-up");
  const nextButton = $<HTMLButtonElement>("next-round");
  const clueList = $("clue-list");
  const attempts = $("attempts");
  const verdict = $("verdict");
  const verdictHeading = $("verdict-heading");
  const verdictRating = $("verdict-rating");
  const sheet = $("evidence-sheet");
  const provenance = $("provenance-note");
  const livePolite = $("live-region");
  const liveAssertive = $("live-assertive");

  $("pool-badge").textContent = poolLabel(round);
  $("difficulty-tag").textContent = round.difficulty;
  renderSleeve($("sleeve-a"), round.endpoints[0]);
  renderSleeve($("sleeve-b"), round.endpoints[1]);
  $("caption-a").textContent = captionFor(round.endpoints[0]);
  $("caption-b").textContent = captionFor(round.endpoints[1]);
  $("question").textContent =
    "One person is credited on both of these records. Who?";

  const answerIds = new Set(round.answer_set.map((a) => a.id));
  const chipRefs = createRng(`chips-${round.id}`).shuffle([
    ...round.answer_set,
    ...round.distractors,
  ]);

  const chips = chipRefs.map((ref, index) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.setAttribute("role", "radio");
    chip.setAttribute("aria-checked", "false");
    chip.className = "chip";
    chip.dataset.chip = String(ref.id);
    chip.tabIndex = index === 0 ? 0 : -1;
    const name = document.createElement("span");
    name.className = "chip__name";
    name.textContent = ref.name;
    const role = document.createElement("span");
    role.className = "chip__role";
    role.textContent = ref.role_category.replaceAll("_", " ");
    chip.append(name, role);
    tray.append(chip);
    return chip;
  });

  const engine: Engine = createEngine(round, render);

  function captionFor(album: AlbumRef): string {
    const parts = [album.title];
    if (album.act) parts.push(album.act);
    if (album.year) parts.push(String(album.year));
    return parts.join(" · ");
  }

  function announce(message: string, assertive = false): void {
    (assertive ? liveAssertive : livePolite).textContent = message;
  }

  function strikeChip(chip: HTMLButtonElement, state: string): void {
    chip.dataset.chipState = state;
    chip.disabled = true;
    chip.setAttribute("aria-disabled", "true");
  }

  function remainingClues(state: EngineState): number {
    return round.clues.length - state.cluesUsed;
  }

  let announcedStrikes = 0;

  function render(state: EngineState): void {
    stage.dataset.phase = state.phase;
    for (const chip of chips) {
      const id = Number(chip.dataset.chip);
      if (state.struck.includes(id) && chip.dataset.chipState !== "struck") {
        strikeChip(chip, "struck");
      }
    }
    if (state.phase === "guessing") {
      attempts.textContent =
        state.attemptsLeft === 1 ? "Last attempt." : "Two attempts per round.";
      if (state.struck.length > announcedStrikes) {
        announcedStrikes = state.struck.length;
        announce(
          state.attemptsLeft === 1
            ? "Not credited on both. One attempt left."
            : "Not credited on both.",
        );
      }
    } else if (state.phase === "revealed") {
      attempts.textContent = "";
    }
    clueButton.textContent =
      remainingClues(state) > 0
        ? `Use a clue (${remainingClues(state)} left)`
        : "No clues left";
    clueButton.disabled =
      state.phase !== "guessing" || remainingClues(state) === 0;
    giveUp.disabled = state.phase !== "guessing";

    if (state.phase === "revealed") {
      finishRound(state);
    }
  }

  function finishRound(state: EngineState): void {
    for (const chip of chips) {
      chip.disabled = true;
      const id = Number(chip.dataset.chip);
      if (answerIds.has(id)) {
        chip.dataset.chipState = "correct";
        chip.setAttribute("aria-checked", "true");
      }
    }
    const names = round.answer_set.map((a) => a.name).join(" and ");
    verdictHeading.textContent = state.solved
      ? `Solved: ${names}`
      : `The answer was ${names}`;
    verdict.hidden = false;
    verdict.dataset.rating = state.rating ?? "";
    verdictRating.textContent =
      state.rating === "clean"
        ? `${ratingGlyph("clean")} Clean solve — no clues, first pick.`
        : state.rating === "with_clues"
          ? `${ratingGlyph("with_clues")} Solved with help.`
          : `${ratingGlyph("revealed")} Revealed — the liner notes have it.`;
    buildEvidence();
    sheet.hidden = false;
    provenance.textContent = round.provenance_note;
    provenance.hidden = false;
    nextButton.hidden = false;
    announce(verdictHeading.textContent ?? "", true);
    verdictHeading.focus();

    const store = load(storage());
    save(storage(), recordRound(store, round.id, state.rating ?? "revealed"));
  }

  function buildEvidence(): void {
    sheet.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = "The liner notes";
    const stampLine = document.createElement("p");
    stampLine.className = "stamp";
    stampLine.textContent = `${poolLabel(round)} · a credit documents participation on a recording`;
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th scope='col'>Record</th><th scope='col'>Credited as</th><th scope='col'>Role</th></tr>";
    const tbody = document.createElement("tbody");
    for (const row of round.evidence) {
      const tr = document.createElement("tr");
      for (const value of [row.release_title, row.credited_as, row.role_text]) {
        const td = document.createElement("td");
        td.textContent = value;
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(thead, tbody);
    sheet.append(heading, stampLine, table);
  }

  // --- interactions ---------------------------------------------------------
  tray.addEventListener("click", (event) => {
    const chip = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "button.chip",
    );
    if (!chip || chip.disabled) return;
    engine.choose(Number(chip.dataset.chip));
  });

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

  clueButton.addEventListener("click", () => {
    const rung = engine.useClue();
    if (rung < 0) return;
    const clue = round.clues[rung];
    const item = document.createElement("li");
    item.textContent = clue.text;
    clueList.append(item);
    if (clue.kind === "eliminate" && clue.eliminate_ids) {
      for (const chip of chips) {
        if (clue.eliminate_ids.includes(Number(chip.dataset.chip))) {
          strikeChip(chip, "eliminated");
        }
      }
    }
    announce(`Clue: ${clue.text}`);
  });

  giveUp.addEventListener("click", () => engine.reveal());

  nextButton.addEventListener("click", () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("round");
    if (!url.searchParams.get("seed"))
      url.searchParams.set("seed", String(Date.now()));
    window.location.assign(url.toString());
  });

  // --- kick off -------------------------------------------------------------
  announce(
    `Two records on the table: ${captionFor(round.endpoints[0])}, and ${captionFor(round.endpoints[1])}.`,
  );
  engine.deal();
  const dealMs = document.documentElement.dataset.motion === "off" ? 0 : 750;
  window.setTimeout(() => engine.present(), dealMs);
}

initFlagship();
