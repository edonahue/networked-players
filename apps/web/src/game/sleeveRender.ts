// Shared sleeve rendering (Connection Guesser + Record Routes, ADR 0046):
// real covers are resolved by canonical album id from the album-art registry
// (game/albumArt.ts), synthetic albums render a generated SVG sleeve, and
// every miss (no registry, no entry, upstream image error) falls back to the
// same polished placeholder disc -- one visual system across every real-data
// surface, never a mode-specific reimplementation.

import { sleeveSvg } from "./sleeves";
import type { ResolvedArt } from "./albumArt";

/** Minimal shape any renderable album ref needs -- both `AlbumRef` (game)
 * and a Record Routes album ref satisfy this. `act`/`label` are only read for
 * a `generated` (synthetic) sleeve; real refs may omit them. */
export interface SleeveAlbum {
  id: string;
  title: string;
  act?: string | null;
  label?: string | null;
  art?: { kind: "generated" } | null;
}

export function placeholderDisc(): HTMLElement {
  const span = document.createElement("span");
  span.className = "album-card__placeholder sleeve__placeholder";
  span.setAttribute("aria-hidden", "true");
  const disc = document.createElement("span");
  disc.className = "album-card__placeholder-disc";
  span.append(disc);
  return span;
}

/** Render `album`'s sleeve into `container`: a generated SVG for synthetic
 * albums, a real cover resolved from `artMap` by album id, or the
 * placeholder -- never a thrown error, never a blocked render. */
export function renderSleeve(
  container: HTMLElement,
  album: SleeveAlbum,
  artMap: Map<string, ResolvedArt>,
): void {
  container.replaceChildren();
  if (album.art && album.art.kind === "generated") {
    container.innerHTML = sleeveSvg({
      id: album.id,
      title: album.title,
      act: album.act ?? null,
      label: album.label ?? null,
    });
    return;
  }
  const art = artMap.get(album.id);
  if (art) {
    const img = document.createElement("img");
    img.src = art.uri150;
    img.width = 150;
    img.height = 150;
    img.alt = `Cover art for ${album.title}`;
    img.loading = "eager";
    img.addEventListener("error", () => {
      container.replaceChildren(placeholderDisc());
    });
    container.append(img);
    return;
  }
  container.append(placeholderDisc());
}
