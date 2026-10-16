---
title: Where the Raff demo runs - the box, its limits, how it is updated and backed up
status: verified
as_of: 2026-10-16
last_verified: 2026-10-16
verification_method: Set up and checked on 2026-10-16 - the box's resources read over SSH before installing anything, the stack built and started with the update script, the health check over HTTPS, a browser walk on the public address (staff demo sign-in, the dashboard, one Copilot answer from the real model), and one backup run and read back
scope: The public demo at raff.eslamhamed.com, on the owner's own server that also hosts their other sites. Not a guide for libraries hosting Raff themselves
confidence: High for what runs and how it was checked, each step run on 2026-10-16. Medium for the memory headroom, measured once at rest, not under traffic
known_gaps: No uptime monitoring and no alert when the nightly backup fails. Restoring a backup was not rehearsed. Google sign-in on this address was not exercised with a real account. The box is shared, so another site's load can slow Raff and the reverse
reverify_when: The box, its other sites, the compose file or the update script change, or Raff starts holding real members' data
---

# Hosting the demo

The public demo runs at https://raff.eslamhamed.com on the owner's own server, the one that serves
eslamhamed.com and several other sites (D-29). It is a demo: the sign-in page offers the staff and
member demo buttons, and the library is generated sample data.

## What runs

- Raff's own Docker Compose stack, project name `raff`: PostgreSQL 16, the one-shot migration, and
  the app (the same image CI builds). The app listens on the box itself only, on port 8150; nginx
  on the box answers for `raff.eslamhamed.com`, holds the Let's Encrypt certificate, redirects plain
  HTTP to HTTPS, and passes requests to the app with buffering off so the Copilot's answers stream.
- The settings live in a file on the box, readable only by the deploy user: production mode, the
  public address, demo sign-in on, a session secret and database password generated on the box,
  the OpenRouter key and the Google sign-in client. None of them is in the repository.
- A memory cap on each container, because the box is shared: 384 MB for the app, 256 MB for the
  database (with `shared_buffers` at 32 MB). Measured at rest on 2026-10-16 after loading the demo
  library: 75 MB for the app, 56 MB for the database.

## The box, as measured before installing (2026-10-16)

| | Measured |
|---|---|
| System | Ubuntu 24.04, 4 cores, load average 2.2 to 2.4 |
| Memory | 7.9 GB, about 2.1 GB available, 1.9 GB of the 4 GB swap in use |
| Disk | 83 GB free |

Memory is the tight resource, which is why the containers are capped.

## How it is changed

- **Update to the latest `main`:** as the deploy user, `~/raff-deploy/update.sh`: pull, rebuild,
  restart, and wait for the health check.
- **Backups:** `~/raff-deploy/backup.sh` runs nightly at 03:17 box time from the deploy user's
  crontab and keeps seven days of compressed dumps in `~/raff-backups`. The first run on
  2026-10-16 produced 1.3 MB with all 13 tables.
- **Reset the demo library:** the seed refuses `--reset` in production, so a reset means running
  it with the production setting overridden for that one command, or restoring a dump.
- **Take it down:** `docker compose -p raff down` in the clone, remove the nginx site and its
  certificate, and remove the `raff` DNS record.

## Not done

Monitoring, a rehearsed restore, and log rotation beyond Docker's defaults. Each is in
`../99-pending.md`.
