// Site-wide header search: one combobox over records and players, backed by
// the published search index and ranked by siteSearch.ts. Everything here is
// lazy -- nothing is fetched until the visitor focuses or types in the box.
// Progressive enhancement: without JS the header shows a plain link to
// /albums/ instead (see SiteSearch.astro).

import {
  fetchSearchIndex,
  searchIndex,
  type SearchEntry,
  type SearchIndex,
} from "./siteSearch";

const DETAILS_URL = "/search/details.json";
const PER_GROUP = 5;

interface Details {
  players: Record<string, { album: string; roles: string[] }>;
  years: Record<string, number>;
}

interface Row {
  href: string;
  title: string;
  detail: string;
  kind: "album" | "contributor";
}

let detailsPromise: Promise<Details> | null = null;
function loadDetails(): Promise<Details> {
  // Optional enrichment: a failure degrades to plainer rows, never to no search.
  detailsPromise ??= fetch(DETAILS_URL)
    .then((r) =>
      r.ok ? (r.json() as Promise<Details>) : { players: {}, years: {} },
    )
    .catch(() => ({ players: {}, years: {} }));
  return detailsPromise;
}

function init(root: HTMLElement) {
  const q = <T extends HTMLElement>(sel: string) => root.querySelector<T>(sel);
  const input = q<HTMLInputElement>("[data-search-input]");
  const panel = q("[data-search-panel]");
  const list = q("[data-search-list]");
  const empty = q("[data-search-empty]");
  const message = q("[data-search-message]");
  const status = q("[data-search-status]");
  const trigger = q<HTMLButtonElement>("[data-search-trigger]");
  const fallback = q("[data-search-fallback]");
  const form = q("[data-search-form]");
  if (!input || !panel || !list || !empty || !message || !status || !form)
    return;

  root.classList.add("is-ready");
  fallback?.setAttribute("hidden", "");
  form.removeAttribute("hidden");
  trigger?.removeAttribute("hidden");

  let index: SearchIndex | null = null;
  let details: Details = { players: {}, years: {} };
  let loading = false;
  let failed = false;
  let active = -1;

  const optionEls = () =>
    Array.from(list.querySelectorAll<HTMLElement>("[role=option]"));

  function setActive(next: number) {
    active = next;
    optionEls().forEach((el, i) => {
      el.setAttribute("aria-selected", String(i === next));
      if (i === next) el.scrollIntoView({ block: "nearest" });
    });
    const el = next >= 0 ? optionEls()[next] : undefined;
    if (el) input!.setAttribute("aria-activedescendant", el.id);
    else input!.removeAttribute("aria-activedescendant");
  }

  function setOpen(open: boolean) {
    panel!.hidden = !open;
    input!.setAttribute("aria-expanded", String(open));
    if (!open) setActive(-1);
  }

  function toRow(entry: SearchEntry): Row {
    if (entry.kind === "album") {
      const year = details.years[entry.id];
      return {
        kind: "album",
        href: `/albums/${entry.id}/`,
        title: entry.label,
        detail: [entry.sublabel, year].filter(Boolean).join(" · "),
      };
    }
    const info = details.players[entry.id];
    return {
      kind: "contributor",
      // Same URL form as the player's own page: Explore opened on one of their
      // records, centred on them.
      href: info
        ? `/explore/${info.album}/?center=${entry.id}`
        : `/contributors/${entry.id}/`,
      title: entry.label,
      detail: info?.roles.length
        ? `Credited: ${info.roles.join(", ")}`
        : "Player",
    };
  }

  function appendGroup(label: string, group: Row[], startAt: number) {
    if (group.length === 0) return startAt;
    const g = document.createElement("div");
    g.setAttribute("role", "group");
    g.className = "site-search__group";
    const h = document.createElement("div");
    h.className = "site-search__group-label";
    h.id = `site-search-group-${label.toLowerCase()}`;
    h.setAttribute("aria-hidden", "true");
    h.textContent = label;
    g.setAttribute("aria-label", label);
    g.append(h);
    group.forEach((row, i) => {
      const opt = document.createElement("div");
      opt.id = `site-search-opt-${startAt + i}`;
      opt.className = "site-search__option";
      opt.setAttribute("role", "option");
      opt.setAttribute("aria-selected", "false");
      opt.dataset.href = row.href;
      opt.dataset.kind = row.kind;
      const t = document.createElement("span");
      t.className = "site-search__title";
      t.textContent = row.title;
      const d = document.createElement("span");
      d.className = "site-search__detail";
      d.textContent = row.detail;
      opt.append(t, d);
      g.append(opt);
    });
    list!.append(g);
    return startAt + group.length;
  }

  function showMessage(text: string, withLinks = false) {
    list!.replaceChildren();
    list!.hidden = true;
    message!.textContent = text;
    message!.hidden = false;
    empty!.hidden = !withLinks;
    setOpen(true);
  }

  function render() {
    const query = input!.value.trim();
    if (!query) {
      setOpen(false);
      status!.textContent = "";
      return;
    }
    if (failed) {
      showMessage(
        "Search couldn't load just now. You can still browse all records or players.",
        true,
      );
      status!.textContent = "Search could not load.";
      return;
    }
    if (!index) {
      showMessage("Searching…");
      return;
    }
    const records = searchIndex(index, query, {
      kinds: ["album"],
      limit: PER_GROUP,
    }).map(toRow);
    const players = searchIndex(index, query, {
      kinds: ["contributor"],
      limit: PER_GROUP,
    }).map(toRow);
    if (records.length + players.length === 0) {
      const nAlbums = index.entries.filter((e) => e.kind === "album").length;
      const nPlayers = index.entries.filter(
        (e) => e.kind === "contributor",
      ).length;
      showMessage(
        `Nothing matches "${query}". This is a bounded collection of ${nAlbums} records and ${nPlayers} players, and search only covers what is published here.`,
        true,
      );
      status!.textContent = "No results.";
      return;
    }
    list!.replaceChildren();
    message!.hidden = true;
    empty!.hidden = true;
    list!.hidden = false;
    const next = appendGroup("Records", records, 0);
    appendGroup("Players", players, next);
    setOpen(true);
    setActive(-1);
    const r = records.length;
    const p = players.length;
    status!.textContent = `${r} ${r === 1 ? "record" : "records"}, ${p} ${p === 1 ? "player" : "players"}. Use the up and down arrow keys to review.`;
  }

  function ensureLoaded() {
    if (index || loading) return;
    loading = true;
    Promise.all([fetchSearchIndex(), loadDetails()])
      .then(([idx, det]) => {
        index = idx;
        details = det;
        failed = false;
      })
      .catch(() => {
        failed = true;
      })
      .finally(() => {
        loading = false;
        render();
      });
  }

  function go(el: HTMLElement | undefined) {
    const href = el?.dataset.href;
    if (href) window.location.assign(href);
  }

  function openMobile() {
    root.classList.add("is-open");
    trigger?.setAttribute("aria-expanded", "true");
    input!.focus();
  }
  function closeMobile(refocus: boolean) {
    root.classList.remove("is-open");
    trigger?.setAttribute("aria-expanded", "false");
    setOpen(false);
    if (refocus) trigger?.focus();
  }

  input.addEventListener("focus", ensureLoaded);
  input.addEventListener("input", () => {
    failed = false; // a new keystroke retries a failed load
    ensureLoaded();
    render();
  });
  input.addEventListener("keydown", (event) => {
    const count = optionEls().length;
    if (event.key === "ArrowDown" && count > 0) {
      event.preventDefault();
      if (panel.hidden) setOpen(true);
      setActive((active + 1) % count);
    } else if (event.key === "ArrowUp" && count > 0) {
      event.preventDefault();
      setActive(active <= 0 ? count - 1 : active - 1);
    } else if (event.key === "Enter") {
      const target = optionEls()[active >= 0 ? active : 0];
      if (!panel.hidden && target) {
        event.preventDefault();
        go(target);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      if (!panel.hidden) setOpen(false);
      else if (root.classList.contains("is-open")) closeMobile(true);
    }
  });
  list.addEventListener("mousedown", (event) => event.preventDefault());
  list.addEventListener("click", (event) => {
    go(
      (event.target as HTMLElement).closest<HTMLElement>("[role=option]") ??
        undefined,
    );
  });
  root.addEventListener("focusout", (event) => {
    const next = event.relatedTarget as Node | null;
    if (next && root.contains(next)) return;
    setOpen(false);
  });

  // Mobile: the trigger reveals the field as a second layer under the header
  // bar, so the bar itself stays a single row.
  trigger?.addEventListener("click", () => {
    if (root.classList.contains("is-open")) closeMobile(true);
    else openMobile();
  });

  // Any control marked data-search-open (e.g. the Explore page's prominent
  // entry) opens and focuses this same search.
  document.addEventListener("click", (event) => {
    if (!(event.target as HTMLElement).closest("[data-search-open]")) return;
    event.preventDefault();
    openMobile();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey)
      return;
    const t = event.target as HTMLElement | null;
    if (
      t &&
      (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))
    )
      return;
    event.preventDefault();
    openMobile();
  });
}

const root = document.querySelector<HTMLElement>("[data-site-search]");
if (root) init(root);
