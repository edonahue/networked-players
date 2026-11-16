"""Self-contained offline HTML review packet (Campaign Atlas work package RP).

Turns machine outputs into ONE `.html` file the owner opens locally, reviews
with the keyboard and exports decisions from. Two modes share one page
template and one code path:

- round mode: the `score-expansion-candidates` output (`{"candidate_count",
  "eligible_count", "candidates": [row, ...]}`, rows as built by
  `networked_players_graph_core.score_expansion_candidates`) plus the current
  catalog and, optionally, the `build-expansion-review-packet` JSON and the
  approved pool.
- collection mode: the `research-album-projection` study JSON
  (`qualifying_clusters`, each with `albums`, `bridge_players`,
  `internal_density`, `year_min/max/span`).

Nothing here approves, publishes or writes a catalog artifact. The only public
file the page can produce is an *addition list* in the exact shape of
`data/albums/approved-pool-v1.json` albums (ADR 0072 s2); the owner appends it
by hand. Everything else the page exports is marked private.

Both modes live in `packages/catalog` (not `packages/research`) because the
template is shared and research already depends on catalog, never the reverse;
the collection input is consumed as plain JSON, so no research import is needed.

Safety properties (each covered by tests):

- Output path must resolve under `data/private/` or `local/`, never
  `apps/web/public/`.
- Deterministic: no clock, the only date is the caller-supplied label.
- All data is embedded as ASCII JSON in a `<script type="application/json">`
  block with `<`, `>`, `&` escaped; the page builds DOM with `textContent`.
- No network: no external CSS/JS/fonts/images, no links, no cover art.
- The scorer's `in_private_seed` flag is dropped here and never reaches the
  page, so nothing in the packet or its exports can indicate collection
  sourcing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PACKET_SCHEMA_VERSION = 1

# ADR 0069's public vocabulary (== networked_players_contracts.catalog
# .VALID_SELECTION_SOURCES). Duplicated as data here so the page can enforce it
# offline; a test pins the two together.
PUBLIC_SELECTION_SOURCES = (
    "editorial",
    "already_published",
    "graph_rich",
    "coverage_gap",
    "generic_candidate",
)

# review-packet bucket -> public selection_source. "personal" maps to the public
# label `editorial` (ADR 0069 s2); the word "personal" never reaches an export.
_BUCKET_TO_SOURCE = {
    "personal": "editorial",
    "graph_rich": "graph_rich",
    "coverage_gap": "coverage_gap",
}

# Scorer row fields carried into the page. `in_private_seed` is deliberately
# absent: it flags personal-collection membership (ADR 0069 s2).
_ROW_NUMERIC = (
    "roster_size",
    "new_performers",
    "new_performer_density",
    "overlap_existing",
    "bridge_span",
    "coverage_delta",
)


class ReviewPacketError(ValueError):
    """Bad input or a refused output path."""


def require_review_output(output: Path) -> None:
    """Refuse any output that does not resolve under `data/private/` or
    `local/` (both git-ignored), and anything under `apps/web/public/`.
    Resolves first so `..` and symlinks cannot escape."""
    parts = output.resolve().parts
    if any(parts[i : i + 3] == ("apps", "web", "public") for i in range(len(parts) - 2)):
        raise ReviewPacketError(
            f"refusing to write a review packet under apps/web/public/: {output}"
        )
    in_private = any(
        parts[i] == "data" and i + 1 < len(parts) and parts[i + 1] == "private"
        for i in range(len(parts))
    )
    # A real path component named `local` (never a substring), excluding the
    # file name itself.
    in_local = "local" in parts[:-1]
    if not (in_private or in_local):
        raise ReviewPacketError(
            f"review packets must be written under data/private/ or local/ (got {output})"
        )


# ------------------------------------------------------------------ data


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isinstance(value, float) else int(value)


def _connections(raw: Any) -> list[dict[str, Any]]:
    """Optional `connections: [{title, artist?, shared_performers: [names]}]`
    carried on a row. The scorer does not emit this today; shown when present."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        shared = entry.get("shared_performers")
        out.append(
            {
                "title": str(entry.get("title") or ""),
                "artist": str(entry.get("artist") or ""),
                "shared_performers": [str(s) for s in shared] if isinstance(shared, list) else [],
            }
        )
    return out


