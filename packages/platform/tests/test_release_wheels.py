"""The release a worker installs must carry exactly the code the digests describe.

Builds the real wheels the way `scripts/build-platform-release.sh` does, unpacks them
and compares per-workload digests with the checkout's. This is the check that proves
the installed-code digest (worker side) and the checkout digest (submit side) agree.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from networked_players_platform.digest import (
    checkout_package_roots,
    entry_modules,
    verify_wheels,
    wheel_package_roots,
    workload_digests,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES = (
    "networked-players-contracts",
    "networked-players-platform",
    "networked-players-catalog",
    "networked-players-research",
)


@pytest.fixture(scope="module")
def wheels(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is required to build the release wheels")
    out = tmp_path_factory.mktemp("wheels")
    for package in PACKAGES:
        subprocess.run(
            ["uv", "build", "--package", package, "--wheel", "--out-dir", str(out)],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
    return out


def test_digests_computed_from_unpacked_wheels_equal_the_checkouts(
    wheels: Path, tmp_path: Path
) -> None:
    roots = wheel_package_roots(wheels, tmp_path / "unpacked")
    from_wheels = workload_digests(entry_modules(), roots)
    from_checkout = workload_digests(entry_modules(), checkout_package_roots(REPO_ROOT))
    assert from_wheels == from_checkout
    assert set(from_wheels) >= {"artifact.validate", "cohort.score", "research.graph-metrics"}


def test_verify_wheels_accepts_the_real_release(wheels: Path, tmp_path: Path) -> None:
    assert verify_wheels(REPO_ROOT, wheels, tmp_path / "work") == []


def test_verify_wheels_refuses_a_wheel_that_differs_from_the_checkout(
    wheels: Path, tmp_path: Path
) -> None:
    tampered = tmp_path / "tampered"
    tampered.mkdir()
    for wheel in wheels.glob("*.whl"):
        with (
            zipfile.ZipFile(wheel) as source,
            zipfile.ZipFile(tampered / wheel.name, "w") as target,
        ):
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "networked_players_contracts/__init__.py":
                    data += b"\n# one extra byte of executed code\n"
                target.writestr(item, data)
    problems = verify_wheels(REPO_ROOT, tampered, tmp_path / "work")
    assert problems and any("wheel digest" in problem for problem in problems)

    missing = tmp_path / "missing"
    missing.mkdir()
    for wheel in wheels.glob("*.whl"):
        if "graph" in wheel.name or "catalog" in wheel.name:
            continue  # ship no catalog wheel: cohort.score cannot be satisfied
        shutil.copy2(wheel, missing / wheel.name)
    problems = verify_wheels(REPO_ROOT, missing, tmp_path / "work2")
    assert any("cohort.score" in problem for problem in problems)
