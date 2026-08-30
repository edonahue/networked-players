#!/usr/bin/env python3
# ruff: noqa: E501
"""Local-only review UI, two modes sharing one binding/state/traversal-guard
server: `--mode cohort` (default, unchanged) reviews one scored cohort;
`--mode workbench` (Phase 7 PR D) runs `packages/research.compare`
comparisons from a browser instead of the `research-compare` CLI. Per the
plan's own architecture decision (section 11): a third mode of this
existing server, not a new app -- this file already solves loopback
binding, LAN opt-in, and atomic private-state writes; the workbench mode
adds a comparison form and result view, no new infrastructure.

Workbench mode's Explore surface, built up slice by slice rather than all
at once (same discipline as compare_albums preceding compare_artists/
compare_scenes): `/api/search` (album/artist name lookup,
`CreditGraph.search_releases`/`search_artists`); `/api/evidence` (click
through a search result to its release/artist credit rows, plus -- for an
artist -- their real scope-tier coverage via `compare.corpus_coverage`,
the plan's "scope selection" bullet); "-> A"/"-> B" pin buttons that copy
a search result straight into the compare form ("compare/pin"); and
past-run "Load" buttons that repopulate the whole compare form from a
saved `request.json` ("saved reproducible request files"). Bounded graph
rendering and route filters remain the plan's fuller "Explore" vision,
not built here -- see the PR D roadmap for why those two need their own
design pass first."""

from __future__ import annotations

