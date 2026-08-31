// Needle-drop rating (docs/WEB_PRODUCT_PLAN.md §5): light and warm, no
// points inflation. A round resolves to exactly one of three ratings.

import type { Rating } from "./types";

export interface RoundOutcome {
  solved: boolean;
  cluesUsed: number;
  wrongAttempts: number;
}

export function rateRound(outcome: RoundOutcome): Rating {
  if (!outcome.solved) return "revealed";
  if (outcome.cluesUsed === 0 && outcome.wrongAttempts === 0) return "clean";
  return "with_clues";
}

export interface SetSummary {
  played: number;
  clean: number;
  withClues: number;
  revealed: number;
}

export function summarizeSet(ratings: readonly Rating[]): SetSummary {
  const summary: SetSummary = {
    played: ratings.length,
    clean: 0,
    withClues: 0,
    revealed: 0,
  };
  for (const rating of ratings) {
    if (rating === "clean") summary.clean += 1;
    else if (rating === "with_clues") summary.withClues += 1;
    else summary.revealed += 1;
  }
  return summary;
}

/** Groove glyphs for summaries and the spoiler-free daily share string. */
export function ratingGlyph(rating: Rating): string {
  switch (rating) {
    case "clean":
      return "●";
    case "with_clues":
      return "◐";
    case "revealed":
      return "○";
  }
}

/** Short display label for a `Rating` (e.g. the daily archive's "Played —
 * clean solve") -- the single source of truth for turning the enum into
 * words, so no caller falls back to swapping an underscore for a space
 * and rendering the raw internal value ("with_clues" -> "with clues" by
 * accident of spelling, not by design). */
export function ratingLabel(rating: Rating): string {
  switch (rating) {
    case "clean":
      return "clean solve";
    case "with_clues":
      return "with clues";
    case "revealed":
      return "revealed";
  }
}
