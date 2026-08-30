// Roving-tabindex arrow-key navigation shared by every `role="radio"` chip
// tray in this codebase: Guesser's contributor/middle-album tray
// (flagship.ts), Routes' length/artist trays (routes.ts), and Connect's
// route-filter tray (connect.ts). Previously hand-copied byte-for-byte into
// flagship.ts and routes.ts independently (routes.ts's own `wireRadioTray`
// even said so in a comment); adding a THIRD copy for Connect was the "rule
// of three" signal to extract this instead.
//
// Deliberately narrow: only the keyboard-navigation mechanics are shared.
// Chip creation, click/selection semantics, and disabled-state handling stay
// local to each caller -- all three have genuinely different selection
// models (Guesser submits a one-shot quiz answer and locks the tray;
// Routes does the same for its length/artist guesses; Connect's filter is a
// freely re-selectable, persistent setting, never disabled). Forcing those
// into one shared shape would risk destabilizing two already-working,
// tested implementations for no real gain.
//
// `getChips` is a GETTER, not a plain array, because Guesser's own chip set
// is rebuilt on every round/step (`chips = refs.map(...)` in flagship.ts) --
// a snapshot captured once at wire time would silently keep navigating a
// stale, already-replaced tray after the first round. Routes' and Connect's
// chip arrays never change after creation, so a getter returning the same
// array each time costs them nothing.
export function wireRadioTray(
  tray: HTMLElement,
  getChips: () => readonly HTMLButtonElement[],
): void {
  tray.addEventListener("keydown", (event) => {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const chips = getChips();
    const enabled = chips.filter((chip) => !chip.disabled);
    if (enabled.length === 0) return;
    const current = document.activeElement as HTMLButtonElement | null;
    const index = Math.max(0, enabled.indexOf(current as HTMLButtonElement));
    const delta =
      event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
    const next = enabled[(index + delta + enabled.length) % enabled.length];
    for (const chip of chips) chip.tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
  });
}