import argparse
import json
import mimetypes
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from networked_players_graph_core.graph import CreditGraph
from networked_players_research.compare import (
    CompareAlbumsRequest,
    CompareArtistsRequest,
    CompareError,
    CompareScenesRequest,
    corpus_coverage,
    run_comparison_and_persist,
)
from networked_players_research.runs import RESEARCH_ROOT

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Networked Players curator</title>
<style>
:root{color-scheme:dark;--bg:#10100e;--ink:#f3eee3;--surface:#1a1a18;--soft:#272722;--line:#4c4c45;--muted:#b8b3a8;--accent:#78aaa0;--approve:#193b2b;--reject:#472323;--strong:#7fb98a;--weak:#c9a86a}:root[data-theme="light"]{color-scheme:light;--bg:#f1ebde;--ink:#202321;--surface:#fff9ee;--soft:#eee7da;--line:#c9c0b1;--muted:#68665f;--accent:#397654;--approve:#dcefe5;--reject:#f5dddd;--strong:#2f6b3d;--weak:#8a6a1f}body{font:16px system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink);transition:background-color 180ms,color 180ms}header{padding:18px 24px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center}main{max-width:1180px;margin:auto;padding:20px}.toolbar{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}.toolbar input,.toolbar select,.note{color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:4px}.toolbar input{padding:8px;min-width:260px}button{padding:8px 12px;border:1px solid var(--line);border-radius:4px;background:var(--soft);color:var(--ink);cursor:pointer}.theme-toggle{width:42px;padding:3px;border-radius:999px}.theme-toggle span{display:block;width:18px;height:18px;border-radius:50%;background:#e4bd61;transition:transform 180ms}.theme-toggle[aria-pressed="true"] span{transform:translateX(16px);background:var(--accent)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:14px}.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px}.card.selected{outline:3px solid var(--accent)}.card.rejected{opacity:.55}
.albums{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:center}.album{display:flex;gap:10px;align-items:center;min-width:0}.album.right{flex-direction:row-reverse;text-align:right}.art{width:76px;height:76px;flex:0 0 76px;object-fit:cover;background:var(--soft);border:1px solid var(--line);border-radius:3px}.album-text{min-width:0}.album-text strong{display:block;overflow-wrap:anywhere}.album-text span{color:var(--muted);font-size:.85rem}.link{font-size:1.4rem;color:var(--muted)}
.meta{color:var(--muted);font-size:.88rem;padding-top:10px;margin-top:10px;border-top:1px solid var(--line)}.warn{color:#d98282}
.chain{margin-top:10px;font-size:.87rem}.hop{border-left:3px solid var(--line);padding:6px 0 6px 10px;margin:8px 0}.hop.same_recording{border-left-color:var(--strong)}.hop.release_scope_credit{border-left-color:var(--weak)}
.hop-head{font-weight:600}.hop-via{color:var(--muted)}.hop-rel{margin-top:2px}.hop-rel a{color:var(--accent)}
.credits{margin:6px 0 0;padding:0;list-style:none;color:var(--muted)}.credits li{padding:1px 0}.credits .who{color:var(--ink)}.role{font-style:italic}.credits li.dim{opacity:.5}.credits li.dim .who{color:var(--muted)}
.tag{display:inline-block;font-size:.72rem;padding:1px 6px;border:1px solid var(--line);border-radius:10px;margin-right:4px;color:var(--muted)}
.common{margin-top:8px;font-size:.87rem}.common b{color:var(--ink)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin-bottom:16px}.panel h2{margin:0 0 4px;font-size:1rem}.panel p{margin:0 0 10px;color:var(--muted);font-size:.85rem}
.breakdown{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}
table.counts{width:100%;border-collapse:collapse;font-size:.87rem}table.counts th{text-align:left;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:4px 8px 6px 0}table.counts td{padding:3px 8px 3px 0;vertical-align:middle}table.counts td.num{text-align:right;font-variant-numeric:tabular-nums;width:1%;white-space:nowrap}
.bar{height:9px;border-radius:2px;background:var(--accent);min-width:2px}.bar.same_recording{background:var(--strong)}.bar.release_scope_credit{background:var(--weak)}.barcell{width:40%}
.note{box-sizing:border-box;width:100%;min-height:48px;margin-top:10px;padding:7px}.actions{display:flex;gap:8px;margin-top:8px}.approve{background:var(--approve)}.reject{background:var(--reject)}.status{margin-left:auto;color:var(--muted)}
</style><script>(()=>{let t=localStorage.getItem('networked-players-curator-theme');document.documentElement.dataset.theme=t==='light'?'light':'dark'})()</script></head><body><header><strong>Networked Players / local curator</strong><span id="source"></span><button class="theme-toggle" type="button" aria-label="Switch to light theme" aria-pressed="false" id="theme"><span aria-hidden="true"></span></button><span class="status" id="saved">Not saved</span></header>
<main><div class="toolbar"><input id="filter" placeholder="Filter artist or album"><select id="view"><option value="all">All suggestions</option><option value="selected">Selected</option><option value="review">Needs review</option></select><button id="save">Save selection</button></div><p id="summary"></p><section class="panel" id="breakdown"></section><section class="grid" id="cards"></section></main>
<script>
let state, decisions=new Map();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key=p=>p.album_a_id+'::'+p.album_b_id;
const applyTheme=(theme,persist=false)=>{let next=theme==='light'?'light':'dark',toggle=document.querySelector('#theme');document.documentElement.dataset.theme=next;if(persist)localStorage.setItem('networked-players-curator-theme',next);toggle.setAttribute('aria-label',next==='light'?'Switch to dark theme':'Switch to light theme');toggle.setAttribute('aria-pressed',String(next==='light'))};
document.querySelector('#theme').onclick=()=>applyTheme(document.documentElement.dataset.theme==='light'?'dark':'light',true);applyTheme(document.documentElement.dataset.theme);
// --- evidence breakdown -------------------------------------------------
// Counts the connections currently in view by the Discogs credit that
// JUSTIFIES them. Credits with justifies_edge=false (Written-By, Remix,
// Executive-Producer, ...) sit on the same record but built no edge, so
// counting them would credit the graph with links it never made. A hop
// contributes one count per distinct justifying role, so role totals can
// exceed the hop total; "pairs" is what a curator actually decides on.
// Role text is Discogs' own -- `null` is a main artist.
const roleLabel=r=>r===null||r===undefined?'(main artist)':r;
function breakdown(rows){
  let byRole=new Map(), byKind=new Map(), hops=0;
  for(const p of rows){
    const pk=key(p);
    for(const h of p.evidence_hops){
      hops++;
      const kind=h.connection||'unclassified';
      if(!byKind.has(kind))byKind.set(kind,{hops:0,pairs:new Set()});
      byKind.get(kind).hops++; byKind.get(kind).pairs.add(pk);
      const roles=new Set((h.credits||[]).filter(c=>c.justifies_edge!==false).map(c=>roleLabel(c.role)));
      if(!roles.size)roles.add('(no credit detail)');
      for(const r of roles){
        if(!byRole.has(r))byRole.set(r,{hops:0,pairs:new Set()});
        byRole.get(r).hops++; byRole.get(r).pairs.add(pk);
      }
    }
  }
  return {byRole,byKind,hops};
}
function countsTable(entries,title,max,cls){
  if(!entries.length)return '';
  return '<div><table class="counts"><thead><tr><th>'+esc(title)+'</th><th class="num">Hops</th><th class="num">Pairs</th><th class="barcell"></th></tr></thead><tbody>'+
    entries.map(([label,v])=>'<tr><td>'+esc(label)+'</td><td class="num">'+v.hops+'</td><td class="num">'+v.pairs.size+'</td>'+
      '<td class="barcell"><div class="bar '+esc(cls?label:'')+'" style="width:'+Math.round(100*v.hops/max)+'%"></div></td></tr>').join('')+
  '</tbody></table></div>';
}
function renderBreakdown(rows){
  const {byRole,byKind,hops}=breakdown(rows);
  const el=document.querySelector('#breakdown');
  if(!hops){el.innerHTML='';return}
  const kinds=[...byKind.entries()].sort((a,b)=>b[1].hops-a[1].hops);
  const roles=[...byRole.entries()].sort((a,b)=>b[1].hops-a[1].hops).slice(0,14);
  const kMax=Math.max(...kinds.map(e=>e[1].hops)), rMax=Math.max(...roles.map(e=>e[1].hops));
  el.innerHTML='<h2>Evidence breakdown</h2><p>'+hops+' connection hop(s) across '+rows.length+' pair(s) in view. Counted by the credit that <em>justifies</em> the edge; credits marked “no edge” on a card are context only.</p>'+
    '<div class="breakdown">'+countsTable(kinds,'Connection type',kMax,true)+countsTable(roles,'Credit type',rMax,false)+'</div>';
}
// -----------------------------------------------------------------------
const album=(cover,artist,title,year,side)=>'<div class="album '+side+'">'+(cover?'<img class="art" src="'+esc(cover)+'" alt="" loading="lazy">':'<div class="art"></div>')+'<div class="album-text"><strong>'+esc(title)+'</strong><span>'+esc(artist)+(year?' · '+esc(year):'')+'</span></div></div>';
// A hop's role text is Discogs' own, never normalised. `null` means a main
// artist credit, which is what "(main artist)" renders.
const credit=c=>'<li'+(c.justifies_edge===false?' class="dim"':'')+'><span class="who">'+esc(c.artist)+'</span> — '+(c.role?'<span class="role">'+esc(c.role)+'</span>':'<span class="role">main artist</span>')+' <span class="tag">'+esc(c.credit_scope||'')+'</span>'+(c.justifies_edge===false?' <span class="tag">no edge</span>':'')+'</li>';
function hopHtml(h){
  if(!h.connection) // packet built without --dataset: ids only
    return '<div class="hop"><div class="hop-rel"><a target="_blank" rel="noreferrer" href="'+esc(h.release_url)+'">Release '+h.release_id+'</a> · '+esc((h.quality_flags||[]).join(', '))+'</div></div>';
  let where=h.connection==='same_recording'
    ? 'together on “'+esc(h.track_title||('track '+(h.track_position||'?')))+'”'
    : 'both credited on the release';
  return '<div class="hop '+esc(h.connection)+'">'+
    '<div class="hop-head">'+esc(h.artist_a)+' <span class="hop-via">↔</span> '+esc(h.artist_b)+'</div>'+
    '<div class="hop-via">'+where+'</div>'+
    '<div class="hop-rel"><a target="_blank" rel="noreferrer" href="'+esc(h.release_url)+'">'+esc(h.release_title||('Release '+h.release_id))+'</a>'+(h.release_year?' ('+esc(h.release_year)+')':'')+'</div>'+
    '<ul class="credits">'+(h.credits||[]).map(credit).join('')+'</ul>'+
    '<div>'+(h.quality_flags||[]).map(f=>'<span class="tag">'+esc(f)+'</span>').join('')+'</div>'+
  '</div>';
}
function render(){let q=document.querySelector('#filter').value.toLowerCase(),v=document.querySelector('#view').value;
let rows=state.ranked_pairs.filter(p=>{let d=decisions.get(key(p))||{};return(!q||JSON.stringify(p).toLowerCase().includes(q))&&(v==='all'||v==='selected'&&d.approved||v==='review'&&p.review_required)});
document.querySelector('#summary').textContent=rows.length+' shown / '+state.pair_count+' scored / '+[...decisions.values()].filter(d=>d.approved).length+' selected';
renderBreakdown(rows);
document.querySelector('#cards').innerHTML=rows.map(p=>{let d=decisions.get(key(p))||{};
let common=(p.intermediaries&&p.intermediaries.length)
  ? '<div class="common">Connected through <b>'+p.intermediaries.map(i=>esc(i.name)).join('</b>, <b>')+'</b></div>'
  : '<div class="common">Connected <b>directly</b> — no intermediary artist</div>';
return '<article data-key="'+esc(key(p))+'" class="card '+(d.approved?'selected ':'')+(d.rejected?'rejected':'')+'">'+
'<div class="albums">'+album(p.cover_image_a,p.artist_a,p.title_a,p.year_a,'left')+'<div class="link">↔</div>'+album(p.cover_image_b,p.artist_b,p.title_b,p.year_b,'right')+'</div>'+
common+
'<div class="chain">'+p.evidence_hops.map(hopHtml).join('')+'</div>'+
'<div class="meta">Score '+p.editorial_score+' · '+esc(p.difficulty)+' · '+p.hop_count+' hop(s)<br>'+esc(p.score_reasons.join('; '))+(p.warnings.length?'<div class="warn">'+esc(p.warnings.join('; '))+'</div>':'')+'</div>'+
'<textarea class="note" placeholder="Private curator note">'+esc(d.note||'')+'</textarea><div class="actions"><button class="approve">'+(d.approved?'Selected':'Select')+'</button><button class="reject">'+(d.rejected?'Rejected':'Reject')+'</button></div></article>'}).join('')||'<p>No pairs match this view.</p>'}
document.querySelector('#filter').oninput=render;document.querySelector('#view').onchange=render;
document.querySelector('#cards').onclick=e=>{let card=e.target.closest('.card');if(!card)return;let p=state.ranked_pairs.find(item=>key(item)===card.dataset.key),d=decisions.get(key(p))||{};if(e.target.classList.contains('approve')){d.approved=!d.approved;d.rejected=false}if(e.target.classList.contains('reject')){d.rejected=!d.rejected;d.approved=false}decisions.set(key(p),d);render()};
document.querySelector('#cards').oninput=e=>{if(e.target.classList.contains('note')){let card=e.target.closest('.card'),p=state.ranked_pairs.find(item=>key(item)===card.dataset.key),d=decisions.get(key(p))||{};d.note=e.target.value;decisions.set(key(p),d)}};
document.querySelector('#save').onclick=async()=>{let approved=[...decisions.entries()].filter(([,d])=>d.approved).map(([k,d])=>{let[a,b]=k.split('::');return{album_a_id:a,album_b_id:b,review_note:d.note||'',allow_flagged_pairs:false}});let r=await fetch('/api/selection',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({approved_pairs:approved,review_note:'Saved from local curator UI'})});document.querySelector('#saved').textContent=r.ok?'Saved locally':'Save failed'};
fetch('/api/state').then(r=>r.json()).then(s=>{state=s;document.querySelector('#source').textContent=s.source_id;for(let p of s.selection.approved_pairs||[])decisions.set(p.album_a_id+'::'+p.album_b_id,{approved:true,note:p.review_note||''});render()});
</script></body></html>"""


# --- Workbench mode (Phase 7 PR D) --------------------------------------
# Same dark/light theme, same minimal-dependency inline-script style as
# PAGE above -- a real, working comparison runner, not a placeholder. The
# result view is a compact, per-mode summary plus the full raw JSON in a
# <details> disclosure. Below the compare form is Explore: a search box
# (album/artist name -> corpus matches) that opens a result's evidence
# (release/artist credit rows) inline (Slice 1), plus "-> A" / "-> B" pin
# buttons on each result that copy its id and the search's own corpus_root
# straight into the compare form's matching mode/fields (Slice 2,
# "compare/pin" from the plan) -- turning "search, note two ids, retype
# them into the form" into one click each. Route filters, scope selection,
# bounded graph rendering, and saved reproducible request files are the
# plan's fuller "Explore" vision, not built yet.
WORKBENCH_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Networked Players research workbench</title>
<style>
:root{color-scheme:dark;--bg:#10100e;--ink:#f3eee3;--surface:#1a1a18;--soft:#272722;--line:#4c4c45;--muted:#b8b3a8;--accent:#78aaa0;--warn:#d98282}:root[data-theme="light"]{color-scheme:light;--bg:#f1ebde;--ink:#202321;--surface:#fff9ee;--soft:#eee7da;--line:#c9c0b1;--muted:#68665f;--accent:#397654;--warn:#a83c3c}
body{font:16px system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}header{padding:18px 24px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center}main{max-width:920px;margin:auto;padding:20px}
form{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:16px;display:flex;flex-direction:column;gap:10px}label{font-size:.85rem;color:var(--muted)}input,select{color:var(--ink);background:var(--soft);border:1px solid var(--line);border-radius:4px;padding:7px;font:inherit}
.row{display:flex;gap:12px;flex-wrap:wrap}.row>div{flex:1;min-width:220px}button{padding:9px 16px;border:1px solid var(--line);border-radius:4px;background:var(--soft);color:var(--ink);cursor:pointer;align-self:flex-start}
.hidden{display:none}.error{color:var(--warn);white-space:pre-wrap}.result{margin-top:20px}.panel{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin-bottom:14px}
table.kv{border-collapse:collapse;width:100%}table.kv td{padding:3px 8px 3px 0;vertical-align:top}table.kv td:first-child{color:var(--muted);white-space:nowrap}
.runs{font-size:.85rem;color:var(--muted)}.runs a{color:var(--accent)}
.run-load-btn{padding:1px 8px;font-size:.85rem;align-self:auto;color:var(--accent);border-color:var(--line)}
.explore-result-row{display:flex;align-items:center;gap:6px}.explore-result-row .explore-result{flex:1;text-align:left}
.pin-btn{padding:4px 9px;font-size:.78rem;align-self:auto}
</style><script>(()=>{let t=localStorage.getItem('networked-players-curator-theme');document.documentElement.dataset.theme=t==='light'?'light':'dark'})()</script></head><body>
<header><strong>Networked Players / research workbench</strong></header>
<main>
<form id="form">
  <div class="row"><div><label for="mode">Compare</label><select id="mode">
    <option value="albums">Two albums</option><option value="artists">Two artists</option><option value="scenes">Two scenes</option>
  </select></div>
  <div><label for="corpus_root">Corpus root</label><input id="corpus_root" placeholder="local/research/&lt;topic&gt;/corpus/snapshot=&lt;date&gt;" required></div>
  <div><label for="topic">Run topic (bookkeeping slug)</label><input id="topic" placeholder="my-comparison" required></div></div>
  <div class="row" id="fields-albums"><div><label for="album_a">Album A (release_id)</label><input id="album_a" type="number"></div><div><label for="album_b">Album B (release_id)</label><input id="album_b" type="number"></div></div>
  <div class="row hidden" id="fields-artists"><div><label for="artist_a">Artist A (artist_id)</label><input id="artist_a" type="number"></div><div><label for="artist_b">Artist B (artist_id)</label><input id="artist_b" type="number"></div></div>
  <div class="row hidden" id="fields-scenes"><div><label for="scene_a">Scene A (space-separated artist_ids)</label><input id="scene_a" placeholder="100 200 300"></div><div><label for="scene_b">Scene B (space-separated artist_ids)</label><input id="scene_b" placeholder="400 500"></div></div>
  <button type="submit">Run comparison</button>
  <p class="error hidden" id="error"></p>
</form>
<div class="result hidden" id="result"></div>
<p class="runs" id="runs"></p>
<section class="panel" id="explore">
  <h2 style="margin-top:0">Explore</h2>
  <div class="row">
    <div><label for="explore_corpus_root">Corpus root (defaults to the compare form's, above)</label><input id="explore_corpus_root" placeholder="local/research/&lt;topic&gt;/corpus/snapshot=&lt;date&gt;"></div>
    <div><label for="explore_kind">Search</label><select id="explore_kind"><option value="albums">Albums</option><option value="artists">Artists</option></select></div>
    <div><label for="explore_q">Name contains</label><input id="explore_q" placeholder="e.g. jamiroquai"></div>
  </div>
  <button type="button" id="explore_search">Search</button>
  <p class="error hidden" id="explore_error"></p>
  <ul id="explore_results" style="list-style:none;padding:0;margin:10px 0 0;display:flex;flex-direction:column;gap:4px"></ul>
</section>
<div id="evidence"></div>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function updateFields(){for(const m of ['albums','artists','scenes'])$('#fields-'+m).classList.toggle('hidden',m!==$('#mode').value)}
$('#mode').onchange=updateFields;updateFields();
function kv(pairs){return '<table class="kv">'+pairs.map(([k,v])=>'<tr><td>'+esc(k)+'</td><td>'+v+'</td></tr>').join('')+'</table>'}
function summarizeAlbums(c){return kv([
  ['Album A',esc(c.album_a.release_id)+(c.album_a.release&&c.album_a.release.title?' — '+esc(c.album_a.release.title):'')],
  ['Album B',esc(c.album_b.release_id)+(c.album_b.release&&c.album_b.release.title?' — '+esc(c.album_b.release.title):'')],
  ['Shared contributors',c.shared_vs_unique.recurring_personnel.length],
  ['Direct route',c.direct_route.connected?'yes':'no'],
  ['Indirect route',c.indirect_route?esc(c.indirect_route.case):'n/a (direct)'],
  ['Network overlap',c.network_overlap.count],
  ['Scope-tier comparison',esc(c.scope_tier_comparison.case)],
])}
function summarizeArtists(c){return kv([
  ['Artist A',esc(c.artist_a.name||c.artist_a.artist_id)],
  ['Artist B',esc(c.artist_b.name||c.artist_b.artist_id)],
  ['Route',esc(c.route.case)],
  ['Shared collaborators',c.shared_collaborators.count],
  ['A hub dependence (degree)',c.artist_a.hub_dependence.degree],
  ['B hub dependence (degree)',c.artist_b.hub_dependence.degree],
])}
function summarizeScenes(c){return kv([
  ['Scene A resolved',c.scene_a.resolved_artist_ids.length+' of '+c.scene_a.member_artist_ids.length],
  ['Scene B resolved',c.scene_b.resolved_artist_ids.length+' of '+c.scene_b.member_artist_ids.length],
  ['Overlap members',c.overlap_and_separation.overlap_artist_ids.length],
  ['Connecting releases',c.connecting_releases.count],
  ['Shared collaborators',c.shared_collaborators.count],
  ['Routes between sets',esc(c.routes_between_sets.case)],
])}
function renderResult(mode,data){
  const summary=mode==='albums'?summarizeAlbums(data.comparison):mode==='artists'?summarizeArtists(data.comparison):summarizeScenes(data.comparison);
  $('#result').innerHTML='<div class="panel"><h2>Run '+esc(data.run_id)+'</h2><p class="runs">'+esc(data.run_root)+'</p>'+summary+'</div>'+
    '<details class="panel"><summary>Full comparison JSON</summary><pre style="white-space:pre-wrap;word-break:break-all">'+esc(JSON.stringify(data.comparison,null,2))+'</pre></details>';
  $('#result').classList.remove('hidden');
}
function loadRequestIntoForm(request){
  $('#mode').value=request.mode;updateFields();
  $('#corpus_root').value=request.corpus_snapshot_root;
  if(request.mode==='albums'){
    $('#album_a').value=request.album_a_release_id;
    $('#album_b').value=request.album_b_release_id;
  }else if(request.mode==='artists'){
    $('#artist_a').value=request.artist_a_id;
    $('#artist_b').value=request.artist_b_id;
  }else{
    $('#scene_a').value=request.scene_a_artist_ids.join(' ');
    $('#scene_b').value=request.scene_b_artist_ids.join(' ');
  }
  $('#form').scrollIntoView({behavior:'smooth',block:'start'});
}
function loadRuns(){
  const topic=$('#topic').value.trim();
  if(!topic){$('#runs').innerHTML='';return}
  fetch('/api/runs?topic='+encodeURIComponent(topic)).then(r=>r.ok?r.json():{runs:[]}).then(d=>{
    if(!d.runs.length){$('#runs').innerHTML='';return}
    // A run with no saved request (recorded before this field existed)
    // still lists, just as plain text -- there's nothing to load.
    $('#runs').innerHTML='Past runs for "'+esc(topic)+'": '+d.runs.map((r,i)=>
      r.request
        ? '<button type="button" class="run-load-btn" data-index="'+i+'">'+esc(r.run_id)+'</button>'
        : esc(r.run_id)
    ).join(', ');
    document.querySelectorAll('.run-load-btn').forEach(btn=>{
      btn.onclick=()=>loadRequestIntoForm(d.runs[Number(btn.dataset.index)].request);
    });
  }).catch(()=>{});
}
$('#topic').onblur=loadRuns;
function evidenceCreditRows(rows){
  if(!rows.length)return '<p class="runs">No credit rows.</p>';
  return '<table class="kv">'+rows.map(r=>'<tr><td>'+esc(r.release_id)+'</td><td>'+esc(r.credit_scope)+(r.role_text?' — '+esc(r.role_text):'')+(r.track_title?' ('+esc(r.track_title)+')':'')+'</td></tr>').join('')+'</table>';
}
function scopeTiersPanel(scopeTiers){
  if(!scopeTiers)return '';
  if(scopeTiers.case!=='measured'){
    return '<p class="runs">Scope tiers: not applicable ('+esc(scopeTiers.reason)+')</p>';
  }
  const rows=scopeTiers.tiers.tiers.map(t=>
    '<tr><td>Tier '+esc(t.tier)+'</td><td>'+esc(t.description)+'<br><span class="runs">'
    +t.release_count+' releases · '+t.distinct_contributor_count+' contributors · '
    +t.graph_node_count+' nodes/'+t.graph_edge_count+' edges · '+t.component_count
    +' components (largest '+t.largest_component_size+') · '
    +(t.role_classified_fraction*100).toFixed(1)+'% role-classified'
    +(t.star_topology?' · star topology':'')+'</span></td></tr>'
  ).join('');
  return '<h4 style="margin:14px 0 4px">Scope-tier coverage</h4><table class="kv">'+rows+'</table>';
}
async function loadEvidence(corpus_root,kind,id){
  $('#evidence').innerHTML='<p class="runs">Loading…</p>';
  try{
    const res=await fetch('/api/evidence?corpus_root='+encodeURIComponent(corpus_root)+'&kind='+kind+'&id='+encodeURIComponent(id));
    const data=await res.json();
    if(!res.ok){$('#evidence').innerHTML='<p class="error">'+esc(data.error||'Evidence lookup failed')+'</p>';return}
    const title=kind==='album'?data.release.title:(data.name||('artist_id '+data.artist_id));
    const subtitle=kind==='album'
      ?('release_id '+esc(data.release.release_id)+(data.release.released?' — '+esc(data.release.released):''))
      :('artist_id '+esc(data.artist_id));
    $('#evidence').innerHTML='<div class="panel"><h3>'+esc(title)+'</h3><p class="runs">'+subtitle+'</p>'
      +evidenceCreditRows(data.credit_rows)+scopeTiersPanel(data.scope_tiers)+'</div>';
  }catch(err){$('#evidence').innerHTML='<p class="error">'+esc(String(err))+'</p>'}
}
function pinToCompare(kind,slot,id,corpus_root){
  $('#mode').value=kind;updateFields();
  $('#corpus_root').value=corpus_root;
  const field=kind==='albums'?(slot==='a'?'#album_a':'#album_b'):(slot==='a'?'#artist_a':'#artist_b');
  $(field).value=id;
  $('#form').scrollIntoView({behavior:'smooth',block:'start'});
}
$('#explore_search').onclick=async()=>{
  $('#explore_error').classList.add('hidden');$('#explore_results').innerHTML='';$('#evidence').innerHTML='';
  const corpus_root=$('#explore_corpus_root').value.trim()||$('#corpus_root').value.trim();
  const kind=$('#explore_kind').value,q=$('#explore_q').value.trim();
  if(!corpus_root||!q){$('#explore_error').textContent='A corpus root and a search term are both required';$('#explore_error').classList.remove('hidden');return}
  try{
    const res=await fetch('/api/search?corpus_root='+encodeURIComponent(corpus_root)+'&kind='+kind+'&q='+encodeURIComponent(q));
    const data=await res.json();
    if(!res.ok){$('#explore_error').textContent=data.error||'Search failed';$('#explore_error').classList.remove('hidden');return}
    if(!data.results.length){$('#explore_results').innerHTML='<li class="runs">No matches</li>';return}
    const entityKind=kind==='albums'?'album':'artist';
    $('#explore_results').innerHTML=data.results.map(r=>{
      const id=kind==='albums'?r.release_id:r.artist_id;
      const label=kind==='albums'?(r.title+(r.released?' ('+esc(r.released)+')':'')):r.name;
      return '<li class="explore-result-row"><button type="button" class="explore-result" data-id="'+id+'">'+esc(label)+'</button>'
        +'<button type="button" class="pin-btn" data-slot="a" data-id="'+id+'" title="Use as '+(kind==='albums'?'Album':'Artist')+' A">&rarr; A</button>'
        +'<button type="button" class="pin-btn" data-slot="b" data-id="'+id+'" title="Use as '+(kind==='albums'?'Album':'Artist')+' B">&rarr; B</button>'
        +'</li>';
    }).join('');
    document.querySelectorAll('.explore-result').forEach(btn=>{btn.onclick=()=>loadEvidence(corpus_root,entityKind,btn.dataset.id)});
    document.querySelectorAll('.pin-btn').forEach(btn=>{btn.onclick=()=>pinToCompare(kind,btn.dataset.slot,btn.dataset.id,corpus_root)});
  }catch(err){$('#explore_error').textContent=String(err);$('#explore_error').classList.remove('hidden')}
};
$('#form').onsubmit=async(e)=>{
  e.preventDefault();
  $('#error').classList.add('hidden');$('#result').classList.add('hidden');
  const mode=$('#mode').value;
  const payload={mode,corpus_root:$('#corpus_root').value.trim(),topic:$('#topic').value.trim()};
  if(mode==='albums'){payload.album_a=Number($('#album_a').value);payload.album_b=Number($('#album_b').value)}
  else if(mode==='artists'){payload.artist_a=Number($('#artist_a').value);payload.artist_b=Number($('#artist_b').value)}
  else{payload.scene_a=$('#scene_a').value.trim().split(/\\s+/).filter(Boolean).map(Number);payload.scene_b=$('#scene_b').value.trim().split(/\\s+/).filter(Boolean).map(Number)}
  const submitBtn=$('#form button[type=submit]');submitBtn.disabled=true;submitBtn.textContent='Running…';
  try{
    const res=await fetch('/api/compare',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
    const data=await res.json();
    if(!res.ok){$('#error').textContent=data.error||'Request failed';$('#error').classList.remove('hidden');return}
    renderResult(mode,data);
    loadRuns();
  }catch(err){$('#error').textContent=String(err);$('#error').classList.remove('hidden')}
  finally{submitBtn.disabled=false;submitBtn.textContent='Run comparison'}
};
</script></body></html>"""


def load_state(analysis_dir: Path, selection_path: Path, source_id: str) -> dict[str, Any]:
    packet = json.loads((analysis_dir / "editorial-review.json").read_text())
    selection = (
        json.loads(selection_path.read_text())
        if selection_path.is_file()
        else {"approved_pairs": []}
    )
    return {"source_id": source_id, **packet, "selection": selection}


def save_selection(path: Path, payload: dict[str, Any], reviewed_by: str) -> None:
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


class WorkbenchRequestError(ValueError):
    """A malformed or unsafe `/api/compare` request -- reported to the
    browser as a 400, never a 500; the payload came from the visitor's own
    form, but this server can also be bound to `--host 0.0.0.0` for trusted-
    LAN access (same as cohort mode), so it still validates rather than
    trusting it outright."""


def _safe_corpus_root(raw: str, allowed_root: Path) -> Path:
    """A comparison's `corpus_root` must resolve under `allowed_root`
    (`local/` in real usage -- every real topic corpus and the canonical
    processed snapshot already live there, see AGENTS.md's `local/`
    convention) -- keeps a LAN-bound instance from being used to open an
    arbitrary path on the host as a "corpus". Mirrors the existing `/art/`
    route's own real-path-containment check just below. Parameterized
    (rather than hardcoding `Path("local")`) so tests can point it at an
    isolated `tmp_path` instead of this repo's own real `local/`."""
    if not raw or not raw.strip():
        raise WorkbenchRequestError("corpus_root is required")
    candidate = Path(raw).resolve()
    if allowed_root != candidate and allowed_root not in candidate.parents:
        raise WorkbenchRequestError(f"corpus_root must resolve under {allowed_root}")
    if not (candidate / "manifest.json").is_file():
        raise WorkbenchRequestError(f"no manifest.json under {candidate} -- not a real corpus")
    return candidate


def _safe_topic(raw: str) -> str:
    """`runs.py`'s `topic_root` joins `research_root / topic_slug` with no
    sanitization of its own -- fine for a CLI flag an operator types
    themselves, not fine for a value taken from an HTTP POST body on a
    server that CAN be LAN-bound. Rejects anything that isn't a single
    plain path segment."""
    if not raw or not raw.strip():
        raise WorkbenchRequestError("topic is required")
    if raw != Path(raw).name or raw in (".", ".."):
        raise WorkbenchRequestError("topic must be a single plain name, not a path")
    return raw


def _positive_int_list(raw: object, field: str) -> tuple[int, ...]:
    if not isinstance(raw, list) or not raw or not all(isinstance(v, int) for v in raw):
        raise WorkbenchRequestError(f"{field} must be a non-empty list of integers")
    return tuple(raw)


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int):
        raise WorkbenchRequestError(f"{field} is required and must be an integer")
    return value


