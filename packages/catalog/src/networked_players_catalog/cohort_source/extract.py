"""Extract album candidates from a saved cohort-source HTML page.

See data/contracts/album-cohort-extracted-v1.md and
docs/decisions/0028-curated-cohort-source-ingestion.md. No live fetching: the
caller always supplies HTML already saved to disk by the operator -- this
module never makes a network request and never will (ADR 0028).

Extraction never *infers* a Discogs identity: `master_id`/`release_id` are
populated only from a literal `/master/<id>` or `/release/<id>` link visible
in the source HTML. A record with ambiguous or missing data is never
dropped -- its field is left null and a warning is appended instead, the
same evidence-preservation spirit `packages/catalog/discogs` applies to
non-linked credit names.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lxml.html
from lxml.etree import ParserError

from .source import CohortSourceMeta

EXTRACTOR_VERSION = 1
CANDIDATE_SCHEMA_VERSION = 1

_MIN_LIST_ITEMS_TO_TRUST = 3
_RANK_PREFIX_RE = re.compile(r"^\s*#?(?P<rank>\d{1,3})[.):]\s*(?P<rest>.+)$", re.DOTALL)
_YEAR_RE = re.compile(r"\(?((?:19|20)\d{2})\)?")
_ARTIST_TITLE_SEPARATORS = (" – ", " — ", " - ")  # en dash, em dash, hyphen  # noqa: RUF001
_MASTER_LINK_RE = re.compile(r"/master/(\d+)")
_RELEASE_LINK_RE = re.compile(r"/release/(\d+)")
_FALLBACK_TAGS = ("h1", "h2", "h3", "h4", "p", "li", "div")

# A second, structural block layout seen on Discogs's own "Digs" listicle pages: each
# entry is a card with title/artist/year in separate classed elements (no inline rank
# text, no artist/title separator to split) rather than one text blob per list item.
_RELEASE_CARD_CONTAINER_CLASS = "release-block-info"
_RELEASE_CARD_TITLE_CLASS = "release-block-title"
_RELEASE_CARD_ARTIST_CLASS = "release-block-artist"
_RELEASE_CARD_YEAR_CLASS = "release-block-year"

WARN_NO_LINK = "no discogs master/release link found in source HTML"
WARN_NO_YEAR = "no year found"
WARN_NO_SEPARATOR = "could not separate artist from title"
WARN_FALLBACK_TIER = "detected via fallback heuristic (non-list block)"
WARN_NO_RANK = "no rank text found in source HTML"
WARN_NO_TITLE = "no title element found in release card"
WARN_NO_ARTIST = "no artist element found in release card"


class CohortSourceExtractionError(RuntimeError):
    """Raised when saved source HTML cannot be parsed at all."""


@dataclass(slots=True)
class ExtractedCandidate:
    rank: int | None
    artist: str | None
    title: str | None
    year: int | None
    master_id: int | None
    release_id: int | None
    confidence: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExtractedCandidatesArtifact:
    schema_version: int
    source: dict[str, Any]
    extractor_version: int
    generated_at: str
    notes: list[str]
    candidates: list[ExtractedCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "extractor_version": self.extractor_version,
            "generated_at": self.generated_at,
            "notes": self.notes,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")


def _source_subset(source: CohortSourceMeta) -> dict[str, Any]:
    # Deliberately excludes raw_html_sha256/raw_html_relpath -- this artifact
    # carries no pointer back into data/private/.
    return {
        "source_url": source.source_url,
        "page_title": source.page_title,
        "saved_at": source.saved_at,
        "operator_note": source.operator_note,
    }


def _matches_rank_prefix(element: lxml.html.HtmlElement) -> bool:
    return bool(_RANK_PREFIX_RE.match(element.text_content().strip()))


def _release_card_elements(tree: lxml.html.HtmlElement) -> list[lxml.html.HtmlElement]:
    elements: list[lxml.html.HtmlElement] = tree.xpath(
        f".//*[contains(@class, '{_RELEASE_CARD_CONTAINER_CLASS}')]"
    )
    return elements


def _candidate_elements(
    tree: lxml.html.HtmlElement,
) -> tuple[list[lxml.html.HtmlElement], str]:
    """Return (candidate block elements, tier), tier one of "release_card",
    "list", "fallback", or "none".

    Tries, in order:
    1. Release-card blocks (structural: title/artist/year in separate classed
       elements, no inline rank or artist/title separator to parse) -- see
       `_extract_release_card_candidate`.
    2. `<li>` elements: if at least `_MIN_LIST_ITEMS_TO_TRUST` of them match a
       leading-rank prefix, every `<li>` in the document is treated as a
       candidate block (not just the matching ones), so a non-conforming
       entry in an otherwise-numbered list still becomes a low-confidence
       candidate rather than being silently dropped.
    3. Headings/paragraphs/divs matching the same rank-prefix pattern.
    """
    release_cards = _release_card_elements(tree)
    if len(release_cards) >= _MIN_LIST_ITEMS_TO_TRUST:
        return release_cards, "release_card"

    list_items = tree.xpath(".//li")
    if sum(_matches_rank_prefix(li) for li in list_items) >= _MIN_LIST_ITEMS_TO_TRUST:
        return list_items, "list"

    fallback_elements = [
        el for tag in _FALLBACK_TAGS for el in tree.xpath(f".//{tag}") if _matches_rank_prefix(el)
    ]
    if len(fallback_elements) >= _MIN_LIST_ITEMS_TO_TRUST:
        return fallback_elements, "fallback"

    return [], "none"


def _split_rank(text: str) -> tuple[int | None, str]:
    match = _RANK_PREFIX_RE.match(text)
    if not match:
        return None, text.strip()
    return int(match.group("rank")), match.group("rest").strip()


def _split_artist_title(rest: str) -> tuple[str | None, str | None, list[str]]:
    for separator in _ARTIST_TITLE_SEPARATORS:
        if separator in rest:
            artist, title = rest.split(separator, 1)
            return artist.strip(), title.strip(), []

    lowered = rest.lower()
    if " by " in lowered:
        idx = lowered.rindex(" by ")
        title, artist = rest[:idx].strip(), rest[idx + 4 :].strip()
        return artist, title, []

    return None, rest.strip() or None, [WARN_NO_SEPARATOR]


def _extract_year(text: str) -> tuple[int | None, str, list[str]]:
    match = _YEAR_RE.search(text)
    if not match:
        return None, text, [WARN_NO_YEAR]
    year = int(match.group(1))
    remainder = (text[: match.start()] + text[match.end() :]).strip()
    return year, remainder, []


def _strip_trailing_link_label(text: str, element: lxml.html.HtmlElement) -> str:
    """Strip a trailing Discogs-link anchor's own label text (e.g. a "Discogs"
    or "View" link appended after the title), using the DOM rather than a
    hardcoded word list.

    Only strips when the label is a proper suffix (not the entire string) --
    this deliberately leaves alone the common case where the anchor text IS
    the album title itself (the whole remaining text equals the label).
    """
    stripped = text
    for anchor in element.xpath(".//a"):
        href = anchor.get("href") or ""
        if not (_MASTER_LINK_RE.search(href) or _RELEASE_LINK_RE.search(href)):
            continue
        label = anchor.text_content().strip()
        if label and stripped.endswith(label) and len(label) < len(stripped):
            stripped = stripped[: -len(label)].rstrip()
    return stripped


def _extract_links(hrefs: list[str]) -> tuple[int | None, int | None, list[str]]:
    master_id: int | None = None
    release_id: int | None = None
    for href in hrefs:
        if master_id is None:
            master_match = _MASTER_LINK_RE.search(href)
            if master_match:
                master_id = int(master_match.group(1))
        if release_id is None:
            release_match = _RELEASE_LINK_RE.search(href)
            if release_match:
                release_id = int(release_match.group(1))
    if master_id is None and release_id is None:
        return None, None, [WARN_NO_LINK]
    return master_id, release_id, []


def _confidence(warnings: list[str], *, is_fallback_tier: bool, artist: str | None) -> str:
    if artist is None or is_fallback_tier or len(warnings) >= 2:
        return "low"
    if warnings:
        return "medium"
    return "high"


def _extract_candidate(
    element: lxml.html.HtmlElement, *, is_fallback_tier: bool
) -> ExtractedCandidate:
    warnings: list[str] = []
    if is_fallback_tier:
        warnings.append(WARN_FALLBACK_TIER)

    rank, rest = _split_rank(element.text_content().strip())

    year, rest_without_year, year_warnings = _extract_year(rest)
    warnings.extend(year_warnings)
    rest_without_year = _strip_trailing_link_label(rest_without_year, element)

    artist, title, split_warnings = _split_artist_title(rest_without_year)
    warnings.extend(split_warnings)

    hrefs = list(element.xpath(".//a/@href"))
    master_id, release_id, link_warnings = _extract_links(hrefs)
    warnings.extend(link_warnings)

    confidence = _confidence(warnings, is_fallback_tier=is_fallback_tier, artist=artist)

    return ExtractedCandidate(
        rank=rank,
        artist=artist,
        title=title,
        year=year,
        master_id=master_id,
        release_id=release_id,
        confidence=confidence,
        warnings=warnings,
    )


def _first_by_class(
    element: lxml.html.HtmlElement, class_name: str
) -> lxml.html.HtmlElement | None:
    matches = element.xpath(f".//*[contains(@class, '{class_name}')]")
    return matches[0] if matches else None


def _extract_release_card_candidate(element: lxml.html.HtmlElement) -> ExtractedCandidate:
    """Extract a candidate from a release-card block: title/artist/year live
    in separate classed descendants (no inline rank, nothing to split), so
    this reads them directly rather than reusing `_extract_candidate`'s
    text-blob parsing. Rank is never inferred from card position -- it's left
    null with `WARN_NO_RANK` when the page doesn't show one, the same
    evidence-preservation rule as every other missing field here.
    """
    warnings: list[str] = [WARN_NO_RANK]

    title_el = _first_by_class(element, _RELEASE_CARD_TITLE_CLASS)
    title = title_el.text_content().strip() if title_el is not None else None
    if title is None:
        warnings.append(WARN_NO_TITLE)

    artist_el = _first_by_class(element, _RELEASE_CARD_ARTIST_CLASS)
    artist = artist_el.text_content().strip() if artist_el is not None else None
    if artist is None:
        warnings.append(WARN_NO_ARTIST)

    year_el = _first_by_class(element, _RELEASE_CARD_YEAR_CLASS)
    year: int | None = None
    if year_el is not None:
        year_match = _YEAR_RE.search(year_el.text_content())
        if year_match:
            year = int(year_match.group(1))
    if year is None:
        warnings.append(WARN_NO_YEAR)

    hrefs = list(element.xpath(".//a/@href"))
    master_id, release_id, link_warnings = _extract_links(hrefs)
    warnings.extend(link_warnings)

    confidence = _confidence(warnings, is_fallback_tier=False, artist=artist)

    return ExtractedCandidate(
        rank=None,
        artist=artist,
        title=title,
        year=year,
        master_id=master_id,
        release_id=release_id,
        confidence=confidence,
        warnings=warnings,
    )


def extract_candidates_from_html(
    html_text: str, *, source: CohortSourceMeta
) -> ExtractedCandidatesArtifact:
    if not html_text or not html_text.strip():
        raise CohortSourceExtractionError("saved source HTML is empty or unparseable")

    try:
        tree = lxml.html.fromstring(html_text)
    except (ParserError, ValueError) as exc:
        raise CohortSourceExtractionError("saved source HTML is empty or unparseable") from exc

    elements, tier = _candidate_elements(tree)
    notes = [] if elements else ["no candidate entries detected"]
    if tier == "release_card":
        candidates = [_extract_release_card_candidate(element) for element in elements]
    else:
        candidates = [
            _extract_candidate(element, is_fallback_tier=(tier == "fallback"))
            for element in elements
        ]

    return ExtractedCandidatesArtifact(
        schema_version=CANDIDATE_SCHEMA_VERSION,
        source=_source_subset(source),
        extractor_version=EXTRACTOR_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        notes=notes,
        candidates=candidates,
    )


def extract_candidates_from_file(
    html_path: Path, *, source: CohortSourceMeta
) -> ExtractedCandidatesArtifact:
    return extract_candidates_from_html(html_path.read_text(encoding="utf-8"), source=source)
