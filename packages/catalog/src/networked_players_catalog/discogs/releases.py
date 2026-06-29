"""Streaming normalization of Discogs release dump XML."""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from lxml import etree


@dataclass(slots=True)
class ParsedRelease:
    release: dict[str, object]
    tracks: list[dict[str, object]]
    credits: list[dict[str, object]]


def _text(element: etree._Element, path: str) -> str | None:
    value = element.findtext(path)
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
    track_position: str | None,
    track_title: str | None,
) -> dict[str, object]:
    artist_id = _integer(_text(artist, "id"))
    return {
        "snapshot_date": snapshot_date,
        "release_id": release_id,
        "track_index": track_index,
        "track_position": track_position,
        "track_title": track_title,
        "credit_scope": scope,
        "artist_id": artist_id,
        "name": _text(artist, "name"),
        "anv": _text(artist, "anv"),
        "join_text": _text(artist, "join"),
        "role_text": _text(artist, "role"),
        "credited_tracks_text": _text(artist, "tracks"),
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
                track_position=track_position,
                track_title=track_title,
            )
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
    release = {
        "snapshot_date": snapshot_date,
        "release_id": release_id,
        "status": element.attrib.get("status"),
        "title": _text(element, "title"),
        "country": _text(element, "country"),
        "released": _text(element, "released"),
        "master_id": master_id,
        "master_is_main_release": (
            master is not None and master.attrib.get("is_main_release", "false").lower() == "true"
        ),
        "data_quality": _text(element, "data_quality"),
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
    for track_index, track in enumerate(element.findall("tracklist/track")):
        position = _text(track, "position")
        title = _text(track, "title")
        tracks.append(
            {
                "snapshot_date": snapshot_date,
                "release_id": release_id,
                "track_index": track_index,
                "position": position,
                "title": title,
                "duration": _text(track, "duration"),
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
            track_position=position,
            track_title=title,
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
        handle_context = gzip.open(path, "rb")
    else:
        handle_context = path.open("rb")
    with handle_context as handle:
        yield from _iter_handle(
            handle,
            snapshot_date=snapshot_date,
            source_url=source_url,
            max_releases=max_releases,
        )
