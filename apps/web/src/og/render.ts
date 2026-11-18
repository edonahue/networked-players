// Build-time renderer: satori (SVG from the card tree) + resvg (PNG).
// Runs only inside Astro static endpoints during `astro build`; nothing here
// fetches the network. Fonts are read from src/og/fonts (OFL, never shipped).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import site from "../data/site.json";
import satori from "satori";
import { Resvg } from "@resvg/resvg-js";
import { cardMarkup, OG_HEIGHT, OG_WIDTH, type CardInput } from "./card";

// Astro bundles endpoints into dist/.prerender, so resolve from the app root
// (the build's working directory) rather than import.meta.url.
const font = (file: string) =>
  readFileSync(resolve(process.cwd(), "src/og/fonts", file));

type Font = {
  name: string;
  data: Buffer;
  weight: 400 | 500 | 600;
  style: "normal";
};
let fonts: Font[] | undefined;

function loadFonts(): Font[] {
  fonts ??= [
    {
      name: "Source Serif 4",
      data: font("source-serif-4-latin-600-normal.woff"),
      weight: 600,
      style: "normal",
    },
    {
      name: "Inter",
      data: font("inter-latin-400-normal.woff"),
      weight: 400,
      style: "normal",
    },
    {
      name: "IBM Plex Mono",
      data: font("ibm-plex-mono-latin-500-normal.woff"),
      weight: 500,
      style: "normal",
    },
  ];
  return fonts;
}

export async function renderCard(input: CardInput): Promise<Response> {
  const svg = await satori(cardMarkup(input, site.title) as never, {
    width: OG_WIDTH,
    height: OG_HEIGHT,
    fonts: loadFonts(),
  });
  const png = new Resvg(svg, { fitTo: { mode: "width", value: OG_WIDTH } })
    .render()
    .asPng();
  return new Response(new Uint8Array(png), {
    headers: { "Content-Type": "image/png" },
  });
}
