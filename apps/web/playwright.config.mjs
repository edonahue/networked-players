import { existsSync } from 'node:fs';
import { defineConfig } from '@playwright/test';

// Use the pre-installed Chromium in this environment when present, rather than
// downloading a browser. Falls back to Playwright's managed browser locally.
const preinstalledChromium = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const launchOptions = existsSync(preinstalledChromium)
  ? { executablePath: preinstalledChromium }
  : {};

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: 'http://127.0.0.1:4321',
    browserName: 'chromium',
    trace: 'retain-on-failure',
    launchOptions,
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4321',
    url: 'http://127.0.0.1:4321',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'list',
});
