"""Streaming normalization of Discogs artist dump XML -- group/member relations only.

Real dump structure is documented in ``docs/discogs-data/raw-dump-schema.md``
("artists.xml.gz"): root ``<artists>``, one ``<artist>`` child per record,
``<id>`` a child element (not an attribute). This parser reads only the
``<groups>`` and ``<members>`` tags -- real, Discogs-editorial, numeric-ID-linked
band/member relationships (e.g. artist 2, a duo, lists members 26 and 27 by
ID) -- and ignores every other field (``name``, ``profile``, ``urls``,
``aliases``, ``namevariations``, ...). This is deliberately narrower than a
general artist parser: the only consumer is group/frontperson relationship
exclusion for game rounds (see ``eligibility.py`` and
``data/albums/artist-family-exclusions-v1.json``), which needs only the
relation graph, never artist biography or alias data.

``<members>`` (on a group-type artist's record) and ``<groups>`` (on an
individual's record) are each other's inverse, but Discogs' own dump is not
guaranteed to mirror them consistently in both directions -- this parser
preserves each tag's rows independently, tagged with which side of the
mirror they came from, rather than assuming symmetry.

Same streaming posture as ``releases.py``/``masters.py``: iterparse with
per-element clearing, memory bounded regardless of dump size.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from lxml import etree

from .releases import _child_text_map, _integer, _text_from_map


@dataclass(slots=True)
class ParsedArtistRelations:
    artist_id: int
    relations: list[dict[str, object]]


def _relation_rows(
    element: etree._Element,
    *,
    tag: str,
    relation: str,
    artist_id: int,
    snapshot_date: str,
    source_url: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name in element.findall(f"{tag}/name"):
        related_id = _integer(name.attrib.get("id"))
        if related_id is None:
            continue
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "artist_id": artist_id,
                "related_artist_id": related_id,
                "related_name": name.text.strip() if name.text else None,
                "relation": relation,
                "source_url": source_url,
            }
        )
    return rows


def parse_artist_element(
    element: etree._Element,
    *,
    snapshot_date: str,
    source_url: str,
) -> ParsedArtistRelations | None:
    text_map = _child_text_map(element)
    artist_id = _integer(_text_from_map(text_map, "id"))
    if artist_id is None:
        return None
    relations = _relation_rows(
        element,
        tag="groups",
        relation="member_of",
        artist_id=artist_id,
        snapshot_date=snapshot_date,
        source_url=source_url,
    ) + _relation_rows(
        element,
        tag="members",
        relation="has_member",
        artist_id=artist_id,
        snapshot_date=snapshot_date,
        source_url=source_url,
    )
    return ParsedArtistRelations(artist_id=artist_id, relations=relations)


def _iter_handle(
    handle: BinaryIO,
    *,
    snapshot_date: str,
    source_url: str,
    max_artists: int | None,
) -> Iterator[ParsedArtistRelations]:
    count = 0
    context = etree.iterparse(
        handle,
        events=("end",),
        tag="artist",
        huge_tree=True,
        recover=False,
        resolve_entities=False,
        no_network=True,
    )
    for _, element in context:
        parsed = parse_artist_element(element, snapshot_date=snapshot_date, source_url=source_url)
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
        if parsed is not None:
            yield parsed
        count += 1
        if max_artists is not None and count >= max_artists:
            break


def iter_artist_relations(
    path: Path,
    *,
    snapshot_date: str,
    source_url: str,
    max_artists: int | None = None,
) -> Iterator[ParsedArtistRelations]:
    """Yield normalized group/member relations while keeping XML memory bounded."""

    if max_artists is not None and max_artists <= 0:
        raise ValueError("max_artists must be positive")
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as handle:
            yield from _iter_handle(
                cast(BinaryIO, handle),
                snapshot_date=snapshot_date,
                source_url=source_url,
                max_artists=max_artists,
            )
    else:
        with path.open("rb") as handle:
            yield from _iter_handle(
                cast(BinaryIO, handle),
                snapshot_date=snapshot_date,
                source_url=source_url,
                max_artists=max_artists,
            )
