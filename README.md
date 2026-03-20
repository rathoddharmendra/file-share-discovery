# Isilon File Share Discovery

This project discovers SMB/NFS shares from Dell EMC Isilon (OneFS Platform API) and stores the results in a local SQLite database.
Then PowerShell can enrich AD security group membership and user email addresses.
Optionally, a small Flask web app provides RBAC so users can fill in business metadata.

## What you run (Windows)

1. Python enricher (discovers shares and ACL groups)
2. PowerShell AD enricher (resolves group members and emails)
3. Flask web app (users edit/view selected fields)

## Prerequisites

1. Python 3.11+ installed
2. Windows PowerShell 5.1+
3. PowerShell modules (for `scripts/ps_enricher.ps1`):
   - `ActiveDirectory` (RSAT-AD-PowerShell)
   - `PSSQLite`

## Setup (one-time)

Run:

```powershell
.\scripts\setup_windows.ps1
```

Run these commands from the project folder (the one containing `inventory.yaml`).

It will:

- Create a virtualenv in `.venv`
- Install Python dependencies
- Create `inventory.yaml` from `examples/inventory.yaml.example` (if missing)
- Copy `examples/.env.example` to `~\.isilon_discovery.env` (if missing)
- Create the `snapshots/` folder

Then edit:

- `~\.isilon_discovery.env` (set `ISILON_PASSWORD` and `FLASK_SECRET_KEY`)
- `inventory.yaml` (edit `nodes:` with your Isilon hostnames/IPs)

## Run discovery (Python)

```powershell
.\scripts\run_discovery.ps1
```

Optional: run only one node:

```powershell
.\scripts\run_discovery.ps1 -Node "isilon-prod-1"
```

## Run AD enrichment (PowerShell)

Run after discovery has created/updated `shares.db`:

```powershell
.\scripts\ps_enricher.ps1 -DbPath ".\shares.db"
```

## One command (Windows)

Run Python discovery + PowerShell enrichment + start the web app:

```powershell
.\scripts\run_all.ps1
```

Optional (if you use Azure AD hybrid and Graph for emails):

```powershell
.\scripts\ps_enricher.ps1 -DbPath ".\shares.db" -UseGraph
```

If you want the script to try installing missing PowerShell modules automatically (where possible):

```powershell
.\scripts\ps_enricher.ps1 -DbPath ".\shares.db" -AutoInstallModules
```

## Start the web app (Flask)

```powershell
.\scripts\run_webapp.ps1
```

Then open:

http://127.0.0.1:5000

## Default file locations

- Inventory: `inventory.yaml`
- Env file: `~\.isilon_discovery.env` (or `ISILON_ENV_FILE`)
- SQLite DB: `shares.db` (configured via inventory/settings)
- Snapshots: `snapshots/`

## Notes

- The SQLite DB is updated by Python; PowerShell reads and enriches in a separate step.
- Run schedules should not overlap these two enrichment steps.

## Run with Docker (optional)

Docker runs the Python discovery + (optionally) the Flask web app. PowerShell AD enrichment still needs Windows PowerShell.

Build the image:

```bash
docker build -t isilon-discovery:latest .
```

Run discovery (mount your env file + inventory.yaml):

```bash
docker run --rm \
  -v "$(pwd)":/app -w /app \
  -e ISILON_ENV_FILE=/root/.isilon_discovery.env \
  -v "$HOME/.isilon_discovery.env":/root/.isilon_discovery.env:ro \
  isilon-discovery:latest --inventory inventory.yaml
```

Start the web app:

```bash
docker run --rm -p 5000:5000 \
  -v "$(pwd)":/app -w /app \
  -e ISILON_ENV_FILE=/root/.isilon_discovery.env \
  -v "$HOME/.isilon_discovery.env":/root/.isilon_discovery.env:ro \
  -e DB_PATH=shares.db \
  --entrypoint python \
  isilon-discovery:latest -m flask --app webapp.app run --host 0.0.0.0 --port 5000 --debug
```

