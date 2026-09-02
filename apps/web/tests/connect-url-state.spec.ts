// Unit specs for Connect's shareable URL state (ADR 0059 Phase 5 PR 4) --
// pure parse/build logic, no browser or fetch needed.

import { expect, test } from "@playwright/test";
import {
  buildConnectSearchParams,
  isSameConnectAlbumPair,
  parseConnectUrlParams,
  parsePartialConnectUrlParams,
} from "../src/game/connectUrlState";

// The app's real surviving mode set -- "behind-the-glass" was retired with
// the ADR 0068 cutover and is now exercised below as an UNRECOGNIZED mode,
// which is exactly what an old bookmarked link now carries.
const VALID_MODES = new Set(["rhythm-section", "guitar-paths"]);

test.describe("parseConnectUrlParams", () => {
  test("parses a real a/b/mode query string", () => {
    expect(
      parseConnectUrlParams(
        "?a=master-1&b=master-2&mode=rhythm-section",
        VALID_MODES,
      ),
    ).toEqual({
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "rhythm-section",
    });
  });

  test("a retired mode in an old link degrades to the default", () => {
    // ADR 0068 retired Behind the Glass. A bookmarked or shared
    // `?mode=behind-the-glass` link must land on a real, correctly-labeled
    // default search rather than erroring or silently keeping a mode the
    // app can no longer satisfy -- this is the parser-level guarantee the
    // Connect UI test relies on.
    expect(
      parseConnectUrlParams(
        "?a=master-1&b=master-2&mode=behind-the-glass",
        VALID_MODES,
      ),
    ).toEqual({
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "none",
    });
  });

  test("mode absent defaults to none", () => {
    expect(
      parseConnectUrlParams("?a=master-1&b=master-2", VALID_MODES),
    ).toEqual({
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "none",
    });
  });

  test("an unrecognized mode value falls back to none, not an error", () => {
    expect(
      parseConnectUrlParams(
        "?a=master-1&b=master-2&mode=retired-mode",
        VALID_MODES,
      ),
    ).toEqual({ albumAId: "master-1", albumBId: "master-2", mode: "none" });
  });

  test("missing a or b is rejected", () => {
    expect(parseConnectUrlParams("?a=master-1", VALID_MODES)).toBeNull();
    expect(parseConnectUrlParams("?b=master-2", VALID_MODES)).toBeNull();
    expect(parseConnectUrlParams("", VALID_MODES)).toBeNull();
  });

  test("an empty a or b is rejected, not treated as a real id", () => {
    expect(parseConnectUrlParams("?a=&b=master-2", VALID_MODES)).toBeNull();
  });

  test("a and b naming the same album is rejected as conflicting, not silently repaired", () => {
    expect(
      parseConnectUrlParams("?a=master-1&b=master-1", VALID_MODES),
    ).toBeNull();
  });

  test("a duplicated param resolves to its first occurrence, deterministically", () => {
    expect(
      parseConnectUrlParams("?a=master-1&a=master-9&b=master-2", VALID_MODES),
    ).toEqual({ albumAId: "master-1", albumBId: "master-2", mode: "none" });
  });

  test("unrelated params are ignored, not rejected", () => {
    expect(
      parseConnectUrlParams(
        "?utm_source=test&a=master-1&b=master-2",
        VALID_MODES,
      ),
    ).toEqual({ albumAId: "master-1", albumBId: "master-2", mode: "none" });
  });
});

test.describe("buildConnectSearchParams", () => {
  test("serializes a/b in canonical order", () => {
    const params = buildConnectSearchParams({
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "none",
    });
    expect(params.toString()).toBe("a=master-1&b=master-2");
  });

  test("omits mode entirely when it is the unfiltered default", () => {
    const params = buildConnectSearchParams({
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "none",
    });
    expect(params.has("mode")).toBe(false);
  });

  test("includes a non-default mode, still in canonical order", () => {
    const params = buildConnectSearchParams({
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "rhythm-section",
    });
    expect(params.toString()).toBe("a=master-1&b=master-2&mode=rhythm-section");
  });

  test("round-trips through parseConnectUrlParams", () => {
    const state = {
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "guitar-paths",
    };
    const params = buildConnectSearchParams(state);
    expect(parseConnectUrlParams(`?${params.toString()}`, VALID_MODES)).toEqual(
      state,
    );
  });
});

test.describe("isSameConnectAlbumPair", () => {
  test("true for the same pair even when mode differs -- the real push-vs-replace test", () => {
    expect(
      isSameConnectAlbumPair(
        "?a=master-1&b=master-2",
        { albumAId: "master-1", albumBId: "master-2", mode: "rhythm-section" },
        VALID_MODES,
      ),
    ).toBe(true);
  });

  test("false when either album differs", () => {
    expect(
      isSameConnectAlbumPair(
        "?a=master-1&b=master-2",
        { albumAId: "master-1", albumBId: "master-9", mode: "none" },
        VALID_MODES,
      ),
    ).toBe(false);
  });

  test("false when nothing is in the URL yet", () => {
    expect(
      isSameConnectAlbumPair(
        "",
        { albumAId: "master-1", albumBId: "master-2", mode: "none" },
        VALID_MODES,
      ),
    ).toBe(false);
  });
});

test.describe("parsePartialConnectUrlParams", () => {
  test("parses a real single a= query string", () => {
    expect(parsePartialConnectUrlParams("?a=master-1")).toEqual({
      albumAId: "master-1",
    });
  });

  test("null when a is absent", () => {
    expect(parsePartialConnectUrlParams("")).toBeNull();
    expect(parsePartialConnectUrlParams("?b=master-2")).toBeNull();
  });

  test("null when a is present but empty", () => {
    expect(parsePartialConnectUrlParams("?a=")).toBeNull();
  });

  // A URL naming a b at all -- even a self-referential a===b -- belongs
  // entirely to parseConnectUrlParams's own "reject, populate nothing"
  // contract; this function must never quietly override that by treating
  // a rejected pair as a valid single-sided one.
  test("null whenever b is present, even self-referentially", () => {
    expect(
      parsePartialConnectUrlParams("?a=master-1&b=master-2&mode=x"),
    ).toBeNull();
    expect(parsePartialConnectUrlParams("?a=master-1&b=master-1")).toBeNull();
  });
});
