# Dachik

**Know where your data goes.**

Dachik is a privacy-first, independent internet data-usage sensor and ISP-accounting comparison tool. It is currently under development. This repository contains the V1 persistence and Data Audit Experiment foundation; it does **not** measure real traffic yet.

V1 is a local-first macOS application: a Python collector will supply cumulative interface counters to a deterministic accounting engine, SQLite will persist local data, FastAPI will expose a loopback-only API, and a React browser UI will present the results. See [the architecture](docs/ARCHITECTURE.md) for the authoritative design.

## Prerequisites

- macOS
- Python 3.12 (the existing `venv/` in this workspace uses Python 3.12)
- Node.js 20.19+, 22.13+, or 24+ (use an active LTS release)
- npm 10 or newer

Do not install Python packages globally.

## Install

From the repository root, install the Python project into the existing Python 3.12 virtual environment:

```bash
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Install the frontend dependencies:

```bash
cd frontend
npm install
cp .env.example .env
```

The `.env` file contains public browser configuration only. Never place secrets in a `VITE_` variable.

## Run locally

Use two terminals from the repository root.

Terminal 1 — start FastAPI on loopback:

```bash
source venv/bin/activate
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765 --reload
```

Terminal 2 — start Vite:

```bash
cd frontend
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The page calls [http://127.0.0.1:8765/health](http://127.0.0.1:8765/health) and shows the local service status.

### Isolated browser verification

Automated or manual browser verification must never use the normal development database or ports. From the repository root, provide an explicit temporary database and run the isolated stack:

```bash
source venv/bin/activate
VERIFICATION_DIR="$(mktemp -d)"
DACHIK_DATABASE_PATH="$VERIFICATION_DIR/dachik-browser-verification.sqlite3" \
  python -m scripts.run_browser_verification --dispose
```

This runs FastAPI at `127.0.0.1:8876`, Vite at `127.0.0.1:5174`, displays a browser-verification banner, and deletes only the temporary SQLite files after the servers stop. The launcher refuses a missing path, a path outside the operating-system temporary directory, or the normal Dachik Application Support database.

### Local configuration

Backend settings are environment variables:

- `DACHIK_DATABASE_PATH`: SQLite path. Defaults to `~/Library/Application Support/Dachik/dachik.sqlite3`.
- `DACHIK_CORS_ORIGINS`: comma-separated allowed browser origins. Defaults to the local Vite origins.

Frontend settings use Vite's environment system:

- `VITE_API_BASE_URL`: local API URL; the safe development value is `http://127.0.0.1:8765`.

Operational endpoints such as `/health` are unversioned. Future domain endpoints will use the `/api/v1` prefix.

### Safely reset development data

Stop the FastAPI backend before resetting the development database. The reset command is deliberately limited to `~/Library/Application Support/Dachik/dachik.sqlite3`; it prints the resolved path, refuses an unexpected target, moves the database plus any `-wal` and `-shm` files into a timestamped backup, recreates the schema through the application's Alembic initialization, and prints the resulting revision.

First inspect the resolved target without changing anything:

```bash
source venv/bin/activate
python -m scripts.reset_development_database
```

After confirming FastAPI is stopped and the displayed path is correct, run:

```bash
python -m scripts.reset_development_database --confirm
```

The reset is recoverable from the printed backup directory. Do not use this command for a packaged/user database.

## Validate

Run Python tests, linting, and type checking from the repository root with the virtual environment active:

```bash
pytest
ruff check .
mypy
```

Run frontend tests, linting, and the production build:

```bash
cd frontend
npm test
npm run lint
npm run build
```

## Repository structure

```text
collector/           Provider-neutral traffic contracts; no real collector yet
backend/app/         Domain models, services, repositories, API, and SQLite lifecycle
backend/tests/       Domain, migration, API, persistence, and health tests
frontend/src/        React audit workflow, typed API client, and component tests
migrations/          Reproducible Alembic schema revisions
docs/ARCHITECTURE.md Authoritative architecture
AGENTS.md            Repository rules for coding agents
pyproject.toml       Python package metadata, dependencies, and tooling
```

## Persistence and API status

SQLite is the only V1 database. Startup creates the configured database, enables foreign keys and WAL mode, and automatically upgrades it to the latest checked-in Alembic revision. The initial revision creates the normalized V1 domain tables and database immutability triggers for counter observations and ISP balance snapshots.

The current local API provides:

- `GET/POST /api/v1/devices`
- `GET/POST /api/v1/bundles`
- `GET/POST /api/v1/experiments`
- `GET /api/v1/experiments/{id}`
- `POST /api/v1/experiments/{id}/start`
- `POST /api/v1/experiments/{id}/complete`
- `GET/POST /api/v1/experiments/{id}/isp-snapshots`

The browser UI gives users one consumer workflow: describe a data plan, declare its current network-reported balance, and start tracking. It composes the existing device, bundle, experiment, and immutable snapshot APIs internally. The active-plan screen intentionally says **“Measurement sensor not running yet.”** because traffic collection is not part of this phase.

## Privacy principle

Dachik stores counters and only the minimum metadata needed for accounting. It must not collect packet payloads, browsing content, URLs, DNS history, page titles, messages, or passwords. Data remains local by default, and a discrepancy must never be presented automatically as proof of ISP fraud.