def build_round_data(
    scored: dict[str, Any],
    *,
    round_number: int,
    catalog: dict[str, Any] | None = None,
    review_packet: dict[str, Any] | None = None,
    approved_pool: dict[str, Any] | None = None,
    guidance: dict[str, int] | None = None,
    generated_at: str = "",
) -> dict[str, Any]:
    candidates = scored.get("candidates") if isinstance(scored, dict) else None
    if not isinstance(candidates, list):
        raise ReviewPacketError("scored candidates JSON needs a 'candidates' list")
    if round_number < 0:
        raise ReviewPacketError("round must be >= 0")

    published: set[int] = set()
    for album in (catalog or {}).get("albums", []):
        mid = _int_or_none(album.get("master_id"))
        if mid is not None:
            published.add(mid)
    for album in (approved_pool or {}).get("albums", []):
        mid = _int_or_none(album.get("master_id"))
        if mid is not None:
            published.add(mid)

    packet_by_master: dict[int, dict[str, Any]] = {}
    for entry in (review_packet or {}).get("entries", []):
        mid = _int_or_none(entry.get("master_id"))
        if mid is not None and mid not in packet_by_master:
            packet_by_master[mid] = entry

    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for cand in candidates:
        mid = _int_or_none(cand.get("master_id"))
        if mid is None or mid <= 0:
            raise ReviewPacketError(f"candidate without a positive integer master_id: {cand!r}")
        if mid in seen:
            raise ReviewPacketError(f"duplicate master_id {mid} in scored candidates")
        seen.add(mid)
        entry = packet_by_master.get(mid, {})
        bucket = entry.get("bucket")
        lane = cand.get("lane") or cand.get("theme") or bucket
        if not lane:
            lane = "editorial" if cand.get("editorial") else "unassigned"
        if bucket in _BUCKET_TO_SOURCE:
            source = _BUCKET_TO_SOURCE[bucket]
        elif cand.get("editorial"):
            source = "editorial"
        else:
            source = "generic_candidate"
        eligibility = cand.get("eligibility")
        row: dict[str, Any] = {
            "master_id": mid,
            "title": str(cand.get("sample_title") or entry.get("title") or ""),
            "artist": str(cand.get("artist_name") or entry.get("artist") or ""),
            "year": _int_or_none(cand.get("year")) or _int_or_none(entry.get("year")),
            "lane": str(lane),
            "eligibility": str(eligibility) if eligibility is not None else "unknown",
            "ambiguous": bool(cand.get("ambiguous") or cand.get("needs_review")),
            "already_published": mid in published,
            "default_source": source,
            "connections": _connections(cand.get("connections")),
        }
        for key in _ROW_NUMERIC:
            row[key] = _num_or_none(cand.get(key))
        rows.append(row)

    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "mode": "round",
        "round": round_number,
        "generated_at": generated_at,
        "guidance": dict(sorted((guidance or {}).items())),
        "rows": rows,
    }


def build_collection_data(study: dict[str, Any], *, generated_at: str = "") -> dict[str, Any]:
    clusters = study.get("qualifying_clusters") if isinstance(study, dict) else None
    if not isinstance(clusters, list):
        raise ReviewPacketError(
            "study JSON has no 'qualifying_clusters' (run research-album-projection, "
            "which writes them by default)"
        )
    out: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters):
        albums = cluster.get("albums")
        if not isinstance(albums, list):
            raise ReviewPacketError(f"cluster {index} has no 'albums' list")
        out.append(
            {
                "index": index,
                "albums": [
                    {
                        "id": str(a.get("id")),
                        "title": str(a.get("title") or ""),
                        "artist": str(a.get("artist") or ""),
                        "year": _int_or_none(a.get("year")),
                    }
                    for a in albums
                ],
                "bridge_players": [
                    {"name": str(b.get("name")), "album_count": _int_or_none(b.get("album_count"))}
                    for b in cluster.get("bridge_players", [])
                ],
                "internal_density": _num_or_none(cluster.get("internal_density")),
                "year_min": _int_or_none(cluster.get("year_min")),
                "year_max": _int_or_none(cluster.get("year_max")),
                "year_span": _int_or_none(cluster.get("year_span")),
                "artist_count": _int_or_none(cluster.get("artist_count")),
            }
        )
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "mode": "collection",
        "generated_at": generated_at,
        "clusters": out,
    }


def input_hash(data: dict[str, Any]) -> str:
    """Stable key for the page's localStorage progress (ignores the label)."""
    stable = {k: v for k, v in data.items() if k != "generated_at"}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode("ascii")).hexdigest()[:16]


