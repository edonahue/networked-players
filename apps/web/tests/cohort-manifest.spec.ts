import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { cohortArtifacts } from "../src/data/cohortArtifacts";
import type { PlayableCohort, PlayableCohortManifest } from "../src/data/cohort";

// Validates apps/web/public/data/cohorts/index.json and every artifact it
// references, plus two-way correspondence with the hand-maintained static
// import map in cohortArtifacts.ts. This is deliberately lighter than the
// Python pipeline's own validate_playable_cohort (data/contracts/
// playable-cohort-v1.md) -- that already guarantees a committed artifact's
// exact contract before it exists. This test exists to catch web-specific
// drift: a manifest entry with no matching static import (or vice versa), a
// missing file, a path that doesn't match convention, or a forbidden
// string/phrase that slipped into a fixture.

const WEB_ROOT = fileURLToPath(new URL("..", import.meta.url));
const PUBLIC_ROOT = `${WEB_ROOT}public`;
const MANIFEST_PATH = `${PUBLIC_ROOT}/data/cohorts/index.json`;

const FORBIDDEN_SUBSTRINGS = ["/home/", "data/private", "local/", ".ssh", "DISCOGS_TOKEN"];
const FORBIDDEN_PHRASES = ["worked with", "collaborated with", "influenced"];

function assertNoForbiddenContent(label: string, rawText: string) {
  const lowered = rawText.toLowerCase();
  for (const substring of FORBIDDEN_SUBSTRINGS) {
    expect(lowered, `${label} must not contain ${JSON.stringify(substring)}`).not.toContain(
      substring.toLowerCase(),
    );
  }
  for (const phrase of FORBIDDEN_PHRASES) {
    expect(lowered, `${label} must not contain ${JSON.stringify(phrase)}`).not.toContain(phrase);
  }
}

const manifestRaw = readFileSync(MANIFEST_PATH, "utf-8");
const manifest: PlayableCohortManifest = JSON.parse(manifestRaw);

test("manifest file exists and parses", () => {
  expect(existsSync(MANIFEST_PATH)).toBe(true);
  expect(manifest).toBeTruthy();
});

test("manifest has schema_version 1 and a non-empty cohort list", () => {
  expect(manifest.schema_version).toBe(1);
  expect(Array.isArray(manifest.cohorts)).toBe(true);
  expect(manifest.cohorts.length).toBeGreaterThan(0);
});

test("every cohort_id is unique", () => {
  const ids = manifest.cohorts.map((entry) => entry.cohort_id);
  expect(new Set(ids).size).toBe(ids.length);
});

test("every status is synthetic or reviewed", () => {
  for (const entry of manifest.cohorts) {
    expect(["synthetic", "reviewed"]).toContain(entry.status);
  }
});

test("every artifact_path starts with /data/cohorts/ and resolves to a real file", () => {
  for (const entry of manifest.cohorts) {
    expect(entry.artifact_path.startsWith("/data/cohorts/")).toBe(true);
    const diskPath = `${PUBLIC_ROOT}${entry.artifact_path}`;
    expect(existsSync(diskPath), `${entry.artifact_path} does not exist on disk`).toBe(true);
  }
});

test("manifest and cohortArtifacts map correspond exactly in both directions", () => {
  const manifestIds = new Set(manifest.cohorts.map((entry) => entry.cohort_id));
  const mapIds = new Set(Object.keys(cohortArtifacts));

  for (const id of manifestIds) {
    expect(mapIds.has(id), `manifest lists ${id} but cohortArtifacts.ts has no matching import`).toBe(
      true,
    );
  }
  for (const id of mapIds) {
    expect(
      manifestIds.has(id),
      `cohortArtifacts.ts imports ${id} but the manifest doesn't list it (dead import?)`,
    ).toBe(true);
  }
});

test("synthetic entries stay self-documenting", () => {
  for (const entry of manifest.cohorts) {
    if (entry.status !== "synthetic") continue;
    const text = `${entry.title} ${entry.description}`.toLowerCase();
    expect(text, `synthetic entry ${entry.cohort_id} should say so in its own text`).toMatch(
      /synthetic|not a real|not real/,
    );
  }
});

test("reviewed entries never use the placeholder example.invalid domain", () => {
  for (const entry of manifest.cohorts) {
    if (entry.status !== "reviewed") continue;
    const artifactPath = `${PUBLIC_ROOT}${entry.artifact_path}`;
    const artifact: PlayableCohort = JSON.parse(readFileSync(artifactPath, "utf-8"));
    expect(artifact.source_url).not.toContain("example.invalid");
  }
});

test("every artifact has the minimum shape needed for web use", () => {
  const requiredKeys = [
    "schema_version",
    "cohort_id",
    "attribution_label",
    "source_url",
    "generated_from_scorer_version",
    "reviewed_at",
    "review_note",
    "albums",
    "pairs",
  ];

  for (const entry of manifest.cohorts) {
    const artifactPath = `${PUBLIC_ROOT}${entry.artifact_path}`;
    const artifact: PlayableCohort = JSON.parse(readFileSync(artifactPath, "utf-8"));

    for (const key of requiredKeys) {
      expect(artifact, `${entry.artifact_path} is missing "${key}"`).toHaveProperty(key);
    }

    const albumIds = new Set(artifact.albums.map((album) => album.id));
    for (const pair of artifact.pairs) {
      expect(albumIds.has(pair.album_a_id), `${pair.album_a_id} is not a real album`).toBe(true);
      expect(albumIds.has(pair.album_b_id), `${pair.album_b_id} is not a real album`).toBe(true);
      for (const hop of pair.hops) {
        expect(Array.isArray(hop.quality_flags)).toBe(true);
        expect(hop.quality_flags.length).toBeGreaterThan(0);
      }
    }
  }
});

test("manifest and every artifact are free of forbidden strings and phrasing", () => {
  assertNoForbiddenContent("index.json", manifestRaw);
  for (const entry of manifest.cohorts) {
    const artifactPath = `${PUBLIC_ROOT}${entry.artifact_path}`;
    const rawText = readFileSync(artifactPath, "utf-8");
    assertNoForbiddenContent(entry.artifact_path, rawText);
  }
});
