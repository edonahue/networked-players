// Gates the ?date= override for Connection of the Day (corrective slice
// 5.1). The override exists so Playwright and local development can pin a
// specific calendar date; it must never let a production visitor peek at a
// future scheduled connection just by editing the URL. No secret is
// involved -- the committed manifest is public either way -- this is only
// about not casually exposing "tomorrow's" answer through a query string.
//
// Allowed when EITHER is true:
//   - `import.meta.env.DEV` -- true only under `astro dev`, false for both
//     `astro build` and the `astro preview` server Playwright's webServer
//     runs against, so a real production deploy (`astro build` +
//     `wrangler deploy`) never has this set.
//   - a test-only global, `window.__NP_ALLOW_DATE_OVERRIDE__ === true`,
//     which only exists when a test harness (Playwright, via
//     `page.addInitScript`) explicitly injects it before navigation. There
//     is no way to set this from outside the page's own JS context, so a
//     production visitor cannot flip it via the URL or dev tools without
//     already having script execution on the page.

declare global {
  interface Window {
    __NP_ALLOW_DATE_OVERRIDE__?: boolean;
  }
}

export function isDateOverrideAllowed(): boolean {
  if (import.meta.env.DEV) return true;
  return (
    typeof window !== "undefined" && window.__NP_ALLOW_DATE_OVERRIDE__ === true
  );
}
