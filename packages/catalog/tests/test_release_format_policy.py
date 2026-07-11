from networked_players_catalog.discogs.release_format_policy import classify_formats


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
