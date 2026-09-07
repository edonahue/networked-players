"""CLI round-trip for the schema-v2 (multi-generation) Connection Guesser
daily-manifest commands (Phase 7 catalog-expansion migration). The
underlying migration/validation logic is thoroughly unit-tested in
packages/graph-core/tests/test_connection_daily_manifest_v2.py; this pins
the CLI wiring only, including the GENERATION_ID=PATH argument parsing
--upgrade/--migrate/--validate share."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from networked_players_catalog.cli import main
from networked_players_graph_core.connection_daily_manifest import ConnectionDailyManifestError

PROVENANCE = {
    "source": "test",
    "license": "test",
    "snapshot_date": "20260601",
    "generated_by": "test",
    "catalog_version": "catalog-v1-20260601-abc",
    "pool_version": "connection-v1-20260601-def",
    "artifact_version": "connection-artifact-v1-20260601-ghi",
    "note": "test",
}

GEN2_PROVENANCE = {
    **PROVENANCE,
    "catalog_version": "catalog-v1-20260601-newcat",
    "pool_version": "connection-v1-20260601-newpool",
    "artifact_version": "connection-artifact-v1-20260601-newart",
}


def _album(album_id: str) -> dict[str, Any]:
    return {
        "id": album_id,
        "title": album_id,
        "year": 1990,
        "act": "Act",
        "label": None,
        "art": None,
    }


def _round(round_id: str, a: str, c: str, answer_id: int) -> dict[str, Any]:
    return {
        "id": round_id,
        "pool": "real-records",
        "kind": "one_hop",
        "difficulty": "hard",
        "endpoints": [_album(a), _album(c)],
        "answer_set": [{"id": answer_id, "name": f"P{answer_id}", "role_category": "guitar"}],
        "distractors": [],
        "clues": [],
        "evidence": [{"contributor_id": answer_id}],
        "provenance_note": "test",
    }


def _pool(provenance: dict[str, Any], offset: int = 0) -> dict[str, Any]:
    rounds = [_round(f"conn-{i + offset:010x}", f"a{i}", f"c{i}", 1000 + i) for i in range(6)]
    return {"schema_version": 1, "provenance": provenance, "rounds": rounds}


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload))
    return path


def _build_v1_manifest(tmp_path: Path) -> tuple[Path, Path]:
    rounds_path = _write(tmp_path / "rounds.json", _pool(PROVENANCE))
    manifest_path = tmp_path / "manifest-v1.json"
    exit_code = main(
        [
            "build-connection-daily-manifest",
            "--rounds",
            str(rounds_path),
            "--start-date",
            "2026-07-22",
            "--days",
            "5",
            "--output",
            str(manifest_path),
            "--generated-at",
            "2026-07-22T00:00:00+00:00",
        ]
    )
    assert exit_code == 0
    return manifest_path, rounds_path


def test_upgrade_to_v2_end_to_end(tmp_path: Path) -> None:
    manifest_path, _rounds_path = _build_v1_manifest(tmp_path)
    output_path = tmp_path / "manifest-v2.json"

    exit_code = main(
        [
            "upgrade-connection-daily-manifest-to-v2",
            "--manifest",
            str(manifest_path),
            "--generation-id",
            "gen-1",
            "--rounds-url",
            "/data/game/generations/gen-1/rounds.json",
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    v2 = json.loads(output_path.read_text())
    assert v2["schema_version"] == 2
    assert v2["generations"][0]["generation_id"] == "gen-1"
    assert all(e["generation"] == "gen-1" for e in v2["schedule"])


def test_migrate_generation_end_to_end(tmp_path: Path) -> None:
    manifest_path, gen1_rounds_path = _build_v1_manifest(tmp_path)
    v2_path = tmp_path / "manifest-v2.json"
    main(
        [
            "upgrade-connection-daily-manifest-to-v2",
            "--manifest",
            str(manifest_path),
            "--generation-id",
            "gen-1",
            "--rounds-url",
            "/data/game/generations/gen-1/rounds.json",
            "--output",
            str(v2_path),
        ]
    )
    v2 = json.loads(v2_path.read_text())
    cutover = v2["schedule"][3]["date"]  # keep the first 3

    gen2_rounds_path = _write(tmp_path / "gen2-rounds.json", _pool(GEN2_PROVENANCE, offset=100))
    migrated_path = tmp_path / "migrated.json"

    exit_code = main(
        [
            "migrate-connection-daily-manifest-generation",
            "--manifest",
            str(v2_path),
            "--new-rounds",
            str(gen2_rounds_path),
            "--cutover-date",
            cutover,
            "--new-generation-id",
            "gen-2",
            "--new-rounds-url",
            "/data/game/rounds.v1.json",
            "--days",
            "5",
            "--generated-at",
            "2026-07-20T00:00:00+00:00",
            "--existing-rounds",
            f"gen-1={gen1_rounds_path}",
            "--output",
            str(migrated_path),
        ]
    )
    assert exit_code == 0
    migrated = json.loads(migrated_path.read_text())
    assert [g["generation_id"] for g in migrated["generations"]] == ["gen-1", "gen-2"]
    kept = [e for e in migrated["schedule"] if e["generation"] == "gen-1"]
    assert len(kept) == 3
    assert kept == v2["schedule"][:3]


def test_migrate_generation_rejects_a_malformed_existing_rounds_argument(tmp_path: Path) -> None:
    manifest_path, _gen1_rounds_path = _build_v1_manifest(tmp_path)
    v2_path = tmp_path / "manifest-v2.json"
    main(
        [
            "upgrade-connection-daily-manifest-to-v2",
            "--manifest",
            str(manifest_path),
            "--generation-id",
            "gen-1",
            "--rounds-url",
            "/data/game/generations/gen-1/rounds.json",
            "--output",
            str(v2_path),
        ]
    )
    gen2_rounds_path = _write(tmp_path / "gen2-rounds.json", _pool(GEN2_PROVENANCE, offset=100))

    with pytest.raises(ValueError, match="GENERATION_ID=PATH"):
        main(
            [
                "migrate-connection-daily-manifest-generation",
                "--manifest",
                str(v2_path),
                "--new-rounds",
                str(gen2_rounds_path),
                "--cutover-date",
                "2026-08-01",
                "--new-generation-id",
                "gen-2",
                "--new-rounds-url",
                "/data/game/rounds.v1.json",
                "--generated-at",
                "2026-07-20T00:00:00+00:00",
                "--existing-rounds",
                "gen-1-no-equals-sign",  # malformed
                "--output",
                str(tmp_path / "out.json"),
            ]
        )


def test_validate_v2_end_to_end(tmp_path: Path) -> None:
    manifest_path, rounds_path = _build_v1_manifest(tmp_path)
    v2_path = tmp_path / "manifest-v2.json"
    main(
        [
            "upgrade-connection-daily-manifest-to-v2",
            "--manifest",
            str(manifest_path),
            "--generation-id",
            "gen-1",
            "--rounds-url",
            "/data/game/generations/gen-1/rounds.json",
            "--output",
            str(v2_path),
        ]
    )

    exit_code = main(
        [
            "validate-connection-daily-manifest-v2",
            "--manifest",
            str(v2_path),
            "--rounds",
            f"gen-1={rounds_path}",
        ]
    )
    assert exit_code == 0


def test_validate_v2_rejects_a_tampered_generation(tmp_path: Path) -> None:
    manifest_path, rounds_path = _build_v1_manifest(tmp_path)
    v2_path = tmp_path / "manifest-v2.json"
    main(
        [
            "upgrade-connection-daily-manifest-to-v2",
            "--manifest",
            str(manifest_path),
            "--generation-id",
            "gen-1",
            "--rounds-url",
            "/data/game/generations/gen-1/rounds.json",
            "--output",
            str(v2_path),
        ]
    )
    tampered = json.loads(rounds_path.read_text())
    tampered["rounds"][0]["answer_set"][0]["name"] = "Tampered"
    tampered_path = _write(tmp_path / "tampered.json", tampered)

    with pytest.raises(ConnectionDailyManifestError, match="fingerprint mismatch"):
        main(
            [
                "validate-connection-daily-manifest-v2",
                "--manifest",
                str(v2_path),
                "--rounds",
                f"gen-1={tampered_path}",
            ]
        )


def _build_v2_manifest(tmp_path: Path) -> tuple[Path, Path]:
    """A v2 manifest whose only generation points at the LIVE rounds URL --
    the state every generation is in before it is frozen."""
    manifest_path, rounds_path = _build_v1_manifest(tmp_path)
    v2_path = tmp_path / "manifest-v2.json"
    assert (
        main(
            [
                "upgrade-connection-daily-manifest-to-v2",
                "--manifest",
                str(manifest_path),
                "--generation-id",
                "gen-1",
                "--rounds-url",
                "/data/game/rounds.v1.json",
                "--output",
                str(v2_path),
            ]
        )
        == 0
    )
    return v2_path, rounds_path


def _freeze_args(manifest: Path, source: Path, frozen: Path, output: Path) -> list[str]:
    return [
        "freeze-connection-daily-manifest-generation",
        "--manifest",
        str(manifest),
        "--generation-id",
        "gen-1",
        "--source-rounds",
        str(source),
        "--frozen-output",
        str(frozen),
        "--rounds-url",
        "/data/game/generations/gen-1/rounds.json",
        "--output",
        str(output),
    ]


def test_freeze_generation_end_to_end(tmp_path: Path) -> None:
    manifest, rounds = _build_v2_manifest(tmp_path)
    frozen = tmp_path / "data" / "game" / "generations" / "gen-1" / "rounds.json"
    output = tmp_path / "manifest-frozen.json"

    assert main(_freeze_args(manifest, rounds, frozen, output)) == 0
    assert frozen.is_file()
    result = json.loads(output.read_text())
    assert result["generations"][0]["rounds_url"] == "/data/game/generations/gen-1/rounds.json"
    # Only the locator moved.
    before = json.loads(manifest.read_text())
    assert result["schedule"] == before["schedule"]
    assert result["generated_at"] == before["generated_at"]


def test_freeze_writes_the_frozen_copy_byte_identically_not_reserialized(
    tmp_path: Path,
) -> None:
    """A frozen pool is published byte-for-byte (ADR 0066's gen-1 precedent),
    and apps/web/.prettierignore's generations/**/rounds.json glob exists on
    the assumption these files are never re-serialized. Deliberately odd but
    valid source formatting must survive."""
    manifest, rounds = _build_v2_manifest(tmp_path)
    odd = tmp_path / "odd-rounds.json"
    odd.write_text(json.dumps(json.loads(rounds.read_text()), indent=4, sort_keys=True))
    frozen = tmp_path / "data" / "game" / "generations" / "gen-1" / "rounds.json"

    assert main(_freeze_args(manifest, odd, frozen, tmp_path / "out.json")) == 0
    assert frozen.read_bytes() == odd.read_bytes()


def test_freeze_is_idempotent_when_the_frozen_copy_already_matches(tmp_path: Path) -> None:
    manifest, rounds = _build_v2_manifest(tmp_path)
    frozen = tmp_path / "data" / "game" / "generations" / "gen-1" / "rounds.json"
    output = tmp_path / "out.json"

    assert main(_freeze_args(manifest, rounds, frozen, output)) == 0
    first = frozen.read_bytes()
    # Re-running against the already-repointed manifest must be a no-op.
    assert main(_freeze_args(output, rounds, frozen, output)) == 0
    assert frozen.read_bytes() == first


def test_freeze_refuses_to_overwrite_a_different_frozen_copy(tmp_path: Path) -> None:
    manifest, rounds = _build_v2_manifest(tmp_path)
    frozen = tmp_path / "data" / "game" / "generations" / "gen-1" / "rounds.json"
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_text(json.dumps({"schema_version": 1, "rounds": []}))

    with pytest.raises(ValueError, match="immutable by definition"):
        main(_freeze_args(manifest, rounds, frozen, tmp_path / "out.json"))


def test_freeze_refuses_when_frozen_output_does_not_match_the_rounds_url(
    tmp_path: Path,
) -> None:
    """A copy published where the manifest does not point is a 404 in the
    browser and an unverifiable generation in validate-public-artifacts."""
    manifest, rounds = _build_v2_manifest(tmp_path)
    with pytest.raises(ValueError, match="does not end with --rounds-url"):
        main(_freeze_args(manifest, rounds, tmp_path / "somewhere-else.json", tmp_path / "o.json"))


def test_freeze_writes_nothing_when_verification_fails(tmp_path: Path) -> None:
    """Verify everything before writing anything -- a refused freeze must not
    leave a half-published frozen pool behind."""
    manifest, _rounds = _build_v2_manifest(tmp_path)
    wrong = _write(tmp_path / "wrong.json", _pool(GEN2_PROVENANCE, offset=50))
    frozen = tmp_path / "data" / "game" / "generations" / "gen-1" / "rounds.json"
    output = tmp_path / "out.json"

    with pytest.raises(ConnectionDailyManifestError, match="may only freeze the pool"):
        main(_freeze_args(manifest, wrong, frozen, output))
    assert not frozen.exists()
    assert not output.exists()
