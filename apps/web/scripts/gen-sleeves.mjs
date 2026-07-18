#!/usr/bin/env node
// Preview CLI for the deterministic synthetic sleeve generator
// (src/game/sleeves.ts). Prints an index of synthetic album ids, or one
// album's SVG to stdout — for eyeballing the label design systems without
// running the site. Never writes into the repository.
//
//   node scripts/gen-sleeves.mjs            # index of album ids
//   node scripts/gen-sleeves.mjs syn-a07    # one sleeve SVG to stdout
//
// The generator is TypeScript (shared with the site build), so this CLI
// re-executes itself under Node's type stripping when needed.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const SELF = fileURLToPath(import.meta.url);
const WEB_ROOT = join(dirname(SELF), "..");

if (!process.execArgv.some((arg) => arg.includes("strip-types"))) {
  const result = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "--no-warnings",
      SELF,
      ...process.argv.slice(2),
    ],
    { stdio: "inherit" },
  );
  process.exit(result.status ?? 1);
}

const universe = JSON.parse(
  readFileSync(join(WEB_ROOT, "public/data/game/universe.v1.json"), "utf8"),
);
const { sleeveSvg } = await import(join(WEB_ROOT, "src/game/sleeves.ts"));

const albumId = process.argv[2];
if (!albumId) {
  for (const album of universe.albums) {
    console.log(`${album.id}\t${album.label}\t${album.title}`);
  }
  process.exit(0);
}
const album = universe.albums.find((a) => a.id === albumId);
if (!album) {
  console.error(`unknown album id ${albumId}`);
  process.exit(1);
}
console.log(sleeveSvg(album));
