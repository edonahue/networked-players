// Shared driver for the Connect Two Records album pickers.
//
// The readiness wait is the whole point. The picker publishes
// `data-picker-state="ready"` on its root once the album catalog has loaded
// (see src/game/connect.ts). Before that contract existed, every spec here
// filled the input and leaned on Playwright's locator auto-retry to paper
// over the initialization race -- which meant a genuinely broken picker and a
// merely slow one were indistinguishable, and a fill that landed before init
// simply hung until the expect timeout. Gating on the real state attribute
// makes the wait explicit and the failure honest.

import { expect, type Page } from "@playwright/test";

export type PickerSide = "a" | "b";

export function picker(page: Page, side: PickerSide) {
  return page.locator(`[data-picker="${side}"]`);
}

export function pickerResults(page: Page, side: PickerSide) {
  return picker(page, side).locator("[data-picker-results] [role='option']");
}

export async function waitForPickerReady(
  page: Page,
  side: PickerSide,
): Promise<void> {
  await expect(picker(page, side)).toHaveAttribute(
    "data-picker-state",
    "ready",
  );
}

export async function selectAlbum(
  page: Page,
  side: PickerSide,
  query: string,
): Promise<void> {
  await waitForPickerReady(page, side);
  await picker(page, side).locator("input").fill(query);
  await pickerResults(page, side).first().click();
}

export type RouteFilterMode = "none" | "rhythm-section" | "guitar-paths";

/** Picks a route filter chip in Connect's role="radiogroup" tray (Slice 4
 * of the UI design/copy pass -- previously a native radio input, `.check()`
 * -able; now a `role="radio"` button, activated the same way a real visitor
 * would: a click). Previously copy-pasted byte-for-byte into three separate
 * spec files. */
export async function selectRouteFilter(
  page: Page,
  value: RouteFilterMode,
): Promise<void> {
  await page
    .locator(`[data-connect-mode-option][data-value="${value}"]`)
    .click();
}
