// Text-only share card markup (satori element tree). Pure: takes strings,
// returns a tree. It never references a remote URL or an image of any kind
// (DATA_AND_RIGHTS: no Discogs image bytes are downloaded, stored or
// rehosted); the only graphics are vector shapes drawn here.

export const OG_WIDTH = 1200;
export const OG_HEIGHT = 630;

const INK = "#fff8e8";
const MUTED = "#b8ae9e";
const ACCENT = "#c9553f";
const BG = "#10100e";

export interface CardInput {
  /** Small mono label above the title, e.g. "RECORD" or "PLAYER". */
  kicker: string;
  title: string;
  /** Second line: artist, or a documented-records summary. */
  subtitle?: string;
  /** Third line: year or similar. */
  meta?: string;
}

export type CardNode = { type: string; props: Record<string, unknown> };

const el = (type: string, props: Record<string, unknown>): CardNode => ({
  type,
  props,
});

export function clip(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : `${t.slice(0, max - 1).trimEnd()}…`;
}

function titleSize(title: string): number {
  if (title.length <= 28) return 84;
  if (title.length <= 48) return 68;
  return 54;
}

/** Groove / liner-note motif: concentric record grooves plus a teal label. */
function groove(): CardNode {
  const ring = (r: number, o: number) =>
    el("circle", {
      cx: 230,
      cy: 230,
      r,
      fill: "none",
      stroke: "#eee5d2",
      strokeOpacity: o,
      strokeWidth: 2,
    });
  return el("svg", {
    width: 460,
    height: 460,
    viewBox: "0 0 460 460",
    style: { position: "absolute", right: -150, top: 85 },
    children: [
      el("circle", {
        cx: 230,
        cy: 230,
        r: 228,
        fill: "#1a1a18",
        stroke: "#eee5d2",
        strokeOpacity: 0.18,
        strokeWidth: 2,
      }),
      ring(190, 0.1),
      ring(150, 0.1),
      ring(110, 0.1),
      el("circle", { cx: 230, cy: 230, r: 74, fill: "#78aaa0" }),
      el("circle", { cx: 230, cy: 230, r: 10, fill: BG }),
    ],
  });
}

export function cardMarkup(input: CardInput, siteName: string): CardNode {
  const title = clip(input.title, 90);
  const rows: CardNode[] = [
    el("div", {
      style: {
        fontFamily: "IBM Plex Mono",
        fontSize: 28,
        letterSpacing: 3,
        color: ACCENT,
      },
      children: input.kicker.toUpperCase(),
    }),
    el("div", {
      style: {
        fontFamily: "Source Serif 4",
        fontWeight: 600,
        fontSize: titleSize(title),
        lineHeight: 1.1,
        color: INK,
        marginTop: 22,
        maxWidth: 760,
      },
      children: title,
    }),
  ];
  if (input.subtitle) {
    rows.push(
      el("div", {
        style: {
          fontFamily: "Inter",
          fontSize: 38,
          color: MUTED,
          marginTop: 26,
          maxWidth: 760,
        },
        children: clip(input.subtitle, 70),
      }),
    );
  }
  if (input.meta) {
    rows.push(
      el("div", {
        style: {
          fontFamily: "Inter",
          fontSize: 30,
          color: MUTED,
          marginTop: 12,
        },
        children: input.meta,
      }),
    );
  }
  return el("div", {
    style: {
      display: "flex",
      position: "relative",
      width: OG_WIDTH,
      height: OG_HEIGHT,
      backgroundColor: BG,
      overflow: "hidden",
    },
    children: [
      groove(),
      el("div", {
        style: {
          display: "flex",
          flexDirection: "column",
          padding: "70px 0 0 80px",
        },
        children: rows,
      }),
      el("div", {
        style: {
          position: "absolute",
          left: 80,
          bottom: 56,
          fontFamily: "IBM Plex Mono",
          fontSize: 26,
          letterSpacing: 2,
          color: MUTED,
        },
        children: siteName,
      }),
    ],
  });
}

/** Every string value in the tree, for tests asserting no remote URLs. */
export function collectStrings(node: unknown, out: string[] = []): string[] {
  if (typeof node === "string") out.push(node);
  else if (Array.isArray(node)) node.forEach((n) => collectStrings(n, out));
  else if (node && typeof node === "object")
    Object.values(node).forEach((n) => collectStrings(n, out));
  return out;
}
