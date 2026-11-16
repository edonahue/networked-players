// Guard (Atlas F6): no spec may name a real catalog album or artist.
//
// Web tests used to pin real catalog contents ("a real verified negative
// pair", fixed album titles, a named hub artist). Every catalog round then
// risked breaking them for reasons unrelated to the behaviour under test.
// Specs now derive albums, artists and ids from the committed artifacts
// (tests/helpers/catalogFacts.ts) or use synthetic fixtures.
//
// Invariant: no string literal in tests/**/*.ts is equal (case-insensitive,
// trimmed) to any catalog album title or album-artist name longer than
// MIN_LENGTH characters, except the explicit, justified ALLOWLIST below.
// Comments and regex literals are not scanned; template literals are scanned
// only when they contain no interpolation.

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { catalogAlbums } from "./helpers/catalogFacts";

const MIN_LENGTH = 4; // "longer than a few characters": 5+ characters are checked

/** Literals that legitimately equal a catalog name. Each entry needs a
 * justification; keep this list empty if at all possible. */
const ALLOWLIST: Record<string, string> = {
  // (none needed today)
};

const testsDir = dirname(fileURLToPath(import.meta.url));

function specFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return specFiles(full);
    return entry.name.endsWith(".ts") ? [full] : [];
  });
}

/** Extracts plain string literals (single, double, backtick-without-${})
 * with their line numbers, skipping comments and regex literals. */
export function stringLiterals(
  source: string,
): { value: string; line: number }[] {
  const found: { value: string; line: number }[] = [];
  let i = 0;
  let line = 1;
  let lastSignificant = "";
  const n = source.length;
  while (i < n) {
    const ch = source[i];
    const next = source[i + 1];
    if (ch === "\n") {
      line++;
      i++;
      continue;
    }
    if (ch === "/" && next === "/") {
      while (i < n && source[i] !== "\n") i++;
      continue;
    }
    if (ch === "/" && next === "*") {
      i += 2;
      while (i < n && !(source[i] === "*" && source[i + 1] === "/")) {
        if (source[i] === "\n") line++;
        i++;
      }
      i += 2;
      continue;
    }
    if (ch === "/" && /[(,=:[!&|?{};]|^$/.test(lastSignificant)) {
      // regex literal
      i++;
      let inClass = false;
      while (i < n && (source[i] !== "/" || inClass)) {
        if (source[i] === "\\") i++;
        else if (source[i] === "[") inClass = true;
        else if (source[i] === "]") inClass = false;
        i++;
      }
      i++;
      while (i < n && /[a-z]/.test(source[i])) i++;
      lastSignificant = "/";
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      const quote = ch;
      const startLine = line;
      let value = "";
      let interpolated = false;
      i++;
      while (i < n && source[i] !== quote) {
        if (source[i] === "\\") {
          value += source[i + 1];
          i += 2;
          continue;
        }
        if (quote === "`" && source[i] === "$" && source[i + 1] === "{") {
          interpolated = true;
          let depth = 0;
          while (i < n) {
            if (source[i] === "{") depth++;
            if (source[i] === "}" && --depth === 0) break;
            if (source[i] === "\n") line++;
            i++;
          }
          i++;
          continue;
        }
        if (source[i] === "\n") line++;
        value += source[i];
        i++;
      }
      i++;
      if (!interpolated) found.push({ value, line: startLine });
      lastSignificant = quote;
      continue;
    }
    if (!/\s/.test(ch)) lastSignificant = ch;
    i++;
  }
  return found;
}

test("the literal scanner finds strings, and skips comments and regexes", () => {
  const sample = [
    'const a = "Alpha Name";',
    "// 'Commented Name'",
    "const b = /don't 'match'/i;",
    "const c = `Tpl Name`;",
    "const d = `Interp ${x} Name`;",
  ].join("\n");
  expect(stringLiterals(sample).map((l) => l.value)).toEqual([
    "Alpha Name",
    "Tpl Name",
  ]);
});

test("no spec names a real catalog album or artist", () => {
  const names = new Map<string, string>();
  for (const album of catalogAlbums) {
    for (const [kind, text] of [
      ["album title", album.title],
      ["artist", album.artist],
    ] as const) {
      if (text.trim().length > MIN_LENGTH) {
        names.set(text.trim().toLowerCase(), `${kind} "${text}"`);
      }
    }
  }
  expect(names.size).toBeGreaterThan(0);

  const offenders: string[] = [];
  for (const file of specFiles(testsDir)) {
    const rel = relative(testsDir, file);
    for (const { value, line } of stringLiterals(readFileSync(file, "utf8"))) {
      const hit = names.get(value.trim().toLowerCase());
      if (hit && !(`${rel}:${value}` in ALLOWLIST)) {
        offenders.push(
          `${rel}:${line} literal ${JSON.stringify(value)} is a real ${hit}`,
        );
      }
    }
  }
  expect(
    offenders,
    "specs must derive albums/artists from the committed artifacts " +
      "(tests/helpers/catalogFacts.ts) or use synthetic fixtures:\n" +
      offenders.join("\n"),
  ).toEqual([]);
});
