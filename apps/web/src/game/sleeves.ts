// Deterministic synthetic sleeve art (docs/WEB_PRODUCT_PLAN.md §7/§8).
// Pure function: album id + label → SVG string. Each fictional label has its
// own design system, and every generated sleeve carries an in-art SYNTHETIC
// edge stamp so the fictional status can never be separated from the artwork.
// No real album artwork is imitated; compositions are generated geometry.

// Minimal structural subject: GameAlbum and synthetic AlbumRef both satisfy it.
export interface SleeveSubject {
  id: string;
  title: string;
  act: string | null;
  label: string | null;
}

// Self-contained seeded PRNG (same xmur3+mulberry32 pair as ./prng) so this
// module also runs under Node's native type stripping for the preview CLI
// (scripts/gen-sleeves.mjs) — type-only imports are erased there, value
// imports of extensionless TS specifiers are not resolvable.
function createRng(seed: string) {
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i += 1) {
    h = Math.imul(h ^ seed.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  h = Math.imul(h ^ (h >>> 16), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  let a = (h ^ (h >>> 16)) >>> 0;
  const random = () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return {
    next: () => random(),
    int: (maxExclusive: number) => Math.floor(random() * maxExclusive),
  };
}

const MERIDIAN_DUOTONES: ReadonlyArray<[string, string]> = [
  ["#78aaa0", "#10100e"],
  ["#c0a568", "#171713"],
  ["#c9553f", "#1d1c17"],
  ["#9bc9be", "#0b0b0a"],
];

const KETTLE_PAPERS: ReadonlyArray<[string, string]> = [
  ["#eee5d2", "#c9553f"],
  ["#f5ead8", "#3f756e"],
  ["#d7c6a9", "#292722"],
  ["#f1ebde", "#9c8248"],
];

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function stamp(x: number, y: number, rotate: number, fill: string): string {
  return (
    `<text x="${x}" y="${y}" transform="rotate(${rotate} ${x} ${y})" ` +
    `font-family="IBM Plex Mono, monospace" font-size="7" letter-spacing="2" ` +
    `fill="${fill}" opacity="0.85">SYNTHETIC</text>`
  );
}

/** Geometric duotone system for the fictional "Meridian" label. */
function meridianSleeve(album: SleeveSubject): string {
  const rng = createRng(`sleeve-${album.id}`);
  const [accent, ground] = MERIDIAN_DUOTONES[rng.int(MERIDIAN_DUOTONES.length)];
  const shapes: string[] = [];
  const bands = 3 + rng.int(3);
  for (let i = 0; i < bands; i += 1) {
    const cy = 30 + rng.int(140);
    const height = 8 + rng.int(26);
    shapes.push(
      `<rect x="0" y="${cy}" width="200" height="${height}" fill="${accent}" opacity="${(0.25 + rng.next() * 0.6).toFixed(2)}"/>`,
    );
  }
  const cx = 50 + rng.int(100);
  const cy = 50 + rng.int(100);
  shapes.push(
    `<circle cx="${cx}" cy="${cy}" r="${18 + rng.int(30)}" fill="none" stroke="${accent}" stroke-width="3"/>`,
  );
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" role="img" ` +
    `aria-label="${escapeXml(`Synthetic sleeve art for ${album.title}`)}">` +
    `<rect width="200" height="200" fill="${ground}"/>` +
    shapes.join("") +
    `<text x="12" y="24" font-family="Georgia, serif" font-size="15" fill="${accent}">${escapeXml(album.act ?? "")}</text>` +
    `<text x="12" y="188" font-family="IBM Plex Mono, monospace" font-size="9" fill="${accent}">${escapeXml(album.title.slice(0, 30))}</text>` +
    stamp(148, 12, 0, accent) +
    `</svg>`
  );
}

/** Type-forward paper system for the fictional "Copper Kettle" label. */
function kettleSleeve(album: SleeveSubject): string {
  const rng = createRng(`sleeve-${album.id}`);
  const [paper, ink] = KETTLE_PAPERS[rng.int(KETTLE_PAPERS.length)];
  const rules: string[] = [];
  const count = 4 + rng.int(4);
  for (let i = 0; i < count; i += 1) {
    const y = 60 + i * (110 / count);
    rules.push(
      `<line x1="14" y1="${y.toFixed(1)}" x2="${120 + rng.int(66)}" y2="${y.toFixed(1)}" stroke="${ink}" stroke-width="${1 + rng.int(3)}"/>`,
    );
  }
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" role="img" ` +
    `aria-label="${escapeXml(`Synthetic sleeve art for ${album.title}`)}">` +
    `<rect width="200" height="200" fill="${paper}"/>` +
    `<rect x="8" y="8" width="184" height="184" fill="none" stroke="${ink}" stroke-width="2"/>` +
    `<text x="14" y="36" font-family="Georgia, serif" font-size="18" fill="${ink}">${escapeXml(album.act ?? "")}</text>` +
    `<text x="14" y="52" font-family="IBM Plex Mono, monospace" font-size="9" fill="${ink}">${escapeXml(album.title.slice(0, 34))}</text>` +
    rules.join("") +
    `<text x="14" y="186" font-family="IBM Plex Mono, monospace" font-size="8" fill="${ink}">${escapeXml((album.label ?? "").toUpperCase())}</text>` +
    stamp(150, 190, 0, ink) +
    `</svg>`
  );
}

/** Deterministic SVG sleeve for a synthetic album. */
export function sleeveSvg(album: SleeveSubject): string {
  return album.label === "Copper Kettle"
    ? kettleSleeve(album)
    : meridianSleeve(album);
}