def build_compare_request(
    mode: str, payload: dict[str, Any], corpus_root: Path
) -> CompareAlbumsRequest | CompareArtistsRequest | CompareScenesRequest:
    if mode == "albums":
        return CompareAlbumsRequest(
            corpus_snapshot_root=corpus_root,
            album_a_release_id=_required_int(payload, "album_a"),
            album_b_release_id=_required_int(payload, "album_b"),
        )
    if mode == "artists":
        return CompareArtistsRequest(
            corpus_snapshot_root=corpus_root,
            artist_a_id=_required_int(payload, "artist_a"),
            artist_b_id=_required_int(payload, "artist_b"),
        )
    if mode == "scenes":
        return CompareScenesRequest(
            corpus_snapshot_root=corpus_root,
            scene_a_artist_ids=_positive_int_list(payload.get("scene_a"), "scene_a"),
            scene_b_artist_ids=_positive_int_list(payload.get("scene_b"), "scene_b"),
        )
    raise WorkbenchRequestError(f"unrecognized mode: {mode!r}")


def list_runs(research_root: Path, topic: str) -> list[dict[str, Any]]:
    """Every run recorded for `topic`, newest first -- reuses the same
    `manifest.json` `research-analyze`/`research-compare` already write,
    never a second bookkeeping format. Each summary also carries `request`
    -- the exact, directly-reusable input `run_comparison_and_persist`
    wrote alongside `comparison.json` (`None` for a run recorded before
    that field existed, so an older run still lists cleanly rather than
    crashing this endpoint)."""
    runs_dir = research_root / topic / "runs"
    if not runs_dir.is_dir():
        return []
    summaries = []
    for run_dir in runs_dir.iterdir():
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        summary = json.loads(manifest_path.read_text())
        request_path = run_dir / "request.json"
        summary["request"] = (
            json.loads(request_path.read_text()) if request_path.is_file() else None
        )
        summaries.append(summary)
    summaries.sort(key=lambda m: m.get("run_id", ""), reverse=True)
    return summaries


