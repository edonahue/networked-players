import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, test } from "@playwright/test";

// Atlas P5b: presentation lives in the stylesheets, not in style="..."
// attributes. A source-level scan (no browser needed) keeps one-off inline
// styles from creeping back into pages and components.
//
// ALLOWLIST: path (relative to apps/web) -> why a dynamic inline style is
// unavoidable. Currently empty; every entry needs a reason.
const ALLOWLIST: Record<string, string> = {};

const roots = ["src/pages", "src/components"];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

test("no inline style attributes in src/pages or src/components", () => {
  const offenders: string[] = [];
  for (const root of roots) {
    for (const file of walk(root)) {
      if (!/\.(astro|html|tsx|jsx|ts)$/.test(file)) continue;
      const rel = relative(".", file);
      if (rel in ALLOWLIST) continue;
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, i) => {
        if (/\sstyle\s*=/.test(line)) offenders.push(`${rel}:${i + 1}`);
      });
    }
  }
  expect(offenders, "move inline styles into a stylesheet class").toEqual([]);
});
