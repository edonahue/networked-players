from networked_players_catalog.discogs.release_format_policy import (
    _EXCLUDE_DESCRIPTORS,
    build_release_format_scoring_index,
    classify_formats,
)


def _formats(*descriptions: str, format_name: str = "Vinyl") -> list[dict[str, object]]:
    return [{"format_name": format_name, "descriptions": list(descriptions)}]


def test_explicit_album_is_allowed() -> None:
    result = classify_formats(_formats("LP", "Album", "Reissue"))
    assert result["decision"] == "allow"
    assert result["shape"] == "studio_album"
    assert result["signals"] == ["explicit_album"]


def test_compilation_wins_over_album() -> None:
    result = classify_formats(_formats("Album", "Compilation"))
    assert result["decision"] == "exclude"
    assert result["shape"] == "compilation"
    assert "explicit_compilation" in result["signals"]


def test_carrier_without_album_requires_review() -> None:
    result = classify_formats(_formats("LP"))
    assert result["decision"] == "review"
    assert result["signals"] == ["album_descriptor_missing"]


def test_missing_formats_requires_review() -> None:
    result = classify_formats([])
    assert result["decision"] == "review"
    assert result["signals"] == ["missing_formats"]


def test_non_studio_descriptors_are_excluded() -> None:
    for descriptor in ("Sampler", "Single", "EP", "Live", "Remix", "Box Set"):
        assert classify_formats(_formats(descriptor))["decision"] == "exclude"


# Full synthetic matrix from docs/RELEASE_FORMAT_RESEARCH.md's "Validation
# plan". Cases that are genuinely about `classify_formats` (structured format
# data only -- it never reads title or track/credit shape) are asserted here.
# The two matrix cases that are NOT inputs to this function at all --
# "compilation with two/four/many track artists" (that's `album_shaped()` /
# `COMPILATION_TRACK_ARTIST_THRESHOLD` in graph.py, a traversal-layer guard)
# and "soundtrack with an individual billed artist" (billed-artist shape is
# also not a format-policy input) -- are noted, not silently skipped.


def test_every_exclude_descriptor_is_individually_excluded() -> None:
    """Every entry in `_EXCLUDE_DESCRIPTORS`, not just a spot-checked subset --
    covers Soundtrack, Bootleg, Unofficial Release, Maxi-Single, Mini-Album,
    and Mixtape, which the pre-existing test above did not exercise."""
    for descriptor in _EXCLUDE_DESCRIPTORS:
        result = classify_formats(_formats(descriptor.title()))
        assert result["decision"] == "exclude", f"{descriptor!r} should exclude"


def test_single_with_a_live_b_side_excludes_via_either_descriptor() -> None:
    # A single format row can carry more than one descriptor (Discogs' own
    # <formats><format><descriptions> shape); "Single" alone is enough to
    # exclude regardless of what else rides along with it.
    result = classify_formats(_formats('7"', "Single", "Live"))
    assert result["decision"] == "exclude"
    assert "explicit_single" in result["signals"]


def test_compilation_with_many_format_rows_still_excludes() -> None:
    # Multiple <format> entries (e.g. a 2xLP + insert), one of which carries
    # the disqualifying descriptor -- classify_formats reads across all rows.
    formats = [
        {"format_name": "Vinyl", "descriptions": ["LP", "Album"]},
        {"format_name": "Vinyl", "descriptions": ["Compilation"]},
    ]
    result = classify_formats(formats)
    assert result["decision"] == "exclude"
    assert result["shape"] == "compilation"


def test_sampler_with_a_misleading_album_like_title_still_excludes() -> None:
    """The whole point of the format-based policy over the legacy title
    guard: classify_formats takes no title parameter at all, so a release
    titled e.g. "Greatest Album Collection Vol. 1" that is structurally a
    Sampler is excluded on real evidence, not fooled by (or dependent on) the
    title text either way."""
    result = classify_formats(_formats("Sampler"))
    assert result["decision"] == "exclude"
    assert "title" not in result  # confirms title genuinely never enters this function


def test_live_album_with_no_title_signal_still_excludes() -> None:
    # A release titled plainly (no "Live" in the title at all) but
    # structurally live -- the case the legacy _TITLE_SIGNAL_PATTERN guard
    # would have missed entirely; the format policy catches it on structured
    # evidence alone.
    result = classify_formats(_formats("Live"))
    assert result["decision"] == "exclude"
    assert "explicit_live" in result["signals"]


def test_reissue_and_deluxe_edition_do_not_disqualify_an_explicit_album() -> None:
    result = classify_formats(_formats("CD", "Album", "Reissue", "Deluxe Edition"))
    assert result["decision"] == "allow"
    assert result["shape"] == "studio_album"


def test_live_title_downgrades_an_otherwise_allowed_album_to_review() -> None:
    """Real-snapshot validation (2026-07-19, see docs/RELEASE_FORMAT_RESEARCH.md)
    found Discogs' structured format descriptors very often omit "Live" even
    when the title makes it unambiguous (e.g. "801 Live", "Live In Japan")."""
    result = classify_formats(_formats("Vinyl", "Album"), title="801 Live")
    assert result["decision"] == "review"
    assert "title_signals_live_or_soundtrack" in result["signals"]

    result = classify_formats(_formats("Album"), title="Unplugged (The Official Bootleg)")
    assert result["decision"] == "review"

    result = classify_formats(_formats("Album"), title="Apollo - Atmospheres & Soundtracks")
    assert result["decision"] == "review"


def test_reissue_title_does_not_trigger_the_live_safety_net() -> None:
    # The safety net is deliberately narrower than the legacy title filter --
    # "Reissue" must keep passing through untouched, matching classify_formats'
    # own explicit "reissue does not disqualify an explicit Album" rule.
    result = classify_formats(_formats("Album", "Reissue"), title="First Light (Reissue)")
    assert result["decision"] == "allow"


def test_title_can_only_downgrade_never_exclude_or_promote() -> None:
    # A title match never overrides an already-exclude decision, and no
    # title, however studio-album-sounding, can promote a review to allow.
    result = classify_formats(_formats("Compilation"), title="Live In Japan")
    assert result["decision"] == "exclude"

    result = classify_formats(_formats("LP"), title="Totally A Studio Album")
    assert result["decision"] == "review"


def test_missing_title_does_not_change_existing_behavior() -> None:
    assert classify_formats(_formats("Album")) == classify_formats(_formats("Album"), title=None)


def test_unknown_or_malformed_format_rows_require_review_not_a_guess() -> None:
    # A format row present but missing the keys classify_formats reads --
    # .get() degrades to an empty descriptor list rather than raising, and an
    # empty descriptor list with no "album" is review, never a silent allow.
    result = classify_formats([{}])
    assert result["decision"] == "review"
    assert result["signals"] == ["album_descriptor_missing"]

    # Descriptions present but blank/whitespace-only normalize to "" and
    # still fail to match "album".
    result = classify_formats(_formats("", "   "))
    assert result["decision"] == "review"


def test_scoring_index_contains_only_allowed_release_ids() -> None:
    index = build_release_format_scoring_index(
        {
            "policy_name": "studio-album-v1",
            "policy_version": 1,
            "snapshot_date": "20260601",
            "classifications": [
                {"release_id": 2, "decision": "exclude"},
                {"release_id": 3, "decision": "allow"},
                {"release_id": 1, "decision": "allow"},
            ],
        }
    )
    assert index["kind"] == "release-format-scoring-index"
    assert index["allowed_release_ids"] == [1, 3]
    assert index["allowed_release_count"] == 2
