// Wires the Connection of the Day archive page (play/daily/archive.astro)
// to dailyArchive.ts's pure calendar logic, plus a local-stats summary
// reusing the progression store's own totals/streak directly -- no new
// backend artifact.

import { buildArchiveDays, type ArchiveDay } from "./dailyArchive";
import { fetchDailyManifest } from "./dailyManifest";
import { fetchFailureMessage } from "./domUtils";
import { localIsoDate } from "./localDate";
import { ratingGlyph, ratingLabel } from "./scoring";
import { load, type StorageLike } from "./store";

function storage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function dayLabel(day: ArchiveDay): string {
  if (day.status === "future") return "Not yet scheduled to play";
  if (day.status === "unplayed") return "Not played";
  return day.rating ? `Played — ${ratingLabel(day.rating)}` : "Played";
}

function dayGlyph(day: ArchiveDay): string {
  if (day.status === "future") return "";
  if (day.status === "unplayed") return "·";
  return day.rating ? ratingGlyph(day.rating) : "·";
}

function renderCalendar(root: HTMLElement, days: ArchiveDay[]): void {
  root.innerHTML = days
    .map((day) => {
      const glyph = dayGlyph(day);
      return (
        `<li class="archive-day" data-status="${day.status}">` +
        `<span class="archive-day__date">${day.date}</span>` +
        `<span class="archive-day__glyph" aria-hidden="true">${glyph}</span>` +
        `<span class="archive-day__status">${dayLabel(day)}</span>` +
        `</li>`
      );
    })
    .join("");
}

export async function initDailyArchive(): Promise<void> {
  const root = document.querySelector<HTMLElement>(
    "[data-testid='daily-archive']",
  );
  if (!root) return;

  const calendarEl = root.querySelector<HTMLUListElement>(
    "[data-archive-calendar]",
  );
  const statusEl = root.querySelector<HTMLElement>("[data-archive-status]");
  const statsEl = root.querySelector<HTMLElement>("[data-archive-stats]");
  if (!calendarEl || !statusEl) return;

  const store = load(storage());
  if (statsEl) {
    statsEl.textContent = `Streak: ${store.streak.current} day${store.streak.current === 1 ? "" : "s"} (best ${store.streak.best}) — ${store.totals.solved} of ${store.totals.played} solved`;
  }

  let manifest;
  try {
    manifest = await fetchDailyManifest();
  } catch {
    statusEl.hidden = false;
    statusEl.textContent = fetchFailureMessage("the daily schedule");
    return;
  }

  const today = localIsoDate(new Date());
  const days = buildArchiveDays(manifest.schedule, store.daily, today);
  statusEl.hidden = true;
  renderCalendar(calendarEl, days);
}
