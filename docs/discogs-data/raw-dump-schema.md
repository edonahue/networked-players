# Discogs monthly dump XML schema

Real structure, grounded in the June 2026 snapshot (`20260601`), downloaded and
directly inspected (`zcat | head`, `grep -c`) on 2026-07-01. All four kinds were
downloaded in full for this inspection — see `docs/DATA_SIZING.md` for their real
sizes and record counts.

## Shared conventions across all four kinds

- **Format:** a single root element (`<releases>`, `<artists>`, `<labels>`,
  `<masters>`) containing one child element per record, gzip-compressed. No XML
  namespace, no schema (`.xsd`/`.dtd`) is published or referenced in the files
  themselves.
- **License:** CC0 ("No Rights Reserved") per the dump landing page's own text:
  *"This data is made available under the CC0 No Rights Reserved license"* — see
  `docs/DATA_AND_RIGHTS.md` for how this project treats that.
- **Record identity is inconsistent between kinds** — worth knowing before writing a
  parser for a new kind: `<release id="...">` and `<master id="...">` carry their ID
  as an XML **attribute**; `<artist>` and `<label>` instead carry it as a nested
  **child element**, `<id>123</id>`. Don't assume one convention for all four.
- **Inline cross-reference markup.** Free-text fields (`profile`, `notes`, etc.)
  use a `[x=Name]` wiki-style convention to link to other entities: `[a=ArtistName]`
  (artist), `[l=LabelName]` (label). Real example (from a label's `profile`):
  `"[a=Carl Craig]'s classic techno label founded in 1991."` These are **not**
  structured references (no ID, just display text) — resolving them to a stable ID
  would require a name-based lookup, which is lossy (name collisions, aliases). Not
  currently parsed or relied on anywhere in this project.
- **Text encoding quirk:** free-text fields use `&#13;` (carriage return) for line
  breaks rather than `\n`, observed consistently across `contactinfo`, `profile`,
  and `notes` fields.
- **Numeric IDs are shared across kinds where they refer to the same real-world
  entity type** — an `artist_id` referenced from a release's `<artists>`, a master's
  `<artists>`, and the standalone `artists.xml.gz` all mean the same Discogs artist.
  There is no kind-local ID namespace.

## `releases.xml.gz` — the only kind this project currently parses

Real 2026-07-01 download: 11,099,074,063 bytes (~11.0 GB), ~19.1M records (May 2026
count, see `DATA_SIZING.md`). Root element `<releases>`, one `<release id="N"
status="...">` child per record.

Real example (release id `1`, abbreviated — the full record also has `<videos>` and
`<companies>`, omitted below for length):

```xml
<release id="1"><artists><artist><id>1</id><name>The Persuader</name></artist></artists>
<title>Stockholm</title>
<labels><label name="Svek" catno="SK032" id="5"/></labels>
<extraartists>
  <artist><id>507025</id><name>George Cutmaster General</name><anv>G Phrupmastergeneral</anv><role>Lacquer Cut By</role></artist>
  <artist><id>239</id><name>Jesper Dahlbäck</name><role>Written-By [All Tracks By]</role></artist>
</extraartists>
<formats><format name="Vinyl" qty="2" text=""><descriptions><description>12"</description><description>33 ⅓ RPM</description></descriptions></format></formats>
<genres><genre>Electronic</genre></genres>
<styles><style>Deep House</style></styles>
<country>Sweden</country>
<released>1999-03-00</released>
<notes>The song titles are the names of six Stockholm districts...</notes>
<data_quality>Correct</data_quality>
<master_id is_main_release="true">1660109</master_id>
<tracklist>
  <track><position>A</position><title>Östermalm</title><duration>4:45</duration></track>
  <!-- ...5 more tracks... -->
</tracklist>
<identifiers>
  <identifier type="Matrix / Runout" description="A-side runout" value="MPO SK 032 A1 G PHRUPMASTERGENERAL T2T LONDON"/>
</identifiers>
</release>
```

Note `<released>1999-03-00</released>` — a real observed date-partiality convention:
day `00` means "month/year known, day unknown." Not currently normalized by this
project's parser (kept verbatim as the `released` string field).

### Fields this project currently parses (`releases.py`)

`id` (attribute), `status` (attribute), `title`, `country`, `released`,
`master_id`/`is_main_release` (attribute), `data_quality`, `artists/artist` and
`extraartists/artist` (each: `id`, `name`, `anv`, `join`, `role`, `tracks`),
`tracklist/track` (`position`, `title`, `duration`, its own nested
`artists`/`extraartists`, and recursive `sub_tracks/track`).

### Fields present in the real data but **not yet parsed** by this project

Confirmed present in the real inspected sample, not represented in
`data/contracts/discogs-release-v2.md`'s current schema v2:

| Field | Real example | Notes |
| --- | --- | --- |
| `<labels><label>` | `name="Svek" catno="SK032" id="5"` | Label name, catalog number, and a real `label_id` — a genuine graph edge (release↔label) this project doesn't extract yet |
| `<formats><format>` | `name="Vinyl" qty="2"`, nested `<descriptions>` (`12"`, `33 ⅓ RPM`) | Physical format facts |
| `<genres>`/`<styles>` | `Electronic` / `Deep House` | Discogs' own genre/style taxonomy (controlled vocabulary, not free text) |
| `<notes>` | Free text | Often contains `[a=]`/`[l=]` cross-references (see above) |
| `<identifiers>` | `type="Matrix / Runout" value="..."` | Matrix/runout, barcode, etc. — physical-artifact-level evidence |
| `<videos>` | `src` (YouTube URL), `duration`, `title`, `description` | Real external links; **not** the same as the API's `images[]` — dump XML has no image data at all |
| `<companies>` | `id`, `name`, `entity_type`, `entity_type_name` (e.g. "Recorded At", "Pressed By") | A second, distinct credit system alongside `artists`/`extraartists` — companies/roles rather than people |

These are real, deliberate gaps (per `AGENTS.md`: "Artists, labels, and masters
parsers remain intentionally deferred"), not oversights — listed here so a future
milestone extending the schema starts from what's actually in the data.

## `artists.xml.gz`

Real 2026-07-01 download: 490,122,874 bytes (~490 MB), **10,081,427 records**
(directly counted, `zcat | grep -c '<artist>'`). Root `<artists>`, one
`<artist>...</artist>` child per record (id is a **child element**, not an
attribute — see "Record identity is inconsistent" above).

Real example (artist id `2`, a duo — illustrates `members`; artist id `1` in the
same file illustrates `aliases`/`namevariations` instead):

```xml
<artist>
  <id>2</id>
  <name>Mr. James Barth &amp; A.D.</name>
  <data_quality>Correct</data_quality>
  <namevariations>
    <name>MR JAMES BARTH &amp; A. D.</name>
    <name>Mr Barth &amp; A.D.</name>
  </namevariations>
  <aliases>
    <name id="2470">Puente Latino</name>
    <name id="1779857">Alexi Delano &amp; Cari Lekebusch</name>
  </aliases>
  <members>
    <name id="26">Alexi Delano</name>
    <name id="27">Cari Lekebusch</name>
  </members>
</artist>
```

### Fields observed

`id`, `name`, `realname` (real person's legal/common name, distinct from the
Discogs display `name`), `profile` (free text, often with `[a=]`/`[l=]`
cross-references), `data_quality`, `urls` (list of external links —
Wikipedia, Bandcamp, socials), `namevariations` (list of alternate spellings of
*the same* `name`, no separate IDs), `aliases` (list of **other artist IDs** that
represent an overlapping or related identity), `groups` (inverse of `members`: the
groups an individual artist belongs to), `members` (for a group-type artist: the
individual artist IDs who belong to it).

### A real identity-modeling nuance worth flagging

This project's own schema deliberately separates **PAN** (`artist_id`, stable
identity) from **ANV** (Artist Name Variation, a *per-credit* display override) —
see `data/contracts/discogs-release-v2.md`. The `artists.xml.gz` dump exposes a
**third**, different kind of name relationship that this project's schema doesn't
model at all yet: `aliases`. Real example above: artist id `1` ("The Persuader",
`realname` "Jesper Dahlbäck") lists artist id `239` ("Jesper Dahlbäck") as one of
its aliases — two **separate, real Discogs artist IDs** for what is arguably the
same person, linked by Discogs' own editorial process, not by this project. This is
structurally different from ANV (same `artist_id`, different display text on one
credit) and from `namevariations` (same `artist_id`, alternate spellings) — `aliases`
crosses artist IDs entirely. Any future work resolving "is this the same real
person" needs to treat `aliases` as its own signal, not conflate it with ANV.

### Not parsed by this project at all (no artist parser exists yet)

Every field above — `packages/catalog` currently only implements `parse-releases`.

## `labels.xml.gz`

Real 2026-07-01 download: 89,019,947 bytes (~89 MB), **2,383,990 records** (directly
counted). Root `<labels>`, one `<label>...</label>` child per record (id is a
**child element**, matching `artist`, not `release`/`master`).

Real example (label id `1`, illustrates `sublabels`):

```xml
<label>
  <id>1</id>
  <name>Planet E</name>
  <contactinfo>Planet E Communications&#13;P.O. Box 27218&#13;Detroit, Michigan...</contactinfo>
  <profile>[a=Carl Craig]'s classic techno label founded in 1991.</profile>
  <data_quality>Needs Vote</data_quality>
  <urls><url>http://planet-e.net</url><!-- ...11 more... --></urls>
  <sublabels>
    <label id="31405">I Ner Zon Sounds</label>
    <label id="277579">Planet E Communications</label>
    <!-- ...6 more... -->
  </sublabels>
</label>
```

### Fields observed

`id`, `name`, `contactinfo` (free text, often a real-world mailing
address/phone/email), `profile` (free text), `data_quality`, `urls`, `sublabels`
(list of other **label IDs** that are imprints/sub-labels of this one — a real
label-hierarchy graph edge, e.g. "Planet E Communications" the sublabel vs. "Planet
E" the parent).

### Not parsed by this project at all (no label parser exists yet)

Every field above. `data/contracts/discogs-release-v2.md`'s `releases` table does
capture a release's `<labels><label>` reference (name + catalog number + a real
`label_id`), but that's the release-side edge, not this standalone dump.

## `masters.xml.gz`

Real 2026-07-01 download: 614,336,787 bytes (~614 MB), **2,560,991 records**
(directly counted, `zcat | grep -c '<master '` — note the trailing space,
distinguishing the opening tag from `</master>`). Root `<masters>`, one `<master
id="N">...</master>` child per record (id is an **attribute**, matching `release`).

Real example (master id `113`, abbreviated — the full record also has 8 `<video>`
entries, omitted below):

```xml
<master id="113">
  <main_release>116925</main_release>
  <artists><artist><id>3225</id><name>Vince Watson</name><join>,</join></artist></artists>
  <genres><genre>Electronic</genre></genres>
  <styles><style>Techno</style><style>Tech House</style></styles>
  <year>2002</year>
  <title>Moments In Time</title>
  <data_quality>Correct</data_quality>
  <videos><!-- ...8 video entries... --></videos>
</master>
```

### Fields observed

`id` (attribute), `main_release` (a `release_id` — the specific release Discogs
considers canonical/representative for this master), `artists` (same
`id`/`name`/`join` shape as a release's release-level artist credit), `genres`,
`styles`, `year`, `title`, `data_quality`, `videos` (same shape as a release's
`videos`).

This is the *other side* of the `<master_id is_main_release="...">` reference
already parsed on the release side: a release points at its master via
`master_id`, and the master's `<main_release>` points back at whichever release is
canonical. This project's schema currently only captures the release→master
direction (`master_id`, `master_is_main_release`), not the master's own record.

### Not parsed by this project at all (no master parser exists yet)

Every field above.
