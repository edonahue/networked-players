// Deterministic PRNG for round selection and shuffles. Seeded from strings
// (round ids, ISO dates for the daily) so identical seeds always produce
// identical sequences — the property the derivation and daily-mode tests
// assert. xmur3 string hash feeding mulberry32, both public-domain algorithms.

function xmur3(str: string): () => number {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i += 1) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return h >>> 0;
  };
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface Rng {
  next(): number;
  int(maxExclusive: number): number;
  pick<T>(items: readonly T[]): T;
  shuffle<T>(items: readonly T[]): T[];
}

export function createRng(seed: string): Rng {
  const random = mulberry32(xmur3(seed)());
  const rng: Rng = {
    next: () => random(),
    int: (maxExclusive) => Math.floor(random() * maxExclusive),
    pick: (items) => {
      if (items.length === 0) throw new Error("pick from empty list");
      return items[rng.int(items.length)];
    },
    shuffle: (items) => {
      const copy = items.slice();
      for (let i = copy.length - 1; i > 0; i -= 1) {
        const j = rng.int(i + 1);
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      return copy;
    },
  };
  return rng;
}

/** Stable seed for the daily round: the UTC date string. */
export function dailySeed(date: Date): string {
  return `np-daily-${date.toISOString().slice(0, 10)}`;
}
