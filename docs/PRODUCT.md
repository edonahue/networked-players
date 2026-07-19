# Product brief

## Intent

Networked Players makes the hidden human network behind recorded music visible and playable. It should reward curiosity while showing the evidence for every connection.

## Public identity

`networked-players.com` hosts the current static public application. Cloudflare builds it
from this GitHub repository's `main` branch. The Music-Credit Graph Study Lab remains the
learning companion; the home cluster is not required for the public experience.

## Audience

- music listeners interested in credits and collaboration;
- record collectors following unexpected personnel across releases;
- players who enjoy connection, path, and deduction games;
- developers learning data products, graph models, and distributed systems on modest hardware.

## Core promise

Given two albums, Networked Players can present a documented route through the credited work connecting them and explain each step without confusing collaboration with artistic influence. Albums are the entry point — the visual, recognizable anchor a listener already has an intuition for — but every connection resolves down to the same evidence unit as always: two artists sharing a documented credit.

## First useful release

A small browser experience presents a grid of albums, each an entry point into the credit graph. Opening an album offers two ways in: **find the connection** (guess which artist links it to another album before revealing the answer) and **reveal the path** (step through the evidence — release, role, credit scope — hop by hop). The experience loads a versioned static challenge and remains functional when all home-hosted services are offline; it is deployed as the core experience at `networked-players.com`.

## Shipped play modes

The site now ships a game-first surface on top of the browse experience (plan:
`docs/WEB_PRODUCT_PLAN.md`; decisions: ADR 0037):

- **Connection Guesser** (`/play/connection/`): two records land on the counter and the player picks the contributor credited on both from a tray of choices — two attempts, an optional clue ladder, an honest give-up. Two-hop rounds hide a middle record: find the bridge credit on each side, then name the record itself. Rounds play in five-round sittings with a needle-drop summary (clean / with help / revealed), stored only on the device.
- **Connection of the Day** (`/play/daily/`): one deterministic round per UTC date, the same for everyone, with a local streak and a spoiler-free share string (the date and grooves, never a name).
- Two content pools, badged during play: a clearly-stamped **synthetic universe** (fictional catalog with generated sleeve art) and **real records** derived from the curated demo dataset (ADR 0012), with cover art hotlinked from Discogs' own CDN.

Every round resolves into a liner-note evidence sheet: the credit rows, role text, and provenance that document the connection. A shared credit documents participation on a recording — never influence.

## Not yet promised

- exhaustive catalog coverage;
- unrestricted arbitrary-artist search;
- real-time multiplayer;
- inference of influence, friendship, or artistic lineage;
- public access to the owner's collection;
- high availability from the home cluster.

## Potential later modes

- producer/engineer-bridge mode: find the behind-the-scenes credit that links two albums, not just a performing artist;
- six-degrees mode: shortest documented route between two albums, with a hop budget;
- curated paths (the daily shipped; a reviewed-cohort browse shell exists, reviewed sets pending);
- hidden contributor;
- role-restricted paths;
- manual relay between players;
- collection-inspired challenges using derived public facts;
- bounded live search and visual exploration.
