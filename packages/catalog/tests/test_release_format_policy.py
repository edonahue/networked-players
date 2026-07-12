from networked_players_catalog.discogs.release_format_policy import (
    build_release_format_scoring_index,
    classify_formats,
)


def _formats(*descriptions: str) -> list[dict[str, object]]:
    return [{"format_name": "Vinyl", "descriptions": list(descriptions)}]


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
