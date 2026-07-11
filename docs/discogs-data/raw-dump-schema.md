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
`formats/format` (`name`, positive `qty` when parseable, `text`, ordered nested
`description` values),
`tracklist/track` (`position`, `title`, `duration`, its own nested
`artists`/`extraartists`, and recursive `sub_tracks/track`).

### Fields present in the real data but **not yet parsed** by this project

Confirmed present in the real inspected sample, not represented in
`data/contracts/discogs-release-v2.md`'s current schema v2:

| Field | Real example | Notes |
| --- | --- | --- |
| `<labels><label>` | `name="Svek" catno="SK032" id="5"` | Label name, catalog number, and a real `label_id` — a genuine graph edge (release↔label) this project doesn't extract yet |
| `<genres>`/`<styles>` | `Electronic` / `Deep House` | Discogs' own genre/style taxonomy (controlled vocabulary, not free text) |
| `<notes>` | Free text | Often contains `[a=]`/`[l=]` cross-references (see above) |
| `<identifiers>` | `type="Matrix / Runout" value="..."` | Matrix/runout, barcode, etc. — physical-artifact-level evidence |
| `<videos>` | `src` (YouTube URL), `duration`, `title`, `description` | Real external links; **not** the same as the API's `images[]` — dump XML has no image data at all |
| `<companies>` | `id`, `name`, `entity_type`, `entity_type_name` (e.g. "Recorded At", "Pressed By") | A second, distinct credit system alongside `artists`/`extraartists` — companies/roles rather than people |
| `<series>` | `<series name="Profound Sounds" catno="Vol. 1" id="527772"/>` | A release-to-series graph edge (own `series_id`), same shape as `<label>`. Confirmed present in ~6.8% of releases (3,377 of 49,461 in a 200MB raw sample, 2026-07-02 real profiling pass below) — found late, via full-dataset profiling rather than the initial schema read; recorded here so it isn't missed again |

