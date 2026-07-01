"""Streaming normalization of Discogs release dump XML."""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from lxml import etree


@dataclass(slots=True)
class ParsedRelease:
    release: dict[str, object]
    tracks: list[dict[str, object]]
    credits: list[dict[str, object]]


def _child_text_map(element: etree._Element) -> dict[str, str | None]:
    """Direct children's text, keyed by tag; first occurrence wins (matches
    findtext()'s semantics). Real profiling (docs/DATA_SIZING.md, 2026-07-01) found
    repeated per-field findtext() calls -- each a fresh linear scan of an element's
    children -- were 54% of total parse time on a 50,000-release sample. Building
    this map once per element and doing O(1) lookups against it removes that
    redundant rescanning; only the tag names this parser actually reads are ever
    looked up, so unread children (e.g. a release's <labels>, <formats>, <notes>)
    are harmlessly present in the map but never touched.
    """
    result: dict[str, str | None] = {}
    for child in element:
        if child.tag not in result:
            result[child.tag] = child.text
    return result


def _text_from_map(text_map: dict[str, str | None], tag: str) -> str | None:
    value = text_map.get(tag)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _artist_row(
    artist: etree._Element,
    *,
    snapshot_date: str,
    release_id: int,
    scope: str,
    track_index: int | None,
    track_path: str | None,
    track_position: str | None,
    track_title: str | None,
) -> dict[str, object]:
    text_map = _child_text_map(artist)
    artist_id = _integer(_text_from_map(text_map, "id"))
    return {
        "snapshot_date": snapshot_date,
        "release_id": release_id,
        "track_index": track_index,
        "track_path": track_path,
        "track_position": track_position,
        "track_title": track_title,
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": _text_from_map(text_map, "name"),
        "anv": _text_from_map(text_map, "anv"),
        "join_text": _text_from_map(text_map, "join"),
        "role_text": _text_from_map(text_map, "role"),
        "credited_tracks_text": _text_from_map(text_map, "tracks"),
        "is_linked": artist_id is not None,
        "playable_identity": artist_id is not None,
    }


def _append_artists(
    parent: etree._Element,
    xpath: str,
    output: list[dict[str, object]],
    *,
    snapshot_date: str,
    release_id: int,
    scope: str,
    track_index: int | None = None,
    track_path: str | None = None,
    track_position: str | None = None,
    track_title: str | None = None,
) -> None:
    for artist in parent.findall(xpath):
        output.append(
            _artist_row(
                artist,
                snapshot_date=snapshot_date,
                release_id=release_id,
                scope=scope,
                track_index=track_index,
                track_path=track_path,
                track_position=track_position,
                track_title=track_title,
            )
        )


def _append_track_tree(
    track: etree._Element,
    *,
    path: tuple[int, ...],
    parent_track_index: int | None,
    snapshot_date: str,
    release_id: int,
    tracks: list[dict[str, object]],
    credits: list[dict[str, object]],
) -> None:
    """Flatten one track and its nested subtracks while preserving hierarchy."""

    track_index = len(tracks)
    track_path = ".".join(str(component) for component in path)
    text_map = _child_text_map(track)
    position = _text_from_map(text_map, "position")
    title = _text_from_map(text_map, "title")
    tracks.append(
        {
            "snapshot_date": snapshot_date,
            "release_id": release_id,
            "track_index": track_index,
            "parent_track_index": parent_track_index,
            "track_path": track_path,
            "position": position,
            "title": title,
            "duration": _text_from_map(text_map, "duration"),
        }
    )
    _append_artists(
        track,
        "artists/artist",
        credits,
        snapshot_date=snapshot_date,
        release_id=release_id,
        scope="track_artist",
        track_index=track_index,
        track_path=track_path,
        track_position=position,
        track_title=title,
    )
    _append_artists(
        track,
        "extraartists/artist",
        credits,
        snapshot_date=snapshot_date,
        release_id=release_id,
        scope="track_credit",
        track_index=track_index,
        track_path=track_path,
        track_position=position,
        track_title=title,
    )

    for child_index, subtrack in enumerate(track.findall("sub_tracks/track")):
        _append_track_tree(
            subtrack,
            path=(*path, child_index),
            parent_track_index=track_index,
            snapshot_date=snapshot_date,
            release_id=release_id,
            tracks=tracks,
            credits=credits,
        )


def parse_release_element(
    element: etree._Element,
    *,
    snapshot_date: str,
    source_url: str,
) -> ParsedRelease:
    release_id = int(element.attrib["id"])
    master = element.find("master_id")
    master_id = _integer(master.text.strip() if master is not None and master.text else None)
    text_map = _child_text_map(element)
    release = {
        "snapshot_date": snapshot_date,
        "release_id": release_id,
        "status": element.attrib.get("status"),
        "title": _text_from_map(text_map, "title"),
        "country": _text_from_map(text_map, "country"),
        "released": _text_from_map(text_map, "released"),
        "master_id": master_id,
        "master_is_main_release": (
            master is not None and master.attrib.get("is_main_release", "false").lower() == "true"
        ),
        "data_quality": _text_from_map(text_map, "data_quality"),
        "source_url": source_url,
    }

    credits: list[dict[str, object]] = []
    _append_artists(
        element,
        "artists/artist",
        credits,
        snapshot_date=snapshot_date,
        release_id=release_id,
        scope="release_artist",
    )
    _append_artists(
        element,
        "extraartists/artist",
        credits,
        snapshot_date=snapshot_date,
        release_id=release_id,
        scope="release_credit",
    )

    tracks: list[dict[str, object]] = []
    for top_level_index, track in enumerate(element.findall("tracklist/track")):
        _append_track_tree(
            track,
            path=(top_level_index,),
            parent_track_index=None,
            snapshot_date=snapshot_date,
            release_id=release_id,
            tracks=tracks,
            credits=credits,
        )

    return ParsedRelease(release=release, tracks=tracks, credits=credits)


def _iter_handle(
    handle: BinaryIO,
    *,
    snapshot_date: str,
    source_url: str,
    max_releases: int | None,
) -> Iterator[ParsedRelease]:
    count = 0
    context = etree.iterparse(
        handle,
        events=("end",),
        tag="release",
        huge_tree=True,
        recover=False,
        resolve_entities=False,
        no_network=True,
    )
    for _, element in context:
        yield parse_release_element(element, snapshot_date=snapshot_date, source_url=source_url)
        count += 1
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
        if max_releases is not None and count >= max_releases:
            break


def iter_releases(
    path: Path,
    *,
    snapshot_date: str,
    source_url: str,
    max_releases: int | None = None,
) -> Iterator[ParsedRelease]:
    """Yield normalized releases while keeping XML memory bounded."""

    if max_releases is not None and max_releases <= 0:
        raise ValueError("max_releases must be positive")
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as handle:
            yield from _iter_handle(
                cast(BinaryIO, handle),
                snapshot_date=snapshot_date,
                source_url=source_url,
                max_releases=max_releases,
            )
    else:
        with path.open("rb") as handle:
            yield from _iter_handle(
                cast(BinaryIO, handle),
                snapshot_date=snapshot_date,
                source_url=source_url,
                max_releases=max_releases,
            )
