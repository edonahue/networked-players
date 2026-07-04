"""Streaming normalization of Discogs master dump XML.

A master groups the release variants of one logical album/work; its
``main_release`` is the release Discogs considers canonical for it. Real
dump structure is documented in ``docs/discogs-data/raw-dump-schema.md``
("masters.xml.gz"): root ``<masters>``, one ``<master id="N">`` child per
record, with ``main_release``, ``artists`` (same id/name/anv/join shape as
a release's release-level artist credit), ``genres``, ``styles``, ``year``,
``title``, and ``data_quality``.

Same evidence rules as the release parser: a linked positive artist ID is
the playable identity; a non-linked name is retained as evidence only.
Same streaming posture: iterparse over the (optionally gzipped) XML with
per-element clearing -- expanded XML never required on disk, memory
bounded regardless of dump size.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from lxml import etree

from .releases import _child_text_map, _integer, _normalize_text, _text_from_map


@dataclass(slots=True)
class ParsedMaster:
    master: dict[str, object]
    artists: list[dict[str, object]]


def parse_master_element(
    element: etree._Element,
    *,
    snapshot_date: str,
    source_url: str,
) -> ParsedMaster:
    master_id = int(element.attrib["id"])
    text_map = _child_text_map(element)
    master = {
        "snapshot_date": snapshot_date,
        "master_id": master_id,
        "main_release_id": _integer(_text_from_map(text_map, "main_release")),
        "title": _text_from_map(text_map, "title"),
        "year": _integer(_text_from_map(text_map, "year")),
        "genres": [
            genre
            for child in element.findall("genres/genre")
            if (genre := _normalize_text(child.text)) is not None
        ],
        "styles": [
            style
            for child in element.findall("styles/style")
            if (style := _normalize_text(child.text)) is not None
        ],
        "data_quality": _text_from_map(text_map, "data_quality"),
        "source_url": source_url,
    }

    artists: list[dict[str, object]] = []
    for artist in element.findall("artists/artist"):
        artist_map = _child_text_map(artist)
        artist_id = _integer(_text_from_map(artist_map, "id"))
        artists.append(
            {
                "snapshot_date": snapshot_date,
                "master_id": master_id,
                "artist_id": artist_id,
                "name": _text_from_map(artist_map, "name"),
                "anv": _text_from_map(artist_map, "anv"),
                "join_text": _text_from_map(artist_map, "join"),
                "is_linked": artist_id is not None,
                "playable_identity": artist_id is not None,
            }
        )
    return ParsedMaster(master=master, artists=artists)


def _iter_handle(
    handle: BinaryIO,
    *,
    snapshot_date: str,
    source_url: str,
    max_masters: int | None,
) -> Iterator[ParsedMaster]:
    count = 0
    context = etree.iterparse(
        handle,
        events=("end",),
        tag="master",
        huge_tree=True,
        recover=False,
        resolve_entities=False,
        no_network=True,
    )
    for _, element in context:
        yield parse_master_element(element, snapshot_date=snapshot_date, source_url=source_url)
        count += 1
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
        if max_masters is not None and count >= max_masters:
            break


def iter_masters(
    path: Path,
    *,
    snapshot_date: str,
    source_url: str,
    max_masters: int | None = None,
) -> Iterator[ParsedMaster]:
    """Yield normalized masters while keeping XML memory bounded."""

    if max_masters is not None and max_masters <= 0:
        raise ValueError("max_masters must be positive")
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as handle:
            yield from _iter_handle(
                cast(BinaryIO, handle),
                snapshot_date=snapshot_date,
                source_url=source_url,
                max_masters=max_masters,
            )
    else:
        with path.open("rb") as handle:
            yield from _iter_handle(
                cast(BinaryIO, handle),
                snapshot_date=snapshot_date,
                source_url=source_url,
                max_masters=max_masters,
            )
