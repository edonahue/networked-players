"""Runtime digests (ADR 0073): a content hash of everything a worker executes.

One pure function family computes the digest identically from a source checkout
(build and submit time) and from the installed packages on a worker. Only file
*content* and package-relative paths feed the hash, so file order, mtime,
``__pycache__`` and the checkout location never change it. Docs, tests, the web
app and data artifacts are not part of any package directory and so never do.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path

DIGEST_FORMAT = "networked-players-runtime-digest/1"
CONTRACTS_PACKAGE = "networked_players_contracts"
PACKAGE_PREFIX = "networked_players_"
# `.json` is included because graph-core ships `placeholder_artists.json`
# inside the wheel and reads it at runtime.
DIGEST_SUFFIXES = (".py", ".json")
KNOWN_PACKAGES = (
    "networked_players_catalog",
    "networked_players_contracts",
    "networked_players_graph_core",
    "networked_players_platform",
    "networked_players_research",
)
RELEASE_ENV = "PLATFORM_RELEASE_JSON"

# package name -> directory containing that package's `__init__.py`
PackageRoots = Mapping[str, Path]


class DigestError(RuntimeError):
    """Raised when a runtime digest cannot be computed honestly."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_files(package_dir: Path) -> list[str]:
    """Digest-eligible files of one package as sorted POSIX relative paths."""
    found: list[str] = []
    for current, dirs, names in os.walk(package_dir):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in names:
            if name.endswith(DIGEST_SUFFIXES):
                found.append((Path(current) / name).relative_to(package_dir).as_posix())
    return sorted(found)


def package_content_lines(name: str, package_dir: Path) -> list[str]:
    return [f"{name}/{rel}\0{file_sha256(package_dir / rel)}" for rel in package_files(package_dir)]


def _combine(header_lines: Iterable[str], content_lines: Iterable[str]) -> str:
    digest = hashlib.sha256()
    digest.update((DIGEST_FORMAT + "\n").encode())
    for line in header_lines:
        digest.update((line + "\n").encode())
    for line in content_lines:
        digest.update((line + "\n").encode())
    return digest.hexdigest()


def contracts_digest(roots: PackageRoots) -> str:
    """Content digest of `networked_players_contracts` alone. The package version is
    a constant and never bumped, so a stale install cannot be seen without this."""
    if CONTRACTS_PACKAGE not in roots:
        raise DigestError(f"{CONTRACTS_PACKAGE} is not available")
    return _combine(
        [f"packages={CONTRACTS_PACKAGE}"],
        package_content_lines(CONTRACTS_PACKAGE, roots[CONTRACTS_PACKAGE]),
    )


def runtime_digest(packages: Iterable[str], roots: PackageRoots, uv_lock_sha256: str) -> str:
    """Digest of every digest-eligible file of `packages`, plus the lock hash."""
    names = sorted(set(packages))
    missing = [name for name in names if name not in roots]
    if missing:
        raise DigestError(f"packages not available for hashing: {missing}")
    content: list[str] = []
    for name in names:
        content.extend(package_content_lines(name, roots[name]))
    return _combine([f"uv.lock={uv_lock_sha256}", "packages=" + ",".join(names)], content)


# --- import closure -------------------------------------------------------------


def _module_file(module: str, roots: PackageRoots) -> Path | None:
    top, _, rest = module.partition(".")
    if top not in roots:
        return None
    base = roots[top]
    if not rest:
        candidate = base / "__init__.py"
        return candidate if candidate.is_file() else None
    parts = rest.split(".")
    as_module = base.joinpath(*parts).with_suffix(".py")
    if as_module.is_file():
        return as_module
    as_package = base.joinpath(*parts, "__init__.py")
    return as_package if as_package.is_file() else None


