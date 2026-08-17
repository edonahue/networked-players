"""Phase 6 PR 6-11: `measure_scope_tiers` reproduces the real,
hand-measured tiering behavior recorded for five real artists in
`local/research/*/scope-tier-analysis.md` (gitignored) -- direct-billed
narrows role coverage upward and collapses graph structure to a star,
over a small synthetic fixture built the same way every other package
here builds one (never real data)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from networked_players_research.cli import main
from networked_players_research.scope_tier import ScopeTierError, measure_scope_tiers

from .conftest import _credit, _release, write_synthetic_dataset

SEED = 100


@pytest.fixture
def scope_tier_corpus(tmp_path: Path) -> Path:
    """Five releases exercising every tier boundary. Release titles
    deliberately avoid `_NON_STUDIO_RELEASE_TITLE_PATTERN` words
    (compilation/live/etc.) except where noted -- that guard drops a
    release from edge construction entirely, which would otherwise
    silently zero out the graph-structure assertions below.

    1. Seed's own album, the main release -- survives every tier
       (A/B/C). One classified ("Vocals") and one unknown-role credit,
       plus a release-scope collaborator (Bob) so B/C have a real edge.
    2. Seed's own reissue, NOT the main release -- survives A/B but is
       excluded from C by `master_is_main_release`.
    3. Bob and Cara co-billed and co-performing, with NO seed credit at
       all -- Tier A includes it regardless (it's "the whole corpus, as
       built", not filtered by seed association); B/C exclude it since
       the seed isn't billed on it at all. Produces a real Bob-Cara edge
       Tier A can see but B/C never can.
    4. A release the seed has no credit on -- proves Tier A really is
       every row in the table, not silently re-filtered to the seed.
    5. Seed and Cara co-billed and co-performing -- like (3), gives Tier
       A a Seed-Cara edge, completing a real triangle (Seed-Bob,
       Bob-Cara, Seed-Cara) that B/C's star-shaped subgraph can't have.
    """
    releases = [
        _release(1, "Seed Solo Album", released="1990"),
        _release(2, "Seed Solo Reissue", released="1991"),
        _release(3, "Bob And Cara Session Two", released="1992"),
        _release(4, "Unrelated Release", released="1993"),
        _release(5, "Seed And Cara Duet", released="1994"),
    ]
    releases[0]["master_is_main_release"] = True
    releases[1]["master_is_main_release"] = False
    releases[2]["master_is_main_release"] = True
    releases[3]["master_is_main_release"] = True
    releases[4]["master_is_main_release"] = True

    credits = [
        _credit(1, artist_id=SEED, name="Seed", scope="release_artist", role_text="Vocals"),
        _credit(
            1, artist_id=SEED, name="Seed", scope="track_artist", role_text=None, track_index=0
        ),
        _credit(1, artist_id=200, name="Bob", scope="release_credit", role_text="Engineer"),
        _credit(2, artist_id=SEED, name="Seed", scope="release_artist", role_text=None),
        _credit(
            2, artist_id=SEED, name="Seed", scope="track_artist", role_text=None, track_index=0
        ),
        _credit(3, artist_id=200, name="Bob", scope="release_artist", role_text=None),
        _credit(3, artist_id=200, name="Bob", scope="track_artist", role_text=None, track_index=0),
        _credit(3, artist_id=300, name="Cara", scope="release_artist", role_text=None),
        _credit(3, artist_id=300, name="Cara", scope="track_artist", role_text=None, track_index=0),
        _credit(4, artist_id=400, name="Dana", scope="release_artist", role_text=None),
        _credit(5, artist_id=SEED, name="Seed", scope="release_artist", role_text=None),
        _credit(
            5, artist_id=SEED, name="Seed", scope="track_artist", role_text=None, track_index=0
        ),
        _credit(5, artist_id=300, name="Cara", scope="release_artist", role_text=None),
        _credit(5, artist_id=300, name="Cara", scope="track_artist", role_text=None, track_index=0),
    ]

    root = tmp_path / "snapshot=20260601"
    return write_synthetic_dataset(root, release_rows=releases, credit_rows=credits)


def test_tier_a_is_the_whole_corpus_not_just_the_seeds_releases(scope_tier_corpus: Path) -> None:
    report = measure_scope_tiers(scope_tier_corpus, SEED)
    tier_a = report["tiers"][0]
    assert tier_a["tier"] == "A"
    assert tier_a["release_count"] == 5  # every release in the table, including #4
    assert tier_a["credit_count"] == 14


def test_tier_b_excludes_releases_where_the_seed_is_not_the_sole_billed_artist(
    scope_tier_corpus: Path,
) -> None:
    report = measure_scope_tiers(scope_tier_corpus, SEED)
    tier_b = report["tiers"][1]
    assert tier_b["tier"] == "B"
    # Releases 1 and 2 only: 3 and 5 bill someone other than the seed
    # (or don't bill the seed at all); 4 doesn't bill the seed either.
    assert tier_b["release_count"] == 2
    assert tier_b["credit_count"] == 5


def test_tier_c_further_excludes_the_non_main_reissue(scope_tier_corpus: Path) -> None:
    report = measure_scope_tiers(scope_tier_corpus, SEED)
    tier_c = report["tiers"][2]
    assert tier_c["tier"] == "C"
    assert tier_c["release_count"] == 1  # release 2 was a real reissue, not the main release
    assert tier_c["credit_count"] == 3


def test_role_classified_fraction_narrows_upward_with_scope(scope_tier_corpus: Path) -> None:
    report = measure_scope_tiers(scope_tier_corpus, SEED)
    fractions = [t["role_classified_fraction"] for t in report["tiers"]]
    # Real, measured direction from the five-artist analysis: the
    # narrower the tier, the higher the classified fraction (never a
    # strict requirement in general -- NEXT_PATH_BRIEF.md records real
    # counter-examples -- but true by construction in this fixture: the
    # unknown-role credits sit disproportionately on releases 2-5, which
    # narrower tiers exclude).
    assert fractions[0] < fractions[1] <= fractions[2]


def test_tier_a_has_graph_structure_the_narrower_tiers_lose(scope_tier_corpus: Path) -> None:
    report = measure_scope_tiers(scope_tier_corpus, SEED)
    tier_a, _tier_b, _tier_c = report["tiers"]
    # A real triangle: Seed-Bob (release 1), Bob-Cara (release 3),
    # Seed-Cara (release 5) -- structure only the full corpus can see,
    # since releases 3 and 5 never survive into Tier B or C.
    assert tier_a["graph_node_count"] == 3
    assert tier_a["graph_edge_count"] == 3
    assert tier_a["component_count"] == 1
    assert tier_a["star_topology"] is False  # a triangle isn't a tree


def test_tier_b_and_c_collapse_to_a_star_through_the_seed(scope_tier_corpus: Path) -> None:
    report = measure_scope_tiers(scope_tier_corpus, SEED)
    _tier_a, tier_b, tier_c = report["tiers"]
    assert tier_b["graph_node_count"] == 2  # seed, Bob
    assert tier_b["graph_edge_count"] == 1
    assert tier_b["star_topology"] is True
    assert tier_c["graph_node_count"] == 2
    assert tier_c["graph_edge_count"] == 1
    assert tier_c["star_topology"] is True


def test_an_empty_tier_reports_zeros_not_an_error(tmp_path: Path) -> None:
    releases = [_release(1, "Solo Release")]
    releases[0]["master_is_main_release"] = True
    credits = [
        _credit(1, artist_id=SEED, name="Seed", scope="release_artist", role_text=None),
        _credit(1, artist_id=999, name="Other", scope="release_artist", role_text=None),
    ]
    root = write_synthetic_dataset(
        tmp_path / "snapshot=20260601", release_rows=releases, credit_rows=credits
    )
    report = measure_scope_tiers(root, SEED)
    tier_b = report["tiers"][1]
    assert tier_b["release_count"] == 0
    assert tier_b["credit_count"] == 0
    assert tier_b["role_classified_fraction"] == 0.0
    assert tier_b["graph_node_count"] == 0
    assert tier_b["component_count"] == 0
    assert tier_b["star_topology"] is False


def test_missing_tables_raise_a_clear_error(tmp_path: Path) -> None:
    empty_root = tmp_path / "snapshot=20260601"
    empty_root.mkdir()
    with pytest.raises(ScopeTierError):
        measure_scope_tiers(empty_root, SEED)


def test_cli_infers_the_seed_from_a_single_seed_manifest(
    scope_tier_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = scope_tier_corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["topic"] = {"seed_artist_ids": [SEED]}
    manifest_path.write_text(json.dumps(manifest))

    exit_code = main(["research-scope-tier", "--corpus-snapshot", str(scope_tier_corpus)])
    assert exit_code == 0
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert report["seed_artist_id"] == SEED
    assert report["tiers"][0]["release_count"] == 5


def test_cli_requires_explicit_seed_when_manifest_has_none_or_many(
    scope_tier_corpus: Path,
) -> None:
    exit_code = main(["research-scope-tier", "--corpus-snapshot", str(scope_tier_corpus)])
    assert exit_code == 1  # this fixture's manifest.json carries no topic.seed_artist_ids


def test_cli_writes_the_output_file_when_requested(scope_tier_corpus: Path, tmp_path: Path) -> None:
    output_path = tmp_path / "report.json"
    exit_code = main(
        [
            "research-scope-tier",
            "--corpus-snapshot",
            str(scope_tier_corpus),
            "--seed-artist-id",
            str(SEED),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    assert json.loads(output_path.read_text())["seed_artist_id"] == SEED
