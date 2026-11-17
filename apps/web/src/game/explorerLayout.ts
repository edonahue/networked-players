// Collision-free layout for the default Explore artist-star view.
//
// Neighbours sit on an ellipse around the centre; their NAMES do not sit
// beside their circles. Each name goes into one of two label columns outside
// the ring (right half of the ring -> left-anchored column on the right, left
// half -> right-anchored column on the left), wrapped to the column's width
// and nudged vertically so no two label blocks overlap. A thin leader line
// joins a node to its label. Because every label column lies wholly outside
// the ring (and the centre label inside it is bounded by the ring's inner
// width), a label can never cover a node circle. The viewBox grows taller as
// needed instead of shrinking text, so labels stay legible.
//
// Pure geometry, no DOM: monospace advance is estimated from the font size so
// the layout is deterministic. Visible text always equals the artist name
// (lines are joined by whitespace/tspans), so accessible names still match.

export interface LayoutMetrics {
  width: number;
  rx: number;
  nodeRadius: number;
  centerRadius: number;
}

export const DESKTOP_METRICS: LayoutMetrics = {
  width: 480,
  rx: 110,
  nodeRadius: 8,
  centerRadius: 14,
};
export const MOBILE_METRICS: LayoutMetrics = {
  width: 320,
  rx: 64,
  nodeRadius: 12,
  centerRadius: 18,
};

export const LABEL_FONT_SIZE = 8;
const CHAR_W = LABEL_FONT_SIZE * 0.62; // mono advance, with a safety margin
export const LABEL_LINE_HEIGHT = 10;
const BLOCK_GAP = 3;
const PAD = 6;
const LEADER_RUN = 8;
const MIN_HEIGHT = 320;
const NODE_GAP = 6;

export interface PlacedLabel {
  lines: string[];
  x: number;
  /** Baseline y of the first line. */
  y: number;
  anchor: "start" | "middle" | "end";
}

export interface PlacedNode {
  x: number;
  y: number;
  label: PlacedLabel;
  leader: { x1: number; y1: number; x2: number; y2: number };
}

export interface ExplorerLayout {
  width: number;
  height: number;
  cx: number;
  cy: number;
  center: PlacedLabel;
  nodes: PlacedNode[];
}

/** Greedy word wrap to `maxChars`. A single word longer than a line is split
 * hard (no hyphen added), so concatenated pieces still read as the name. */
export function wrapName(name: string, maxChars: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of name.split(/\s+/).filter(Boolean)) {
    let w = word;
    while (w.length > maxChars) {
      if (line) {
        lines.push(line);
        line = "";
      }
      lines.push(w.slice(0, maxChars));
      w = w.slice(maxChars);
    }
    if (!line) line = w;
    else if (line.length + 1 + w.length <= maxChars) line += ` ${w}`;
    else {
      lines.push(line);
      line = w;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [name];
}

function ellipsePerimeter(a: number, b: number): number {
  return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
}

export function computeLayout(
  centerName: string,
  names: string[],
  m: LayoutMetrics,
): ExplorerLayout {
  const n = names.length;
  const cx = m.width / 2;
  const r = m.nodeRadius;
  const colGap = r + LEADER_RUN;
  const labelX = cx + m.rx + colGap + 4;
  const maxChars = Math.max(
    4,
    Math.floor((m.width - labelX - 2) / CHAR_W), // same room on both sides
  );
  const wrapped = names.map((nm) => wrapName(nm, maxChars));
  const blockH = (lines: string[]) => lines.length * LABEL_LINE_HEIGHT;

  // Side by angle: right half of the ring uses the right column.
  const angles = names.map((_, i) => (2 * Math.PI * i) / n - Math.PI / 2);
  const right = (i: number) => Math.cos(angles[i]) >= 0;
  const sideTotal = (isRight: boolean) =>
    wrapped.reduce(
      (s, l, i) => (right(i) === isRight ? s + blockH(l) + BLOCK_GAP : s),
      0,
    );
  let height = Math.max(
    MIN_HEIGHT,
    Math.ceil(Math.max(sideTotal(true), sideTotal(false)) + 2 * PAD),
  );
  // Enough ring circumference that circles never touch.
  const need = n * (2 * r + NODE_GAP);
  while (ellipsePerimeter(m.rx, height / 2 - PAD - r) < need) height += 8;

  const cy = height / 2;
  const ry = height / 2 - PAD - r;
  const pts = angles.map((a) => ({
    x: cx + m.rx * Math.cos(a),
    y: cy + ry * Math.sin(a),
  }));

  const labelTop = new Array<number>(n).fill(0);
  for (const isRight of [true, false]) {
    const idx = pts
      .map((_, i) => i)
      .filter((i) => right(i) === isRight)
      .sort((a, b) => pts[a].y - pts[b].y);
    // Forward pass: as near the node as possible without overlapping.
    let floor = PAD;
    for (const i of idx) {
      const h = blockH(wrapped[i]);
      labelTop[i] = Math.max(pts[i].y - h / 2, floor);
      floor = labelTop[i] + h + BLOCK_GAP;
    }
    // Backward pass: pull back up if the stack ran past the bottom.
    let ceil = height - PAD;
    for (const i of [...idx].reverse()) {
      const h = blockH(wrapped[i]);
      labelTop[i] = Math.min(labelTop[i], ceil - h);
      ceil = labelTop[i] - BLOCK_GAP;
    }
  }

  const nodes: PlacedNode[] = pts.map((p, i) => {
    const isRight = right(i);
    const lines = wrapped[i];
    const h = blockH(lines);
    const x = isRight ? labelX : m.width - labelX;
    const midY = labelTop[i] + h / 2;
    return {
      x: p.x,
      y: p.y,
      label: {
        lines,
        x,
        y: labelTop[i] + LABEL_LINE_HEIGHT * 0.78,
        anchor: isRight ? "start" : "end",
      },
      leader: {
        x1: p.x,
        y1: p.y,
        x2: isRight ? x - 3 : x + 3,
        y2: midY,
      },
    };
  });

  // Centre label sits under the centre node, bounded by the ring's inner
  // width so it can't reach a ring node (nearest ones are at +-rx).
  const halfW = m.rx - r - 4;
  const centerLines = wrapName(
    centerName,
    Math.max(4, Math.floor((2 * halfW) / CHAR_W)),
  );
  const center: PlacedLabel = {
    lines: centerLines,
    x: cx,
    y: cy + m.centerRadius + 4 + LABEL_LINE_HEIGHT * 0.78,
    anchor: "middle",
  };
  return { width: m.width, height, cx, cy, center, nodes };
}