def _imported_modules(module: str, path: Path, roots: PackageRoots) -> set[str]:
    """Every `networked_players_*` module a source file may import, including
    imports inside functions and `if TYPE_CHECKING` blocks (conservative)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise DigestError(f"cannot parse {path}: {exc}") from exc
    is_package = path.name == "__init__.py"
    package = module if is_package else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor_parts = package.split(".")
                keep = len(anchor_parts) - (node.level - 1)
                if keep < 1:
                    continue
                base = ".".join(anchor_parts[:keep])
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            if not target:
                continue
            found.add(target)
            for alias in node.names:
                if alias.name != "*":
                    found.add(f"{target}.{alias.name}")
    return {
        name
        for name in found
        if name.startswith(PACKAGE_PREFIX) and _module_file(name, roots) is not None
    }


def import_closure(entry_module: str, roots: PackageRoots) -> frozenset[str]:
    """Top-level `networked_players_*` packages reachable from `entry_module`."""
    if _module_file(entry_module, roots) is None:
        raise DigestError(f"entry module {entry_module!r} is not in the available packages")
    seen: set[str] = set()
    pending = [entry_module]
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_file(module, roots)
        if path is None:
            continue
        # Importing `a.b.c` executes `a/__init__.py` and `a/b/__init__.py` first.
        parts = module.split(".")
        pending.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        pending.extend(_imported_modules(module, path, roots) - seen)
    return frozenset(module.partition(".")[0] for module in seen)


def workload_digests(
    entry_modules: Mapping[str, str], roots: PackageRoots, uv_lock_sha256: str
) -> dict[str, str]:
    """workload_id -> runtime digest, given each workload's handler module."""
    return {
        workload_id: runtime_digest(import_closure(module, roots), roots, uv_lock_sha256)
        for workload_id, module in sorted(entry_modules.items())
    }


def workload_closures(
    entry_modules: Mapping[str, str], roots: PackageRoots
) -> dict[str, tuple[str, ...]]:
    return {
        workload_id: tuple(sorted(import_closure(module, roots)))
        for workload_id, module in sorted(entry_modules.items())
    }


# --- where the files are ----------------------------------------------------------


def checkout_package_roots(repo_root: Path) -> dict[str, Path]:
    """`networked_players_*` package directories of a source checkout."""
    roots: dict[str, Path] = {}
    for src in sorted((repo_root / "packages").glob("*/src")):
        for child in sorted(src.iterdir()):
            if (
                child.is_dir()
                and child.name.startswith(PACKAGE_PREFIX)
                and (child / "__init__.py").is_file()
            ):
                roots[child.name] = child
    return roots


def installed_package_roots() -> dict[str, Path]:
    """`networked_players_*` package directories importable in this interpreter."""
    roots: dict[str, Path] = {}
    for name in KNOWN_PACKAGES:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            continue
        roots[name] = Path(next(iter(spec.submodule_search_locations)))
    return roots


def uv_lock_sha256(repo_root: Path) -> str:
    lock = repo_root / "uv.lock"
    if not lock.is_file():
        raise DigestError(f"uv.lock not found under {repo_root}")
    return file_sha256(lock)


def handler_modules() -> dict[str, str]:
    """workload_id -> module that defines its handler, from the installed registry."""
    from .workloads import discover_workloads

    return {
        workload_id: registered.handler.__module__
        for workload_id, registered in discover_workloads().items()
    }


def checkout_runtime_digests(repo_root: Path) -> dict[str, str]:
    """Digests a worker must advertise to run a job built from this checkout."""
    return workload_digests(
        handler_modules(), checkout_package_roots(repo_root), uv_lock_sha256(repo_root)
    )


def checkout_contracts_digest(repo_root: Path) -> str:
    return contracts_digest(checkout_package_roots(repo_root))


def release_manifest() -> dict[str, object] | None:
    """The `release.json` of the deployed release, or None when not configured."""
    value = os.environ.get(RELEASE_ENV, "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text())
    return payload if isinstance(payload, dict) else None


@cache
def installed_runtime_digests() -> dict[str, str]:
    """Digests of the code actually installed here. Hashed once per process and
    cached (bounded work on a 1 GB worker); empty when the deployed release does
    not record a `uv.lock` hash, so the worker is refused with an explicit reason
    instead of being matched on a guess."""
    manifest = release_manifest()
    lock = manifest.get("uv_lock_sha256") if manifest else None
    if not isinstance(lock, str) or not lock:
        return {}
    digests = workload_digests(handler_modules(), installed_package_roots(), lock)
    expected = manifest.get("runtime_digests") if manifest else None
    if isinstance(expected, dict):
        for workload_id, digest in digests.items():
            if workload_id in expected and expected[workload_id] != digest:
                print(
                    f"warning: installed code for {workload_id} differs from the release "
                    "manifest (incomplete or modified install)",
                    file=sys.stderr,
                )
    return digests


@cache
def installed_contracts_digest() -> str:
    return contracts_digest(installed_package_roots())


def contracts_version() -> str:
    import networked_players_contracts

    return str(networked_players_contracts.__version__)
