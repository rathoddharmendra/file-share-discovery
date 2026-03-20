# Isilon File Share Discovery

Discover SMB/NFS shares from Dell EMC Isilon (OneFS Platform API), store metadata in SQLite, enrich AD membership via PowerShell, and manage user-owned metadata in a Flask web app.

## Architecture (Docker Compose First)

This project is organized for `docker compose up/down` with separate services:

- `db`: persistent SQLite data volume bootstrap (`shares.db`, `snapshots/`)
- `isilon`: Python discovery/enrichment loop for Isilon API
- `webapp`: Flask RBAC UI (LDAP/AD login)
- `ps` (optional profile): PowerShell enrichment runner for AD/Graph

All services are attached to `discovery_net` and can reach enterprise endpoints (AD, Isilon) through Docker host outbound networking.

## Project Layout

Only project-level files are at the repo root; implementation code is inside folders:

- `isilon_discovery/` core discovery, models, DB, orchestrator
- `webapp/` Flask app/auth/routes
- `docker/` service-specific Dockerfiles
- `config/` compose inventory templates
- `scripts/` PowerShell helpers
- `tests/` pytest tests

## Quick Start (Compose)

1. Create runtime files:

```bash
cp .env.compose.example .env
```

2. Edit `.env`:

- `ISILON_USERNAME`, `ISILON_PASSWORD`
- AD settings for web app (`AD_SERVER`, `AD_DOMAIN`, `AD_BASE_DN`, `AD_ADMIN_GROUP`)
- `FLASK_SECRET_KEY`

3. Edit `config/inventory.yaml` and set your Isilon hosts.

4. Start stack:

```bash
docker compose up -d --build
```

5. Open web app:

- [http://127.0.0.1:5000](http://127.0.0.1:5000)

6. Stop stack:

```bash
docker compose down
```

## Optional PowerShell Enrichment Container

Run the `ps` service only when needed:

```bash
docker compose --profile ps run --rm ps
```

Notes:

- `ps` uses PowerShell 7 container + `PSSQLite` module.
- Native `ActiveDirectory` module is Windows-specific; in Linux container environments use `-UseGraph` flow with Graph credentials.

## Useful Make Targets

```bash
make up
make down
make logs
make ps-run
```

## Archived Legacy Files

Files that are no longer needed for the compose-only flow were archived with a `.arc` extension.
