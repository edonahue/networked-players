"""Payload-size budgets over the committed public artifacts (Atlas F4b).

Budgets previously lived only in prose (ADR 0070, `docs/SITE_REPROFILE_METHOD.md`).
This makes them a reviewed, committed file (`data/integrity/payload-budgets-v1.json`)
and a check. Byte counts of published artifacts are publishable; they are not
performance measurements.

Budget file:

    schema_version                 1
    graph_gzip_hard_bytes          fail when the graph's gzip exceeds this
    graph_gzip_warn_bytes          reported as data (`warnings`), never a failure
    data_total_raw_hard_bytes      fail when the raw total of the data tree exceeds this

gzip is deterministic: level 9, mtime 0. Dependency-free (stdlib only).
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

PAYLOAD_BUDGETS_SCHEMA_VERSION = 1
GRAPH_RELATIVE_PATH = "pathfinding/graph.v4.json"
_BUDGET_KEYS = frozenset(
    {
        "schema_version",
        "graph_gzip_hard_bytes",
        "graph_gzip_warn_bytes",
        "data_total_raw_hard_bytes",
    }
)


def deterministic_gzip_size(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def data_tree_raw_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _bad(message: str) -> dict[str, Any]:
    return {"measured": {}, "failures": [message], "warnings": []}


def payload_budget_report(data_root: Path, budgets: Any) -> dict[str, Any]:
    """`{"measured": {...}, "failures": [...], "warnings": [...]}` for the
    committed data tree under `data_root` (`apps/web/public/data`)."""
    if not isinstance(budgets, dict) or set(budgets.keys()) != _BUDGET_KEYS:
        return _bad(f"payload budgets must be an object with keys {sorted(_BUDGET_KEYS)}")
    if budgets.get("schema_version") != PAYLOAD_BUDGETS_SCHEMA_VERSION:
        return _bad(f"payload budgets schema_version must be {PAYLOAD_BUDGETS_SCHEMA_VERSION}")
    for key in sorted(_BUDGET_KEYS - {"schema_version"}):
        value = budgets[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return _bad(f"payload budget {key} must be a positive integer")
    if budgets["graph_gzip_warn_bytes"] > budgets["graph_gzip_hard_bytes"]:
        return _bad("graph_gzip_warn_bytes must not exceed graph_gzip_hard_bytes")
    graph_path = data_root / GRAPH_RELATIVE_PATH
    if not graph_path.is_file():
        return _bad(f"{GRAPH_RELATIVE_PATH} not found under {data_root}")
    graph_gzip = deterministic_gzip_size(graph_path.read_bytes())
    total_raw = data_tree_raw_bytes(data_root)
    failures: list[str] = []
    warnings: list[str] = []
    if graph_gzip > budgets["graph_gzip_hard_bytes"]:
        failures.append(
            f"{GRAPH_RELATIVE_PATH} gzip is {graph_gzip} bytes, over the hard budget "
            f"{budgets['graph_gzip_hard_bytes']}"
        )
    elif graph_gzip > budgets["graph_gzip_warn_bytes"]:
        warnings.append(
            f"{GRAPH_RELATIVE_PATH} gzip is {graph_gzip} bytes, over the warning threshold "
            f"{budgets['graph_gzip_warn_bytes']} (ADR 0072 format-change trigger)"
        )
    if total_raw > budgets["data_total_raw_hard_bytes"]:
        failures.append(
            f"public data tree is {total_raw} raw bytes, over the hard ceiling "
            f"{budgets['data_total_raw_hard_bytes']}"
        )
    return {
        "measured": {"graph_gzip_bytes": graph_gzip, "data_total_raw_bytes": total_raw},
        "failures": failures,
        "warnings": warnings,
    }
