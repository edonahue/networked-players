// Connect Two Records' shareable URL state (ADR 0059 Phase 5 PR 4): real
// browser assertions against the committed pathfinding graph -- Connect is
// the first surface in this codebase to write URL state at all
// (`pushState`/`replaceState`/`popstate`), extending the read-only
// `?round=`/`?seed=`/`?motion=off` convention `flagship.ts`/`routes.ts`
// already use. "Discovery" (Daft Punk) <-> "The Joshua Tree" (U2) is the
// same real, directly-connected pair `game-connect.spec.ts` already uses.

import { expect, test } from "@playwright/test";
import {
  picker,
  selectAlbum,
  selectRouteFilter,
} from "./helpers/connectPicker";

async function currentParams(page: import("@playwright/test").Page) {
  return new URL(page.url()).searchParams;
}

test("a completed search writes a canonical a/b URL and reveals Copy link", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });

  const params = await currentParams(page);
  expect(params.get("a")).toBe("master-26647");
  expect(params.get("b")).toBe("master-64290");
  expect(params.has("mode")).toBe(false); // unfiltered default is omitted

  await expect(page.locator("[data-connect-copy-link]")).toBeVisible();
});

test("visiting a real a/b link auto-populates both pickers and runs the search without a click", async ({
  page,
}) => {
  await page.goto("/play/connect/?a=master-26647&b=master-64290");
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toContainText("Discovery");
  await expect(
    picker(page, "b").locator("[data-picker-selected]"),
  ).toContainText("Joshua Tree");
});

test("a stale/unknown album id in the URL is cleaned without an alarming error, no auto-search", async ({
  page,
}) => {
  await page.goto("/play/connect/?a=master-not-a-real-album&b=master-64290");
  // No search should run -- one side never resolved.
  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await page.waitForFunction(() => !window.location.search);
  expect(await currentParams(page)).toEqual(new URLSearchParams());
});

test("a and b naming the same album is rejected -- no auto-search, nothing populated", async ({
  page,
}) => {
  await page.goto("/play/connect/?a=master-26647&b=master-26647");
  await expect(page.locator("[data-connect-results]")).toBeHidden();
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toBeHidden();
});

test("an unrecognized mode value falls back to the unfiltered default rather than failing", async ({
  page,
}) => {
  await page.goto(
    "/play/connect/?a=master-26647&b=master-64290&mode=a-retired-mode-name",
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
  await selectAlbum(page, "a", "Ziggy Stardust");
  await selectAlbum(page, "b", "A Night At The Opera");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const afterFirstSearch = page.url();

  await selectRouteFilter(page, "behind-the-glass");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const afterModeChange = page.url();
  expect(afterModeChange).not.toBe(afterFirstSearch);
  expect(new URL(afterModeChange).searchParams.get("mode")).toBe(
    "behind-the-glass",
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
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
  await page.locator("[data-connect-search]").click();
  await expect(page.locator("[data-connect-results]")).toBeVisible({
    timeout: 15000,
  });
  const firstUrl = page.url();

  await selectAlbum(page, "a", "Ziggy Stardust");
  await selectAlbum(page, "b", "A Night At The Opera");
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
  ).toContainText("Discovery");
});

test("popstate back to the pre-search page clears the displayed result", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
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
  await selectAlbum(page, "a", "Discovery");
  await selectAlbum(page, "b", "Joshua Tree");
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
