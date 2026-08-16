# Dachik

**Know where your data goes.**

Dachik is a privacy-first, independent internet data-usage sensor and ISP-accounting comparison tool. It is currently under development. This repository contains the initial V1 application foundation; it does **not** measure real traffic yet.

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

### Local configuration

Backend settings are environment variables:

- `DACHIK_DATABASE_PATH`: SQLite path. Defaults to `~/Library/Application Support/Dachik/dachik.sqlite3`.
- `DACHIK_CORS_ORIGINS`: comma-separated allowed browser origins. Defaults to the local Vite origins.

Frontend settings use Vite's environment system:

- `VITE_API_BASE_URL`: local API URL; the safe development value is `http://127.0.0.1:8765`.

Operational endpoints such as `/health` are unversioned. Future domain endpoints will use the `/api/v1` prefix.

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
backend/app/         FastAPI settings, application, schemas, and SQLite lifecycle
backend/tests/       Local API and persistence tests
frontend/src/        React shell, typed API client, and component tests
docs/ARCHITECTURE.md Authoritative architecture
AGENTS.md            Repository rules for coding agents
pyproject.toml       Python package metadata, dependencies, and tooling
```

## Persistence status

SQLite is the only V1 database. Startup creates the configured database, enables foreign keys and WAL mode, and records an initial schema version. A migration framework is intentionally deferred until Dachik has its first real domain table; adding one now would create machinery without a schema to migrate.

## Privacy principle

Dachik stores counters and only the minimum metadata needed for accounting. It must not collect packet payloads, browsing content, URLs, DNS history, page titles, messages, or passwords. Data remains local by default, and a discrepancy must never be presented automatically as proof of ISP fraud.
