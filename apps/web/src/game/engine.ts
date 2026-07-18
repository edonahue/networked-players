// Round engine: the pure state machine from docs/WEB_PRODUCT_PLAN.md §5.
//
//   idle → dealing → guessing ⇄ (clue) → resolving → revealed
//
// Two-hop rounds walk three steps inside `guessing`: bridge_a → bridge_b →
// middle (bridges-then-hidden-middle). The engine owns no DOM and does no
// I/O; the UI layer renders snapshots and calls actions, which is what keeps
// ambitious interaction testable without pixel assertions.

import type { EngineState, GameRound, Rating, Step } from "./types";
import { rateRound } from "./scoring";

const ATTEMPTS_PER_STEP = 2;

export interface Engine {
  readonly round: GameRound;
  state(): EngineState;
  /** idle → dealing. */
  deal(): void;
  /** dealing → guessing (animation finished or skipped). */
  present(): void;
  /** Answer the current step with a contributor id (or album id for `middle`). */
  choose(choice: number | string): void;
  /** Reveal the next clue rung; returns the rung index or -1 when exhausted. */
  useClue(): number;
  /** Give up: resolve the round as revealed. */
  reveal(): void;
}

function initialStep(round: GameRound): Step {
  return round.kind === "one_hop" ? "single" : "bridge_a";
}

export function createEngine(
  round: GameRound,
  onChange?: (state: EngineState) => void,
): Engine {
  let state: EngineState = {
    phase: "idle",
    step: initialStep(round),
    attemptsLeft: ATTEMPTS_PER_STEP,
    cluesUsed: 0,
    struck: [],
    struckAlbums: [],
    solvedSteps: [],
    solved: false,
    failed: false,
    rating: null,
  };
  let wrongAttempts = 0;

  const emit = () => {
    if (onChange) onChange({ ...state });
  };

  const answerIds = (step: Step): Set<number> => {
    if (step === "single") {
      return new Set(round.answer_set.map((a) => a.id));
    }
    if (!round.bridge_answer_sets) return new Set();
    const [a, b] = round.bridge_answer_sets;
    return new Set((step === "bridge_a" ? a : b).map((entry) => entry.id));
  };

  const resolve = (solved: boolean) => {
    state.solved = solved;
    state.failed = !solved;
    state.phase = "resolving";
    const rating: Rating = rateRound({
      solved,
      cluesUsed: state.cluesUsed,
      wrongAttempts,
    });
    state.rating = rating;
    state.phase = "revealed";
    emit();
  };

  const advanceStep = () => {
    state.solvedSteps = [...state.solvedSteps, state.step];
    if (round.kind === "one_hop") {
      resolve(true);
      return;
    }
    if (state.step === "bridge_a") {
      state.step = "bridge_b";
    } else if (state.step === "bridge_b") {
      state.step = "middle";
    } else {
      resolve(true);
      return;
    }
    state.attemptsLeft = ATTEMPTS_PER_STEP;
    emit();
  };

  return {
    round,
    state: () => ({ ...state }),
    deal() {
      if (state.phase !== "idle") return;
      state.phase = "dealing";
      emit();
    },
    present() {
      if (state.phase !== "dealing") return;
      state.phase = "guessing";
      emit();
    },
    choose(choice) {
      if (state.phase !== "guessing") return;
      if (state.step === "middle") {
        if (typeof choice !== "string") return;
        if (state.struckAlbums.includes(choice)) return;
        if (round.middle && choice === round.middle.album.id) {
          advanceStep();
          return;
        }
        state.struckAlbums = [...state.struckAlbums, choice];
      } else {
        if (typeof choice !== "number") return;
        if (state.struck.includes(choice)) return;
        if (answerIds(state.step).has(choice)) {
          advanceStep();
          return;
        }
        state.struck = [...state.struck, choice];
      }
      wrongAttempts += 1;
      state.attemptsLeft -= 1;
      if (state.attemptsLeft <= 0) {
        resolve(false);
        return;
      }
      emit();
    },
    useClue() {
      if (state.phase !== "guessing") return -1;
      if (state.cluesUsed >= round.clues.length) return -1;
      const rung = state.cluesUsed;
      state.cluesUsed += 1;
      emit();
      return rung;
    },
    reveal() {
      if (state.phase !== "guessing" && state.phase !== "dealing") return;
      resolve(false);
    },
  };
}