def _embed_json(data: dict[str, Any]) -> str:
    text = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_html(data: dict[str, Any]) -> str:
    """Render the single-file page. Pure and deterministic."""
    payload = dict(data)
    payload["input_hash"] = input_hash(data)
    payload["public_selection_sources"] = list(PUBLIC_SELECTION_SOURCES)
    return (
        _TEMPLATE.replace("/*__CSS__*/", _CSS)
        .replace("/*__JS__*/", _JS)
        .replace("__DATA__", _embed_json(payload))
    )


# ------------------------------------------------------------------ page

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Review packet</title>
<style>/*__CSS__*/</style>
</head>
<body>
<header>
<h1 id="page-title">Review packet</h1>
<p id="what" class="lede"></p>
<p class="lede"><strong>Private working file.</strong> Using this page publishes nothing and
approves nothing by itself. It makes no network requests and keeps your progress only in this
browser (localStorage) so a reload does not lose work.</p>
<p id="exports-help" class="lede"></p>
</header>
<nav aria-label="Controls" class="bar">
<label>Filter <input id="filter" type="search" placeholder="press / to focus" autocomplete="off"></label>
<span id="counts" role="status" aria-live="polite"></span>
</nav>
<section id="lane-counts" aria-label="Counts by lane"></section>
<main id="main" tabindex="-1"></main>
<section id="export" aria-label="Export"></section>
<section id="legend" aria-label="Keyboard shortcuts"></section>
<script type="application/json" id="packet-data">__DATA__</script>
<script>/*__JS__*/</script>
</body>
</html>
"""

_CSS = """
:root{color-scheme:light dark;--bg:#fafaf7;--fg:#1c1c1a;--mut:#5c5c56;--line:#cfcfc6;--acc:#1a5fb4;
--ok:#1b6e3c;--no:#a3262a;--df:#8a5a00;--sel:#e8eef8;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#171715;--fg:#e8e8e2;--mut:#a4a49a;--line:#3a3a35;
--acc:#7fb2f0;--ok:#6fd397;--no:#f08a8d;--df:#e6b65c;--sel:#232b3a;--card:#1f1f1c}}
*{box-sizing:border-box}
body{margin:0;padding:12px 16px 48px;background:var(--bg);color:var(--fg);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1{font-size:1.3rem;margin:.2rem 0}
.lede{max-width:70ch;margin:.3rem 0;color:var(--mut)}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:12px 0;position:sticky;top:0;
background:var(--bg);padding:6px 0;z-index:2;border-bottom:1px solid var(--line)}
input,select,textarea,button{font:inherit;color:inherit;background:var(--card);
border:1px solid var(--line);border-radius:4px;padding:3px 6px}
button{cursor:pointer}
:focus-visible{outline:3px solid var(--acc);outline-offset:1px}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th button{border:0;background:none;font-weight:600;padding:0}
tr.cur{background:var(--sel);outline:2px solid var(--acc);outline-offset:-2px}
.st-approved{color:var(--ok);font-weight:600}.st-rejected{color:var(--no);font-weight:600}
.st-deferred{color:var(--df);font-weight:600}
.tag{display:inline-block;border:1px solid var(--line);border-radius:3px;padding:0 5px;
font-size:.8rem;margin-right:4px}
.warn{color:var(--df);font-weight:600}
dl.expl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:.5rem 0}
dl.expl dt{font-weight:600}dl.expl dd{margin:0;color:var(--mut)}
.detail,.cluster{background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:10px 14px;margin:12px 0}
.cluster.cur{outline:3px solid var(--acc)}
.cluster ul{list-style:none;padding:0;margin:.4rem 0}
.cluster li{padding:2px 0}.cluster li.dropped{text-decoration:line-through;color:var(--mut)}
kbd{border:1px solid var(--line);border-bottom-width:2px;border-radius:3px;padding:0 5px;
font-family:ui-monospace,monospace;font-size:.85rem}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}
textarea{width:100%;min-height:3.5em}
#export button{margin-right:8px}
#export-msg{margin:.5rem 0}
.err{color:var(--no);font-weight:600}
@media (prefers-reduced-motion:no-preference){tr,.cluster{transition:background .12s}}
@media (max-width:600px){body{padding:8px 10px 40px}}
"""

_JS = r"""
"use strict";
/* ---- pure core: no DOM; the Node test loads this file's script and calls it ---- */
var Core = (function () {
  var ENTRY_KEYS = ["master_id", "round", "selection_source"];
  function isPosInt(v) { return typeof v === "number" && isFinite(v) && Math.floor(v) === v && v > 0; }
  function isNonNegInt(v) { return typeof v === "number" && isFinite(v) && Math.floor(v) === v && v >= 0; }
  /* Throws unless the entry is EXACTLY {master_id, round, selection_source} with a public label. */
  function validateEntry(entry, publicSources) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error("entry must be an object");
    }
    var keys = Object.keys(entry).sort();
    if (keys.join(",") !== ENTRY_KEYS.slice().sort().join(",")) {
      throw new Error("refusing to export entry with fields " + JSON.stringify(keys) +
        "; only " + JSON.stringify(ENTRY_KEYS) + " are allowed");
    }
    if (!isPosInt(entry.master_id)) throw new Error("invalid master_id");
    if (!isNonNegInt(entry.round)) throw new Error("invalid round");
    if (publicSources.indexOf(entry.selection_source) < 0) {
      throw new Error("non-public selection_source: " + JSON.stringify(entry.selection_source));
    }
    return entry;
  }
  function validateEntries(entries, publicSources) {
    var seen = {};
    entries.forEach(function (e) {
      validateEntry(e, publicSources);
      if (seen[e.master_id]) throw new Error("duplicate master_id " + e.master_id);
      seen[e.master_id] = true;
    });
    return entries;
  }
  /* Approved rows only, sorted by master_id (the pool's required order). */
  function buildAdditions(rows, decisions, sources, round, publicSources) {
    var entries = [];
    rows.forEach(function (r) {
      var d = decisions[r.master_id];
      if (!d || d.status !== "approved") return;
      if (r.already_published) throw new Error("master_id " + r.master_id + " is already published");
      entries.push({
        master_id: r.master_id,
        round: round,
        selection_source: (sources[r.master_id] || r.default_source)
      });
    });
    entries.sort(function (a, b) { return a.master_id - b.master_id; });
    return validateEntries(entries, publicSources);
  }
  function buildRoundNotes(data, decisions, sources, notes) {
    return {
      private: true,
      kind: "review-notes",
      warning: "PRIVATE. Never commit or publish. Not an approval record; the approved pool is.",
      round: data.round,
      input_hash: data.input_hash,
      decisions: data.rows.map(function (r) {
        var d = decisions[r.master_id] || {};
        return {
          master_id: r.master_id, title: r.title, artist: r.artist, lane: r.lane,
          status: d.status || "undecided", decided_at: d.at || null,
          selection_source: sources[r.master_id] || r.default_source,
          note: notes[r.master_id] || ""
        };
      })
    };
  }
  function buildCollectionSelection(data, state) {
    return {
      private: true,
      kind: "collection-selection",
      warning: "PRIVATE. Never commit or publish. Approves and publishes nothing by itself.",
      input_hash: data.input_hash,
      clusters: data.clusters.map(function (c) {
        var s = state[c.index] || {};
        var dropped = s.dropped || {};
        var status = s.status || "undecided";
        return {
          cluster: c.index, status: status,
          working_title: s.title || "", note: s.note || "",
          kept_records: status === "drop" ? [] : c.albums.filter(function (a) {
            return !dropped[a.id];
          }).map(function (a) {
            return { id: a.id, title: a.title, artist: a.artist, year: a.year };
          })
        };
      })
    };
  }
  return { validateEntry: validateEntry, validateEntries: validateEntries,
    buildAdditions: buildAdditions, buildRoundNotes: buildRoundNotes,
    buildCollectionSelection: buildCollectionSelection };
})();

