// Connect Two Records' shareable URL state (ADR 0059 Phase 5 PR 4): real
// browser assertions against the committed pathfinding graph -- Connect is
// the first surface in this codebase to write URL state at all
// (`pushState`/`replaceState`/`popstate`), extending the read-only
// `?round=`/`?seed=`/`?motion=off` convention `flagship.ts`/`routes.ts`
// already use. The album pair is the computed "connected" pair
// (helpers/catalogFacts.ts) every Connect spec shares.

import { expect, test } from "@playwright/test";
import {
  picker,
  selectAlbumById,
  selectRouteFilter,
} from "./helpers/connectPicker";
import { catalogFacts } from "./helpers/catalogFacts";

// Albums are derived from the committed artifacts by rule (see
// helpers/catalogFacts.ts), never named here.
const facts = await catalogFacts();
const CONNECTED = facts.connected;
const RHYTHM = facts.rhythm;
const SECOND = facts.secondConnected;
const REPLACEMENT_B = facts.replacementB;

async function currentParams(page: import("@playwright/test").Page) {
  return new URL(page.url()).searchParams;
}

test("a completed search writes a canonical a/b URL and reveals Copy link", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const params = await currentParams(page);
  expect(params.get("a")).toBe(CONNECTED.a.id);
  expect(params.get("b")).toBe(CONNECTED.b.id);
  expect(params.has("mode")).toBe(false); // unfiltered default is omitted

  await expect(page.locator("[data-connect-copy-link]")).toBeVisible();
});

test("visiting a real a/b link auto-populates both pickers and runs the search without a click", async ({
  page,
}) => {
  await page.goto(`/play/connect/?a=${CONNECTED.a.id}&b=${CONNECTED.b.id}`);
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText(CONNECTED.a.title);
  await expect(
    picker(page, "b").locator("[data-picker-selected]"),
  ).toContainText(CONNECTED.b.title);
});

test("a stale/unknown album id in the URL is cleaned without an alarming error, no auto-search", async ({
  page,
}) => {
  await page.goto(
    `/play/connect/?a=master-not-a-real-album&b=${CONNECTED.b.id}`,
  );
  // No search should run -- one side never resolved.
  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await page.waitForFunction(() => !window.location.search);
  expect(await currentParams(page)).toEqual(new URLSearchParams());
});

test("a and b naming the same album is rejected -- no auto-search, nothing populated", async ({
  page,
}) => {
  await page.goto(`/play/connect/?a=${CONNECTED.a.id}&b=${CONNECTED.a.id}`);
  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toBeHidden();
});

test("an unrecognized mode value falls back to the unfiltered default rather than failing", async ({
  page,
}) => {
  await page.goto(
    `/play/connect/?a=${CONNECTED.a.id}&b=${CONNECTED.b.id}&mode=a-retired-mode-name`,
  );
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    page.locator("[data-connect-mode-option][data-value='none']"),
  ).toHaveAttribute("aria-checked", "true");
});

test("re-running the same pair under a different mode replaces the history entry, not pushes a new one", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  // The computed Rhythm Section pair (helpers/catalogFacts.ts): a pair that resolves in BOTH the unfiltered and the filtered mode, so the
  // history assertion below is about history, not about one mode finding
  // nothing. (Behind the Glass, this test's original filtered mode, was
  // retired in ADR 0068.)
  await selectAlbumById(page, "a", RHYTHM.a);
  await selectAlbumById(page, "b", RHYTHM.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const afterFirstSearch = page.url();

  await selectRouteFilter(page, "rhythm-section");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const afterModeChange = page.url();
  expect(afterModeChange).not.toBe(afterFirstSearch);
  expect(new URL(afterModeChange).searchParams.get("mode")).toBe(
    "rhythm-section",
  );

  // A REPLACED entry means going back once returns to the page before this
  // whole session's searches began, not to the unfiltered-mode search.
  await page.goBack();
  await expect(page).toHaveURL(/\/play\/connect\/?$/);
});

test("searching a genuinely different pair pushes a new, navigable history entry", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const firstUrl = page.url();

  await selectAlbumById(page, "a", SECOND.a);
  await selectAlbumById(page, "b", REPLACEMENT_B);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const secondUrl = page.url();
  expect(secondUrl).not.toBe(firstUrl);

  await page.goBack();
  await expect(page).toHaveURL(firstUrl);
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText(CONNECTED.a.title);
});

test("popstate back to the pre-search page clears the displayed result", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  await page.goBack();
  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toBeHidden();
});

test("Copy link puts the current URL on the clipboard with accessible feedback", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/play/connect/");
  await selectAlbumById(page, "a", CONNECTED.a);
  await selectAlbumById(page, "b", CONNECTED.b);
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const copyButton = page.locator("[data-connect-copy-link]");
  await copyButton.click();
  await expect(copyButton).toHaveText("Copied");
  await expect(page.locator("[data-connect-announce]")).toContainText(
    /copied/i,
  );

  const clipboardText = await page.evaluate(() =>
    navigator.clipboard.readText(),
  );
  expect(clipboardText).toBe(page.url());
});