def _required_query_int(raw: str, field: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise WorkbenchRequestError(f"{field} must be an integer") from None


def search_corpus(graph: CreditGraph, kind: str, query: str) -> list[dict[str, Any]]:
    """`/api/search`'s dispatch -- a plain substring lookup, not ranked or
    fuzzy, over whichever `CreditGraph.search_*` matches `kind`."""
    if not query or not query.strip():
        raise WorkbenchRequestError("q is required")
    if kind == "albums":
        return graph.search_releases(query)
    if kind == "artists":
        return graph.search_artists(query)
    raise WorkbenchRequestError("kind must be one of albums/artists")


def load_evidence(
    graph: CreditGraph, kind: str, entity_id: int, corpus_root: Path
) -> dict[str, Any]:
    """`/api/evidence`'s dispatch -- the click-through target for a search
    result: a release's own record plus its credit rows, or an artist's
    name plus their whole-dataset credit rows (`credit_rows_for_artist`,
    not a `neighbors()` walk, for the same solo-release reason
    `compare_artists` needs it) plus their scope-tier coverage (Explore's
    "scope selection" slice -- reuses `compare.corpus_coverage` unchanged,
    the exact function `compare_artists` already calls per artist)."""
    if kind == "album":
        release = graph.release(entity_id)
        if release is None:
            raise WorkbenchRequestError(f"release_id {entity_id} not found in corpus")
        credit_rows = graph.credit_rows_for_releases([entity_id]).get(entity_id, [])
        return {"kind": "album", "release": release, "credit_rows": credit_rows}
    if kind == "artist":
        name = graph.artist_name(entity_id)
        credit_rows = graph.credit_rows_for_artist(entity_id)
        if name is None and not credit_rows:
            raise WorkbenchRequestError(f"artist_id {entity_id} not found in corpus")
        return {
            "kind": "artist",
            "artist_id": entity_id,
            "name": name,
            "credit_rows": credit_rows,
            "scope_tiers": corpus_coverage(corpus_root, entity_id),
        }
    raise WorkbenchRequestError("kind must be one of album/artist")


def make_workbench_handler(
    research_root: Path, *, allowed_corpus_root: Path | None = None
) -> type[BaseHTTPRequestHandler]:
    corpus_allowlist_root = allowed_corpus_root or Path("local").resolve()

    class WorkbenchHandler(BaseHTTPRequestHandler):
        def _respond_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = WORKBENCH_PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/runs":
                topic = parse_qs(parsed.query).get("topic", [""])[0]
                try:
                    topic = _safe_topic(topic)
                except WorkbenchRequestError as exc:
                    self._respond_json(400, {"error": str(exc)})
                    return
                self._respond_json(200, {"runs": list_runs(research_root, topic)})
                return
            if parsed.path == "/api/search":
                query_params = parse_qs(parsed.query)
                try:
                    corpus_root = _safe_corpus_root(
                        query_params.get("corpus_root", [""])[0], corpus_allowlist_root
                    )
                    kind = query_params.get("kind", [""])[0]
                    query = query_params.get("q", [""])[0]
                    with CreditGraph.open(corpus_root) as graph:
                        results = search_corpus(graph, kind, query)
                except WorkbenchRequestError as exc:
                    self._respond_json(400, {"error": str(exc)})
                    return
                self._respond_json(200, {"results": results})
                return
            if parsed.path == "/api/evidence":
                query_params = parse_qs(parsed.query)
                try:
                    corpus_root = _safe_corpus_root(
                        query_params.get("corpus_root", [""])[0], corpus_allowlist_root
                    )
                    kind = query_params.get("kind", [""])[0]
                    entity_id = _required_query_int(query_params.get("id", [""])[0], "id")
                    with CreditGraph.open(corpus_root) as graph:
                        evidence = load_evidence(graph, kind, entity_id, corpus_root)
                except WorkbenchRequestError as exc:
                    self._respond_json(400, {"error": str(exc)})
                    return
                self._respond_json(200, evidence)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/compare":
                self.send_error(404)
                return
            try:
                raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(raw_body)
                if not isinstance(payload, dict):
                    raise WorkbenchRequestError("request body must be a JSON object")
                mode = payload.get("mode")
                if mode not in ("albums", "artists", "scenes"):
                    raise WorkbenchRequestError("mode must be one of albums/artists/scenes")
                corpus_root = _safe_corpus_root(
                    payload.get("corpus_root", ""), corpus_allowlist_root
                )
                topic = _safe_topic(payload.get("topic", ""))
                compare_request = build_compare_request(mode, payload, corpus_root)
                result = run_comparison_and_persist(
                    mode, compare_request, topic=topic, research_root=research_root
                )
            except (WorkbenchRequestError, json.JSONDecodeError, CompareError) as exc:
                self._respond_json(400, {"error": str(exc)})
                return
            self._respond_json(200, result)

        def log_message(self, format: str, *args: object) -> None:
            return

    return WorkbenchHandler


def make_handler(
    analysis_dir: Path, selection_path: Path, source_id: str, reviewed_by: str, art_dir: Path | None
) -> type[BaseHTTPRequestHandler]:
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
    parser = argparse.ArgumentParser(
        description="Serve the local cohort curator or research workbench UI"
    )
    parser.add_argument(
        "--mode",
        choices=("cohort", "workbench"),
        default="cohort",
        help="cohort (default, unchanged) reviews one scored cohort; workbench (Phase 7 PR D) "
        "runs research-compare comparisons from a browser",
    )
    parser.add_argument("--source-id", help="required for --mode cohort")
    parser.add_argument("--analysis-dir", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--reviewed-by", default="local-curator")
    parser.add_argument("--art-dir", type=Path, help="optional local album-art directory")
    parser.add_argument(
        "--research-root",
        type=Path,
        default=RESEARCH_ROOT,
        help="for --mode workbench: where runs are written (default local/research/)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="use 0.0.0.0 only for explicit LAN access"
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.mode == "cohort":
        if not args.source_id:
            parser.error("--source-id is required for --mode cohort")
        analysis_dir = args.analysis_dir or Path("local/analysis/cohorts") / args.source_id
        selection = (
            args.selection
            or Path("data/private/cohort-review") / f"{args.source_id}-selection.json"
        )
        handler = make_handler(
            analysis_dir, selection, args.source_id, args.reviewed_by, args.art_dir
        )
        label = "Local curator"
    else:
        handler = make_workbench_handler(args.research_root)
        label = "Local research workbench"

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"{label} listening on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
