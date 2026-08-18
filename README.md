# Dachik

**Know where your data goes.**

Dachik is a privacy-first, independent internet data-usage sensor and ISP-accounting comparison tool. It is currently under development. The macOS V1 measures cumulative RX/TX byte counters in the background, tracks a data plan, preserves network-balance checkpoints, and turns deterministic local evidence into a continuous audit that can be viewed or exported at any time.

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

Install and start the user-level development sensor once from the repository root:

```bash
source venv/bin/activate
python -m collector service install
python -m collector service start
python -m collector service status
```

The sensor then runs independently of the browser, Vite, FastAPI, and any open
terminal. It starts at login and launchd restarts it after an unexpected failure,
with a five-minute throttle to avoid tight configuration-error loops. It uses the
current virtual environment's exact Python executable and the normal local Dachik
database. Moving or deleting this repository or `venv/` invalidates this
development configuration; production installer integration remains deferred.

Use two terminals for the local API and browser UI.

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

### Development sensor lifecycle

All lifecycle commands are user-level and require no `sudo`:

```bash
python -m collector service install
python -m collector service start
python -m collector service stop
python -m collector service restart
python -m collector service status
python -m collector service uninstall
```

Installation writes only
`~/Library/LaunchAgents/io.dachik.collector.development.plist`, with user-only
permissions. Uninstall verifies Dachik ownership before removing that file and
does not delete measurements, the database, or unrelated LaunchAgents. The
collector's privacy-safe rotating diagnostic log is stored at
`~/Library/Application Support/Dachik/logs/collector.log` (1 MB per file, three
backups). launchd stdout and stderr are discarded so they cannot grow without
bound.

The development policy keeps the collector available continuously. It records
counters locally and attributes only compatible intervals inside the one active
plan's tracking window. With no active plan, it does not invent plan usage.
Sleep, long sampling gaps, interface changes, and process restarts establish new
baselines/discontinuities rather than fabricating traffic.

The data-plan audit remains active across those breaks. Accepted measurement
periods before and after a safe new baseline accumulate against the original
network balance recorded when tracking began. Dachik separates measured time,
known non-attributable time, and unknown time; none of the latter two is silently
converted to zero usage. The current coverage percentage means accepted measured
duration divided by eligible tracking duration—it is not a confidence score.

V1 tracks one explicitly selected current plan on this Mac. Starting another
plan requires confirming a switch; the previous audit is not automatically
completed or deleted. If legacy development data contains multiple active audits
without a current selection, Dachik refuses to choose the newest row and asks the
user to select a plan.

For Wi-Fi attribution, the collector binds the active plan to an opaque SHA-256
fingerprint derived locally from the current network name and default gateway.
The underlying network name is not persisted or logged. A changed or
unidentifiable connection is not counted merely because macOS continues using
the same physical interface name.

For debugging only, run the collector interactively:

```bash
source venv/bin/activate
python -m collector monitor
```

The development defaults sample every 10 seconds and reject gaps longer than 30 seconds. They can be configured explicitly for either a reinstall or an interactive run:

```bash
python -m collector service stop
python -m collector service install --interval 10 --max-gap 30
python -m collector service start

# Or interactive debugging:
python -m collector monitor --interval 10 --max-gap 30
```

The collector selects the active physical `en` interface used by the IPv4 default route. To make an intentional physical-interface selection:

```bash
python -m collector monitor --interface en0
```

The collector refuses virtual/default interfaces it cannot classify safely and never sniffs packets. Stop an interactive run with Ctrl+C; every completed observation is committed before the next sleep. Do not run the interactive collector at the same time as the background service.

An audit created before connection fingerprinting is never rebound silently. With
the Mac connected to the network used by the active data plan, explicitly confirm
that connection once, then restart the development sensor:

```bash
python -m collector connection confirm
python -m collector service restart
```

The command refuses to guess if a development database contains multiple active
audits. In that exceptional development-only case, inspect the records and pass
the intended audit explicitly with `--experiment-id`; the consumer UI will not
expose this internal identifier.

The confirmation stores only an opaque connection fingerprint on the existing
traffic source. It does not expose the network name, replace the active audit,
change its starting balance, or rewrite observations, intervals, or ISP balance
evidence.

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
collector/           Provider contract, macOS counters, monitor, and LaunchAgent lifecycle
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
- `GET /api/v1/measurement/status`
- `GET /api/v1/usage/current-experiment` (accepts an optional timezone-aware
  `as_of` timestamp for deterministic point-in-time accounting)
- `GET /api/v1/audits` and `GET /api/v1/audits/current`
- `GET /api/v1/audits/{id}` with optional timezone-aware `as_of`
- `GET /api/v1/audits/{id}/report.pdf`
- `GET /api/v1/audits/{id}/export.csv`
- `GET /api/v1/audits/{id}/export.json`

The browser UI gives users one consumer workflow: describe a data plan, declare its current network-reported balance, start tracking, update the balance their network reports, and open **View audit** at any time. The audit provides point-in-time totals, daily and hourly evidence, exact measurement events, aligned provider-comparison windows, measurement quality, past-audit access, and local PDF/CSV/JSON downloads. Missing observations remain unknown, known non-attributable time stays separate, and provider-reported values never replace Dachik's measured series.

## Privacy principle

Dachik stores cumulative interface counters, derived byte intervals, continuity metadata, and only the minimum metadata needed for accounting. It does not collect packet payloads, browsing content, URLs, DNS history, page titles, messages, or passwords. V1 observes this Mac only—not other phones, hotspot clients, or router-wide traffic. Data remains local by default, and a discrepancy must never be presented automatically as proof of ISP fraud.
