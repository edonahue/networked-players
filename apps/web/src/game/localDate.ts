// Connection of the Day rolls over at the PLAYER'S LOCAL calendar midnight,
// not UTC midnight (corrective slice 5.1) -- a deliberate product decision:
// the committed manifest (daily-manifest.v1.json) assigns one ordinary
// YYYY-MM-DD date label per day, and every browser resolves that same label
// against its OWN local calendar date. Two players in different time zones
// therefore enter the next scheduled puzzle at their own local midnight, not
// simultaneously -- the schedule itself never changes, only when each
// browser considers "today" to have arrived.

/** The local (not UTC) calendar date of `date`, as `YYYY-MM-DD`. Uses only
 * the local-time getters (`getFullYear`/`getMonth`/`getDate`) -- never
 * `toISOString`/`getUTC*`, which would report the UTC calendar date and can
 * disagree with the player's own local date by a day near midnight. */
export function localIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
