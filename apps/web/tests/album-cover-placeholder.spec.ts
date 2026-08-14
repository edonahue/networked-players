// Proves /albums/[album].astro's TRUE placeholder branch -- both the
// registry (coverFor()) and the album.cover_image fallback falsy at once --
// actually renders .play-header__placeholder with no <img> at all. Not
// achievable against the real dist/: 0 of 140 committed albums currently
// lack a registry entry, so no real navigable page can reach that branch
// through the normal build (game-albumart-buildtime.spec.ts already proves
// coverFor() itself can return null, but never navigates a real page, so it
// says nothing about whether the astro template's conditional actually
// takes the else branch).
//
// Runs its own isolated second build (NP_TEST_OUT_DIR=dist-test-artwork,
// gitignored, never the real dist/) against a generated-at-test-time copy
// of the real registry with one real album's entry removed
// (helpers/albumArtFixture.ts) and its own preview server on a distinct
// port -- the normal suite's dist/ and port-4321 server are never touched,
// so this cannot destabilize any other test.

import { execSync, spawn, type ChildProcess } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { generatePlaceholderFixture } from "./helpers/albumArtFixture";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 4322;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const OUT_DIR = "dist-test-artwork";

let previewProcess: ChildProcess | undefined;
let albumId = "";
let albumTitle = "";

async function waitForServer(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Server at ${url} never became ready: ${String(lastError)}`);
}

test.beforeAll(async () => {
  const fixture = generatePlaceholderFixture(webRoot);
  albumId = fixture.albumId;
  albumTitle = fixture.albumTitle;

  execSync("npx astro build", {
    cwd: webRoot,
    env: {
      ...process.env,
      NP_TEST_OUT_DIR: OUT_DIR,
      NP_ALBUM_ART_REGISTRY_PATH: fixture.registryPath,
    },
    stdio: "pipe",
  });

  previewProcess = spawn(
    "npx",
    ["astro", "preview", "--port", String(PORT), "--host", "127.0.0.1"],
    {
      cwd: webRoot,
      env: { ...process.env, NP_TEST_OUT_DIR: OUT_DIR },
      stdio: "pipe",
      // `npx astro preview` launches the actual Astro server as a CHILD of
      // the npx wrapper -- killing just the wrapper process leaves that
      // child (the thing actually bound to the port) running, causing
      // EADDRINUSE on a retry or a later local run. Detached spawns it into
      // its own process group instead, so afterAll can kill the whole
      // group (negative pid, POSIX-only -- this repo's CI and local dev
      // both run Linux/macOS).
      detached: true,
    },
  );
  await waitForServer(`${BASE_URL}/albums/${albumId}/`, 30_000);
});

test.afterAll(async () => {
  if (!previewProcess || previewProcess.pid === undefined) return;
  const pid = previewProcess.pid;
  await new Promise<void>((resolve) => {
    const proc = previewProcess!;
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    proc.once("exit", finish);
    try {
      process.kill(-pid, "SIGTERM");
    } catch {
      finish(); // already exited
      return;
    }
    // Fallback if SIGTERM alone doesn't bring the group down in time.
    setTimeout(() => {
      if (settled) return;
      try {
        process.kill(-pid, "SIGKILL");
      } catch {
        // already gone
      }
      finish();
    }, 5_000);
  });
});

test("an album whose registry entry and cover_image are both absent renders the accessible placeholder, not a broken image", async ({
  page,
}) => {
  await page.goto(`${BASE_URL}/albums/${albumId}/`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    albumTitle,
  );

  await expect(page.locator(".play-header__placeholder")).toBeVisible();
  await expect(page.locator(".play-header__cover")).toHaveCount(0);
});
