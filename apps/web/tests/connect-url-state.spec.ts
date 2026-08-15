// Unit specs for Connect's shareable URL state (ADR 0059 Phase 5 PR 4) --
// pure parse/build logic, no browser or fetch needed.

import { expect, test } from "@playwright/test";
import {
  buildConnectSearchParams,
  isSameConnectAlbumPair,
  parseConnectUrlParams,
} from "../src/game/connectUrlState";

const VALID_MODES = new Set([
  "behind-the-glass",
  "rhythm-section",
  "guitar-paths",
]);

test.describe("parseConnectUrlParams", () => {
  test("parses a real a/b/mode query string", () => {
    expect(
      parseConnectUrlParams(
        "?a=master-1&b=master-2&mode=behind-the-glass",
        VALID_MODES,
      ),
    ).toEqual({
      albumAId: "master-1",
      albumBId: "master-2",
      mode: "behind-the-glass",
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
