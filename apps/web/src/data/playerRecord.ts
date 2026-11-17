// Build-time derivation for the player page: what a person is documented
// PLAYING, and what else they are credited for. Both come straight from the
// role text already carried by the contributor index (`evidence[].role_text`
// and `role_text_examples`) -- nothing is added to the artifact.
//
// ADR 0068: only voice/instrument credits make a connection. Producer,
// engineer, writer and similar credits are kept as evidence ("Also
// credited") and never counted as playing.

import type { Contributor } from "./contributors";
import {
  isPerformerRole,
  performanceCategory,
  PERFORMANCE_CATEGORY_ORDER,
  type PerformanceCategory,
} from "../game/roleTaxonomy";

/** Plain-language phrase per family, for "documented on ...". */
const PLAYED_PHRASE: Record<PerformanceCategory, string> = {
  vocals: "vocals",
  "guitar-bass": "guitar and bass",
  keys: "keys and synths",
  "drums-percussion": "drums and percussion",
  strings: "strings",
  "horns-winds": "horns and woodwinds",
  other: "other instruments",
};

export interface PlayerRoles {
  /** Instrument/voice families, in the site's usual order. */
  played: PerformanceCategory[];
  /** Distinct non-performance credits, as written (bracket notes removed). */
  also: string[];
}

function components(roleText: string): string[] {
  return roleText
    .split(",")
    .map((c) => c.replace(/\[.*?\]/g, "").trim())
    .filter((c) => c.length > 0);
}

export function playerRoles(contributor: Contributor): PlayerRoles {
  const texts = [
    ...contributor.evidence.map((e) => e.role_text),
    ...contributor.role_text_examples,
  ];
  const played = new Set<PerformanceCategory>();
  const also = new Map<string, string>();
  for (const text of texts) {
    for (const component of components(text)) {
      if (isPerformerRole(component)) {
        const category = performanceCategory(component);
        if (category) played.add(category);
      } else if (!also.has(component.toLowerCase())) {
        also.set(component.toLowerCase(), component);
      }
    }
  }
  return {
    played: PERFORMANCE_CATEGORY_ORDER.filter((c) => played.has(c)),
    also: [...also.values()].sort((a, b) => a.localeCompare(b)),
  };
}

function joinList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

/** "guitar and bass, keys and synths, and vocals" -- or null when no
 * performance credit is indexed. */
export function playedPhrase(played: PerformanceCategory[]): string | null {
  if (played.length === 0) return null;
  return joinList(played.map((c) => PLAYED_PHRASE[c]));
}
