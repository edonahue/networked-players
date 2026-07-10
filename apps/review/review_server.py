#!/usr/bin/env python3
# ruff: noqa: E501
"""Local-only human review UI for one scored cohort."""

from __future__ import annotations

import argparse
import json
import mimetypes
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Networked Players curator</title>
<style>
:root{color-scheme:dark;--bg:#10100e;--ink:#f3eee3;--surface:#1a1a18;--soft:#272722;--line:#4c4c45;--muted:#b8b3a8;--accent:#78aaa0;--approve:#193b2b;--reject:#472323}:root[data-theme="light"]{color-scheme:light;--bg:#f1ebde;--ink:#202321;--surface:#fff9ee;--soft:#eee7da;--line:#c9c0b1;--muted:#68665f;--accent:#397654;--approve:#dcefe5;--reject:#f5dddd}body{font:16px system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink);transition:background-color 180ms,color 180ms}header{padding:18px 24px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center}main{max-width:1100px;margin:auto;padding:20px}.toolbar{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}.toolbar input,.toolbar select,.note{color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:4px}.toolbar input{padding:8px;min-width:260px}button{padding:8px 12px;border:1px solid var(--line);border-radius:4px;background:var(--soft);color:var(--ink);cursor:pointer}.theme-toggle{width:42px;padding:3px;border-radius:999px}.theme-toggle span{display:block;width:18px;height:18px;border-radius:50%;background:#e4bd61;transition:transform 180ms}.theme-toggle[aria-pressed="true"] span{transform:translateX(16px);background:var(--accent)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px}.card.selected{outline:3px solid var(--accent)}.card.rejected{opacity:.55}.art{width:82px;height:82px;object-fit:cover;background:var(--soft);float:left;margin:0 12px 8px 0}.meta{clear:both;color:var(--muted);font-size:.88rem;padding-top:8px}.evidence{margin-top:8px;font-size:.85rem}.evidence a{color:var(--accent)}.warn{color:#d98282}.note{box-sizing:border-box;width:100%;min-height:48px;margin-top:10px;padding:7px}.actions{display:flex;gap:8px;margin-top:8px}.approve{background:var(--approve)}.reject{background:var(--reject)}.status{margin-left:auto;color:var(--muted)}
</style><script>(()=>{let t=localStorage.getItem('networked-players-curator-theme');document.documentElement.dataset.theme=t==='light'?'light':'dark'})()</script></head><body><header><strong>Networked Players / local curator</strong><span id="source"></span><button class="theme-toggle" type="button" aria-label="Switch to light theme" aria-pressed="false" id="theme"><span aria-hidden="true"></span></button><span class="status" id="saved">Not saved</span></header>
<main><div class="toolbar"><input id="filter" placeholder="Filter artist or album"><select id="view"><option value="all">All suggestions</option><option value="selected">Selected</option><option value="review">Needs review</option></select><button id="save">Save selection</button></div><p id="summary"></p><section class="grid" id="cards"></section></main>
<script>
let state, decisions=new Map();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key=p=>p.album_a_id+'::'+p.album_b_id;
const applyTheme=(theme,persist=false)=>{let next=theme==='light'?'light':'dark',toggle=document.querySelector('#theme');document.documentElement.dataset.theme=next;if(persist)localStorage.setItem('networked-players-curator-theme',next);toggle.setAttribute('aria-label',next==='light'?'Switch to dark theme':'Switch to light theme');toggle.setAttribute('aria-pressed',String(next==='light'))};
document.querySelector('#theme').onclick=()=>applyTheme(document.documentElement.dataset.theme==='light'?'dark':'light',true);applyTheme(document.documentElement.dataset.theme);
function render(){let q=document.querySelector('#filter').value.toLowerCase(),v=document.querySelector('#view').value;
let rows=state.ranked_pairs.filter(p=>{let d=decisions.get(key(p))||{};return(!q||JSON.stringify(p).toLowerCase().includes(q))&&(v==='all'||v==='selected'&&d.approved||v==='review'&&p.review_required)});
document.querySelector('#summary').textContent=rows.length+' shown / '+state.pair_count+' scored / '+[...decisions.values()].filter(d=>d.approved).length+' selected';
document.querySelector('#cards').innerHTML=rows.map(p=>{let d=decisions.get(key(p))||{};let art=(p.cover_image_a||p.cover_image_b)?'<img class="art" src="'+esc(p.cover_image_a||p.cover_image_b)+'" alt="">':'<div class="art"></div>';return '<article data-key="'+esc(key(p))+'" class="card '+(d.approved?'selected ':'')+(d.rejected?'rejected':'')+'">'+art+
'<div><strong>'+esc(p.artist_a)+'<br>'+esc(p.title_a)+'</strong><br>↔<br><strong>'+esc(p.artist_b)+'<br>'+esc(p.title_b)+'</strong></div>'+
'<div class="meta">Score '+p.editorial_score+' · '+esc(p.difficulty)+' · '+p.hop_count+' hop(s)<br>'+esc(p.score_reasons.join('; '))+(p.warnings.length?'<div class="warn">'+esc(p.warnings.join('; '))+'</div>':'')+'</div>'+ '<div class="evidence">'+p.evidence_hops.map(h=>'<a target="_blank" rel="noreferrer" href="'+esc(h.release_url)+'">Release '+h.release_id+'</a> · '+esc(h.quality_flags.join(', '))).join('<br>')+'</div>'+
'<textarea class="note" placeholder="Private curator note">'+esc(d.note||'')+'</textarea><div class="actions"><button class="approve">'+(d.approved?'Selected':'Select')+'</button><button class="reject">'+(d.rejected?'Rejected':'Reject')+'</button></div></article>'}).join('')||'<p>No pairs match this view.</p>'}
document.querySelector('#filter').oninput=render;document.querySelector('#view').onchange=render;
document.querySelector('#cards').onclick=e=>{let card=e.target.closest('.card');if(!card)return;let p=state.ranked_pairs.find(item=>key(item)===card.dataset.key),d=decisions.get(key(p))||{};if(e.target.classList.contains('approve')){d.approved=!d.approved;d.rejected=false}if(e.target.classList.contains('reject')){d.rejected=!d.rejected;d.approved=false}decisions.set(key(p),d);render()};
document.querySelector('#cards').oninput=e=>{if(e.target.classList.contains('note')){let card=e.target.closest('.card'),p=state.ranked_pairs.find(item=>key(item)===card.dataset.key),d=decisions.get(key(p))||{};d.note=e.target.value;decisions.set(key(p),d)}};
document.querySelector('#save').onclick=async()=>{let approved=[...decisions.entries()].filter(([,d])=>d.approved).map(([k,d])=>{let[a,b]=k.split('::');return{album_a_id:a,album_b_id:b,review_note:d.note||'',allow_flagged_pairs:false}});let r=await fetch('/api/selection',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({approved_pairs:approved,review_note:'Saved from local curator UI'})});document.querySelector('#saved').textContent=r.ok?'Saved locally':'Save failed'};
fetch('/api/state').then(r=>r.json()).then(s=>{state=s;document.querySelector('#source').textContent=s.source_id;for(let p of s.selection.approved_pairs||[])decisions.set(p.album_a_id+'::'+p.album_b_id,{approved:true,note:p.review_note||''});render()});
</script></body></html>"""


def load_state(analysis_dir: Path, selection_path: Path, source_id: str) -> dict:
    packet = json.loads((analysis_dir / "editorial-review.json").read_text())
    selection = (
        json.loads(selection_path.read_text())
        if selection_path.is_file()
        else {"approved_pairs": []}
    )
    return {"source_id": source_id, **packet, "selection": selection}


def save_selection(path: Path, payload: dict, reviewed_by: str) -> None:
    approved = payload.get("approved_pairs", [])
    if not isinstance(approved, list):
        raise ValueError("approved_pairs must be a list")
    output = {
        "schema_version": 1,
        "reviewed_by": reviewed_by,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "review_note": str(payload.get("review_note", "")),
        "allow_flagged_pairs": False,
        "approved_pairs": approved,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def make_handler(
    analysis_dir: Path, selection_path: Path, source_id: str, reviewed_by: str, art_dir: Path | None
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                body, kind = PAGE.encode(), "text/html; charset=utf-8"
            elif path == "/api/state":
                body, kind = (
                    json.dumps(load_state(analysis_dir, selection_path, source_id)).encode(),
                    "application/json",
                )
            elif path.startswith("/art/") and art_dir:
                candidate = (art_dir / path.removeprefix("/art/")).resolve()
                if art_dir.resolve() not in candidate.parents or not candidate.is_file():
                    self.send_error(404)
                    return
                body, kind = (
                    candidate.read_bytes(),
                    mimetypes.guess_type(candidate.name)[0] or "application/octet-stream",
                )
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/selection":
                self.send_error(404)
                return
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                save_selection(selection_path, payload, reviewed_by)
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_error(400, str(exc))
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the local cohort curator UI")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--analysis-dir", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--reviewed-by", default="local-curator")
    parser.add_argument("--art-dir", type=Path, help="optional local album-art directory")
    parser.add_argument(
        "--host", default="127.0.0.1", help="use 0.0.0.0 only for explicit LAN access"
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    analysis_dir = args.analysis_dir or Path("local/analysis/cohorts") / args.source_id
    selection = (
        args.selection or Path("data/private/cohort-review") / f"{args.source_id}-selection.json"
    )
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(analysis_dir, selection, args.source_id, args.reviewed_by, args.art_dir),
    )
    print(f"Local curator listening on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
