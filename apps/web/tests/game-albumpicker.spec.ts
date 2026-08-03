import { expect, test } from "@playwright/test";
import { filterAlbums, type PickableAlbum } from "../src/game/albumPicker";

const ALBUMS: PickableAlbum[] = [
  {
    id: "master-1",
    title: "The Dark Side Of The Moon",
    artist: "Pink Floyd",
    artist_id: 1,
    year: 1973,
  },
  {
    id: "master-2",
    title: "Nevermind",
    artist: "Nirvana",
    artist_id: 2,
    year: 1991,
  },
  {
    id: "master-3",
    title: "Moon Safari",
    artist: "Air",
    artist_id: 3,
    year: 1998,
  },
];

test("empty query returns no results", () => {
  expect(filterAlbums(ALBUMS, "")).toEqual([]);
  expect(filterAlbums(ALBUMS, "   ")).toEqual([]);
});

test("matches by title, case-insensitively", () => {
  const results = filterAlbums(ALBUMS, "moon");
  expect(results.map((a) => a.id)).toEqual(["master-1", "master-3"]);
});

test("matches by artist name", () => {
  const results = filterAlbums(ALBUMS, "nirvana");
  expect(results.map((a) => a.id)).toEqual(["master-2"]);
});

test("respects the limit", () => {
  const results = filterAlbums(ALBUMS, "a", 1);
  expect(results).toHaveLength(1);
});
