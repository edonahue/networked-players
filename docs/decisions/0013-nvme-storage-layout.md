# ADR 0013: NVMe storage layout and coordination-stack relocation

- **Status:** Accepted
- **Date:** 2026-07-01

## Context

A 1TB Samsung 970 EVO Plus NVMe is now physically attached to the ZimaBoard 832
coordination host — the exact drive `docs/DATA_SIZING.md` planned around ("The planned
1 TB project NVMe is sufficient with explicit retention..."). Both ADR 0007 and ADR 0010
left this moment as an explicit open decision: ADR 0007's consequences state "the
coordination host's local data root (Postgres/Redis volumes, `local/raw`,
`local/processed`) remains undecided until the NVMe is attached," with a revisit trigger
naming "relocation plan, mount point, and a revised free-space floor for the
coordination host's Ansible host_vars." ADR 0010 separately flags that the coordination
stack's `postgres-data`/`redis-data` Docker volumes, brought up ahead of schedule on the
28GB eMMC, "must be migrated (not simply recreated) onto the NVMe once it's attached, or
accumulated state is lost." The drive carried a stale partition table from prior,
unrelated use; nothing on it was mounted, and the operator had already copied off
anything they wanted before this session, confirming it was safe to wipe. The operator
also wants this drive to eventually host other, unrelated projects, not just this one.

Two things were confirmed rather than assumed before deciding:
- This host runs CasaOS, which has its own Storage app. Its `local-storage.service`
  already catalogs every block device and partition (`/var/lib/casaos/db/local-storage.json`
  listed the drive's prior partitions before this ADR's work began) purely from its own
  periodic scan — independent of mount method. So a manually-mounted drive is not hidden
  from the CasaOS UI; it simply doesn't get CasaOS's one-click format/eject controls
  (mergerfs is also disabled on this host: `EnableMergerFS = False`).
- `infra/ansible/playbooks/health.yml`'s free-space assertion is hardcoded to check `/`,
  with a comment explicitly deferring the real 250GB floor ("set per group, not enforced
  here"). Simply raising the coordinator's `min_free_gb` to 250 without also
  repointing the check would make it permanently fail, since `/` is still the 28GB eMMC
  after this migration.

## Decision

1. **Mount manually via `/etc/fstab`, not CasaOS's Storage app** — full control over the
   mount path for scripted/documented use, at no cost to CasaOS visibility (see above).
2. **ext4, one partition spanning the whole disk**, mounted at `/mnt/data`, owned
   `casaos:casaos`, mode `750`. Top-level directories per project
   (`/mnt/data/networked-players/`, future projects as siblings) rather than
   pre-partitioning or using LVM/btrfs subvolumes — avoids committing to per-project
   sizes up front, matches the eMMC's own filesystem choice.
3. **No LUKS encryption.** This data is already excluded from git via `data/private/`
   and `local/`; physical drive theft is not in this project's current threat model, and
   encryption would add an unlock step to every headless reboot.
4. **Replace the repo's `local/` directory with a symlink** to
   `/mnt/data/networked-players/local/`. Every script and CLI argument in the repo
   already references `local/...` as a relative path (`docs/OPERATOR_SETUP.md`), so this
   requires zero code changes anywhere. Discovered while doing this: git does **not**
   transparently resolve a tracked file through a newly-symlinked parent directory —
   the previously-tracked `local/.gitignore` showed as deleted, and the new `local`
   symlink showed as a separate untracked entry, once `local/` stopped being a real
   directory. `.gitignore`'s old `local/**` / `!local/.gitignore` pair (meant to keep a
   placeholder file tracked) is replaced with a single `local` line that ignores the
   path itself regardless of whether it's a directory or a symlink, and the stale
   `local/.gitignore` blob is untracked (`git rm --cached`).
5. **Migrate only the coordination stack's `postgres-data`/`redis-data` Docker volumes**
   onto `/mnt/data/docker-volumes/`, via a new `infra/swarm/migrate-coordination-volumes-to-nvme.sh`
   and a `driver_opts` bind-mount edit to `docker-compose.coordination.yml`'s top-level
   `volumes:` block — not Docker's entire data-root. The same Docker daemon also runs
   CasaOS's own installed apps; relocating everything is a larger blast radius than this
   ADR's scope and can be revisited separately if eMMC headroom becomes tight again.
6. **Parameterize, not just bump, the Ansible free-space floor.** `health.yml` gains a
   `disk_floor_mount` variable (default `/`, so every other host's behavior is
   unchanged); `infra/ansible/inventories/local/host_vars/coordinator.yml` sets
   `disk_floor_mount: /mnt/data` and `min_free_gb: 250`, so the coordinator's floor is
   both correct in value and checked against the right filesystem.

## Consequences

The coordination host now has real, documented headroom for the bulk Discogs dump
pipeline (`docs/DATA_SIZING.md`'s ~250GB floor, Milestone 3 in `docs/BUILD_PLAN.md`),
though Milestone 3 itself is not being started by this ADR — only the storage
prerequisite it was blocked on. `local/` being a symlink is transparent to every script
in the repo (plain relative-path opens resolve through it identically to a real
directory) but **not** to git, which needed the `.gitignore` fix described above — a
future contributor running `ls -la local` should not be surprised either way;
`docs/OPERATOR_SETUP.md` now says so explicitly. The eMMC's `docker`
data-root still holds every other container's images/volumes (including CasaOS's own
apps); this ADR does not relieve eMMC pressure from those. `/mnt/data` is unencrypted, so
if the threat model changes (e.g. the host leaves a trusted physical location), that
tradeoff should be revisited explicitly rather than assumed away.

Running the migration script surfaced an unrelated, pre-existing footgun, not introduced
by this ADR but worth recording here since it was found here: `docker-compose.coordination.yml`
and `docker-compose.portainer.yml` both live in `infra/swarm/` with no explicit Compose
project name set, so Compose infers the same project (`swarm`) for both, confirmed live
by a `down` on the coordination file logging Portainer's container as an "orphan" of
that project. `down` alone left it alone; `--remove-orphans` would not have. Both
compose files now carry an inline caution comment against ever adding
`--remove-orphans`. Deliberately not fixed further here (an explicit-project-name fix
would force a Portainer first-login reset unless its volume is migrated the same way
`postgres-data`/`redis-data` were) — left as a documented caveat pending a decision the
operator, not this ADR, should make.

## Validation

`df -h /mnt/data` reports the ext4 filesystem correctly mounted; `git status --short`
shows no unexpected changes after the `local/` symlink swap and the `.gitignore` fix
(confirmed: `git check-ignore -v local` reports it ignored); `docker compose -f
infra/swarm/docker-compose.coordination.yml ps` shows both services `Up (healthy)` on
the NVMe-backed volumes post-migration, with `ss -tln` still showing loopback-only
binding (unchanged from ADR 0010); `find /mnt/data/docker-volumes -maxdepth 2` shows
real Postgres/Redis internal file layouts, not empty directories;
`ansible-playbook playbooks/health.yml` reports the coordinator's free space against
`/mnt/data` and passes the 250GB floor.

## Revisit trigger

Closes ADR 0007's and ADR 0010's revisit triggers. Revisit this ADR if: eMMC headroom
becomes tight again from CasaOS's own app images/volumes (would raise the "relocate
Docker's entire data-root" option this ADR deliberately deferred); the drive's physical
security context changes (would raise the encryption question this ADR answered "no"
to); or a second project's storage needs require a layout convention beyond flat
top-level directories under `/mnt/data`.
