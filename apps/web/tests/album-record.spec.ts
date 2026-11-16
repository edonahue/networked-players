// The album page as a record: roster, "where these players lead", and
// evidence that reads without JavaScript. Albums are picked by reading the
// committed artifacts, never by hardcoded name.

import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { pickBoundedConnectedAlbum } from "./helpers/challengeAlbums";
import { stubCoverArt } from "./helpers/coverArt";

// Plain instrument/vocal role strings that are unambiguously performance
// credits; deliberately a tiny independent list, not the page's own logic.
const PLAIN_PERFORMER_ROLES = new Set([
  "Drums",
  "Bass",
  "Guitar",
  "Vocals",
  "Piano",
  "Keyboards",
  "Backing Vocals",
  "Lead Vocals",
]);

async function pickAlbumWithLeads(request: APIRequestContext) {
  const [membershipRes, challengeRes] = await Promise.all([
    request.get("/data/albums/credit-membership.v1.json"),
    request.get("/data/challenge.v3.json"),
  ]);
  const membership = (await membershipRes.json()) as {
    albums: {
      album_id: string;
      credits: {
        artist_id: number;
        credit_scope: string;
        role_text: string | null;
      }[];
    }[];
  };
  const { albums } = (await challengeRes.json()) as {
    albums: { id: string; title: string; artist_id: number }[];
  };
  const albumById = new Map(albums.map((a) => [a.id, a]));
  const performers = new Map<string, Set<number>>();
  for (const entry of membership.albums) {
    performers.set(
      entry.album_id,
      new Set(
        entry.credits
          .filter(
            (c) =>
              c.credit_scope !== "release_artist" &&
              c.role_text !== null &&
              PLAIN_PERFORMER_ROLES.has(c.role_text),
          )
          .map((c) => c.artist_id),
      ),
    );
  }
  // Smallest page first keeps the test fast; ties broken by id.
  const sorted = [...performers.entries()]
    .filter(([id, set]) => set.size >= 3 && albumById.has(id))
    .sort((a, b) => a[1].size - b[1].size || a[0].localeCompare(b[0]));
  for (const [id, mine] of sorted) {
    const me = albumById.get(id)!;
    for (const [otherId, theirs] of performers) {
      const other = albumById.get(otherId);
      if (!other || otherId === id || other.artist_id === me.artist_id)
        continue;
      if ([...mine].some((a) => theirs.has(a))) return { album: me };
    }
  }
  throw new Error("no album with a cross-artist shared performer found");
}

async function expectNoViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations,
    results.violations
      .map(
        (v) =>
          `[${v.impact}] ${v.id}: ${v.description} -- ${v.nodes
            .map((n) => n.target.join(" "))
            .join(", ")}`,
      )
      .join("\n"),
  ).toEqual([]);
}

test("with JavaScript disabled the roster, a lead and the evidence are all readable", async ({
  browser,
  request,
}) => {
  const { album } = await pickAlbumWithLeads(request);
  const { album: connected } = await pickBoundedConnectedAlbum(request);
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await stubCoverArt(page);

  // Roster + leads on an album that has shared performers.
  await page.goto(`/albums/${album.id}/`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    album.title,
  );
  await expect(
    page.getByRole("heading", { level: 2, name: "Who played on this record" }),
  ).toBeVisible();
  const firstPerson = page
    .locator("[data-record-roster] .roster-list li")
    .first();
  await expect(firstPerson).toBeVisible();
  await expect(firstPerson.locator(".roster-person__name")).not.toHaveText("");
  await expect(
    page.getByRole("heading", { level: 2, name: "Where these players lead" }),
  ).toBeVisible();
  const lead = page.locator("[data-record-leads] .lead").first();
  await expect(lead).toBeVisible();
  await expect(lead.locator(".lead__shared")).toContainText("shared player");
  await expect(
    lead.locator("a[href^='/albums/master-']").first(),
  ).toBeVisible();
  await expect(
    lead.getByRole("link", { name: /Connect these two/ }),
  ).toHaveAttribute(
    "href",
    new RegExp(`^/play/connect/\\?a=${album.id}&b=master-\\d+$`),
  );

  // Evidence on an album with documented paths: no hidden attribute, no
  // masked text, no guess controls without scripting.
  await page.goto(`/albums/${connected.id}/`);
  await expect(page.locator("[data-guess-toggle]")).toBeHidden();
  await expect(page.locator("[data-guess-mask]:visible")).toHaveCount(0);
  await expect(page.locator("[data-guess-title]").first()).toBeVisible();
  const table = page.locator("[data-connection] .evidence table").first();
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Role" })).toBeVisible();
  await expect(table.locator("tbody tr").first()).toBeVisible();
  // Evidence is a native <details>, so it opens with no script.
  const summaries = page.locator("[data-connection] > details > summary");
  expect(await summaries.count()).toBeGreaterThan(0);

  await context.close();
});

test("an album page has no accessibility violations in dark and light themes", async ({
  page,
  request,
}) => {
  test.slow();
  const { album } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);
  await page.goto(`/albums/${album.id}/`);
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", "light");
  await expectNoViolations(page);

  await page.locator("[data-theme-toggle]").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expectNoViolations(page);
});

test("guess mode keeps no accessibility violations", async ({
  page,
  request,
}) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);
  await page.goto(`/albums/${album.id}/`);
  await page
    .getByRole("button", { name: "Guess the connections first" })
    .click();
  await expectNoViolations(page);
});

test.describe("at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the album page does not scroll sideways and controls are 44px targets", async ({
    page,
    request,
  }) => {
    const { album } = await pickBoundedConnectedAlbum(request);
    await stubCoverArt(page);
    await page.goto(`/albums/${album.id}/`);
    await expect(
      page.getByRole("heading", {
        level: 2,
        name: "Who played on this record",
      }),
    ).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    for (const locator of [
      page.getByRole("button", { name: "Guess the connections first" }),
      page.locator("[data-connection] summary").first(),
      page.getByRole("link", { name: /Search this route/ }).first(),
    ]) {
      const box = await locator.boundingBox();
      expect(box, "control is rendered").not.toBeNull();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  });
});

test("heading order never skips a level", async ({ page, request }) => {
  const { album } = await pickBoundedConnectedAlbum(request);
  await stubCoverArt(page);
  await page.goto(`/albums/${album.id}/`);
  const levels = await page
    .locator("main h1, main h2, main h3, main h4")
    .evaluateAll((els) => els.map((e) => Number(e.tagName.slice(1))));
  expect(levels[0]).toBe(1);
  for (let i = 1; i < levels.length; i++) {
    expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
  }
});

test("a very large roster is compact with a native expander", async ({
  page,
  request,
}) => {
  const res = await request.get("/data/albums/credit-membership.v1.json");
  const { albums } = (await res.json()) as {
    albums: { album_id: string; credits: { artist_id: number }[] }[];
  };
  const biggest = albums
    .map((a) => ({
      id: a.album_id,
      people: new Set(a.credits.map((c) => c.artist_id)).size,
    }))
    .sort((a, b) => b.people - a.people)[0];
  await stubCoverArt(page);
  await page.goto(`/albums/${biggest.id}/`);
  const expander = page
    .locator("[data-record-roster] details.record-more > summary")
    .first();
  await expect(expander).toContainText("Show all");
  // Collapsed by default: only a bounded number of roster rows are visible.
  const visibleRows = await page
    .locator("[data-record-roster] .roster-list li:visible")
    .count();
  expect(visibleRows).toBeLessThanOrEqual(30 + 12);
});
