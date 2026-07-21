// Client controller for the flagship Connection Guesser
// (docs/WEB_PRODUCT_PLAN.md §5). Fetches the round pool at runtime
// (fetchRounds), drives the pure engine, and renders every phase into the
// static shells in play/connection.astro. One-hop rounds ask a single
// question; two-hop rounds walk bridge_a → bridge_b → hidden middle,
// rebuilding the tray per step. Nothing here marks which chip is correct —
// answers are checked in memory, and verdict/evidence markup exists only
// after the round resolves.

import { createEngine, type Engine } from "./engine";
import { createRng, dailySeed } from "./prng";
import { ratingGlyph, summarizeSet } from "./scoring";
import {
  load,
  loadSet,
  recordDaily,
  recordRound,
  recordSetRound,
  save,
  saveSet,
  SET_SIZE,
  setComplete,
  freshSet,
  type GameStore,
  type SetState,
  type StorageLike,
} from "./store";
import { sleeveSvg } from "./sleeves";
import type {
  AlbumRef,
  ContributorRef,
  EngineState,
  GameRound,
  Rating,
  Step,
} from "./types";

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

/** The set lives with the sitting: sessionStorage, degrading silently. */
function sessionStore(): StorageLike | null {
  try {
    return window.sessionStorage;
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

/** The face-down hidden-middle slot: a question mark, never a spoiler. */
function mysterySleeve(): HTMLElement {
  const span = document.createElement("span");
  span.className = "sleeve__mystery";
  span.setAttribute("aria-hidden", "true");
  span.textContent = "?";
  return span;
}

function pickRound(
  rounds: GameRound[],
  params: URLSearchParams,
  set: SetState,
): GameRound {
  const pinned = params.get("round");
  if (pinned) {
    const match = rounds.find((r) => r.id === pinned);
    if (match) return match;
  }
  const pool = rounds.filter((r) => r.kind === set.kind);
  const ordered = createRng(`flagship-${set.seed}`).shuffle(pool);
  const inSet = new Set(set.entries.map((e) => e.roundId));
  const seen = new Set(load(storage()).seenRounds);
  return (
    ordered.find((r) => !inSet.has(r.id) && !seen.has(r.id)) ??
    ordered.find((r) => !inSet.has(r.id)) ??
    ordered[set.entries.length % ordered.length]
  );
}

/** The daily deal: derived from the UTC date alone — the same for everyone. */
function pickDaily(rounds: GameRound[], isoDate: string): GameRound {
  const pool = rounds.filter((r) => r.kind === "one_hop");
  const seed = dailySeed(new Date(`${isoDate}T12:00:00Z`));
  return createRng(seed).shuffle(pool)[0];
}

export interface FlagshipOptions {
  /** Connection of the Day: deterministic date round, streaks, no set arc. */
  daily?: boolean;
}

/** The real pool is fetched at runtime, not embedded in the page -- it is
 * well past a reasonable inline-HTML budget at real-launch scale (500 real
 * rounds, ~1.2 MB). Cached by the browser like any other static asset after
 * the first load; nothing here is per-user or per-request. */
async function fetchRounds(): Promise<GameRound[]> {
  const response = await fetch("/data/game/rounds.v1.json");
  if (!response.ok) {
    throw new Error(`failed to load rounds.v1.json: ${response.status}`);
  }
  const data = (await response.json()) as { rounds: GameRound[] };
  return data.rounds;
}

export async function initFlagship(
  options: FlagshipOptions = {},
): Promise<void> {
  let rounds: GameRound[];
  try {
    rounds = await fetchRounds();
  } catch {
    const stage = document.querySelector('[data-testid="stage"]');
    const question = document.querySelector('[data-testid="question"]');
    if (question) {
      question.textContent =
        "Could not load the round pool right now — try refreshing the page.";
    }
    stage?.setAttribute("data-phase", "error");
    return;
  }
  const params = new URLSearchParams(window.location.search);
  if (
    params.get("motion") === "off" ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    document.documentElement.dataset.motion = "off";
  }

  const daily = options.daily === true;
  const isoDate = daily
    ? (params.get("date") ?? new Date().toISOString().slice(0, 10))
    : "";

  const activeKind =
    !daily && params.get("kind") === "two_hop" ? "two_hop" : "one_hop";
  document
    .querySelector(`[data-testid="kind-toggle"] a[data-kind="${activeKind}"]`)
    ?.setAttribute("aria-current", "true");

  let set = daily
    ? freshSet(activeKind, `daily-${isoDate}`)
    : loadSet(
        sessionStore(),
        activeKind,
        params.get("seed") ?? String(Date.now()),
      );
  if (!daily) saveSet(sessionStore(), set);

  const round = daily
    ? pickDaily(rounds, isoDate)
    : pickRound(rounds, params, set);
  const stage = $("stage");
  const tray = $("chip-tray");
  const clueButton = $<HTMLButtonElement>("clue-button");
  const giveUp = $<HTMLButtonElement>("give-up");
  const nextButton = $<HTMLButtonElement>("next-round");
  const clueList = $("clue-list");
  const attempts = $("attempts");
  const setProgress = $("set-progress");
  const setSummary = $("set-summary");
  const dailyPanel = $("daily-panel");
  const stepLabel = $("step-label");
  const middleSlot = $("middle-slot");
  const middleArt = $("sleeve-middle");
  const middleCaption = $("caption-middle");
  const verdict = $("verdict");
  const verdictHeading = $("verdict-heading");
  const verdictRating = $("verdict-rating");
  const sheet = $("evidence-sheet");
  const provenance = $("provenance-note");
  const livePolite = $("live-region");
  const liveAssertive = $("live-assertive");

  const twoHop = round.kind === "two_hop";
  stage.dataset.kind = round.kind;
  stage.dataset.round = round.id;
  $("pool-badge").textContent = poolLabel(round);
  $("difficulty-tag").textContent = round.difficulty;
  renderSleeve($("sleeve-a"), round.endpoints[0]);
  renderSleeve($("sleeve-b"), round.endpoints[1]);
  $("caption-a").textContent = captionFor(round.endpoints[0]);
  $("caption-b").textContent = captionFor(round.endpoints[1]);
  if (twoHop) {
    middleSlot.hidden = false;
    middleArt.replaceChildren(mysterySleeve());
    middleCaption.textContent = "Hidden record";
  }

  /** "Round N of 5" plus the groove glyphs earned so far this sitting. */
  function renderSetProgress(): void {
    if (daily) {
      setProgress.textContent = `Connection of the Day · ${isoDate}`;
      return;
    }
    const glyphs = set.entries.map((e) => ratingGlyph(e.rating)).join(" ");
    const current = Math.min(set.entries.length + 1, SET_SIZE);
    setProgress.textContent = setComplete(set)
      ? `Set complete · ${glyphs}`
      : glyphs
        ? `Round ${current} of ${SET_SIZE} · ${glyphs}`
        : `Round ${current} of ${SET_SIZE}`;
  }
  renderSetProgress();

  // Replay guard: the daily is one play per day. A recorded result renders
  // the stored spoiler-free card instead of re-dealing the round.
  if (daily) {
    const playedShare = load(storage()).daily[isoDate];
    if (playedShare) {
      tray.hidden = true;
      attempts.hidden = true;
      clueButton.hidden = true;
      giveUp.hidden = true;
      $("question").textContent = "You've already played today's connection.";
      stage.dataset.phase = "played";
      buildDailyPanel(playedShare, load(storage()).streak, true);
      dailyPanel.hidden = false;
      announce("You've already played today's connection. Come back tomorrow.");
      return;
    }
  }

  let chips: HTMLButtonElement[] = [];

  /** Contributor refs that answer a given step -- one-hop's `answer_set`,
   * or the relevant side of a two-hop's `bridge_answer_sets`. Two-hop's
   * `answer_set` is always empty (the connection has no single "the
   * answer"; each bridge does), so callers must go through this rather
   * than reading `round.answer_set` directly for a two-hop round. */
  function answersForStep(step: Step): ContributorRef[] {
    if (step === "single" || !round.bridge_answer_sets) {
      return round.answer_set;
    }
    const [a, b] = round.bridge_answer_sets;
    return step === "bridge_a" ? a : b;
  }

  /** Contributor refs for the tray of a given step. */
  function stepRefs(step: Step): ContributorRef[] {
    return [...answersForStep(step), ...round.distractors];
  }

  function questionFor(step: Step): string {
    const [a, b] = round.endpoints;
    switch (step) {
      case "single":
        return "One eligible performer is credited on both of these records. Who?";
      case "bridge_a":
        // Precise, not "no one": a producer/engineer could still be credited
        // on both without satisfying the game's performer-only eligibility
        // rule (instrument/vocal credits only) -- see eligibility.py.
        return `No eligible performer appears on both of these records — a hidden middle record links them. Who is credited on both ${a.title} and the hidden record?`;
      case "bridge_b":
        return `Now the other side: who is credited on both ${b.title} and the hidden record?`;
      case "middle":
        return "Last step: which record is the hidden middle?";
    }
  }

  function stepLabelFor(step: Step): string {
    switch (step) {
      case "single":
        return "";
      case "bridge_a":
        return "Step 1 of 3 · first bridge";
      case "bridge_b":
        return "Step 2 of 3 · second bridge";
      case "middle":
        return "Step 3 of 3 · the hidden record";
    }
  }

  function makeChip(value: string, index: number): HTMLButtonElement {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.setAttribute("role", "radio");
    chip.setAttribute("aria-checked", "false");
    chip.className = "chip";
    chip.dataset.chip = value;
    chip.tabIndex = index === 0 ? 0 : -1;
    return chip;
  }

  function buildContributorTray(step: Step): void {
    tray.replaceChildren();
    const refs = createRng(`chips-${round.id}-${step}`).shuffle(stepRefs(step));
    chips = refs.map((ref, index) => {
      const chip = makeChip(String(ref.id), index);
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
  }

  /** Middle-step tray: album choices as mini-sleeve chips (choices ship pre-shuffled). */
  function buildMiddleTray(): void {
    if (!round.middle) return;
    tray.replaceChildren();
    chips = round.middle.choices.map((album, index) => {
      const chip = makeChip(album.id, index);
      chip.classList.add("chip--album");
      const art = document.createElement("span");
      art.className = "chip__sleeve";
      art.setAttribute("aria-hidden", "true");
      renderSleeve(art, album);
      const name = document.createElement("span");
      name.className = "chip__name";
      name.textContent = album.title;
      const role = document.createElement("span");
      role.className = "chip__role";
      role.textContent = captionFor(album).replace(`${album.title} · `, "");
      chip.append(art, name, role);
      tray.append(chip);
      return chip;
    });
  }

  let trayStep: Step | null = null;
  /** A paid eliminate clue keeps its strikes across step tray rebuilds. */
  const eliminatedIds = new Set<number>();

  function syncTray(state: EngineState): void {
    if (state.step !== trayStep) {
      trayStep = state.step;
      if (state.step === "middle") buildMiddleTray();
      else buildContributorTray(state.step);
      tray.setAttribute(
        "aria-label",
        state.step === "middle"
          ? "Pick the hidden middle record"
          : "Pick the contributor credited on both records",
      );
      stepLabel.textContent = stepLabelFor(state.step);
      $("question").textContent = questionFor(state.step);
    }
    for (const chip of chips) {
      const value = chip.dataset.chip ?? "";
      if (state.step !== "middle" && eliminatedIds.has(Number(value))) {
        if (chip.dataset.chipState !== "eliminated") {
          strikeChip(chip, "eliminated");
        }
        continue;
      }
      const struck =
        state.step === "middle"
          ? state.struckAlbums.includes(value)
          : state.struck.includes(Number(value));
      if (struck && chip.dataset.chipState !== "struck") {
        strikeChip(chip, "struck");
      }
    }
  }

  const engine: Engine = createEngine(round, render);

  function captionFor(album: AlbumRef): string {
    const parts = [album.title];
    if (album.act) parts.push(album.act);
    if (album.year) parts.push(String(album.year));
    return parts.join(" · ");
  }

  function namesFor(refs: ContributorRef[]): string {
    return refs.map((r) => r.name).join(" and ");
  }

  /** The full, honest reveal text: one-hop names every valid answer;
   * two-hop names both bridges (each may itself have more than one valid
   * performer) plus the hidden middle record. Never reads from a single
   * `answer_set` for a two-hop round -- it's always empty there by design
   * (see `answersForStep`). */
  function describeAnswer(): string {
    if (!twoHop || !round.middle || !round.bridge_answer_sets) {
      return namesFor(round.answer_set);
    }
    const [bridgeA, bridgeB] = round.bridge_answer_sets;
    return (
      `${namesFor(bridgeA)} on one side and ${namesFor(bridgeB)} on the other, ` +
      `through the hidden record ${round.middle.album.title}`
    );
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
  let announcedSteps = 0;

  function render(state: EngineState): void {
    stage.dataset.phase = state.phase;
    stage.dataset.step = state.step;
    syncTray(state);
    if (state.phase === "guessing") {
      attempts.textContent =
        state.attemptsLeft === 1
          ? "Last attempt."
          : twoHop
            ? "Two attempts per step."
            : "Two attempts per round.";
      const strikes = state.struck.length + state.struckAlbums.length;
      if (strikes > announcedStrikes) {
        announcedStrikes = strikes;
        announce(
          state.attemptsLeft === 1
            ? "Not this one. One attempt left."
            : "Not this one.",
        );
      }
      if (state.solvedSteps.length > announcedSteps) {
        announcedSteps = state.solvedSteps.length;
        announce(`Found. ${questionFor(state.step)}`);
        chips.find((chip) => !chip.disabled)?.focus();
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
    // trayStep reflects whichever step's tray last rendered -- the step the
    // player was on when the round resolved (solved, struck out, or gave
    // up). Its correct-answer set must come from THAT step, never a single
    // round-wide `answer_set` -- two-hop rounds don't have one (each bridge
    // does), so using it here was always empty for a two-hop round and no
    // chip was ever marked correct on a give-up/fail before the middle step.
    const stepAnswerIds =
      trayStep === "middle"
        ? null
        : new Set(answersForStep(trayStep ?? "single").map((a) => a.id));
    for (const chip of chips) {
      chip.disabled = true;
      const value = chip.dataset.chip ?? "";
      const correct =
        trayStep === "middle"
          ? value === round.middle?.album.id
          : (stepAnswerIds?.has(Number(value)) ?? false);
      if (correct) {
        chip.dataset.chipState = "correct";
        chip.setAttribute("aria-checked", "true");
      }
    }
    if (twoHop && round.middle) {
      renderSleeve(middleArt, round.middle.album);
      middleCaption.textContent = captionFor(round.middle.album);
    }
    const path = describeAnswer();
    verdictHeading.textContent = state.solved
      ? `Solved: ${path}`
      : `The answer was ${path}`;
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

    const rating = state.rating ?? "revealed";
    if (daily) {
      nextButton.hidden = true;
      const share = shareString(rating, state.cluesUsed);
      const updated = recordDaily(load(storage()), isoDate, rating, share);
      save(storage(), updated);
      buildDailyPanel(share, updated.streak, false);
      dailyPanel.hidden = false;
      return;
    }

    const store = load(storage());
    save(storage(), recordRound(store, round.id, rating));

    set = recordSetRound(set, round.id, rating);
    saveSet(sessionStore(), set);
    renderSetProgress();
    if (setComplete(set)) {
      buildSetSummary();
      setSummary.hidden = false;
      nextButton.textContent = "Start a new set";
    } else {
      nextButton.textContent = `Next round (${set.entries.length + 1} of ${SET_SIZE})`;
    }
  }

  /** Spoiler-free by construction: the date and glyphs — never a name. */
  function shareString(rating: Rating, cluesUsed: number): string {
    const clueNote =
      cluesUsed > 0 ? ` · ${cluesUsed} clue${cluesUsed === 1 ? "" : "s"}` : "";
    return `Networked Players · Connection of the Day ${isoDate} · ${ratingGlyph(rating)}${clueNote}`;
  }

  /** The daily card: share text, copy, streak, and the honest ground rules. */
  function buildDailyPanel(
    share: string,
    streak: GameStore["streak"],
    alreadyPlayed: boolean,
  ): void {
    dailyPanel.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = alreadyPlayed
      ? "Already in the crate today"
      : "Connection of the Day";
    const shareLine = document.createElement("p");
    shareLine.className = "daily-panel__share";
    shareLine.dataset.testid = "share-string";
    shareLine.textContent = share;
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "stage__action";
    copy.dataset.testid = "share-copy";
    copy.textContent = "Copy share text";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(share);
        copy.textContent = "Copied";
      } catch {
        announce("Copy failed — select the share text above instead.");
      }
    });
    const streakLine = document.createElement("p");
    streakLine.dataset.testid = "streak-line";
    streakLine.textContent =
      streak.current > 0
        ? `Streak: ${streak.current} day${streak.current === 1 ? "" : "s"} · best ${streak.best}`
        : `Streak reset — best ${streak.best}.`;
    const note = document.createElement("p");
    note.className = "stamp";
    note.textContent = alreadyPlayed
      ? "One connection per day. Tomorrow's record is already on its way."
      : "Same connection for everyone today. Share the grooves, never the answer.";
    dailyPanel.append(heading, shareLine, copy, streakLine, note);
  }

  /** The needle-drop set card: glyph strip, counts, and a local-only note. */
  function buildSetSummary(): void {
    setSummary.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = "Set complete";
    const glyphs = document.createElement("p");
    glyphs.className = "set-summary__glyphs";
    glyphs.textContent = set.entries
      .map((e) => ratingGlyph(e.rating))
      .join(" ");
    const summary = summarizeSet(set.entries.map((e) => e.rating));
    const parts: string[] = [];
    if (summary.clean) parts.push(`${summary.clean} clean`);
    if (summary.withClues) parts.push(`${summary.withClues} with help`);
    if (summary.revealed) parts.push(`${summary.revealed} revealed`);
    const line = document.createElement("p");
    line.textContent = `${summary.played} rounds this sitting — ${parts.join(", ")}.`;
    const note = document.createElement("p");
    note.className = "stamp";
    note.textContent =
      "Ratings stay on this device. A new set starts whenever you do.";
    setSummary.append(heading, glyphs, line, note);
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
    const value = chip.dataset.chip ?? "";
    engine.choose(trayStep === "middle" ? value : Number(value));
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
      for (const id of clue.eliminate_ids) eliminatedIds.add(id);
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
    if (setComplete(set)) {
      // A finished set: reseed the sitting and let the next load start fresh.
      saveSet(sessionStore(), freshSet(activeKind, String(Date.now())));
      url.searchParams.delete("seed");
    }
    window.location.assign(url.toString());
  });

  // --- kick off -------------------------------------------------------------
  announce(
    `Two records on the table: ${captionFor(round.endpoints[0])}, and ${captionFor(round.endpoints[1])}.${twoHop ? " A hidden record sits between them." : ""}`,
  );
  engine.deal();
  const dealMs = document.documentElement.dataset.motion === "off" ? 0 : 750;
  window.setTimeout(() => engine.present(), dealMs);
}
