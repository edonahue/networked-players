"""Runtime digests (ADR 0073): a content hash of the first-party code a worker executes.

One pure function family computes the digest identically from a source checkout
(build and submit time) and from the installed packages on a worker. Only file
*content* and package-relative paths feed the hash, so file order, mtime,
``__pycache__`` and the checkout location never change it. Docs, tests, the web
app and data artifacts are not part of any package directory and so never do.

`uv.lock` is deliberately NOT part of the digest: it is the whole-workspace lock
(dev tools included) and workers do not install from it, so matching on it would
create false skew while pinning nothing. It is recorded as provenance only.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from functools import cache
from pathlib import Path

DIGEST_FORMAT = "networked-players-runtime-digest/2"
CONTRACTS_PACKAGE = "networked_players_contracts"
PACKAGE_PREFIX = "networked_players_"
BUILTIN_ENTRY_MODULE = "networked_players_platform.workloads"
BUILTIN_WORKLOADS = ("artifact.validate", "platform.self-test", "research.corpus-check")
WORKLOAD_ENTRY_GROUP = "networked_players.workloads"
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
    """Every file of one package as sorted POSIX relative paths, except bytecode.

    The allowlist is "everything but `__pycache__`/`*.pyc`" so a packaged
    non-Python file cannot escape the digest. The wheel and the checkout must
    therefore contain the same files; `verify_wheels` enforces that at build time.
    """
    found: list[str] = []
    for current, dirs, names in os.walk(package_dir):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in names:
            if not name.endswith(".pyc"):
                found.append((Path(current) / name).relative_to(package_dir).as_posix())
    return sorted(found)


class PackageHashCache:
    """Hashes each package once per cache, however many workloads share it."""

    def __init__(self) -> None:
        self._lines: dict[tuple[str, Path], list[str]] = {}

    def lines(self, name: str, package_dir: Path) -> list[str]:
        key = (name, package_dir)
        if key not in self._lines:
            self._lines[key] = [
                f"{name}/{rel}\0{file_sha256(package_dir / rel)}"
                for rel in package_files(package_dir)
            ]
        return self._lines[key]


def _combine(header: str, content_lines: Iterable[str]) -> str:
    digest = hashlib.sha256()
    digest.update((DIGEST_FORMAT + "\n").encode())
    digest.update((header + "\n").encode())
    for line in content_lines:
        digest.update((line + "\n").encode())
    return digest.hexdigest()


def contracts_digest(roots: PackageRoots, cache: PackageHashCache | None = None) -> str:
    """Content digest of `networked_players_contracts` alone. The package version is
    a constant and never bumped, so a stale install cannot be seen without this."""
    if CONTRACTS_PACKAGE not in roots:
        raise DigestError(f"{CONTRACTS_PACKAGE} is not available")
    cache = cache or PackageHashCache()
    return _combine(
        f"packages={CONTRACTS_PACKAGE}", cache.lines(CONTRACTS_PACKAGE, roots[CONTRACTS_PACKAGE])
    )


def runtime_digest(
    packages: Iterable[str], roots: PackageRoots, cache: PackageHashCache | None = None
) -> str:
    """Digest of every file of `packages` (see `package_files`)."""
    names = sorted(set(packages))
    missing = [name for name in names if name not in roots]
    if missing:
        raise DigestError(f"packages not available for hashing: {missing}")
    cache = cache or PackageHashCache()
    content: list[str] = []
    for name in names:
        content.extend(cache.lines(name, roots[name]))
    return _combine("packages=" + ",".join(names), content)


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
    except (SyntaxError, UnicodeDecodeError) as exc:
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


def workload_digests(entry_modules: Mapping[str, str], roots: PackageRoots) -> dict[str, str]:
    """workload_id -> runtime digest. Strict: any failure raises (used at build time)."""
    cache = PackageHashCache()
    return {
        workload_id: runtime_digest(import_closure(module, roots), roots, cache)
        for workload_id, module in sorted(entry_modules.items())
    }


def safe_workload_digests(
    entry_modules: Mapping[str, str], roots: PackageRoots
) -> tuple[dict[str, str], dict[str, str]]:
    """(digests, errors): one workload that cannot be hashed is reported unavailable;
    the others stay advertised."""
    cache = PackageHashCache()
    digests: dict[str, str] = {}
    errors: dict[str, str] = {}
    for workload_id, module in sorted(entry_modules.items()):
        try:
            digests[workload_id] = runtime_digest(import_closure(module, roots), roots, cache)
        except (DigestError, OSError, ValueError) as exc:
            errors[workload_id] = str(exc)[:200]
    return digests, errors


def workload_closures(
    entry_modules: Mapping[str, str], roots: PackageRoots
) -> dict[str, tuple[str, ...]]:
    return {
        workload_id: tuple(sorted(import_closure(module, roots)))
        for workload_id, module in sorted(entry_modules.items())
    }


# --- workload registration modules (import-free) -----------------------------------


def workload_id_for_entry_point(name: str) -> str:
    """Convention: entry point `cohort-score` registers workload `cohort.score`
    (first hyphen becomes a dot). Loading verifies the registered id matches, and a
    test checks every entry point, so a violation cannot ship silently."""
    return name.replace("-", ".", 1)


def entry_point_name_for_workload(workload_id: str) -> str:
    return workload_id.replace(".", "-", 1)


def entry_modules() -> dict[str, str]:
    """workload_id -> registration module, WITHOUT importing any plugin. For plugin
    workloads this is the entry point's module (which imports the handler)."""
    modules = dict.fromkeys(BUILTIN_WORKLOADS, BUILTIN_ENTRY_MODULE)
    for entry_point in importlib.metadata.entry_points(group=WORKLOAD_ENTRY_GROUP):
        modules[workload_id_for_entry_point(entry_point.name)] = entry_point.module
    return modules


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


