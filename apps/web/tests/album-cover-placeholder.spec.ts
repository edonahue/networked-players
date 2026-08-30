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
// gitignored, never the real dist/) against a generated-at-test-time
// SYNTHETIC empty art registry (helpers/albumArtFixture.ts -- no field is
// read from or derived from the real committed registry, per AGENTS.md's
// "keep fixtures synthetic and reproducible"), plus its own preview server
// on a distinct port -- the normal suite's dist/ and port-4321 server are
// never touched, so this cannot destabilize any other test. The one real
// read is challenge.v2.json, used only to pick which real, already-
// generated album page to navigate to.

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
  // This is the only spec in the suite that runs its own full, isolated
  // `astro build` (1067 pages, ~15s alone) inside a hook instead of reusing
  // the shared global webServer -- the default 30s per-test timeout
  // (playwright.config.mjs) has no headroom left for the preview-server
  // startup and first navigation that follow, once other workers are
  // competing for CPU/IO during a full-suite run. Root cause of an
  // intermittent beforeAll-timeout failure seen only under full-suite load,
  // never in isolation.
  test.setTimeout(90_000);
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
  const proc = previewProcess;

  const exited = new Promise<void>((resolve) => {
    proc.once("exit", () => resolve());
  });

  try {
    process.kill(-pid, "SIGTERM");
  } catch {
    return; // whole group already gone
  }

  // Race a graceful exit against a deadline, then ALWAYS probe the group
  // afterward -- regardless of which one won. The npx wrapper exiting does
  // not prove its Astro child (the thing actually bound to the port) has
  // too: gating the follow-up kill on the wrapper's own "exit" event was
  // itself a real gap here (a slower-to-shut-down descendant could survive
  // a SIGTERM the wrapper had already reacted to). Signal 0 is a liveness
  // probe, not a real signal -- it throws ESRCH if the group is genuinely
  // empty, so this only force-kills if something is still actually there.
  await Promise.race([
    exited,
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  try {
    process.kill(-pid, 0);
    process.kill(-pid, "SIGKILL");
  } catch {
    // group already empty
  }
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
