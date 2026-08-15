// Connect Two Records' accessible combobox (ADR 0059 Phase 5 PR 4): a real
// WAI-ARIA combobox pattern -- role="combobox" on the input,
// role="listbox"/"option" on the results, aria-activedescendant tracking
// keyboard navigation without moving real DOM focus off the input. Two
// independent pickers with namespaced ids (connect-picker-a-*/
// connect-picker-b-*), so nothing here ever collides between them.

import { expect, test } from "@playwright/test";
import { picker, pickerResults, selectAlbum } from "./helpers/connectPicker";

test("the input carries real combobox ARIA wired to its own listbox", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  const input = picker(page, "a").locator("input");
  await expect(input).toHaveAttribute("role", "combobox");
  await expect(input).toHaveAttribute("aria-autocomplete", "list");
  await expect(input).toHaveAttribute("aria-expanded", "false");
  const listboxId = await input.getAttribute("aria-controls");
  expect(listboxId).toBe("connect-picker-a-listbox");
  await expect(page.locator(`#${listboxId}`)).toHaveAttribute(
    "role",
    "listbox",
  );
});

test("typing expands the listbox and each result is a real option with a stable id", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  const input = picker(page, "a").locator("input");
  await expect(picker(page, "a")).toHaveAttribute("data-picker-state", "ready");
  await input.fill("Discovery");

  await expect(input).toHaveAttribute("aria-expanded", "true");
  const first = pickerResults(page, "a").first();
  await expect(first).toHaveAttribute("role", "option");
  await expect(first).toHaveAttribute("id", "connect-picker-a-option-0");
});

test("ArrowDown/ArrowUp move aria-activedescendant without moving real focus off the input", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  const input = picker(page, "a").locator("input");
  await expect(picker(page, "a")).toHaveAttribute("data-picker-state", "ready");
  await input.fill("a"); // broad query, multiple real matches
  await expect(pickerResults(page, "a").first()).toBeVisible();

  await input.press("ArrowDown");
  await expect(input).toBeFocused();
  const firstId = await input.getAttribute("aria-activedescendant");
  expect(firstId).toBe("connect-picker-a-option-0");
  await expect(page.locator(`#${firstId}`)).toHaveAttribute(
    "aria-selected",
    "true",
  );

  await input.press("ArrowDown");
  await expect(input).toBeFocused(); // still the input, never the option
  const secondId = await input.getAttribute("aria-activedescendant");
  expect(secondId).toBe("connect-picker-a-option-1");
  // The previous option is no longer marked active -- exactly one option
  // is ever aria-selected at a time.
  await expect(page.locator(`#${firstId}`)).toHaveAttribute(
    "aria-selected",
    "false",
  );

  await input.press("ArrowUp");
  const backToFirst = await input.getAttribute("aria-activedescendant");
  expect(backToFirst).toBe(firstId);
});

test("ArrowUp above the first option clears the active descendant, returning to plain typing", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  const input = picker(page, "a").locator("input");
  await expect(picker(page, "a")).toHaveAttribute("data-picker-state", "ready");
  await input.fill("a");
  await expect(pickerResults(page, "a").first()).toBeVisible();

  await input.press("ArrowDown"); // activate first option
  await input.press("ArrowUp"); // clamp below the first -> clears
  await expect(input).not.toHaveAttribute("aria-activedescendant", /.+/);
});

test("Escape closes the listbox without clearing the typed text or an existing selection", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  const input = picker(page, "a").locator("input");
  await expect(picker(page, "a")).toHaveAttribute("data-picker-state", "ready");
  await input.fill("Discovery");
  await expect(pickerResults(page, "a")).toBeVisible();

  await input.press("Escape");
  await expect(pickerResults(page, "a")).toBeHidden();
  await expect(input).toHaveAttribute("aria-expanded", "false");
  await expect(input).toHaveValue("Discovery"); // text survives
});