class InstalledRoots(Mapping[str, Path]):
    """Locates any importable `networked_players_*` package on demand, so a plugin
    package needs no registration in a hard-coded list."""

    def __init__(self) -> None:
        self._found: dict[str, Path | None] = {}

    def __getitem__(self, name: str) -> Path:
        if name not in self._found:
            self._found[name] = self._locate(name)
        found = self._found[name]
        if found is None:
            raise KeyError(name)
        return found

    @staticmethod
    def _locate(name: str) -> Path | None:
        if not name.startswith(PACKAGE_PREFIX):
            return None
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            return None
        if spec is None or not spec.submodule_search_locations:
            return None
        return Path(next(iter(spec.submodule_search_locations)))

    def __iter__(self) -> Iterator[str]:
        return iter(name for name, path in self._found.items() if path is not None)

    def __len__(self) -> int:
        return sum(1 for path in self._found.values() if path is not None)


def installed_package_roots() -> InstalledRoots:
    return InstalledRoots()


def uv_lock_sha256(repo_root: Path) -> str:
    """Provenance only: not part of any eligibility digest."""
    lock = repo_root / "uv.lock"
    if not lock.is_file():
        raise DigestError(f"uv.lock not found under {repo_root}")
    return file_sha256(lock)


def checkout_runtime_digests(repo_root: Path) -> dict[str, str]:
    """Digests a worker must advertise to run a job built from this checkout."""
    return workload_digests(entry_modules(), checkout_package_roots(repo_root))


def checkout_contracts_digest(repo_root: Path) -> str:
    return contracts_digest(checkout_package_roots(repo_root))


# --- worker side ---------------------------------------------------------------------


def release_manifest() -> dict[str, object] | None:
    """The `release.json` of the deployed release (provenance), or None."""
    value = os.environ.get(RELEASE_ENV, "").strip()
    if not value or not Path(value).is_file():
        return None
    try:
        payload = json.loads(Path(value).read_text())
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


@cache
def installed_digest_report() -> tuple[dict[str, str], dict[str, str]]:
    """(digests, errors) of the code actually installed here, hashed once per process
    and cached. Each package is hashed once however many workloads share it. A bad
    release manifest only produces a warning: it is provenance, not eligibility."""
    digests, errors = safe_workload_digests(entry_modules(), installed_package_roots())
    manifest = release_manifest()
    expected = manifest.get("runtime_digests") if manifest else None
    if isinstance(expected, dict):
        for workload_id, value in digests.items():
            if workload_id in expected and expected[workload_id] != value:
                print(
                    f"warning: installed code for {workload_id} differs from the release "
                    "manifest (incomplete or modified install)",
                    file=sys.stderr,
                )
    for workload_id, message in errors.items():
        print(f"warning: no runtime digest for {workload_id}: {message}", file=sys.stderr)
    return digests, errors


def installed_runtime_digests() -> dict[str, str]:
    return installed_digest_report()[0]


@cache
def installed_contracts_digest() -> str:
    return contracts_digest(installed_package_roots())


def contracts_version() -> str:
    import networked_players_contracts

    return str(networked_players_contracts.__version__)


# --- build-time wheel verification ---------------------------------------------------


def wheel_package_roots(wheels_dir: Path, extract_to: Path) -> dict[str, Path]:
    """Unpack every wheel and return the `networked_players_*` package dirs found."""
    roots: dict[str, Path] = {}
    for wheel in sorted(wheels_dir.glob("*.whl")):
        target = extract_to / wheel.stem
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(target)
        for child in sorted(target.iterdir()):
            if child.is_dir() and child.name.startswith(PACKAGE_PREFIX):
                roots[child.name] = child
    return roots


def verify_wheels(repo_root: Path, wheels_dir: Path, work_dir: Path) -> list[str]:
    """Problems found comparing per-workload digests computed from the unpacked
    wheels with those computed from the checkout; empty means the release carries
    exactly the code the checkout's digests describe."""
    problems: list[str] = []
    checkout = checkout_package_roots(repo_root)
    wheel = wheel_package_roots(wheels_dir, work_dir)
    modules = entry_modules()
    expected = workload_digests(modules, checkout)
    for workload_id, module in sorted(modules.items()):
        try:
            closure = import_closure(module, checkout)
            for package in sorted(closure):
                if package not in wheel:
                    problems.append(f"{workload_id}: package {package} is missing from the wheels")
                    continue
                if package_files(checkout[package]) != package_files(wheel[package]):
                    extra = set(package_files(checkout[package])) ^ set(
                        package_files(wheel[package])
                    )
                    problems.append(
                        f"{workload_id}: {package} file set differs between checkout and wheel: "
                        f"{sorted(extra)[:5]}"
                    )
            actual = runtime_digest(closure, wheel)
        except DigestError as exc:
            problems.append(f"{workload_id}: {exc}")
            continue
        if actual != expected[workload_id]:
            problems.append(
                f"{workload_id}: wheel digest {actual} != checkout {expected[workload_id]}"
            )
    return problems
