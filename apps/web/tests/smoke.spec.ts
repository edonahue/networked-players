import { expect, test } from '@playwright/test';

test('home renders hero and nav', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Trace the credits');
  await expect(page.getByRole('link', { name: 'Try the demo' }).first()).toBeVisible();
});

test('about page renders', async ({ page }) => {
  await page.goto('/about/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
});

test('demo renders a path with evidence and switches paths', async ({ page }) => {
  await page.goto('/demo/');
  // First path visible by default with an evidence table.
  await expect(page.locator('.path-card:not([hidden])')).toHaveCount(1);
  await expect(page.locator('.path-card:not([hidden]) .evidence table').first()).toBeVisible();

  // Switch to another path via the picker.
  await page.getByRole('button', { name: 'Casey Guitar → Robin Strings' }).click();
  await expect(page.locator('.path-card:not([hidden])')).toHaveCount(1);
  await expect(page.locator('.path-card:not([hidden])')).toContainText('Robin Strings');
});

test('theme toggle persists', async ({ page }) => {
  await page.goto('/');
  const html = page.locator('html');
  await expect(html).toHaveAttribute('data-theme', 'dark');
  await page.locator('[data-theme-toggle]').click();
  await expect(html).toHaveAttribute('data-theme', 'light');
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'light');
});

test('static demo artifact is reachable', async ({ request }) => {
  const res = await request.get('/data/challenge.v1.json');
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.schema_version).toBe(1);
  expect(Array.isArray(body.paths)).toBe(true);
});