/* ---- page (browser only) ---- */
(function () {
  if (typeof document === "undefined") { globalThis.__RP_CORE__ = Core; return; }
  var data = JSON.parse(document.getElementById("packet-data").textContent);
  var PUB = data.public_selection_sources;
  var KEY = "rp-review:" + data.mode + ":" + data.input_hash;
  var state = { decisions: {}, sources: {}, notes: {}, clusters: {}, cur: 0, sort: null, filter: "" };

  function load() {
    try { var s = localStorage.getItem(KEY); if (s) { var o = JSON.parse(s);
      ["decisions", "sources", "notes", "clusters"].forEach(function (k) { if (o[k]) state[k] = o[k]; }); } }
    catch (e) { /* storage unavailable: page still works */ }
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify({ decisions: state.decisions,
      sources: state.sources, notes: state.notes, clusters: state.clusters })); } catch (e) { }
  }
  function h(tag, props, kids) {
    var el = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      if (k === "text") el.textContent = props[k];
      else if (k === "on") Object.keys(props.on).forEach(function (ev) { el.addEventListener(ev, props.on[ev]); });
      else if (k === "class") el.className = props[k];
      else if (props[k] === true) el.setAttribute(k, "");
      else if (props[k] !== false && props[k] != null) el.setAttribute(k, String(props[k]));
    });
    (kids || []).forEach(function (c) { el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return el;
  }
  function $(id) { return document.getElementById(id); }
  function fmt(v, d) { return v === null || v === undefined ? "n/a" : (typeof v === "number" && d !== undefined ? v.toFixed(d) : String(v)); }
  function download(name, obj) {
    var blob = new Blob([JSON.stringify(obj, null, 2) + "\n"], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }
  function msg(text, isErr) {
    var m = $("export-msg"); if (!m) return; m.textContent = text; m.className = isErr ? "err" : "";
  }

  /* ---------------- round mode ---------------- */
  var COLS = [
    ["title", "Title", "Album title from Discogs data (text only)."],
    ["artist", "Artist", "Credited album artist."],
    ["year", "Year", "Release year, text only."],
    ["master_id", "Master", "Discogs master id; this is what a decision records."],
    ["lane", "Lane", "Which lane or theme proposed this candidate."],
    ["eligibility", "Eligibility", "Whether the studio-album gate passed; any other value names the reason it did not."],
    ["roster_size", "Roster", "Performers credited on the album's selected main release."],
    ["new_performers", "New performers", "Roster members not yet in the published graph."],
    ["new_performer_density", "New density", "New performers divided by roster size (0 to 1)."],
    ["overlap_existing", "Overlap", "Roster members already in the published graph; the album would connect through them."],
    ["bridge_span", "Bridge span", "Distinct published albums one hop from the overlapping performers. Blank when no graph was scored."],
    ["coverage_delta", "Coverage", "How many of its decade/genre/style values fall in an under-represented bucket."]
  ];
  function rowStatus(r) { var d = state.decisions[r.master_id]; return d ? d.status : "undecided"; }
  function visibleRows() {
    var f = state.filter.toLowerCase();
    var rows = data.rows.filter(function (r) {
      if (!f) return true;
      return (r.title + " " + r.artist + " " + r.lane + " " + r.master_id + " " + r.eligibility + " " + rowStatus(r))
        .toLowerCase().indexOf(f) >= 0;
    });
    if (state.sort) {
      var k = state.sort.key, dir = state.sort.dir;
      rows = rows.slice().sort(function (a, b) {
        var x = a[k], y = b[k];
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        var c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return (c || a.master_id - b.master_id) * dir;
      });
    }
    return rows;
  }
  function setStatus(r, status) {
    if (r.already_published && status === "approved") { msg("Already in the published catalog; cannot approve.", true); return; }
    if (status === "undecided") delete state.decisions[r.master_id];
    else state.decisions[r.master_id] = { status: status, at: new Date().toISOString() };
    save(); render();
  }
  function renderCounts(rows) {
    var c = { approved: 0, rejected: 0, deferred: 0, undecided: 0 };
    data.rows.forEach(function (r) { c[rowStatus(r)]++; });
    $("counts").textContent = "Approved " + c.approved + " / rejected " + c.rejected +
      " / deferred " + c.deferred + " / undecided " + c.undecided + " (showing " + rows.length + " of " + data.rows.length + ")";
    var lanes = {};
    data.rows.forEach(function (r) { var l = lanes[r.lane] = lanes[r.lane] || { a: 0, n: 0 }; l.n++; if (rowStatus(r) === "approved") l.a++; });
    Object.keys(data.guidance || {}).forEach(function (k) { lanes[k] = lanes[k] || { a: 0, n: 0 }; });
    var box = $("lane-counts"); box.textContent = "";
    var ul = h("ul", { "class": "row" });
    Object.keys(lanes).sort().forEach(function (k) {
      var g = data.guidance && data.guidance[k];
      ul.appendChild(h("li", { "class": "tag", text: k + ": " + lanes[k].a + " approved of " + lanes[k].n + " candidates" + (g !== undefined ? " (guidance " + g + ")" : "") }));
    });
    box.appendChild(ul);
  }
  function renderRound() {
    var rows = visibleRows();
    if (state.cur >= rows.length) state.cur = Math.max(0, rows.length - 1);
    renderCounts(rows);
    var main = $("main"); main.textContent = "";
    var thead = h("tr");
    thead.appendChild(h("th", { scope: "col", text: "Decision" }));
    COLS.forEach(function (c) {
      var active = state.sort && state.sort.key === c[0];
      thead.appendChild(h("th", { scope: "col", "aria-sort": active ? (state.sort.dir > 0 ? "ascending" : "descending") : "none", title: c[2] }, [
        h("button", { type: "button", text: c[1] + (active ? (state.sort.dir > 0 ? " ▲" : " ▼") : ""), on: { click: function () {
          state.sort = active && state.sort.dir < 0 ? null : { key: c[0], dir: active ? -1 : 1 }; render();
        } } })]));
    });
    var tbody = h("tbody");
    rows.forEach(function (r, i) {
      var st = rowStatus(r);
      var tr = h("tr", { "class": i === state.cur ? "cur" : "", "aria-current": i === state.cur ? "true" : false, on: { click: function () { state.cur = i; render(); } } });
      tr.appendChild(h("td", { "class": "st-" + st, text: st }));
      var elig = h("td");
      if (r.eligibility === "eligible") elig.appendChild(document.createTextNode("eligible"));
      else elig.appendChild(h("span", { "class": "warn", text: r.eligibility }));
      if (r.ambiguous) elig.appendChild(h("span", { "class": "tag warn", text: "ambiguous - needs review" }));
      if (r.already_published) elig.appendChild(h("span", { "class": "tag", text: "already published" }));
      COLS.forEach(function (c) {
        if (c[0] === "eligibility") { tr.appendChild(elig); return; }
        tr.appendChild(h("td", { text: fmt(r[c[0]], c[0] === "new_performer_density" ? 2 : undefined) }));
      });
      tbody.appendChild(tr);
    });
    main.appendChild(h("div", { "class": "tablewrap" }, [h("table", {}, [
      h("caption", { "class": "lede", text: "Candidates. Columns are independent facts; there is no combined score. Sort by any one column." }),
      h("thead", {}, [thead]), tbody])]));
    var cur = rows[state.cur];
    if (cur) main.appendChild(roundDetail(cur));
    var curRow = main.querySelector("tr.cur"); if (curRow && curRow.scrollIntoView) curRow.scrollIntoView({ block: "nearest" });
  }
  function roundDetail(r) {
    var box = h("section", { "class": "detail", "aria-label": "Selected candidate" });
    box.appendChild(h("h2", { text: r.title + " - " + r.artist + (r.year ? " (" + r.year + ")" : "") }));
    var dl = h("dl", { "class": "expl" });
    COLS.slice(6).forEach(function (c) {
      dl.appendChild(h("dt", { text: c[1] + ": " + fmt(r[c[0]], c[0] === "new_performer_density" ? 2 : undefined) }));
      dl.appendChild(h("dd", { text: c[2] }));
    });
    box.appendChild(dl);
    if (r.connections.length) {
      box.appendChild(h("h3", { text: "Would connect to" }));
      var ul = h("ul");
      r.connections.forEach(function (c) {
        ul.appendChild(h("li", { text: c.title + (c.artist ? " - " + c.artist : "") + (c.shared_performers.length ? " via " + c.shared_performers.join(", ") : "") }));
      });
      box.appendChild(ul);
    } else {
      box.appendChild(h("p", { "class": "lede", text: "No connection list in this input; only the counts above." }));
    }
    var sel = h("select", { id: "source-select", "aria-label": "Public selection source if approved", on: { change: function (e) { state.sources[r.master_id] = e.target.value; save(); } } });
    PUB.forEach(function (p) { var o = h("option", { value: p, text: p }); if ((state.sources[r.master_id] || r.default_source) === p) o.selected = true; sel.appendChild(o); });
    box.appendChild(h("div", { "class": "row" }, [h("label", {}, ["Selection source if approved (public label): ", sel]), h("span", { "class": "lede", text: "key s cycles it" })]));
    var ta = h("textarea", { id: "note-box", "aria-label": "Private note", on: { input: function (e) { state.notes[r.master_id] = e.target.value; save(); } } });
    ta.value = state.notes[r.master_id] || "";
    box.appendChild(h("label", {}, ["Private note (never exported to the public additions file)", ta]));
    return box;
  }

  /* ---------------- collection mode ---------------- */
  function cl(c) { return state.clusters[c.index] || (state.clusters[c.index] = { dropped: {} }); }
  function renderCollection() {
    var f = state.filter.toLowerCase();
    var list = data.clusters.filter(function (c) {
      return !f || (cl(c).title || "").toLowerCase().indexOf(f) >= 0 || c.albums.some(function (a) { return (a.title + " " + a.artist).toLowerCase().indexOf(f) >= 0; })
        || c.bridge_players.some(function (b) { return b.name.toLowerCase().indexOf(f) >= 0; });
    });
    if (state.cur >= list.length) state.cur = Math.max(0, list.length - 1);
    var counts = { keep: 0, drop: 0, "needs-work": 0, undecided: 0 };
    data.clusters.forEach(function (c) { counts[cl(c).status || "undecided"]++; });
    $("counts").textContent = "Keep " + counts.keep + " / drop " + counts.drop + " / needs work " + counts["needs-work"] + " / undecided " + counts.undecided + " (showing " + list.length + " of " + data.clusters.length + ")";
    $("lane-counts").textContent = "";
    var main = $("main"); main.textContent = "";
    list.forEach(function (c, i) {
      var s = cl(c);
      var sec = h("section", { "class": "cluster" + (i === state.cur ? " cur" : ""), "aria-label": "Cluster " + c.index, "aria-current": i === state.cur ? "true" : false, on: { click: function () { state.cur = i; } } });
      sec.appendChild(h("h2", { text: "Cluster " + c.index + " - " + (s.status || "undecided") }));
      sec.appendChild(h("p", { "class": "lede", text: c.albums.length + " records, " + fmt(c.artist_count) + " artists; internal density " + fmt(c.internal_density, 2) + " (share of record pairs that share performers); years " + fmt(c.year_min) + "-" + fmt(c.year_max) + " (span " + fmt(c.year_span) + ")." }));
      sec.appendChild(h("p", { text: "Bridge players (performers on 2+ of these records): " + (c.bridge_players.map(function (b) { return b.name + " (" + b.album_count + ")"; }).join(", ") || "none") }));
      var ul = h("ul");
      c.albums.forEach(function (a) {
        var off = !!s.dropped[a.id];
        var cb = h("input", { type: "checkbox", "aria-label": "Keep " + a.title, on: { change: function (e) { if (e.target.checked) delete s.dropped[a.id]; else s.dropped[a.id] = true; save(); render(); } } });
        cb.checked = !off;
        ul.appendChild(h("li", { "class": off ? "dropped" : "" }, [h("label", {}, [cb, " " + a.title + " - " + a.artist + (a.year ? " (" + a.year + ")" : "")])]));
      });
      sec.appendChild(ul);
      var ti = h("input", { type: "text", "aria-label": "Working title for cluster " + c.index, placeholder: "working title", on: { input: function (e) { s.title = e.target.value; save(); } } });
      ti.value = s.title || "";
      var ta = h("textarea", { "aria-label": "Note for cluster " + c.index, on: { input: function (e) { s.note = e.target.value; save(); } } });
      ta.value = s.note || "";
      sec.appendChild(h("div", { "class": "row" }, [h("label", {}, ["Working title ", ti])]));
      sec.appendChild(h("label", {}, ["Note", ta]));
      main.appendChild(sec);
    });
    var curEl = main.querySelector(".cluster.cur"); if (curEl && curEl.scrollIntoView) curEl.scrollIntoView({ block: "nearest" });
  }
  function setCluster(status) {
    var visible = main_visibleClusters();
    var c = visible[state.cur]; if (!c) return;
    if (status === "undecided") delete cl(c).status; else cl(c).status = status;
    save(); render();
  }
  function main_visibleClusters() {
    var secs = Array.prototype.slice.call(document.querySelectorAll(".cluster"));
    return secs.map(function (s) { return data.clusters[parseInt(s.getAttribute("aria-label").split(" ")[1], 10)]; });
  }

  /* ---------------- export + legend ---------------- */
  function renderExport() {
    var box = $("export"); box.textContent = "";
    box.appendChild(h("h2", { text: "Export" }));
    if (data.mode === "round") {
      box.appendChild(h("button", { type: "button", text: "Download approved-pool-additions.json", on: { click: function () {
        try { download("approved-pool-additions.json", Core.buildAdditions(data.rows, state.decisions, state.sources, data.round, PUB)); msg("Exported public additions (approved items only; three fields each)."); }
        catch (e) { msg("Export refused: " + e.message, true); }
      } } }));
      box.appendChild(h("button", { type: "button", text: "Download review-notes.private.json", on: { click: function () {
        download("review-notes.private.json", Core.buildRoundNotes(data, state.decisions, state.sources, state.notes)); msg("Exported PRIVATE notes. Never commit this file.");
      } } }));
    } else {
      box.appendChild(h("button", { type: "button", text: "Download collection-selection.private.json", on: { click: function () {
        download("collection-selection.private.json", Core.buildCollectionSelection(data, state.clusters)); msg("Exported PRIVATE selection. It publishes nothing by itself.");
      } } }));
    }
    box.appendChild(h("button", { type: "button", text: "Clear saved progress", on: { click: function () {
      if (window.confirm("Clear all saved decisions in this browser for this packet?")) { state.decisions = {}; state.sources = {}; state.notes = {}; state.clusters = {}; save(); render(); }
    } } }));
    box.appendChild(h("p", { id: "export-msg", role: "status" }));
  }
  function renderLegend() {
    var keys = data.mode === "round"
      ? [["j / k, arrows", "next / previous"], ["a", "approve"], ["r", "reject"], ["d", "defer"], ["u", "clear decision"], ["s", "cycle public selection source"], ["/", "filter"], ["Esc", "leave filter or note"]]
      : [["j / k, arrows", "next / previous cluster"], ["a", "keep cluster"], ["r", "drop cluster"], ["d", "needs work"], ["u", "clear"], ["Tab, Space", "toggle individual records"], ["/", "filter"], ["Esc", "leave a field"]];
    var box = $("legend"); box.textContent = "";
    box.appendChild(h("h2", { text: "Keys" }));
    var ul = h("ul", { "class": "row" });
    keys.forEach(function (k) { ul.appendChild(h("li", {}, [h("kbd", { text: k[0] }), " " + k[1]])); });
    box.appendChild(ul);
  }

  function render() { if (data.mode === "round") renderRound(); else renderCollection(); }

  document.addEventListener("keydown", function (e) {
    var t = e.target, tag = t && t.tagName;
    if (e.key === "Escape") { if (t && t.blur && (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT")) t.blur(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || tag === "BUTTON") {
      if (!(tag === "INPUT" && t.type === "checkbox")) return;
      if (e.key === " ") return;
    }
    var n = data.mode === "round" ? visibleRows().length : document.querySelectorAll(".cluster").length;
    var k = e.key;
    if (k === "j" || k === "ArrowDown") { state.cur = Math.min(n - 1, state.cur + 1); render(); e.preventDefault(); }
    else if (k === "k" || k === "ArrowUp") { state.cur = Math.max(0, state.cur - 1); render(); e.preventDefault(); }
    else if (k === "/") { $("filter").focus(); e.preventDefault(); }
    else if (data.mode === "round") {
      var r = visibleRows()[state.cur]; if (!r) return;
      if (k === "a") setStatus(r, "approved");
      else if (k === "r") setStatus(r, "rejected");
      else if (k === "d") setStatus(r, "deferred");
      else if (k === "u") setStatus(r, "undecided");
      else if (k === "s") { var i = PUB.indexOf(state.sources[r.master_id] || r.default_source); state.sources[r.master_id] = PUB[(i + 1) % PUB.length]; save(); render(); }
    } else {
      if (k === "a") setCluster("keep"); else if (k === "r") setCluster("drop");
      else if (k === "d") setCluster("needs-work"); else if (k === "u") setCluster("undecided");
    }
  });

  $("filter").addEventListener("input", function (e) { state.filter = e.target.value; state.cur = 0; render(); });
  $("page-title").textContent = data.mode === "round" ? "Expansion round " + data.round + " review packet" : "Collection candidate review packet";
  $("what").textContent = data.mode === "round"
    ? "Review each candidate album and approve, reject or defer it. Nothing is approved until you append the exported additions to data/albums/approved-pool-v1.json yourself."
    : "Review each cluster of records: keep or drop individual records, mark the cluster keep / drop / needs work, and give it a working title.";
  $("exports-help").textContent = data.mode === "round"
    ? "approved-pool-additions.json holds only master_id, round and selection_source for approved albums, ready to append to the pool. review-notes.private.json holds everything else (all decisions, notes, timestamps) and stays private."
    : "collection-selection.private.json holds your kept records, working titles and notes; it stays private and approves nothing by itself.";
  if (data.generated_at) $("what").textContent += " Generated: " + data.generated_at + ".";
  load(); renderLegend(); renderExport(); render();
})();
"""
