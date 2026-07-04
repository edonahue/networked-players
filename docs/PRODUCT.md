# Product brief

## Intent

Networked Players makes the hidden human network behind recorded music visible and playable. It should reward curiosity while showing the evidence for every connection.

## Public identity

`networked-players.com` is registered and reserved as the eventual production host for the public game. The GitHub repository remains the source and development record, while the Music-Credit Graph Study Lab remains the learning companion. No application is deployed at the domain yet.

## Audience

- music listeners interested in credits and collaboration;
- record collectors following unexpected personnel across releases;
- players who enjoy connection, path, and deduction games;
- developers learning data products, graph models, and distributed systems on modest hardware.

## Core promise

Given two albums, Networked Players can present a documented route through the credited work connecting them and explain each step without confusing collaboration with artistic influence. Albums are the entry point — the visual, recognizable anchor a listener already has an intuition for — but every connection resolves down to the same evidence unit as always: two artists sharing a documented credit.

## First useful release

A small browser experience presents a grid of albums, each an entry point into the credit graph. Opening an album offers two ways in: **find the connection** (guess which artist links it to another album before revealing the answer) and **reveal the path** (step through the evidence — release, role, credit scope — hop by hop). The experience loads a versioned static challenge and remains functional when all home-hosted services are offline; it is deployed as the core experience at `networked-players.com`.

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
- daily or curated paths;
- hidden contributor;
- role-restricted paths;
- manual relay between players;
- collection-inspired challenges using derived public facts;
- bounded live search and visual exploration.