These are real, deliberate gaps (per `AGENTS.md`: "Artists, labels, and masters
parsers remain intentionally deferred"), not oversights — listed here so a future
milestone extending the schema starts from what's actually in the data.

## Real full-dataset profiling (2026-07-02)

The first genuinely complete parse of a real snapshot (`snapshot=20260601`,
19,192,301 releases / 178,224,810 tracks / 220,015,758 credits — see
`docs/BUILD_PLAN.md` Milestone 3, `docs/DATA_SIZING.md`'s "Full unbounded run:
complete") made it possible to profile the actual *output* dataset, not just
inspect the raw XML by hand. Run with `scripts/profile-discogs-dataset.sh`
(reusable against any future snapshot: `SNAPSHOT=YYYYMMDD make
profile-discogs`), using the DuckDB CLI already installed on the coordination
host (`scripts/install-duckdb-cli.sh`). Full captured output:
`local/monitoring/profile-20260601.txt` (git-ignored, real derived data).

### Dimensions and referential shape

Average 9.29 tracks and 11.46 credits per release. Only 1 of 19,192,301
releases has zero tracks; every release has at least one credit (the
`release_artist` row is never absent).

### Column quality and format findings

| Column | Finding | Verdict |
| --- | --- | --- |
| `status` (releases) | `NULL` for all 19,192,301 rows | Not a bug — the raw `<release>` element has no `status` attribute at all in this dump (checked byte-for-byte); the *dump* format simply doesn't carry it, unlike the API |
| `master_is_main_release` (releases) | Never `NULL` (always a real bool); 41.6% of releases (7,981,915) have `master_id IS NULL` and this field `= false` | Not a parser bug — traced to raw XML: `<master_id>` is present in ~99.999% of releases, and Discogs' own dump encodes "no master" as `<master_id is_main_release="false">0</master_id>` (`_integer()` already treats sentinel `0` as no master). The code's always-boolean output faithfully reflects real signal. **The contract doc's "nullable: yes" was the actual bug** — fixed in `data/contracts/discogs-release-v2.md` |
| `country` (releases) | 602,395 `NULL` (3.1%); top values US/UK/Germany/Japan/France, all plausible | No issue |
| `released` (releases) | Shape families: year-only 56.1% (10,777,003), full-date 26.3% (5,057,231), empty/null 13.3% (2,554,491), partial-day `YYYY-MM-00` 4.2% (803,525), other/malformed 0.0003% (51 rows: `1980s`, Arabic-Indic/fullwidth digits, `200?`, no-separator `20061014`, truncated dates) | Expected — field is intentionally kept verbatim, not normalized (see above) |
| `duration` (tracks) | 84,610,443 empty (47.5%), 93,544,302 match `M:SS` (52.5%), ~70K residual (0.04%): real `H:MM:SS` for long tracks (`1:00:00`, `2:00:00`) and single-digit-second source formatting (`3:5` = 3:05) | Expected — preserved verbatim, not reformatted |
| `position` (tracks) | 4,116,591 `NULL` (2.3%); top values are plain integers and vinyl side/position codes (`A1`, `B1`, ...) | No issue |
| Release/credit titles and names | 89 of 19,192,301 titles (0.0005%) contain mojibake (e.g. `Ãvutmã`, replacement characters `�`). Traced release `1417404` byte-for-byte in the raw XML: the corruption is already present in Discogs' own source dump (cross-referenced against the same release's clean matrix/runout text and a repeated-corruption track title) — not introduced by download/decompression/parsing | Not a bug — preserving it verbatim is the correct behavior per this project's evidence-preservation rule |
| `name` (credits) | Max length 4,159 chars — a single non-linked (`artist_id IS NULL`) credit listing dozens of names as one comma-separated blob (a large ensemble credited as a unit) | Not a bug — genuine free-text source data, correctly retained as evidence without inventing individual playable identities |
| `role_text` (credits) | 3,345,564 distinct values across 220,015,758 rows; 14,013 rows exceed 200 chars (max 2,655) | Expected — free text by design (`AGENTS.md`: "preserve original role text"), not a small enum. Concrete sizing evidence for a future role-taxonomy milestone (see `docs/BUILD_PLAN.md` Milestone 11) |
| `is_linked` × `playable_identity` (credits) | Only two combinations exist in 220M rows: `(true, true)` and `(false, false)` | Confirms the "no non-linked identity is ever playable" invariant holds at 100% in real data |
| `credit_scope` (credits) | `track_credit` 40.7%, `release_credit` 32.0%, `track_artist` 16.7%, `release_artist` 10.6% | No issue |
| `data_quality` (releases) | 90.6% `Needs Vote`, 8.0% `Correct`, remainder split across `Complete and Correct`/`Needs Minor Changes`/`Needs Major Changes`/`Entirely Incorrect` | No issue — real community-moderation skew, not a parsing artifact |
| Prolific `artist_id`s (credits) | Top by credit count: `194`/"Various" (1,387,275), `151641`/"Traditional" (521,164), `355`/"Unknown Artist" (420,079), then classical composers (Bach, Mozart, Beethoven) and well-known artists (David Bowie, Bob Dylan) | Sanity-check passed — the ranking is exactly what a real Discogs credit distribution should look like |

### Remediation taken

One small parser fix, evidence-scoped (see findings above): `status`
(`releases.py`, attribute path) is now stripped and coerced from empty
string to `None`, matching the convention every element-text field already
uses (`_text_from_map`). Zero effect on the existing real dataset (0
releases in this dump have `status=""`) — purely defensive for a future
dump. No other code changes were made: `<series>`'s gap is a documentation
fix (above), `master_is_main_release`'s nullability is a contract-doc fix
(`data/contracts/discogs-release-v2.md`), and every other finding above is
confirmed genuine source-data behavior, correctly preserved verbatim.
Nothing here required (or triggered) a re-run of the 6-hour full ingest.

### Query performance and DB setup

Setup: the standalone DuckDB CLI (`v1.5.4`, embedded — no server process),
reading zstd-compressed Parquet directly off the NVMe-backed
`local/processed/discogs/snapshot=20260601/` via glob patterns (no load
step, no persistent `.duckdb` file, no indexes) — the same coordination
host (ZimaBoard 832, 4 CPUs) that ran the ingest.

The full profiling script (27 queries, most scanning the full 19.19M/
178.2M/220M-row tables, several with `GROUP BY`/`ORDER BY`/regex on the
credits table) completed in **229.7 seconds total** (~3m50s), averaging
8.5s/query (min 0.15s for a view creation, max 77.7s for the heaviest
query — a `GROUP BY artist_id, name ORDER BY count DESC` over all 220M
credit rows). Most queries reported `user` time 2.5-3x their `real` time
(e.g. the 77.7s query: 216.2s user, 20.9s sys) — DuckDB automatically
parallelizes these Parquet scans across all 4 host cores by default, no
tuning required. This stands in useful contrast to the ingestion parser
itself, which is single-threaded by design (`docs/DATA_SIZING.md`'s "Real
profiling" section) — ad hoc analytical queries over the same or larger
row volumes finish in seconds to low tens of seconds, not hours, simply
because DuckDB's columnar engine reads only the referenced columns and
uses every available core without being asked.

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