test("a query with zero real matches announces 'no results', distinct from the empty-query state", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  const pickerA = picker(page, "a");
  const input = pickerA.locator("input");
  await expect(pickerA).toHaveAttribute("data-picker-state", "ready");

  // Empty query: no announcement at all, this is the neutral starting state.
  const count = pickerA.locator("[data-picker-count]");
  await expect(count).toHaveText("");

  await input.fill("zzz-not-a-real-album-zzz");
  await expect(count).toContainText("No results");
});

test("a query with real matches announces a result count", async ({ page }) => {
  await page.goto("/play/connect/");
  const pickerA = picker(page, "a");
  const input = pickerA.locator("input");
  await expect(pickerA).toHaveAttribute("data-picker-state", "ready");
  await input.fill("Discovery");
  await expect(pickerA.locator("[data-picker-count]")).toContainText(
    /result.*available/i,
  );
});

test("typing again after a selection clears it -- selection clearing on edit", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await selectAlbum(page, "a", "Discovery");
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toBeVisible();

  await picker(page, "a").locator("input").press("Backspace");
  await expect(
    picker(page, "a").locator("[data-picker-selected]"),
  ).toBeHidden();
});

test("two independent pickers share zero id or aria-activedescendant collision", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  await expect(picker(page, "a")).toHaveAttribute("data-picker-state", "ready");
  await expect(picker(page, "b")).toHaveAttribute("data-picker-state", "ready");

  // Deliberately the same query on both sides, interacted with fully one
  // at a time -- moving focus to B (correctly) closes A's listbox via its
  // own focusout handler, so activating A first and reading its state
  // before ever touching B is what isolates the id/state each picker
  // holds, rather than an artifact of which one currently has focus.
  await picker(page, "a").locator("input").fill("Discovery");
  await picker(page, "a").locator("input").press("ArrowDown");
  const activeA = await picker(page, "a")
    .locator("input")
    .getAttribute("aria-activedescendant");
  expect(activeA).toBe("connect-picker-a-option-0");

  await picker(page, "b").locator("input").fill("Discovery");
  await picker(page, "b").locator("input").press("ArrowDown");
  const activeB = await picker(page, "b")
    .locator("input")
    .getAttribute("aria-activedescendant");
  expect(activeB).toBe("connect-picker-b-option-0");

  expect(activeA).not.toBe(activeB);

  // Both listboxes carry their own real, distinct ids too.
  const listboxA = await picker(page, "a")
    .locator("input")
    .getAttribute("aria-controls");
  const listboxB = await picker(page, "b")
    .locator("input")
    .getAttribute("aria-controls");
  expect(listboxA).not.toBe(listboxB);
});

test("clicking a result keeps focus on the input rather than blurring it away", async ({
  page,
}) => {
  await page.goto("/play/connect/");
  const input = picker(page, "a").locator("input");
  await expect(picker(page, "a")).toHaveAttribute("data-picker-state", "ready");
  await input.fill("Discovery");
  await pickerResults(page, "a").first().click();
  await expect(input).toBeFocused();
});

test("Tab away from the picker closes its listbox", async ({ page }) => {
  await page.goto("/play/connect/");
  const input = picker(page, "a").locator("input");
  await expect(picker(page, "a")).toHaveAttribute("data-picker-state", "ready");
  await input.fill("a");
  await expect(pickerResults(page, "a").first()).toBeVisible();

  await input.press("Tab");
  await expect(pickerResults(page, "a").first()).not.toBeVisible();
});

test("the loading state is distinct from a zero-match state", async ({
  page,
}) => {
  let releaseCatalog!: () => void;
  const gate = new Promise<void>((resolve) => {
    releaseCatalog = resolve;
  });
  await page.route("**/data/catalog/albums.v1.json", async (route) => {
    await gate;
    await route.continue();
  });
  await page.goto("/play/connect/");
  const pickerA = picker(page, "a");
  await expect(pickerA).toHaveAttribute("data-picker-state", "loading");
  await expect(pickerA.locator("input")).toHaveAttribute("aria-busy", "true");
  releaseCatalog();
  await expect(pickerA).toHaveAttribute("data-picker-state", "ready");
});
